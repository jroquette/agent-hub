"""The ``hub setup`` checklist: its items, their lines, the summary and the exit rule; pure.

Each item prints as ``f"{state:<7} {item}: {detail}"``, then `` Fix: <fix>`` when it has one, then
its sub-lines indented 8 spaces. The tool items read what a probe gave (``ProbeResult``); the cli
runs the probes, git and the doctor and gives their outcome to the identity, repo and doctor
items. No text here names a credential's value or a remote URL: the tracker item reads only
whether ``LINEAR_API_KEY`` is set, and a repo line names ``owner/name`` and the scheme. An
identity value is free text from a file or git, so it is shown through ``one_line``: a control
character or a bidi override is escaped, never sent to the terminal.
"""

import re
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Literal, NamedTuple

from agent_hub.core.hub_config.effective_identity import IdentityKey, Sourced, email_giver
from agent_hub.core.hub_config.local_config import LOCAL_FILE_MAX_BYTES
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_config.workspace_repos import WorkspaceRepo

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

IDENTITY_FILE_FIX: Final = (
    "./hub setup --yes, or write hub.local.json yourself (docs/design/developer-identity.md)"
)
PREFIX_FIX: Final = (
    "write hub.local.json with project.branch_prefix (docs/design/developer-identity.md)"
)
INVALID_LOCAL_FIX: Final = "fix hub.local.json (docs/design/developer-identity.md)"
RERUN_FIX: Final = "./hub setup"
SHORTER_GIT_FIX: Final = "shorten git's user.name or user.email in the hub, then ./hub setup"
GITIGNORE_FIX: Final = "add the line hub.local.json to .gitignore and commit it"
CLONE_FIX: Final = (
    "check that your git credentials can read github.com/{github} (e.g. gh auth setup-git),"
    " then ./hub setup"
)
FETCH_FIX: Final = "git -C ../{dir} fetch origin"
MOVE_AWAY_FIX: Final = "move ../{dir} away, then ./hub setup"
DOCTOR_FIX: Final = "fix each error below, then ./hub doctor"

_SUB_LINE_INDENT: Final = " " * 8
_NOT_ON_PATH: Final = "not on PATH"
_UNREADABLE: Final = "cannot read its version"
_TIMED_OUT: Final = f"timed out after {PROBE_TIMEOUT_SECONDS:g} s"
# Tool output is untrusted: each part is capped, so the search stays linear and ``int`` never
# sees more digits than it accepts. A longer number is no version, not a truncated one.
_VERSION_PART_DIGITS: Final = 6
_VERSION_PART: Final = f"([0-9]{{1,{_VERSION_PART_DIGITS}}})"
_VERSION: Final = re.compile(
    rf"(?<![0-9]){_VERSION_PART}\.{_VERSION_PART}\.{_VERSION_PART}(?![0-9])"
)

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


class IdentityGap(StrEnum):
    """Why the identity item is missing, for the gaps whose text takes no value."""

    DECLINED = "declined"
    NO_TERMINAL = "no-terminal"
    INVALID_LOCAL = "invalid-local"
    APPEARED = "appeared"
    NO_PREFIX = "no-prefix"
    TOO_LARGE = "too-large"


class RepoOutcome(StrEnum):
    """What the repo step did with one ``repos`` entry."""

    CLONED = "cloned"
    FETCHED = "fetched"
    CLONE_FAILED = "clone-failed"
    CLONE_TIMED_OUT = "clone-timed-out"
    FETCH_FAILED = "fetch-failed"
    FETCH_TIMED_OUT = "fetch-timed-out"
    NOT_A_REPO = "not-a-repo"
    GIT_NOT_FOUND = "git-not-found"


class _Text(NamedTuple):
    detail: str
    fix: str | None


