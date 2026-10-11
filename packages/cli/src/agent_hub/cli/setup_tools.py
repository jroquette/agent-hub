"""``hub setup``'s tools section: uv, git, python3, claude, gh and the tracker credential.

Each tool is looked up on ``PATH`` and, for uv, python3 and gh, run once through a ``ToolProbe``
with a timeout; the core checklist turns what it gave into a line. The probe is a cli-internal
seam, not a port: ``setup_command`` gets it from ``tool_probe``, which the tests replace. A
tool runs without ``LINEAR_API_KEY`` in its environment, and of the key only its presence is
read, never its value.
"""

import os
import shutil
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Final, Literal, Protocol

from agent_hub.cli.child_process import run_child
from agent_hub.cli.effective_config import EffectiveConfig, effective_or_problems
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import CHILD_HIDDEN, KEY_VARIABLE, without
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workspace.setup_checklist import (
    PROBE_TIMEOUT_SECONDS,
    ChecklistItem,
    ProbeResult,
    gh_item,
    presence_item,
    python_item,
    tracker_item,
    uv_item,
)

# A version line is short: only the tail of a tool's stdout is kept.
OUTPUT_LIMIT: Final = 4096

type Transport = Literal["api", "mcp"]


class ToolProbe(Protocol):
    """Finds a tool on ``PATH`` and runs it with a timeout."""

    def which(self, name: str) -> str | None:
        """The tool's absolute path, or None when it is not on ``PATH``."""
        ...

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult:
        """Run ``argv`` for at most ``timeout`` seconds; what it gave."""
        ...


class SubprocessToolProbe:
    """Runs each tool as a child process, in ``cwd``, with ``environ`` minus the tracker key."""

    def __init__(self, environ: Mapping[str, str], cwd: Path) -> None:
        self._environ = dict(environ)
        self._child_env = without(environ, CHILD_HIDDEN)
        self._cwd = cwd

    def which(self, name: str) -> str | None:
        found = shutil.which(name, path=self._environ.get("PATH", os.defpath))
        # PATH may hold a relative folder, found from the process cwd; the tool runs elsewhere.
        return None if found is None else os.path.abspath(found)

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult:
        try:
            result = run_child(
                argv,
                cwd=self._cwd,
                env=self._child_env,
                timeout=timeout,
                output_limit=OUTPUT_LIMIT,
            )
        except ChildTimedOutError:
            return ProbeResult(None, b"", is_timed_out=True)
        except OSError:
            return ProbeResult(None, b"", is_timed_out=False)
        return ProbeResult(result.returncode, result.stdout, is_timed_out=False)


def tool_probe(environ: Mapping[str, str], *, cwd: Path) -> ToolProbe:
    """The probe ``hub setup`` uses (tests replace this factory)."""
    return SubprocessToolProbe(environ, cwd)


def effective_transport(config: HubConfig, *, home: Path) -> Transport:
    """``tracker.transport`` from ``home``'s ``hub.local.json`` over ``hub.json``'s; ``hub.json``'s
    alone when the local file is invalid (the identity step reports its problems)."""
    loaded = effective_or_problems(config, home=home)
    if isinstance(loaded, EffectiveConfig):
        return loaded.config.tracker.transport
    return config.tracker.transport


def tool_items(
    probe: ToolProbe, *, transport: Transport, environ: Mapping[str, str]
) -> Iterator[ChecklistItem]:
    """The items in order: uv, git, python3, claude, gh, tracker; each probe bounded at 10 s."""
    uv = probe.which("uv")
    yield uv_item(uv, None if uv is None else _version(probe, uv))
    yield presence_item("git", probe.which("git"))
    python3 = probe.which("python3")
    yield python_item(python3, None if python3 is None else _version(probe, python3))
    claude = probe.which("claude")
    yield presence_item("claude", claude)
    gh = probe.which("gh")
    yield gh_item(
        gh, None if gh is None else probe.run([gh, "auth", "status"], timeout=PROBE_TIMEOUT_SECONDS)
    )
    yield tracker_item(
        transport=transport,
        is_key_set=bool(environ.get(KEY_VARIABLE)),
        has_claude=claude is not None,
    )


def _version(probe: ToolProbe, path: str) -> ProbeResult:
    return probe.run([path, "--version"], timeout=PROBE_TIMEOUT_SECONDS)
