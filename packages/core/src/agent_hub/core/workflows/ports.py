"""The engine's ports (ADR 0032): what runs a node, records a run, tells the time, checks outputs.

The engine (``engine.py``) is a pure interpreter over these four, plus a ``CheckoutProbe`` for
``mutates_checkout: false`` nodes. The cli implements ``NodeRunner`` (``claude -p``, programs,
scripts), ``Clock`` and ``CheckoutProbe`` (``git status``); ``generator`` implements
``OutputValidator`` with JSON Schema; ``events.py`` builds the run's events from a
``RunRecorder``'s calls, and the cli also writes them to the run's record under ``.agent-runs/``.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Literal, Protocol

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.failures import FailureKind, RetryRecord
from agent_hub.core.workflows.gates import GateForm, GateKind
from agent_hub.core.workflows.nodes import ExecutableNode
from agent_hub.core.workflows.scope import RefScope
from agent_hub.core.workflows.substitution import RefContext

type StepStatus = Literal["ok", "failed", "skipped"]
type SkipCause = Literal[
    "upstream_failed", "upstream_skipped", "condition", "condition_parse_error", "prior_success"
]
type RunStatus = Literal["done", "failed", "cancelled"]
# A report's status: a run's end, or ``paused`` on an open gate (no end yet).
type ReportStatus = Literal["done", "failed", "cancelled", "paused"]


@dataclass(frozen=True)
class NodeCall:
    """One attempt of an executable node, its texts already rendered by the engine.

    ``argv`` is a shell node's ``command`` or a script node's ``args``; ``prompt`` is an inline
    prompt (a ``prompt_file`` is read and rendered by the runner, against ``context``).
    ``resume_session`` is the session to continue: ``context.resume``'s, or a loop's previous
    iteration's without ``fresh_context``. ``iteration`` counts a loop's turns from 1, else 0.
    ``scope`` is how a text written in the node's own workflow reads here: the runner renders a
    ``prompt_file`` with ``scope.render(template, context)``.
    """

    node: ExecutableNode
    attempt: int
    context: RefContext
    iteration: int = 0
    argv: tuple[str, ...] = ()
    cwd: str | None = None
    env: Mapping[str, str] = field(default_factory=dict)
    prompt: str | None = None
    resume_session: str | None = None
    scope: RefScope = field(default_factory=RefScope)


@dataclass(frozen=True)
class NodeReply:
    """What an attempt gave back: the final message or stdout, and an agent's session id."""

    text: str
    session: str | None = None


class NodeRunner(Protocol):
    """Runs node attempts (the cli implements it); a failure raises ``NodeFailedError``."""

    def run(self, call: NodeCall) -> NodeReply:
        """Run ``call`` once; raise ``NodeFailedError`` with the kind where it failed."""
        ...

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        """Run a loop's rendered ``until_bash`` after ``call``'s iteration; its exit code."""
        ...


class Clock(Protocol):
    """The time a run sees: tests pass a fake that never sleeps."""

    def now(self) -> datetime:
        """The current instant, with an offset."""
        ...

    def sleep(self, delay: timedelta) -> None:
        """Wait ``delay`` (a retry's backoff)."""
        ...


class CheckoutProbe(Protocol):
    """The checkout's state as text (the cli's ``git status``), read around a read-only node."""

    def status(self) -> str:
        """The current status; the same text before and after means nothing changed."""
        ...


class OutputValidator(Protocol):
    """Checks outputs against an ``output_format`` (JSON Schema 2020-12; ``generator``)."""

    def schema_problems(self, schema: Mapping[str, JsonValue]) -> tuple[str, ...]:
        """What keeps ``schema`` from compiling; empty when it does."""
        ...

    def check(self, schema: Mapping[str, JsonValue], value: JsonValue) -> None:
        """Raise ``NodeFailedError``: ``output_contract`` when ``value`` breaks ``schema``,
        ``config`` when ``schema`` cannot be used."""
        ...


@dataclass(frozen=True)
class StepStart:
    node: str
    attempt: int
    at: datetime


@dataclass(frozen=True)
class StepEnd:
    """A node attempt's end, or a skip. ``origin`` is the node an upstream cause comes from.

    ``output`` and ``detail`` (a failure's or a halt's text) belong to the run's record only,
    never to events (ADR 0019).
    """

    node: str
    attempt: int
    status: StepStatus
    at: datetime
    failure_kind: FailureKind | None = None
    skip_cause: SkipCause | None = None
    origin: str | None = None
    output: JsonValue = None
    detail: str = ""


@dataclass(frozen=True)
class RunEnd:
    """The run's end: ``status`` apart from the authored ``outcome``.

    ``reason`` is engine metadata only: the failed or halting node's id.
    """

    status: RunStatus
    at: datetime
    outcome: JsonValue = None
    reason: str | None = None


@dataclass(frozen=True)
class GateRequest:
    """A gate opened by an ``approval`` or ``wait`` node's attempt.

    ``text`` (the rendered message, or a wait's ``until``) belongs to the run's record only,
    never to events (ADR 0019); ``choices`` are the ids an answer may choose.
    """

    node: str
    attempt: int
    kind: GateKind
    form: GateForm
    at: datetime
    choices: tuple[str, ...] = ()
    text: str = ""
    due: datetime | None = None


class RunRecorder(Protocol):
    """Receives a run's steps, retries, gates and end, in order (events, the run's record)."""

    def step_started(self, start: StepStart) -> None: ...

    def step_ended(self, end: StepEnd) -> None: ...

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None: ...

    def run_ended(self, end: RunEnd) -> None: ...

    def gate_requested(self, request: GateRequest) -> None: ...
