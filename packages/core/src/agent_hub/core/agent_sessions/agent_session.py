"""An agent session as the API shows it, its cloud sibling, and the bodies the routes take.

``AgentSession`` is what ``GET /agent-sessions/{id}`` answers: the stored row plus, while the
session is live, the open permission request from memory (E10: its summary is raw there,
redacted in the stored record). A cloud start is a row of the same table (``kind="cloud"``),
shown as a ``CloudSession``.
"""

from collections.abc import Iterator
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, Field, JsonValue, StringConstraints, model_validator

from agent_hub.core.agent_sessions.driver import (
    ModelName,
    PastSession,
    PermissionMode,
    PermissionSuggestion,
    RequestKind,
)
from agent_hub.core.readmodels.view_types import ApiTimestamp, Money, ViewModel
from agent_hub.core.sessions.session import TokenUsage

WORKDIR_ID_PATTERN: Final = r"^[0-9a-f]{16}$"
UUID_PATTERN: Final = (
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)
CLOUD_ID_PATTERN: Final = r"^[A-Za-z0-9_-]{1,128}$"
MAX_PROJECT_CHARS: Final = 200
MAX_TITLE_CHARS: Final = 200
MAX_DECISION_MESSAGE: Final = 2048
MAX_ANSWERS: Final = 16
MAX_CLOUD_TASK_CHARS: Final = 65536


class AgentSessionStatus(StrEnum):
    """Where a session is (P18): ``idle`` between turns, ``running`` in a turn,
    ``waiting_permission`` while a request is unanswered; ``ended`` and ``failed`` are final."""

    RUNNING = "running"
    IDLE = "idle"
    WAITING_PERMISSION = "waiting_permission"
    ENDED = "ended"
    FAILED = "failed"


TERMINAL_STATUSES: Final = frozenset({AgentSessionStatus.ENDED, AgentSessionStatus.FAILED})


class EndReason(StrEnum):
    """Why a session ended."""

    CLOSED = "closed"
    IDLE_TIMEOUT = "idle_timeout"
    SERVER_STOPPED = "server_stopped"
    FAILED = "failed"
    LOG_FULL = "log_full"


type AgentSessionKind = Literal["local", "cloud"]

ProjectName = Annotated[str, StringConstraints(min_length=1, max_length=MAX_PROJECT_CHARS)]
WorkdirId = Annotated[str, StringConstraints(pattern=WORKDIR_ID_PATTERN)]


class OpenPermission(ViewModel):
    """The permission request a live session waits on, as memory holds it (E10).

    ``summary`` is the input summary (at most 4 KiB); ``input`` is the tool input only for an
    ``AskUserQuestion`` (its questions) or a plan approval (its plan), None for a tool.
    """

    request_id: str
    tool: str
    request_kind: RequestKind
    summary: str
    input: dict[str, JsonValue] | None = None
    suggestions: tuple[PermissionSuggestion, ...] = ()
    asked_at: ApiTimestamp
    deadline_at: ApiTimestamp


class AgentSession(ViewModel):
    """One session ``hub web`` started (or one cloud start, ``kind="cloud"``).

    ``claude_session_id`` links it to the hook-observed Session once ``init`` arrives (or at
    start when the id is given, P13); ``observed_session_id`` is that Session's id once it has
    been observed, else ``null`` (a twin may never arrive, D2). ``last_seq`` is the last
    persisted record's ``seq``. ``cost_usd`` and ``usage`` add up the turns' results (an estimate).
    """

    id: str
    kind: AgentSessionKind = "local"
    project: str
    workdir_id: str
    workdir_label: str
    claude_session_id: str | None = None
    cloud_id: str | None = None
    url: str | None = None
    status: AgentSessionStatus
    mode: PermissionMode
    model: str | None = None
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    created_at: ApiTimestamp
    updated_at: ApiTimestamp
    ended_at: ApiTimestamp | None = None
    end_reason: EndReason | None = None
    cost_usd: Money | None = None
    usage: TokenUsage | None = None
    last_seq: int = Field(default=0, ge=0)
    open_permission: OpenPermission | None = None
    observed_session_id: str | None = None


class AgentSessionList(ViewModel):
    """``GET /agent-sessions``: newest first."""

    items: tuple[AgentSession, ...]


class CloudSession(ViewModel):
    """A session started in the cloud (D8): where to open it and how to teleport it here."""

    id: str
    project: str
    workdir_id: str
    cloud_id: str
    url: str | None = None
    teleport_command: str
    title: str | None = Field(default=None, max_length=MAX_TITLE_CHARS)
    created_at: ApiTimestamp
    followups: int = Field(default=0, ge=0)


class CloudSessionList(ViewModel):
    """``GET /agent-sessions/cloud``: the persisted cloud starts, newest first, at most 50."""

    items: tuple[CloudSession, ...]


class Workdir(ViewModel):
    """A folder a session may start in (D6): the hub, a repo checkout or one of its worktrees.

    ``workdir_id`` is opaque and stable; the server resolves it only by lookup. ``skills`` are
    the names under its ``.claude/skills/`` (the ``/skill`` shortcut, P15).
    """

    workdir_id: WorkdirId
    kind: Literal["hub", "repo", "worktree"]
    label: str
    repo: str | None = None
    worktree: str | None = None
    skills: tuple[str, ...] = ()


