"""The ``SessionDriver`` port: how ``hub web`` starts and talks to one Claude Code process.

An engine (the Claude Agent SDK, or a ``claude -p --input-format stream-json`` subprocess)
implements it in ``agent_hub.claude_sessions``; core never imports either. Everything the
engine says comes back as a ``DriverEvent`` of a closed union, so the rest of the platform
never sees an engine's own message types.

Driver semantics every implementation keeps (``SessionDriverContract`` checks them):

- ``start`` returns a handle at once; no event is emitted before the first ``send``. The first
  turn opens with ``InitEvent`` (the CLI emits it on its first turn).
- ``send`` starts a turn, or queues the text behind the running one, in order. Its optional
  ``images`` go with the text as one user message, images first; they are never kept.
- Each turn ends with exactly one ``TurnResult``; an interrupted turn ends with one whose
  ``terminal_reason`` is ``ABORTED_TERMINAL_REASON``.
- A ``PermissionRequest`` parks the turn until ``answer_permission`` (or ``interrupt`` or
  ``close``, which deny it).
- ``close`` is idempotent: it denies what is pending, ends the process, and ``events`` yields
  ``Exited`` and stops. Any other command on a closed handle raises ``SessionTerminalError``.
- ``events`` has one consumer per handle and ends after ``Exited``.
"""

import re
from collections.abc import AsyncIterator, Iterator, Mapping
from typing import Annotated, Final, Literal, NewType, Protocol

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, JsonValue, model_validator

from agent_hub.core.readmodels.view_types import ApiTimestamp, Money
from agent_hub.core.sessions.session import TokenUsage

# The modes the web offers (D5); never bypassPermissions, dontAsk or auto. The adapter maps
# ``default`` to the installed CLI's own name for it when that differs (E15).
type PermissionMode = Literal["default", "acceptEdits", "plan"]
PERMISSION_MODES: Final = ("default", "acceptEdits", "plan")

# A model is an alias or an id matching the pattern (L6); an unknown but valid id reaches the
# CLI, whose refusal becomes an ``error`` record.
MODEL_ALIASES: Final = ("default", "opus", "sonnet", "haiku")
MODEL_PATTERN: Final = r"^[A-Za-z0-9._\-\[\]]{1,64}$"
_MODEL = re.compile(MODEL_PATTERN)

# The terminal reason of a turn ended by ``interrupt`` (the CLI's own word for it).
ABORTED_TERMINAL_REASON: Final = "aborted_streaming"

DriverHandle = NewType("DriverHandle", str)


def is_valid_model(model: str) -> bool:
    """Whether ``model`` may be passed to the CLI: an alias or an id matching the pattern."""
    return model in MODEL_ALIASES or _MODEL.fullmatch(model) is not None


def _checked_model(model: str) -> str:
    if not is_valid_model(model):
        msg = "model must be an alias (default, opus, sonnet, haiku) or match " + MODEL_PATTERN
        raise ValueError(msg)
    return model


# A model name as requests and specs carry it (422 when invalid).
type ModelName = Annotated[str, AfterValidator(_checked_model)]


class DriverModel(BaseModel):
    """Base of the port's values: frozen, unknown keys refused."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class StartSpec(DriverModel):
    """What one session starts with: a resolved working directory (never a free path from the
    browser), the mode, an optional model, an optional session to resume (and fork), an
    optional session id to give the new session (P13), and variables added to the child's
    environment (``AGENT_HUB_WEB_URL``; never the access token, L5)."""

    cwd: str = Field(min_length=1)
    mode: PermissionMode
    model: ModelName | None = None
    resume: str | None = None
    fork: bool = False
    session_id: str | None = None
    environment_extra: Mapping[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _fork_needs_resume(self) -> StartSpec:
        if self.fork and self.resume is None:
            msg = "fork needs a session to resume"
            raise ValueError(msg)
        return self


class DriverImage(DriverModel):
    """An image sent with a user message (a decoded PNG); its repr shows only the media type
    and the size, so a log line or a traceback never prints the bytes."""

    media_type: Literal["image/png"]
    data: bytes

    def __repr_args__(self) -> Iterator[tuple[str, object]]:
        yield "media_type", self.media_type
        yield "bytes", len(self.data)


class InitEvent(DriverModel):
    """The session started its first turn: Claude's ``session_id``, the model, slash commands."""

    kind: Literal["init"] = "init"
    session_id: str
    model: str | None = None
    slash_commands: tuple[str, ...] = ()


class TextDelta(DriverModel):
    """A piece of assistant text in block ``block``; ``index`` counts the block's deltas from
    0. Deltas live only in memory; the ``TextBlock`` that follows supersedes them."""

    kind: Literal["text.delta"] = "text.delta"
    block: int = Field(ge=0)
    index: int = Field(ge=0)
    text: str


class TextBlock(DriverModel):
    """A completed block of assistant text (markdown)."""

    kind: Literal["text"] = "text"
    block: int = Field(ge=0)
    text: str


class Thinking(DriverModel):
    """A completed thinking block."""

    kind: Literal["thinking"] = "thinking"
    text: str


class ToolCall(DriverModel):
    """Claude called a tool; ``parent_tool_use_id`` is the calling subagent's tool use."""

    kind: Literal["tool.call"] = "tool.call"
    tool_use_id: str
    name: str
    input: dict[str, JsonValue]
    parent_tool_use_id: str | None = None


