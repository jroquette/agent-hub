"""SDK messages as the port's ``DriverEvent``s (D.3).

``EventMapper`` holds the little state the mapping needs, one per session:

- ``init``: the CLI sends ``system/init`` at the start of every turn; only the first becomes an
  ``InitEvent``.
- Text: partial ``text_delta`` stream events become ``TextDelta``s numbered within their block;
  each completed text block becomes a ``TextBlock`` with the same block number. Numbers restart
  with each turn.
- A subagent's own text, deltas and thinking (``parent_tool_use_id`` set) are not shown; its tool
  calls are, nested under the calling tool use.
- ``TodoWrite`` calls also give the whole todo list as ``Todos``.
- ``ResultMessage`` becomes ``TurnResult``; any ``aborted_*`` terminal reason (the CLI says
  ``aborted_tools`` when interrupted during a tool) is reported as ``ABORTED_TERMINAL_REASON``.

Messages the web does not show (status, hooks, rate limits, an echoed prompt) map to nothing.
"""

from decimal import Decimal
from typing import Any, Final, cast

from claude_agent_sdk import (
    AssistantMessage,
    Message,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)
from pydantic import JsonValue, ValidationError

from agent_hub.core.agent_sessions import driver
from agent_hub.core.agent_sessions.diff import patch_diff, write_diff
from agent_hub.core.agent_sessions.driver import (
    ABORTED_TERMINAL_REASON,
    DriverError,
    DriverEvent,
    InitEvent,
    TextDelta,
    Thinking,
    TodoItem,
    Todos,
    ToolCall,
    ToolResult,
    TurnResult,
)
from agent_hub.core.sessions.session import TokenUsage

TODO_TOOL: Final = "TodoWrite"
_ABORTED_PREFIX: Final = "aborted"


class EventMapper:
    """Maps one session's SDK messages, in order; see the module docstring."""

    def __init__(self) -> None:
        self._initialized = False
        self._block = 0
        self._delta = 0

    def to_events(self, message: Message) -> list[DriverEvent]:
        """The events ``message`` stands for (often none, sometimes several)."""
        match message:
            case SystemMessage(subtype="init", data=data):
                return self._init(data)
            case StreamEvent(event=event, parent_tool_use_id=None):
                return self._stream(event)
            case AssistantMessage():
                return self._assistant(message)
            case UserMessage(content=list() as blocks):
                results = [block for block in blocks if isinstance(block, ToolResultBlock)]
                # The engine's report of a file tool's change goes with its (one) result.
                diff = _result_diff(message.tool_use_result) if len(results) == 1 else None
                return [_tool_result(block, diff) for block in results]
            case ResultMessage():
                self._block, self._delta = 0, 0
                return [_turn_result(message)]
            case _:
                return []

    def _init(self, data: dict[str, Any]) -> list[DriverEvent]:
        session_id = data.get("session_id")
        if self._initialized or not isinstance(session_id, str):
            return []
        self._initialized = True
        model = data.get("model")
        commands = data.get("slash_commands") or []
        return [
            InitEvent(
                session_id=session_id,
                model=model if isinstance(model, str) else None,
                slash_commands=tuple(str(command) for command in commands),
            )
        ]

    def _stream(self, event: dict[str, Any]) -> list[DriverEvent]:
        delta = event.get("delta")
        if event.get("type") != "content_block_delta" or not isinstance(delta, dict):
            return []
        text = delta.get("text")
        if delta.get("type") != "text_delta" or not isinstance(text, str):
            return []
        found = TextDelta(block=self._block, index=self._delta, text=text)
        self._delta += 1
        return [found]

    def _assistant(self, message: AssistantMessage) -> list[DriverEvent]:
        events: list[DriverEvent] = []
        if message.error is not None:
            events.append(DriverError(message=f"claude reported {message.error}"))
        own = message.parent_tool_use_id is None
        for block in message.content:
            match block:
                case TextBlock(text=text) if own:
                    events.append(driver.TextBlock(block=self._block, text=text))
                    self._block, self._delta = self._block + 1, 0
                case ThinkingBlock(thinking=text) if own:
                    events.append(Thinking(text=text))
                case ToolUseBlock():
                    events.extend(_tool_call(block, message.parent_tool_use_id))
                case _:
                    pass
        return events


def _tool_call(block: ToolUseBlock, parent: str | None) -> list[DriverEvent]:
    call = ToolCall(
        tool_use_id=block.id,
        name=block.name,
        input=cast("dict[str, JsonValue]", block.input),
        parent_tool_use_id=parent,
    )
    if block.name != TODO_TOOL:
        return [call]
    todos = _todos(block.input)
    return [call] if todos is None else [call, todos]


def _todos(data: dict[str, Any]) -> Todos | None:
    entries = data.get("todos")
    if not isinstance(entries, list):
        return None
    try:
        items = tuple(
            TodoItem(
                content=entry["content"],
                status=entry["status"],
                active_form=entry.get("activeForm"),
            )
            for entry in entries
        )
    except KeyError, TypeError, AttributeError, ValidationError:
        return None
    return Todos(items=items)


def _tool_result(block: ToolResultBlock, diff: str | None = None) -> DriverEvent:
    content: JsonValue = "" if block.content is None else cast("JsonValue", block.content)
    return ToolResult(
        tool_use_id=block.tool_use_id,
        content=content,
        is_error=bool(block.is_error),
        diff=None if block.is_error else diff,
    )


def _result_diff(report: object) -> str | None:
    """The change a file tool made, from the engine's report of it (``tool_use_result``): its
    ``structuredPatch`` with the file's line numbers, or a new file's whole content."""
    if not isinstance(report, dict):
        return None
    path = report.get("filePath")
    if not isinstance(path, str):
        return None
    content = report.get("content")
    if report.get("type") == "create" and isinstance(content, str):
        return write_diff(path, content)
    return patch_diff(path, report.get("structuredPatch"))


def _turn_result(message: ResultMessage) -> TurnResult:
    reason = message.terminal_reason
    if reason is not None and reason.startswith(_ABORTED_PREFIX):
        reason = ABORTED_TERMINAL_REASON
    cost = None if message.total_cost_usd is None else Decimal(str(message.total_cost_usd))
    return TurnResult(
        subtype=message.subtype,
        terminal_reason=reason,
        cost_usd=cost,
        usage=None if message.usage is None else _usage(message.usage),
        model_usage=cast("dict[str, JsonValue] | None", message.model_usage),
        duration_ms=max(message.duration_ms, 0),
        num_turns=max(message.num_turns, 0),
    )


def _usage(usage: dict[str, Any]) -> TokenUsage:
    def count(key: str) -> int:
        value = usage.get(key)
        return value if isinstance(value, int) and value >= 0 else 0

    return TokenUsage(
        input=count("input_tokens"),
        output=count("output_tokens"),
        cache_read=count("cache_read_input_tokens"),
        cache_write=count("cache_creation_input_tokens"),
    )
