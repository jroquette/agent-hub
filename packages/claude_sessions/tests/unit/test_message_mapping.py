"""SDK messages as ``DriverEvent``s (D.3), from synthetic SDK objects."""

from decimal import Decimal
from typing import Any

from claude_agent_sdk import (
    AssistantMessage,
    ResultMessage,
    StreamEvent,
    SystemMessage,
    TextBlock,
    ThinkingBlock,
    ToolResultBlock,
    ToolUseBlock,
    UserMessage,
)

from agent_hub.claude_sessions.message_mapping import EventMapper
from agent_hub.core.agent_sessions.driver import (
    ABORTED_TERMINAL_REASON,
    DriverError,
    InitEvent,
    TextDelta,
    Thinking,
    TodoItem,
    Todos,
    ToolCall,
    ToolResult,
    TurnResult,
)
from agent_hub.core.agent_sessions.driver import (
    TextBlock as TextEvent,
)
from agent_hub.core.sessions.session import TokenUsage

SESSION = "00000000-0000-4000-8000-000000000001"


def _init(model: str = "claude-stub-model") -> SystemMessage:
    data = {"subtype": "init", "session_id": SESSION, "model": model, "slash_commands": ["review"]}
    return SystemMessage(subtype="init", data=data)


def _delta(text: str, *, kind: str = "text_delta", parent: str | None = None) -> StreamEvent:
    event = {"type": "content_block_delta", "index": 0, "delta": {"type": kind, "text": text}}
    return StreamEvent(uuid="u", session_id=SESSION, event=event, parent_tool_use_id=parent)


def _assistant(*blocks: Any, parent: str | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=list(blocks), model="claude-stub-model", parent_tool_use_id=parent
    )


def _result(**overrides: Any) -> ResultMessage:
    fields: dict[str, Any] = {
        "subtype": "success",
        "duration_ms": 12,
        "duration_api_ms": 10,
        "is_error": False,
        "num_turns": 1,
        "session_id": SESSION,
        "total_cost_usd": 0.0021,
        "usage": {
            "input_tokens": 20,
            "output_tokens": 4,
            "cache_read_input_tokens": 3,
            "cache_creation_input_tokens": 2,
        },
        "model_usage": {"claude-stub-model": {"inputTokens": 20, "costUSD": 0.0021}},
        "terminal_reason": "completed",
    }
    return ResultMessage(**(fields | overrides))


def test_maps_init_once_when_cli_repeats_it_each_turn() -> None:
    mapper = EventMapper()

    first = mapper.to_events(_init())
    again = mapper.to_events(_init("sonnet"))

    assert first == [
        InitEvent(session_id=SESSION, model="claude-stub-model", slash_commands=("review",))
    ]
    assert again == []


def test_numbers_deltas_and_blocks_when_text_streams() -> None:
    mapper = EventMapper()

    events = [
        *mapper.to_events(_delta("Hel")),
        *mapper.to_events(_delta("lo.")),
        *mapper.to_events(_delta("{", kind="input_json_delta")),
        *mapper.to_events(_assistant(TextBlock(text="Hello."))),
        *mapper.to_events(_delta("Next")),
        *mapper.to_events(_assistant(TextBlock(text="Next."))),
    ]

    assert events == [
        TextDelta(block=0, index=0, text="Hel"),
        TextDelta(block=0, index=1, text="lo."),
        TextEvent(block=0, text="Hello."),
        TextDelta(block=1, index=0, text="Next"),
        TextEvent(block=1, text="Next."),
    ]


def test_restarts_blocks_when_turn_ends() -> None:
    mapper = EventMapper()
    mapper.to_events(_assistant(TextBlock(text="One.")))
    mapper.to_events(_result())

    assert mapper.to_events(_assistant(TextBlock(text="Two."))) == [TextEvent(block=0, text="Two.")]


def test_maps_thinking_and_tool_call_when_assistant_uses_tool() -> None:
    blocks = (
        ThinkingBlock(thinking="Check the tree first.", signature="sig"),
        ToolUseBlock(id="toolu_1", name="Bash", input={"command": "git status"}),
    )

    events = EventMapper().to_events(_assistant(*blocks))

    assert events == [
        Thinking(text="Check the tree first."),
        ToolCall(tool_use_id="toolu_1", name="Bash", input={"command": "git status"}),
    ]