class ToolResult(DriverModel):
    """What a tool call returned (text, or the tool's content blocks)."""

    kind: Literal["tool.result"] = "tool.result"
    tool_use_id: str
    content: JsonValue
    is_error: bool = False


class TodoItem(DriverModel):
    """One entry of Claude's todo list (``TodoWrite``)."""

    content: str
    status: str
    active_form: str | None = None


class Todos(DriverModel):
    """The whole todo list, as ``TodoWrite`` last set it."""

    kind: Literal["todos"] = "todos"
    items: tuple[TodoItem, ...]


class PermissionSuggestion(DriverModel):
    """A rule Claude suggests for "always allow"; ``index`` is its position in the request,
    ``rule`` is passed back to the CLI verbatim. Only ``localSettings`` ones are offered (D5)."""

    index: int = Field(ge=0)
    destination: str
    rule: JsonValue


# What a permission request asks: a tool use, an ``AskUserQuestion`` or a plan approval
# (``ExitPlanMode``), L8.
type RequestKind = Literal["tool", "ask_user_question", "plan_approval"]


class PermissionRequest(DriverModel):
    """The CLI asks whether ``tool`` may run with ``input``; the turn waits for the answer.

    ``request_kind`` says what the browser shows (the plan's ``kind``, renamed because ``kind``
    is the union's discriminator).
    """

    kind: Literal["permission.request"] = "permission.request"
    request_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    tool: str
    input: dict[str, JsonValue]
    suggestions: tuple[PermissionSuggestion, ...] = ()
    request_kind: RequestKind = "tool"


class TurnResult(DriverModel):
    """A turn ended: how (``subtype``, ``terminal_reason``), its estimated cost and tokens."""

    kind: Literal["result"] = "result"
    subtype: str
    terminal_reason: str | None = None
    cost_usd: Money | None = None
    usage: TokenUsage | None = None
    model_usage: dict[str, JsonValue] | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    num_turns: int | None = Field(default=None, ge=0)


class DriverError(DriverModel):
    """The engine reported an error (redacted and clipped before it is stored)."""

    kind: Literal["error"] = "error"
    message: str


class Exited(DriverModel):
    """The process ended; ``code`` is its exit status when known."""

    kind: Literal["exited"] = "exited"
    code: int | None = None


type DriverEvent = Annotated[
    InitEvent
    | TextDelta
    | TextBlock
    | Thinking
    | ToolCall
    | ToolResult
    | Todos
    | PermissionRequest
    | TurnResult
    | DriverError
    | Exited,
    Field(discriminator="kind"),
]


class Allow(DriverModel):
    """Let the tool run, with ``updated_input`` (answers of an ``AskUserQuestion``) and the
    suggested rules to keep (``always``)."""

    decision: Literal["allow"] = "allow"
    updated_input: dict[str, JsonValue] | None = None
    updated_permissions: tuple[PermissionSuggestion, ...] = ()


class Deny(DriverModel):
    """Refuse the tool use; ``message`` tells Claude why."""

    decision: Literal["deny"] = "deny"
    message: str = ""


type DriverAnswer = Annotated[Allow | Deny, Field(discriminator="decision")]


class DriverCapabilities(DriverModel):
    """What this machine can do: whether sessions can start (and why not), the engine, the
    ``claude`` version, the model aliases offered, and the cloud commands the CLI lists."""

    available: bool
    reason: str | None = None
    engine: str | None = None
    cli_version: str | None = None
    models: tuple[str, ...] = MODEL_ALIASES
    cloud: bool = False
    cloud_followup: bool = False


class PastSession(DriverModel):
    """A Claude session of a working directory that can be resumed; ``title`` is redacted and
    at most 200 characters."""

    session_id: str
    title: str | None = Field(default=None, max_length=200)
    last_activity: ApiTimestamp
    cwd: str


class SessionDriver(Protocol):
    """Starts and drives Claude Code sessions (S1); see the module docstring for the rules."""

    async def start(self, spec: StartSpec) -> DriverHandle:
        """Start a session; no event comes before the first ``send``."""
        ...

    async def send(
        self, handle: DriverHandle, text: str, *, images: tuple[DriverImage, ...] = ()
    ) -> None:
        """Send a user message (``images`` first, then ``text``): it starts a turn, or waits
        behind the running one."""
        ...

    async def interrupt(self, handle: DriverHandle) -> None:
        """End the running turn; its ``TurnResult`` follows. No-op between turns."""
        ...

    async def answer_permission(
        self, handle: DriverHandle, request_id: str, answer: DriverAnswer
    ) -> None:
        """Answer a parked permission request (``UnknownPermissionError`` when not pending)."""
        ...

    async def set_mode(self, handle: DriverHandle, mode: PermissionMode) -> None:
        """Change the permission mode."""
        ...

    async def set_model(self, handle: DriverHandle, model: str | None) -> None:
        """Change the model (None = the CLI's default)."""
        ...

    async def close(self, handle: DriverHandle) -> None:
        """Deny what is pending and end the process; idempotent."""
        ...

    def events(self, handle: DriverHandle) -> AsyncIterator[DriverEvent]:
        """The session's events in emit order, ending after ``Exited``; one consumer."""
        ...

    async def list_resumable(self, cwd: str) -> tuple[PastSession, ...]:
        """Past sessions of ``cwd``, newest first, at most 200."""
        ...

    async def capabilities(self) -> DriverCapabilities:
        """What this machine can do; never raises (``available: false`` with a reason)."""
        ...
