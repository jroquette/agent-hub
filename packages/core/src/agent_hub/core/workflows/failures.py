"""Failure kinds and the retry decision (docs/design/workflow-schema.md § Running, ADR 0032).

A kind is set where the failure happens (an exception type, an exit code, a structured field),
never read from message text: executors raise ``NodeFailedError`` or call ``kind_for_exit``, and the
engine asks ``retry_decision`` whether and when to try again. Everything here is pure; jitter
comes from a source the caller injects, so a run is deterministic under a seeded one.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Final, Literal

from agent_hub.core.errors import AgentHubError
from agent_hub.core.workflows.nodes import Retry

type FailureKind = Literal[
    "transient",
    "timeout",
    "rate_limited",
    "overloaded",
    "exec_failed",
    "output_contract",
    "max_iterations",
    "unknown",
    "config",
    "auth",
    "cancelled",
    "fatal",
]
type ExecutableType = Literal["agent", "shell", "script", "loop"]

# Retried with backoff by default; the provider pushback kinds wait longer, with jitter.
TRANSIENT_KINDS: Final[frozenset[FailureKind]] = frozenset(
    {"transient", "timeout", "rate_limited", "overloaded"}
)
PUSHBACK_KINDS: Final[frozenset[FailureKind]] = frozenset({"rate_limited", "overloaded"})
# Retried only under ``on_error: all``; every other kind (config, auth, cancelled, fatal) never.
OPT_IN_KINDS: Final[frozenset[FailureKind]] = frozenset(
    {"exec_failed", "output_contract", "max_iterations", "unknown"}
)
# A command's stdout breaking its ``output_format`` fails the same way on every run.
_NO_RETRY_ON_COMMANDS: Final[frozenset[FailureKind]] = frozenset({"output_contract"})
DEFAULT_RETRY: Final = Retry()
PUSHBACK_FLOOR: Final = timedelta(seconds=45)
PUSHBACK_CAP: Final = timedelta(minutes=5)
# Defence in depth over the model's own bound: no computed wait ever exceeds this.
MAX_RETRY_DELAY: Final = timedelta(hours=1)
MAX_DURATION_DIGITS: Final = 6
_UNITS: Final = {"s": 1, "m": 60, "h": 3600, "d": 86400}
_LAST_DRAW: Final = math.nextafter(1.0, 0.0)


class DurationError(AgentHubError):
    """A duration outside ``^[1-9][0-9]{0,5}(s|m|h|d)$``."""


class NodeFailedError(AgentHubError):
    """A node attempt failed with ``kind``; ``detail`` stays in the run record, never in events."""

    def __init__(self, kind: FailureKind, detail: str = "") -> None:
        self.kind: FailureKind = kind
        self.detail = detail
        super().__init__(detail or kind)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay: timedelta


@dataclass(frozen=True)
class RetryRecord:
    """What the engine records for each retry: the failed ``attempt``, its kind and the wait."""

    attempt: int
    kind: FailureKind
    delay: timedelta


def kind_for_exit(exit_code: int, *, timed_out: bool = False) -> FailureKind | None:
    """A shell or script exit: ``None`` on success, else only ``exec_failed`` or ``timeout``."""
    if timed_out:
        return "timeout"
    return None if exit_code == 0 else "exec_failed"


def parse_duration(value: str) -> timedelta:
    """A duration of at most six digits and a unit, else ``DurationError``."""
    digits, unit = value[:-1], value[-1:]
    if not (digits.isascii() and digits.isdigit()) or len(digits) > MAX_DURATION_DIGITS:
        msg = f"a duration is 1 to {MAX_DURATION_DIGITS} digits and a unit (s, m, h, d)"
        raise DurationError(msg)
    if unit not in _UNITS or digits.startswith("0"):
        msg = "a duration starts with a non-zero digit and ends with s, m, h or d"
        raise DurationError(msg)
    return timedelta(seconds=int(digits) * _UNITS[unit])


def retry_decision(
    kind: FailureKind,
    policy: Retry | None,
    *,
    node_type: ExecutableType,
    retries_done: int,
    jitter: Callable[[], float],
) -> RetryDecision:
    """Whether a node that failed with ``kind`` after ``retries_done`` retries tries again.

    ``retries_done`` counts this execution's retries, not the run-wide ``attempt``. The delay
    is the policy's ``delay × 2^retries_done``; ``rate_limited`` and ``overloaded`` start at
    no less than 45s, cap at 5 minutes and spread ±50% by ``jitter`` (a draw in [0, 1), a
    draw outside clamped into it). No delay ever exceeds ``MAX_RETRY_DELAY``.
    """
    policy = policy or DEFAULT_RETRY
    if retries_done >= policy.max_attempts or not _retryable(kind, policy, node_type):
        return RetryDecision(retry=False, delay=timedelta(0))
    base = parse_duration(policy.delay)
    if kind not in PUSHBACK_KINDS:
        return RetryDecision(retry=True, delay=_doubled(base, retries_done, MAX_RETRY_DELAY))
    delay = _doubled(max(base, PUSHBACK_FLOOR), retries_done, PUSHBACK_CAP)
    draw = min(max(jitter(), 0.0), _LAST_DRAW)
    return RetryDecision(retry=True, delay=min(delay * (0.5 + draw), MAX_RETRY_DELAY))


def _doubled(base: timedelta, times: int, cap: timedelta) -> timedelta:
    """``base × 2^times`` clamped to ``cap`` (and ``MAX_RETRY_DELAY``), never past it."""
    cap = min(cap, MAX_RETRY_DELAY)
    delay = min(base, cap)
    for _ in range(times):
        if delay >= cap:
            break
        delay = min(delay * 2, cap)
    return delay


def _retryable(kind: FailureKind, policy: Retry, node_type: ExecutableType) -> bool:
    if kind in TRANSIENT_KINDS:
        return True
    if kind not in OPT_IN_KINDS or policy.on_error != "all":
        return False
    return not (node_type in {"shell", "script"} and kind in _NO_RETRY_ON_COMMANDS)
