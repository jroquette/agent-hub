"""The ``hub setup`` checklist: its items, their lines, the summary and the exit rule; pure.

Each item prints as ``f"{state:<7} {item}: {detail}"``, then `` Fix: <fix>`` when it has one, then
its sub-lines indented 8 spaces. The tool items read what a probe gave (``ProbeResult``); the cli
runs the probes. No text here names a credential's value: the tracker item reads only whether
``LINEAR_API_KEY`` is set.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, NamedTuple

PROBE_TIMEOUT_SECONDS: Final = 10.0
UV_MINIMUM: Final = (0, 9, 0)
PYTHON_MINIMUM: Final = (3, 9, 0)

UV_FIX: Final = "curl -LsSf https://astral.sh/uv/install.sh | sh"
UV_UPDATE_FIX: Final = "uv self update"
GIT_FIX: Final = "install git 2.28 or newer (https://git-scm.com/downloads)"
PYTHON_FIX: Final = "install Python 3.9 or newer as python3 (https://www.python.org/downloads/)"
CLAUDE_FIX: Final = "install Claude Code (https://docs.anthropic.com/en/docs/claude-code/setup)"
GH_FIX: Final = "install the GitHub CLI (https://cli.github.com), then gh auth login"
GH_LOGIN_FIX: Final = "gh auth login"
TRACKER_KEY_FIX: Final = (
    'export LINEAR_API_KEY=<your Linear API key>, or set tracker.transport "mcp" in hub.local.json'
)

_SUB_LINE_INDENT: Final = " " * 8
_NOT_ON_PATH: Final = "not on PATH"
_UNREADABLE: Final = "cannot read its version"
_TIMED_OUT: Final = f"timed out after {PROBE_TIMEOUT_SECONDS:g} s"
_VERSION: Final = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)")

type Version = tuple[int, int, int]


class State(StrEnum):
    """An item's state: ``ok``, or ``missing`` (the run then exits 1)."""

    OK = "ok"
    MISSING = "missing"


@dataclass(frozen=True)
class ChecklistItem:
    """One checklist item: its state, name, detail, the fix when it has one and its sub-lines."""

    state: State
    item: str
    detail: str
    fix: str | None
    sub_lines: tuple[str, ...] = ()


@dataclass(frozen=True)
class ProbeResult:
    """What one tool run gave: its exit code (None when it did not finish), stdout, a timeout."""

    returncode: int | None
    stdout: bytes
    is_timed_out: bool


class _VersionedTool(NamedTuple):
    item: str
    minimum: Version
    minimum_text: str
    absent_fix: str
    old_fix: str
    unreadable_fix: str


_UV: Final = _VersionedTool(
    item="uv",
    minimum=UV_MINIMUM,
    minimum_text="0.9.0",
    absent_fix=UV_FIX,
    old_fix=UV_UPDATE_FIX,
    unreadable_fix="uv --version",
)
_PYTHON: Final = _VersionedTool(
    item="python3",
    minimum=PYTHON_MINIMUM,
    minimum_text="3.9",
    absent_fix=PYTHON_FIX,
    old_fix=PYTHON_FIX,
    unreadable_fix="python3 --version",
)
_PRESENCE_FIXES: Final = {"git": GIT_FIX, "claude": CLAUDE_FIX}


def item_lines(item: ChecklistItem) -> list[str]:
    """The item's line, with its fix when it has one, then its sub-lines indented 8 spaces."""
    line = f"{item.state:<7} {item.item}: {item.detail}"
    if item.fix is not None:
        line += f" Fix: {item.fix}"
    return [line, *(_SUB_LINE_INDENT + sub_line for sub_line in item.sub_lines)]


def summary_line(items: Iterable[ChecklistItem]) -> str:
    """The last line, ``setup: <n> ok`` or ``setup: <m> missing, <n> ok``; sub-lines not counted."""
    states = [item.state for item in items]
    missing = states.count(State.MISSING)
    ok = states.count(State.OK)
    if missing == 0:
        return f"setup: {ok} ok"
    return f"setup: {missing} missing, {ok} ok"


