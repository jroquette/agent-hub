"""What this machine can do with Claude Code (S8, AC-165.38, AC-165.55).

``detect`` finds ``claude`` on ``PATH`` and runs ``claude --version`` and ``claude --help`` side
by side, each within 5 s and 64 KiB: no shell, no network flag. Sessions are available when the
version answers. ``cloud`` is true when the help lists both ``--cloud`` and ``--teleport``;
starting one stays link-out guidance (the CLI needs a terminal for it, spike L9).
``cloud_followup`` (``claude -p --cloud <id>``) is offered only when the caller turns its flag on:
its success output has not been observed yet. That this module imports at all means the SDK is
installed (the ``sessions`` extra); without it the API wires an unavailable driver instead.

``CapabilityCache`` keeps an answer for 60 s, so the routes do not start processes per request.
"""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Final, Protocol

from agent_hub.claude_sessions.options import claude_path
from agent_hub.claude_sessions.process_tree import Completed, RunTimeoutError, run_bounded
from agent_hub.core.agent_sessions.driver import MODEL_ALIASES, DriverCapabilities

DETECT_TIMEOUT_SECONDS: Final = 5
OUTPUT_LIMIT_BYTES: Final = 64 * 1024
CACHE_SECONDS: Final = 60.0
ENGINE: Final = "claude-agent-sdk"
NO_CLAUDE: Final = "no claude executable on PATH: install Claude Code"
_VERSION = re.compile(r"\d+\.\d+\.\d+[0-9A-Za-z.+-]*")


class Runner(Protocol):
    """Runs one short command with a deadline and an output limit."""

    async def __call__(self, argv: Sequence[str], *, timeout: float, limit: int) -> Completed:
        """Run ``argv``; ``RunTimeoutError`` past the deadline."""
        ...


async def bounded_runner(argv: Sequence[str], *, timeout: float, limit: int) -> Completed:
    """The production runner: ``process_tree.run_bounded``."""
    return await run_bounded(argv, timeout=timeout, limit=limit)


async def _probe(run: Runner, argv: list[str]) -> Completed | RunTimeoutError:
    try:
        return await run(argv, timeout=DETECT_TIMEOUT_SECONDS, limit=OUTPUT_LIMIT_BYTES)
    except RunTimeoutError as timed_out:
        return timed_out


def _version_problem(answer: Completed | RunTimeoutError) -> str | None:
    if isinstance(answer, RunTimeoutError):
        return f"claude --version did not answer within {DETECT_TIMEOUT_SECONDS} s"
    if answer.overflow:
        return "claude --version wrote more than 64 KiB"
    if answer.code != 0:
        return f"claude --version failed (exit {answer.code})"
    return None


def _lists_cloud(answer: Completed | RunTimeoutError) -> bool:
    if isinstance(answer, RunTimeoutError) or answer.code != 0 or answer.overflow:
        return False
    text = answer.stdout.decode("utf-8", errors="replace")
    return "--cloud" in text and "--teleport" in text


async def detect(
    environ: Mapping[str, str], run: Runner, *, cloud_followup: bool = False
) -> DriverCapabilities:
    """What the ``claude`` on ``environ``'s ``PATH`` can do; never raises."""
    claude = claude_path(environ)
    if claude is None:
        return DriverCapabilities(available=False, reason=NO_CLAUDE, engine=ENGINE)
    version, help_text = await asyncio.gather(
        _probe(run, [claude, "--version"]), _probe(run, [claude, "--help"])
    )
    problem = _version_problem(version)
    if problem is not None or isinstance(version, RunTimeoutError):
        return DriverCapabilities(available=False, reason=problem, engine=ENGINE)
    found = _VERSION.search(version.stdout.decode("utf-8", errors="replace"))
    cloud = _lists_cloud(help_text)
    return DriverCapabilities(
        available=True,
        engine=ENGINE,
        cli_version=None if found is None else found.group(0),
        models=MODEL_ALIASES,
        cloud=cloud,
        cloud_followup=cloud and cloud_followup,
    )


class CapabilityCache:
    """Keeps the last answer of ``probe`` for ``ttl`` seconds; callers share one probe."""

    def __init__(
        self,
        probe: Callable[[], Awaitable[DriverCapabilities]],
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl: float = CACHE_SECONDS,
    ) -> None:
        self._probe = probe
        self._clock = clock
        self._ttl = ttl
        self._lock = asyncio.Lock()
        self._answer: DriverCapabilities | None = None
        self._at = 0.0

    async def get(self) -> DriverCapabilities:
        """The cached answer, or a fresh one once it is older than ``ttl``."""
        async with self._lock:
            if self._answer is None or self._clock() - self._at >= self._ttl:
                self._answer = await self._probe()
                self._at = self._clock()
            return self._answer