class WorkdirList(ViewModel):
    """``GET /agent-sessions/workdirs``; ``warnings`` name folders that could not be read."""

    items: tuple[Workdir, ...]
    warnings: tuple[str, ...] = ()


class ResumableList(ViewModel):
    """``GET /agent-sessions/resumable``: past Claude sessions of a workdir, newest first."""

    items: tuple[PastSession, ...]


class MessageAccepted(ViewModel):
    """``POST /{id}/messages`` (202): the ``seq`` of the ``user.message`` record."""

    seq: int = Field(ge=1)


class Screenshot(ViewModel):
    """A PNG of the screen sent with the first prompt, base64-encoded; its decoded size and
    signature are checked by ``decode_screenshot`` (413, 422)."""

    media_type: Literal["image/png"]
    data: str = Field(min_length=1)

    # The repr shows only the media type and the length: a log line or a traceback never
    # prints the data.
    def __repr_args__(self) -> Iterator[tuple[str, object]]:
        yield "media_type", self.media_type
        yield "chars", len(self.data)


class CreateAgentSession(ViewModel):
    """``POST /agent-sessions``: where, how, and an optional first prompt (its byte size is
    checked against the message limit, 413), or a past session to resume (and fork).
    ``screenshot`` goes with the first prompt as an image, so it needs one."""

    project: ProjectName
    workdir_id: WorkdirId
    mode: PermissionMode = "default"
    model: ModelName | None = None
    prompt: str | None = Field(default=None, min_length=1)
    resume_session_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    fork: bool = False
    screenshot: Screenshot | None = None

    @model_validator(mode="after")
    def _fork_needs_resume(self) -> CreateAgentSession:
        if self.fork and self.resume_session_id is None:
            msg = "fork needs resume_session_id"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _screenshot_needs_prompt(self) -> CreateAgentSession:
        if self.screenshot is not None and self.prompt is None:
            msg = "screenshot needs prompt"
            raise ValueError(msg)
        return self


class SendMessage(ViewModel):
    """``POST /{id}/messages``: one user message (byte limit checked, 413)."""

    text: str = Field(min_length=1)


AnswerKey = Annotated[str, StringConstraints(min_length=1, max_length=200)]
AnswerValue = Annotated[str, StringConstraints(max_length=1024)]


class PermissionDecision(ViewModel):
    """``POST /{id}/permissions/{request_id}`` (E7).

    ``allow`` may carry ``answers`` (an ``AskUserQuestion``) or ``mode`` (a plan approval);
    ``deny`` may carry ``message``; ``always`` needs ``suggestion``, the index of the
    ``localSettings`` rule to keep. Any other combination is refused (422); whether the fields
    fit the request is the permission policy's check.
    """

    decision: Literal["allow", "deny", "always"]
    message: str | None = Field(default=None, max_length=MAX_DECISION_MESSAGE)
    answers: dict[AnswerKey, AnswerValue] | None = Field(default=None, max_length=MAX_ANSWERS)
    suggestion: int | None = Field(default=None, ge=0)
    mode: Literal["default", "acceptEdits"] | None = None

    @model_validator(mode="after")
    def _fields_fit_decision(self) -> PermissionDecision:
        problems = {
            "always needs suggestion": self.decision == "always" and self.suggestion is None,
            "suggestion only with always": self.decision != "always"
            and self.suggestion is not None,
            "message only with deny": self.decision != "deny" and self.message is not None,
            "answers only with allow": self.decision != "allow" and self.answers is not None,
            "mode only with allow": self.decision != "allow" and self.mode is not None,
        }
        broken = [name for name, failed in problems.items() if failed]
        if broken:
            raise ValueError("; ".join(broken))
        return self


class SessionSettings(ViewModel):
    """``POST /{id}/settings``: a new mode, a new model, or both (at least one)."""

    mode: PermissionMode | None = None
    model: ModelName | None = None

    @model_validator(mode="after")
    def _needs_one(self) -> SessionSettings:
        if self.mode is None and self.model is None:
            msg = "give mode, model or both"
            raise ValueError(msg)
        return self


def _not_a_flag(task: str) -> str:
    if task.startswith("-"):
        msg = "a task cannot start with '-'"
        raise ValueError(msg)
    return task


class StartCloud(ViewModel):
    """``POST /agent-sessions/cloud``: a task for ``claude --cloud``, passed as one argument."""

    project: ProjectName
    workdir_id: WorkdirId
    task: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_CLOUD_TASK_CHARS),
        AfterValidator(_not_a_flag),
    ]


class CloudMessage(ViewModel):
    """``POST /agent-sessions/cloud/{cloud_id}/messages``: a one-shot follow-up."""

    text: Annotated[
        str,
        StringConstraints(min_length=1, max_length=MAX_CLOUD_TASK_CHARS),
        AfterValidator(_not_a_flag),
    ]