def setup_exit(items: Iterable[ChecklistItem]) -> int:
    """0 when every item is ok, else 1."""
    return 1 if any(item.state is State.MISSING for item in items) else 0


def version_in(stdout: bytes) -> Version | None:
    """The first ``X.Y.Z`` of the tool's output read as UTF-8, or None when it has none."""
    match = _VERSION.search(stdout.decode("utf-8", errors="replace"))
    if match is None:
        return None
    major, minor, patch = (int(part) for part in match.groups())
    return (major, minor, patch)


def uv_item(path: str | None, result: ProbeResult | None) -> ChecklistItem:
    """The ``uv`` item from ``uv --version``'s result (None, or ``path`` None, when not on PATH)."""
    return _versioned_item(_UV, path, result)


def python_item(path: str | None, result: ProbeResult | None) -> ChecklistItem:
    """The ``python3`` item from ``python3 --version``'s result, as ``uv_item``."""
    return _versioned_item(_PYTHON, path, result)


def presence_item(name: Literal["git", "claude"], path: str | None) -> ChecklistItem:
    """The ``git`` or ``claude`` item: ok when the tool is on PATH."""
    if path is None:
        return _missing(name, _NOT_ON_PATH, _PRESENCE_FIXES[name])
    return _ok(name, "on PATH")


def gh_item(path: str | None, result: ProbeResult | None) -> ChecklistItem:
    """The ``gh`` item from ``gh auth status``'s result: ok on exit 0."""
    if path is None or result is None:
        return _missing("gh", _NOT_ON_PATH, GH_FIX)
    if result.is_timed_out:
        return _missing("gh", _TIMED_OUT, GH_LOGIN_FIX)
    if result.returncode is None:
        return _missing("gh", "cannot run gh auth status", GH_LOGIN_FIX)
    if result.returncode != 0:
        return _missing("gh", f"gh auth status exited {result.returncode}", GH_LOGIN_FIX)
    return _ok("gh", "logged in")


def tracker_item(
    *, transport: Literal["api", "mcp"], is_key_set: bool, has_claude: bool
) -> ChecklistItem:
    """The ``tracker`` item for the effective transport; the key's value is never read here."""
    if transport == "mcp":
        if not has_claude:
            return _missing("tracker", "transport mcp needs claude on PATH", CLAUDE_FIX)
        return _ok(
            "tracker",
            "transport mcp: Linear through claude -p (its Linear MCP server is not checked)",
        )
    if not is_key_set:
        return _missing("tracker", "LINEAR_API_KEY is not set (transport api)", TRACKER_KEY_FIX)
    return _ok("tracker", "LINEAR_API_KEY set (transport api)")


def _versioned_item(
    tool: _VersionedTool, path: str | None, result: ProbeResult | None
) -> ChecklistItem:
    if path is None or result is None:
        return _missing(tool.item, _NOT_ON_PATH, tool.absent_fix)
    if result.is_timed_out:
        return _missing(tool.item, _TIMED_OUT, tool.unreadable_fix)
    version = version_in(result.stdout) if result.returncode == 0 else None
    if version is None:
        return _missing(tool.item, _UNREADABLE, tool.unreadable_fix)
    shown = ".".join(str(part) for part in version)
    if version < tool.minimum:
        return _missing(tool.item, f"{shown}, need {tool.minimum_text} or newer", tool.old_fix)
    return _ok(tool.item, shown)


def _ok(item: str, detail: str) -> ChecklistItem:
    return ChecklistItem(state=State.OK, item=item, detail=detail, fix=None)


def _missing(item: str, detail: str, fix: str) -> ChecklistItem:
    return ChecklistItem(state=State.MISSING, item=item, detail=detail, fix=fix)
