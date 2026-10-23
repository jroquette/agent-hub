"""An agent session as the API shows it, its cloud sibling, and the bodies the routes take.

``AgentSession`` is what ``GET /agent-sessions/{id}`` answers: the stored row plus, while the
session is live, the open permission request from memory (E10: its summary is raw there,
redacted in the stored record). A cloud start is a row of the same table (``kind="cloud"``),
shown as a ``CloudSession``.
"""

from collections.abc import Iterator, Mapping
from enum import StrEnum
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, Field, JsonValue, StringConstraints, model_validator

from agent_hub.core.agent_sessions.driver import (
    ModelName,
    PastSession,
    PermissionMode,
    PermissionSuggestion,
    RequestKind,
    ToolAccess,
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
# An answer's key is the question's own text, written by Claude, so it may be long; the value is
# the labels picked (joined) or the user's own words. The request body's byte cap still bounds both.
MAX_ANSWER_KEY_CHARS: Final = 8192
MAX_ANSWER_VALUE_CHARS: Final = 8192
MAX_CLOUD_TASK_CHARS: Final = 65536
# The Sessions list's glimpse of a session: the last prompt and reply, and the files changed.
MAX_SNIPPET_CHARS: Final = 280
MAX_CHANGED_FILES: Final = 200
# At most this many repositories a session's review remembers.
MAX_REVIEW_TARGETS: Final = 8


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


class ChangedFile(ViewModel):
    """A file the session's tool calls changed (``Edit``, ``MultiEdit``, ``Write``,
    ``NotebookEdit``, subagents' included); ``last_change_id`` is the ``tool_use_id`` of the
    latest change to it, the id the chat's review marks compare with."""

    path: str
    last_change_id: str


class ReviewTarget(ViewModel):
    """What a session's review read in one repository, kept so the review outlives the folder:
    the hub repo (``repo``, its ``hub.json`` name) and the checkout it read (``root``, a worktree
    that may be removed later), its branch, the ``base`` it was compared with and the commit it
    forked from (``base_sha``), the last commit read (``head_sha``) and the branch's pull request
    once one is found. With these the review reads the branch's commits from the repo's own
    checkout once the worktree is gone."""

    repo: str | None = None
    label: str
    root: str
    branch: str | None = None
    base: str | None = None
    base_sha: str | None = None
    head_sha: str | None = None
    pr_number: int | None = None
    pr_url: str | None = None


class AgentSession(ViewModel):
    """One session ``hub web`` started (or one cloud start, ``kind="cloud"``).

    ``claude_session_id`` links it to the hook-observed Session once ``init`` arrives (or at
    start when the id is given, P13); ``observed_session_id`` is that Session's id once it has
    been observed, else ``null`` (a twin may never arrive, D2). ``last_seq`` is the last
    persisted record's ``seq``. ``cost_usd`` and ``usage`` add up the turns' results (an estimate).
    ``last_prompt`` and ``last_reply`` are the latest ``user.message`` and assistant ``text`` of
    the stored (redacted) log as one line of at most 280 characters, the reply's markdown
    marks dropped; ``changed_files`` the files changed, latest change first, at most 200
    (``digest``). ``tool_access`` is the tools it may use, kept so a reopened session keeps
    them; it is the server's own (``exclude``: never in an answer, so the contract is unchanged).
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
    last_prompt: str | None = Field(default=None, max_length=MAX_SNIPPET_CHARS)
    last_reply: str | None = Field(default=None, max_length=MAX_SNIPPET_CHARS)
    changed_files: tuple[ChangedFile, ...] = Field(default=(), max_length=MAX_CHANGED_FILES)
    review_targets: tuple[ReviewTarget, ...] = Field(default=(), max_length=MAX_REVIEW_TARGETS)
    open_permission: OpenPermission | None = None
    observed_session_id: str | None = None
    # Held to a ``SessionRestriction`` (an investigation session, E-15): its permission mode
    # cannot change. ``True`` or left out of the JSON, so other sessions read as before.
    restricted: bool | None = Field(default=None, exclude_if=lambda value: value is None)
    tool_access: ToolAccess = Field(default="all", exclude=True)

    def with_fields(self, fields: Mapping[str, object]) -> AgentSession:
        """This session with ``fields`` changed, validated again; ``tool_access`` is kept,
        though a dump leaves it out."""
        return AgentSession.model_validate(
            self.model_dump() | {"tool_access": self.tool_access} | dict(fields)
        )


class FinalReply(ViewModel):
    """What a session answered its last message: the assistant's text (None before any) and
    whether that turn was interrupted."""

    text: str | None = None
    interrupted: bool = False


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
    """A PNG image sent with a message (a screenshot, or an image pasted in the chat),
    base64-encoded; its decoded size and signature are checked by ``decode_screenshot`` (413,
    422)."""

    media_type: Literal["image/png"]
    data: str = Field(min_length=1)

    # The repr shows only the media type and the length: a log line or a traceback never
    # prints the data.
    def __repr_args__(self) -> Iterator[tuple[str, object]]:
        yield "media_type", self.media_type
        yield "chars", len(self.data)


# The most files one message carries: each is a PDF or a UTF-8 text of at most
# ``MAX_MESSAGE_FILE_BYTES``.
MAX_MESSAGE_FILES: Final = 10
MAX_FILE_NAME_CHARS: Final = 255

MessageFileMediaType = Literal["application/pdf", "text/plain"]


class MessageFile(ViewModel):
    """A file attached to a message for Claude to read: a PDF or a UTF-8 text, base64-encoded;
    its decoded size and content are checked by ``decode_message_file`` (413, 422)."""

    name: str = Field(min_length=1, max_length=MAX_FILE_NAME_CHARS)
    media_type: MessageFileMediaType
    data: str = Field(min_length=1)

    # Like ``Screenshot``: a log line or a traceback never prints the data.
    def __repr_args__(self) -> Iterator[tuple[str, object]]:
        yield "name", self.name
        yield "media_type", self.media_type
        yield "chars", len(self.data)


# The most images one message carries: each is a PNG of at most ``MAX_SCREENSHOT_BYTES``.
MAX_MESSAGE_SCREENSHOTS: Final = 10


class CreateAgentSession(ViewModel):
    """``POST /agent-sessions``: where, how, and an optional first prompt (its byte size is
    checked against the message limit, 413), or a past session to resume (and fork).
    ``screenshot`` (the screen's capture), ``screenshots`` (images pasted in the first
    message) and ``files`` go with the first prompt, so they need one."""

    project: ProjectName
    workdir_id: WorkdirId
    mode: PermissionMode = "default"
    model: ModelName | None = None
    prompt: str | None = Field(default=None, min_length=1)
    resume_session_id: str | None = Field(default=None, pattern=UUID_PATTERN)
    fork: bool = False
    screenshot: Screenshot | None = None
    screenshots: tuple[Screenshot, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_MESSAGE_SCREENSHOTS
    )
    files: tuple[MessageFile, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_MESSAGE_FILES
    )

    @model_validator(mode="after")
    def _fork_needs_resume(self) -> CreateAgentSession:
        if self.fork and self.resume_session_id is None:
            msg = "fork needs resume_session_id"
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _screenshot_needs_prompt(self) -> CreateAgentSession:
        attached = (self.screenshot, self.screenshots, self.files)
        if any(item is not None for item in attached) and self.prompt is None:
            msg = "screenshot, screenshots and files need prompt"
            raise ValueError(msg)
        return self


class SendMessage(ViewModel):
    """``POST /{id}/messages``: one user message (byte limit checked, 413), with the files and
    images attached to it, sent to Claude before the text."""

    text: str = Field(min_length=1)
    screenshots: tuple[Screenshot, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_MESSAGE_SCREENSHOTS
    )
    files: tuple[MessageFile, ...] | None = Field(
        default=None, min_length=1, max_length=MAX_MESSAGE_FILES
    )


AnswerKey = Annotated[str, StringConstraints(min_length=1, max_length=MAX_ANSWER_KEY_CHARS)]
AnswerValue = Annotated[str, StringConstraints(max_length=MAX_ANSWER_VALUE_CHARS)]


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