def test_keeps_only_tool_calls_when_subagent_speaks() -> None:
    mapper = EventMapper()
    message = _assistant(
        TextBlock(text="subagent text"),
        ToolUseBlock(id="toolu_2", name="Read", input={"file_path": "README.md"}),
        parent="toolu_task",
    )

    events = [*mapper.to_events(_delta("sub", parent="toolu_task")), *mapper.to_events(message)]

    assert events == [
        ToolCall(
            tool_use_id="toolu_2",
            name="Read",
            input={"file_path": "README.md"},
            parent_tool_use_id="toolu_task",
        )
    ]


def test_maps_todos_when_todowrite_called() -> None:
    todos = {
        "todos": [
            {
                "content": "Run the tests",
                "status": "in_progress",
                "activeForm": "Running the tests",
            },
            {"content": "Open the PR", "status": "pending"},
        ]
    }

    events = EventMapper().to_events(
        _assistant(ToolUseBlock(id="toolu_3", name="TodoWrite", input=todos))
    )

    assert events[1] == Todos(
        items=(
            TodoItem(
                content="Run the tests", status="in_progress", active_form="Running the tests"
            ),
            TodoItem(content="Open the PR", status="pending"),
        )
    )
    assert isinstance(events[0], ToolCall)


def test_skips_todos_when_todowrite_input_malformed() -> None:
    message = _assistant(ToolUseBlock(id="toolu_4", name="TodoWrite", input={"todos": "none"}))

    assert [event.kind for event in EventMapper().to_events(message)] == ["tool.call"]


def test_maps_tool_results_when_user_message_carries_them() -> None:
    message = UserMessage(
        content=[
            ToolResultBlock(tool_use_id="toolu_1", content="clean", is_error=False),
            ToolResultBlock(
                tool_use_id="toolu_2", content=[{"type": "text", "text": "x"}], is_error=None
            ),
            ToolResultBlock(tool_use_id="toolu_3", content=None, is_error=True),
        ]
    )

    assert EventMapper().to_events(message) == [
        ToolResult(tool_use_id="toolu_1", content="clean"),
        ToolResult(tool_use_id="toolu_2", content=[{"type": "text", "text": "x"}]),
        ToolResult(tool_use_id="toolu_3", content="", is_error=True),
    ]


def test_maps_result_when_cost_and_usage_present() -> None:
    assert EventMapper().to_events(_result()) == [
        TurnResult(
            subtype="success",
            terminal_reason="completed",
            cost_usd=Decimal("0.0021"),
            usage=TokenUsage(input=20, output=4, cache_read=3, cache_write=2),
            model_usage={"claude-stub-model": {"inputTokens": 20, "costUSD": 0.0021}},
            duration_ms=12,
            num_turns=1,
        )
    ]


def test_reports_aborted_when_interrupted_during_tool() -> None:
    message = _result(
        subtype="error_during_execution", is_error=True, terminal_reason="aborted_tools"
    )

    [result] = EventMapper().to_events(message)

    assert isinstance(result, TurnResult)
    assert result.terminal_reason == ABORTED_TERMINAL_REASON


def test_maps_result_without_cost_when_cli_omits_it() -> None:
    [result] = EventMapper().to_events(_result(total_cost_usd=None, usage=None, model_usage=None))

    assert isinstance(result, TurnResult)
    assert (result.cost_usd, result.usage, result.model_usage) == (None, None, None)


def test_reports_error_code_when_assistant_message_failed() -> None:
    message = AssistantMessage(content=[], model="claude-stub-model", error="rate_limit")

    assert EventMapper().to_events(message) == [DriverError(message="claude reported rate_limit")]


def test_ignores_message_when_kind_not_mapped() -> None:
    status = SystemMessage(subtype="status", data={"permissionMode": "plan"})

    assert EventMapper().to_events(status) == []
    assert EventMapper().to_events(UserMessage(content="echoed prompt")) == []