_IDENTITY_GAPS: Final[Mapping[IdentityGap, _Text]] = {
    IdentityGap.DECLINED: _Text("hub.local.json not written (declined)", IDENTITY_FILE_FIX),
    IdentityGap.NO_TERMINAL: _Text(
        "hub.local.json not written (stdin is not a terminal)", IDENTITY_FILE_FIX
    ),
    IdentityGap.INVALID_LOCAL: _Text("hub.local.json is invalid", INVALID_LOCAL_FIX),
    IdentityGap.APPEARED: _Text("hub.local.json appeared while writing; left as is", RERUN_FIX),
    # The sub-lines (``no_prefix_lines``) list where a prefix can be set.
    IdentityGap.NO_PREFIX: _Text("no branch prefix", PREFIX_FIX),
    # Only git's values are free in length: the proposal holds nothing else (and the prefix).
    IdentityGap.TOO_LARGE: _Text(
        f"hub.local.json not written (larger than {LOCAL_FILE_MAX_BYTES} bytes)", SHORTER_GIT_FIX
    ),
}
_GIT_KEYS: Final = {IdentityKey.AUTHOR_NAME: "user.name", IdentityKey.AUTHOR_EMAIL: "user.email"}
# What a value git holds but the key's shape refuses is; the value itself is never repeated.
_GIT_REJECTED: Final = {
    IdentityKey.AUTHOR_NAME: "git's user.name holds a control character",
    IdentityKey.AUTHOR_EMAIL: "git's user.email is not an email address",
}
_GIT_SET_COMMANDS: Final = {
    IdentityKey.AUTHOR_NAME: 'git config user.name "<Your Name>"',
    IdentityKey.AUTHOR_EMAIL: "git config user.email <you@example.com>",
}
# Filled with ``str.format``: ``dir``, ``github``, ``scheme``, ``returncode``, ``seconds``.
# Each outcome's text needs the ``repo_item`` argument named here; it is refused without it.
_REPO_TEXTS: Final[Mapping[RepoOutcome, _Text]] = {
    RepoOutcome.CLONED: _Text("cloned {github} into ../{dir} ({scheme})", None),
    RepoOutcome.FETCHED: _Text("present, fetched", None),
    RepoOutcome.CLONE_FAILED: _Text("clone failed (git exit {returncode})", CLONE_FIX),
    RepoOutcome.CLONE_TIMED_OUT: _Text("clone timed out after {seconds} s", CLONE_FIX),
    RepoOutcome.FETCH_FAILED: _Text("fetch failed (git exit {returncode})", FETCH_FIX),
    RepoOutcome.FETCH_TIMED_OUT: _Text("fetch timed out after {seconds} s", FETCH_FIX),
    RepoOutcome.NOT_A_REPO: _Text(
        "../{dir} exists but is not a git repository; left untouched", MOVE_AWAY_FIX
    ),
    RepoOutcome.GIT_NOT_FOUND: _Text("git not found", GIT_FIX),
}

_REPO_ARGUMENTS: Final[Mapping[RepoOutcome, str]] = {
    RepoOutcome.CLONED: "scheme",
    RepoOutcome.CLONE_FAILED: "returncode",
    RepoOutcome.FETCH_FAILED: "returncode",
    RepoOutcome.CLONE_TIMED_OUT: "timeout_seconds",
    RepoOutcome.FETCH_TIMED_OUT: "timeout_seconds",
}


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
    minimum_text=".".join(str(part) for part in UV_MINIMUM),
    absent_fix=UV_FIX,
    old_fix=UV_UPDATE_FIX,
    unreadable_fix="uv --version",
)
_PYTHON: Final = _VersionedTool(
    item="python3",
    minimum=PYTHON_MINIMUM,
    minimum_text=".".join(str(part) for part in PYTHON_MINIMUM[:2]),
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
    """The first ``X.Y.Z`` of the tool's output read as UTF-8, or None when it has none.

    Each part is 1 to 6 ASCII digits and not part of a longer number.
    """
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


def identity_text(values: Mapping[IdentityKey, Sourced]) -> str:
    """The prefix, then ``name <email>`` (or the one given), joined by ``, ``; each escaped.

    Every value goes through ``one_line``, so a non-printable character shows as its escape.
    """
    prefix, name, email = (
        values.get(key)
        for key in (IdentityKey.BRANCH_PREFIX, IdentityKey.AUTHOR_NAME, IdentityKey.AUTHOR_EMAIL)
    )
    parts = [one_line(prefix.value)] if prefix is not None else []
    if name is not None and email is not None:
        parts.append(f"{one_line(name.value)} <{one_line(email.value)}>")
    else:
        parts.extend(one_line(given.value) for given in (name, email) if given is not None)
    return ", ".join(parts)


def identity_written_item(values: Mapping[IdentityKey, Sourced]) -> ChecklistItem:
    """``identity`` after ``hub.local.json`` was written: only the written keys are named.

    Raises ``ValueError`` when ``values`` is empty: a written file holds at least one key.
    """
    return _ok("identity", f"wrote hub.local.json: {sourced_identity_text(values)}")


def identity_resolved_item(values: Mapping[IdentityKey, Sourced]) -> ChecklistItem:
    """``identity`` resolved from the files and git, each source named once, in key order.

    Raises ``ValueError`` when ``values`` is empty: an ok identity shows at least one value.
    """
    return _ok("identity", sourced_identity_text(values))


def identity_missing_item(gap: IdentityGap, *, sub_lines: Sequence[str] = ()) -> ChecklistItem:
    """``identity`` missing for ``gap``, with its sub-lines (file problems, no-prefix reasons)."""
    text = _IDENTITY_GAPS[gap]
    return ChecklistItem(
        state=State.MISSING,
        item="identity",
        detail=text.detail,
        fix=text.fix,
        sub_lines=tuple(sub_lines),
    )


def git_lacks_item(
    lacking: Collection[IdentityKey],
    *,
    rejected: Collection[IdentityKey] = (),
    git_problem: str | None = None,
) -> ChecklistItem:
    """``identity`` missing because git gives no valid ``user.name``/``user.email``.

    ``rejected`` are the ``lacking`` keys git holds a value of the wrong shape for: each is
    named as such, not as absent. ``git_problem`` (``git not found``, ``git timed out``) says
    why git gave no answer at all.
    """
    keys = [key for key in (IdentityKey.AUTHOR_NAME, IdentityKey.AUTHOR_EMAIL) if key in lacking]
    if not keys or IdentityKey.BRANCH_PREFIX in lacking:
        msg = "git lacks only author_name or author_email (git has no branch_prefix key)"
        raise ValueError(msg)
    if not set(rejected) <= set(keys):
        msg = "a rejected key is one git lacks a valid value for"
        raise ValueError(msg)
    absent = [_GIT_KEYS[key] for key in keys if key not in rejected]
    parts = ["git config in the hub has no " + " or ".join(absent)] if absent else []
    parts.extend(_GIT_REJECTED[key] for key in keys if key in rejected)
    commands = " and ".join(_GIT_SET_COMMANDS[key] for key in keys)
    return ChecklistItem(
        state=State.MISSING,
        item="identity",
        detail="; ".join(parts),
        fix=f"{commands}, then ./hub setup",
        sub_lines=() if git_problem is None else (f"git: {git_problem}",),
    )


def invalid_prefix_item(email: Sourced) -> ChecklistItem:
    """``identity`` missing because the effective email's local part is not a valid prefix.

    The text names where that email comes from: git's ``user.email``, or ``hub.json``'s (or
    ``hub.local.json``'s) ``project.author_email``.
    """
    local_part = one_line(email.value.rpartition("@")[0])
    return _missing(
        "identity",
        f'{email_giver(email)} gives "{local_part}", not a valid branch prefix',
        PREFIX_FIX,
    )


def write_error_item(error: str) -> ChecklistItem:
    """``identity`` missing because writing ``hub.local.json`` failed with ``error``.

    ``error`` is the ``OSError``'s ``strerror`` only, never ``str(error)``: that one carries
    the file's path.
    """
    return _missing("identity", f"could not write hub.local.json: {error}", IDENTITY_FILE_FIX)


def gitignore_item() -> ChecklistItem:
    """``gitignore``, printed only when git does not ignore ``hub.local.json``."""
    return _missing("gitignore", "hub.local.json is not ignored by git", GITIGNORE_FIX)


def repo_item(
    repo: WorkspaceRepo,
    outcome: RepoOutcome,
    *,
    scheme: Literal["ssh", "https"] | None = None,
    returncode: int | None = None,
    timeout_seconds: float | None = None,
) -> ChecklistItem:
    """``repo <dir>`` for ``outcome``; names ``owner/name`` and the scheme, never a URL.

    Raises ``ValueError`` when the outcome's text needs an argument not given: ``scheme`` for
    ``cloned``, ``returncode`` for a failure, ``timeout_seconds`` for a timeout.
    """
    given = {"scheme": scheme, "returncode": returncode, "timeout_seconds": timeout_seconds}
    needed = _REPO_ARGUMENTS.get(outcome)
    if needed is not None and given[needed] is None:
        msg = f"repo outcome {outcome} needs {needed}"
        raise ValueError(msg)
    text = _REPO_TEXTS[outcome]
    fields = {
        "dir": repo.dir,
        "github": repo.github,
        "scheme": scheme,
        "returncode": returncode,
        "seconds": f"{timeout_seconds:g}" if timeout_seconds is not None else None,
    }
    state = State.OK if outcome in {RepoOutcome.CLONED, RepoOutcome.FETCHED} else State.MISSING
    return ChecklistItem(
        state=state,
        item=f"repo {repo.dir}",
        detail=text.detail.format_map(fields),
        fix=None if text.fix is None else text.fix.format_map(fields),
    )


def doctor_item(*, totals: str, has_errors: bool, finding_lines: Sequence[str]) -> ChecklistItem:
    """``hub doctor``: its totals line, missing when it found an error; findings as sub-lines."""
    return ChecklistItem(
        state=State.MISSING if has_errors else State.OK,
        item="hub doctor",
        detail=totals,
        fix=DOCTOR_FIX if has_errors else None,
        sub_lines=tuple(finding_lines),
    )


def sourced_identity_text(values: Mapping[IdentityKey, Sourced]) -> str:
    """``identity_text`` of ``values``, then their distinct sources in key order in brackets.

    Raises ``ValueError`` when ``values`` is empty.
    """
    if not values:
        msg = "an identity item needs at least one identity value"
        raise ValueError(msg)
    # A derived prefix carries its email's source.
    sources = dict.fromkeys(values[key].source.value for key in IdentityKey if key in values)
    return f"{identity_text(values)} ({', '.join(sources)})"


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
