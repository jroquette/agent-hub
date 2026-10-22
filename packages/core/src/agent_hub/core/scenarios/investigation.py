"""An interactive scenario run's investigation: its gate, its answers and the proposal an agent
records for it (P-5, P-8, AM-1, AM-3, AM-11; docs/design/scenarios.md § Investigation).

A divergence of an ``action`` or ``expect`` step (not a ``config`` failure) pauses an
interactive scenario run at the gate ``<step>__investigation`` (``investigation_gate``), a
``choice`` answered with ``pick`` (the option id as text), ``retry`` or ``stop``. A scenario run
opens at most ``MAX_INVESTIGATIONS``; the next divergence fails it as in regression mode. Which
gate is an investigation's comes from the run's record (an ``investigation`` line names its
``gate``), never from the id's suffix.

``parse_proposal`` reads what ``hub scenario propose`` gets on stdin, a fixed schema of
untrusted text: ``{"findings": [{"title", "text", "evidence"?}], "options": [{"summary",
"steps": [{"action", "with"?}]}]}``, unknown keys refused, every bound of
``docs/design/scenarios.md`` § Events and bounds checked (the first problem is the error), then
every text redacted of the secret shapes (``secret_shapes.redact_shapes``).

The investigation session's tools (P-17, AM-3, AM-4 safety 1): ``tool_verdict`` judges each call
the session's ``PreToolUse`` hook sees against a ``ToolPolicy`` (the hub's real path, its
``actions/`` folder, every declared env file's real path and the run). ``Read``, ``Glob`` and
``Grep`` pass only inside the workspace (the folder holding the hub and its repos, E-13) and
never on a declared env file, both by resolved real path (a symlink, a ``..`` or a relative form
is caught); a ``Glob`` whose pattern can reach one, or a ``Grep`` on one or on the folder
holding one, is denied (E-5: a folder above with no filter passes, the env file being
git-ignored). A ``Grep`` filter becomes ripgrep globs that override ``.gitignore``, split in
ways not worth mimicking, so a ``Grep`` with any filter is denied under a root holding a
declared env file at any depth. The three are denied under ``/proc`` too, where a running
action's environment (its env file's values) can be read, and a ``Glob`` or ``Grep`` of the
whole file system with it. ``Write`` passes only under ``actions/<pack>/``. ``Bash`` passes only
for ``./hub action list|plan …``, ``./hub action run … --run <run>`` and ``./hub scenario
propose --run <run>``, each word plain (no shell metacharacter); the proposal's JSON may follow
``propose`` as one quoted here-document (``<<'END'``), whose body the shell never expands. Every
other tool is denied. A verdict's reason names the tool and the rule, never a path's content.
This is not a sandbox (known limit 2).
"""

import os
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Final, Self

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.secret_shapes import redact_shapes

INVESTIGATION_SUFFIX: Final = "__investigation"
# The ``reason`` of an investigation's ``gate.request`` event.
INVESTIGATION_REASON: Final = "investigation"
PICK: Final = "pick"
RETRY: Final = "retry"
STOP: Final = "stop"
CHOICES: Final = (PICK, RETRY, STOP)
MAX_INVESTIGATIONS: Final = 10
# Proposals one investigation records (owner decision, AGH-360 review Q7).
MAX_PROPOSALS: Final = 10
MAX_PROPOSAL_BYTES: Final = 256 * 1024
MAX_FINDINGS: Final = 20
MAX_TITLE_CHARS: Final = 120
MAX_TEXT_CHARS: Final = 2000
MAX_OPTIONS: Final = 5
MAX_SUMMARY_CHARS: Final = 300
MAX_STEPS: Final = 10
_SHOWN_KEY_CHARS: Final = 40


class ProposalError(AgentHubError):
    """A proposal that does not fit the schema or its bounds: the first problem, plainly."""


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    title: str
    text: str
    evidence: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class ProposedStep:
    """One step of an option: an action reference and its ``with`` values."""

    action: str
    inputs: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True, slots=True)
class Option:
    summary: str
    steps: tuple[ProposedStep, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class Proposal:
    findings: tuple[Finding, ...]
    options: tuple[Option, ...]


def investigation_gate(step: str) -> str:
    """The id of the investigation gate after ``step`` (both as recorded)."""
    return f"{step}{INVESTIGATION_SUFFIX}"


def option_id(index: int) -> str:
    """The id an option is picked by: ``o<n>``, its place in the proposal from 1."""
    return f"o{index}"


def parse_proposal(data: bytes) -> Proposal:
    """The proposal ``data`` holds, its texts redacted; raises ``ProposalError``."""
    if len(data) > MAX_PROPOSAL_BYTES:
        raise ProposalError(f"the proposal is larger than {MAX_PROPOSAL_BYTES} bytes")
    try:
        value = load_json_bytes(data, strict=True)
    except InvalidJsonError:
        raise ProposalError("the proposal is not one JSON value in UTF-8") from None
    top = _object(value, "the proposal", required=("findings", "options"), allowed=())
    findings = _items(top["findings"], "findings", MAX_FINDINGS)
    options = _items(top["options"], "options", MAX_OPTIONS)
    return Proposal(
        findings=tuple(_finding(item, n) for n, item in enumerate(findings, 1)),
        options=tuple(_option(item, n) for n, item in enumerate(options, 1)),
    )


def _finding(value: JsonValue, number: int) -> Finding:
    where = f"finding {number}"
    given = _object(value, where, required=("title", "text"), allowed=("evidence",))
    return Finding(
        title=_text(given["title"], f"{where}: title", MAX_TITLE_CHARS, empty=False),
        text=_text(given["text"], f"{where}: text", MAX_TEXT_CHARS),
        evidence=_text(given.get("evidence", ""), f"{where}: evidence", MAX_TEXT_CHARS),
    )


def _option(value: JsonValue, number: int) -> Option:
    where = f"option {number}"
    given = _object(value, where, required=("summary", "steps"), allowed=())
    steps = _items(given["steps"], f"{where}: steps", MAX_STEPS)
    return Option(
        summary=_text(given["summary"], f"{where}: summary", MAX_SUMMARY_CHARS, empty=False),
        steps=tuple(_step(item, f"{where} step {n}") for n, item in enumerate(steps, 1)),
    )


def _step(value: JsonValue, where: str) -> ProposedStep:
    given = _object(value, where, required=("action",), allowed=("with",))
    action = _text(given["action"], f"{where}: action", MAX_TITLE_CHARS, empty=False)
    raw = given.get("with", {})
    if not isinstance(raw, dict) or not all(
        isinstance(item, str | int | float) for item in raw.values()
    ):
        raise ProposalError(f"{where}: with must map names to text, numbers or booleans")
    inputs = {
        redact_shapes(key): redact_shapes(item) if isinstance(item, str) else item
        for key, item in raw.items()
    }
    return ProposedStep(action=action, inputs=inputs)


def _object(
    value: JsonValue, where: str, *, required: Sequence[str], allowed: Sequence[str]
) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProposalError(f"{where} must be an object")
    if unknown := [key for key in value if key not in (*required, *allowed)]:
        shown = unknown[0][:_SHOWN_KEY_CHARS]
        raise ProposalError(f"{where} has an unknown key {shown!r}")
    if missing := [key for key in required if key not in value]:
        raise ProposalError(f"{where} needs {missing[0]}")
    return value


def _items(value: JsonValue, where: str, most: int) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ProposalError(f"{where} must be a list")
    if len(value) > most:
        raise ProposalError(f"{where}: at most {most}")
    return value


def _text(value: JsonValue, where: str, most: int, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > most or (not empty and not value.strip()):
        least = 0 if empty else 1
        raise ProposalError(f"{where} must be text of {least} to {most} characters")
    return redact_shapes(value)


# The investigation session's built-in tools; the hook (``tool_verdict``) holds each call.
INVESTIGATION_TOOLS: Final = ("Read", "Glob", "Grep", "Write", "Bash")
ACTIONS_FOLDER: Final = "actions"
HUB_COMMAND: Final = "./hub"
_WORD = re.compile(r"[A-Za-z0-9_./:=@,+%-]+")
_HEREDOC = re.compile(r"<<'(?P<end>[A-Za-z_][A-Za-z0-9_]{0,31})'")
_GLOB_CHARACTERS: Final = frozenset("*?[{")
_RUN_FLAG: Final = "--run"
# Where a process's environment can be read (an action's, with its env file's values).
_PROCESS_FILES: Final = ("/proc", "/dev/fd")


class WorkspaceRootError(AgentHubError):
    """A read root (the hub or a declared repo) that is ``/``, the home folder or one of its
    ancestors: reads there would reach the developer's own credentials, so no investigation
    policy is built (no session starts)."""


class ToolPolicy(BaseModel):
    """What the investigation session may touch: ``workdir`` (the hub's real path) resolves a
    relative path, ``read_roots`` (the real paths of the hub and of each declared repo present)
    are where ``Read``, ``Glob`` and ``Grep`` may look, ``actions`` is where ``Write`` may
    write (a pack's folder below it), ``env_files`` are the declared env files' real paths and
    ``run_id`` the scenario run its ``./hub`` commands must name. It holds paths only, never an
    env file's content."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    workdir: str
    read_roots: tuple[str, ...]
    actions: str
    env_files: tuple[str, ...]
    run_id: str

    @classmethod
    def of(
        cls, *, hub: str, env_files: Iterable[str], run_id: str, repos: Iterable[str] = ()
    ) -> Self:
        """The policy of ``run_id`` in ``hub``; ``repos`` (``hub.json``'s ``repos[].dir``) and
        ``env_files`` are relative to the workspace (the folder holding the hub and its repos),
        as the config declares them. A repo that is absent is not a root.
        ``WorkspaceRootError`` when a root is ``/``, the home folder or one of its ancestors."""
        real = os.path.realpath(hub)
        workspace = os.path.dirname(real)
        repo_roots = (os.path.realpath(os.path.join(workspace, repo)) for repo in repos)
        roots = tuple(dict.fromkeys([real, *(root for root in repo_roots if os.path.isdir(root))]))
        home = os.path.realpath(Path.home())
        for root in roots:
            if root == os.path.dirname(root) or home == root or home.startswith(f"{root}/"):
                msg = (
                    f"investigation reads at {root} would reach the home folder or the root:"
                    " keep the hub and its repos in folders of their own"
                )
                raise WorkspaceRootError(msg)
        resolved = (os.path.realpath(os.path.join(workspace, path)) for path in env_files)
        return cls(
            workdir=real,
            read_roots=roots,
            actions=os.path.realpath(os.path.join(real, ACTIONS_FOLDER)),
            env_files=tuple(dict.fromkeys(resolved)),
            run_id=run_id,
        )


@dataclass(frozen=True, kw_only=True, slots=True)
class ToolVerdict:
    """Whether a tool call may run; ``reason`` says why not."""

    allowed: bool
    reason: str = ""


_ALLOWED: Final = ToolVerdict(allowed=True)


def _denied(reason: str) -> ToolVerdict:
    return ToolVerdict(allowed=False, reason=f"investigation: {reason}")


def tool_verdict(policy: ToolPolicy, tool: str, tool_input: Mapping[str, object]) -> ToolVerdict:
    """Whether the investigation session may call ``tool`` with ``tool_input`` (P-17)."""
    match tool:
        case "Read":
            return _read_verdict(policy, tool_input)
        case "Glob":
            return _glob_verdict(policy, tool_input)
        case "Grep":
            return _grep_verdict(policy, tool_input)
        case "Write":
            return _write_verdict(policy, tool_input)
        case "Bash":
            return _bash_verdict(policy, tool_input)
        case _:
            return _denied(f"{tool[:64]} is not one of the investigation's tools")


def _env_file_denied(tool: str) -> ToolVerdict:
    return _denied(f"{tool} reaches the env file of a declared environment")


def _outside_denied(tool: str) -> ToolVerdict:
    return _denied(f"{tool} reaches outside the hub and its declared repos")


def _process_files_denied(tool: str) -> ToolVerdict:
    return _denied(f"{tool} reaches the processes' files (/proc), where credentials can be read")


def _in_process_files(real: str) -> bool:
    return any(real == root or real.startswith(f"{root}/") for root in _PROCESS_FILES)


class _Paths:
    """The policy's env files, compared ignoring case (stricter, never looser)."""

    def __init__(self, policy: ToolPolicy) -> None:
        self.workdir = policy.workdir
        self.roots = policy.read_roots
        self.env_files = tuple(path.lower() for path in policy.env_files)

    def resolve(self, path: str) -> str:
        return os.path.realpath(os.path.join(self.workdir, os.path.expanduser(path)))

    def inside(self, real: str) -> bool:
        """Whether ``real`` is a read root (the hub or a declared repo) or below one."""
        return any(real == root or real.startswith(f"{root}/") for root in self.roots)

    def is_env_file(self, real: str) -> bool:
        return real.lower() in self.env_files

    def holds(self, folder: str) -> bool:
        return any(os.path.dirname(path) == folder.lower() for path in self.env_files)

    def under(self, folder: str) -> list[str]:
        """Each env file below ``folder``, as a path from it."""
        base = folder.lower().rstrip("/") + "/"
        return [path[len(base) :] for path in self.env_files if path.startswith(base)]


def _text_input(tool_input: Mapping[str, object], key: str) -> str | None:
    value = tool_input.get(key)
    return value if isinstance(value, str) else None


def _read_verdict(policy: ToolPolicy, tool_input: Mapping[str, object]) -> ToolVerdict:
    path = _text_input(tool_input, "file_path")
    if not path:
        return _denied("Read needs a file_path")
    paths = _Paths(policy)
    real = paths.resolve(path)
    if _in_process_files(real):
        return _process_files_denied("Read")
    if not paths.inside(real):
        return _outside_denied("Read")
    return _env_file_denied("Read") if paths.is_env_file(real) else _ALLOWED


def _segments_reach(segments: Sequence[str], parts: Sequence[str]) -> bool:
    """Whether glob ``segments`` match all of ``parts``: ``*`` within a part, ``**`` any run of
    parts; a segment with braces or ``..`` counts as reaching. One pass per segment."""
    if any(segment == ".." for segment in segments):
        return True
    reach = [True] + [False] * len(parts)
    for segment in segments:
        if segment == "**":
            for index in range(1, len(reach)):
                reach[index] = reach[index] or reach[index - 1]
        else:
            pattern = "*" if "{" in segment else segment
            reach = [False] + [
                reach[index] and fnmatchcase(parts[index], pattern) for index in range(len(parts))
            ]
    return reach[-1]


def _glob_verdict(policy: ToolPolicy, tool_input: Mapping[str, object]) -> ToolVerdict:
    pattern = _text_input(tool_input, "pattern")
    if not pattern:
        return _denied("Glob needs a pattern")
    if ".." in pattern.split("/"):
        return _outside_denied("Glob")
    paths = _Paths(policy)
    root = paths.resolve(_text_input(tool_input, "path") or ".")
    parts = os.path.join(root, os.path.expanduser(pattern)).split("/")
    first = next((index for index, part in enumerate(parts) if _GLOB_CHARACTERS & set(part)), None)
    if first is None:
        real = paths.resolve("/".join(parts))
        if _in_process_files(real):
            return _process_files_denied("Glob")
        if not paths.inside(real):
            return _outside_denied("Glob")
        return _env_file_denied("Glob") if paths.is_env_file(real) else _ALLOWED
    base = paths.resolve("/".join(parts[:first]) or "/")
    rest = [part.lower() for part in parts[first:] if part]
    if _in_process_files(base) or (base == "/" and _segments_reach(rest[:1], ["proc"])):
        return _process_files_denied("Glob")
    if not paths.inside(base):
        return _outside_denied("Glob")
    reached = any(_segments_reach(rest, rel.split("/")) for rel in paths.under(base))
    return _env_file_denied("Glob") if reached else _ALLOWED


def _grep_verdict(policy: ToolPolicy, tool_input: Mapping[str, object]) -> ToolVerdict:
    paths = _Paths(policy)
    root = paths.resolve(_text_input(tool_input, "path") or ".")
    if root == "/" or _in_process_files(root):
        return _process_files_denied("Grep")
    if not paths.inside(root):
        return _outside_denied("Grep")
    if paths.is_env_file(root):
        return _env_file_denied("Grep")
    if not os.path.isdir(root):
        return _ALLOWED
    grep_glob = _text_input(tool_input, "glob") or ""
    if not grep_glob.strip():
        return _env_file_denied("Grep") if paths.holds(root) else _ALLOWED
    if ".." in grep_glob:
        return _outside_denied("Grep")
    if paths.under(root):
        return _env_file_denied("Grep")
    return _ALLOWED


def _write_verdict(policy: ToolPolicy, tool_input: Mapping[str, object]) -> ToolVerdict:
    path = _text_input(tool_input, "file_path")
    paths = _Paths(policy)
    real = paths.resolve(path) if path else ""
    base = policy.actions.rstrip("/") + "/"
    inside = real.startswith(base) and len(real[len(base) :].split("/")) >= 2  # noqa: PLR2004 -- pack, file
    if not inside or paths.is_env_file(real):
        return _denied("Write only writes under actions/<pack>/")
    return _ALLOWED


def _bash_verdict(policy: ToolPolicy, tool_input: Mapping[str, object]) -> ToolVerdict:
    command = _text_input(tool_input, "command") or ""
    head, newline, body = command.partition("\n")
    words = head.split(" ")
    if newline and not _closes_heredoc(words, body):
        words = []
    if newline:
        words = words[:-1]
    if (
        words
        and all(_WORD.fullmatch(word) for word in words)
        and _hub_call(words, policy, heredoc=bool(newline))
    ):
        return _ALLOWED
    return _denied(
        f"Bash runs only {HUB_COMMAND} action list|plan, {HUB_COMMAND} action run … "
        f"{_RUN_FLAG} {policy.run_id} and {HUB_COMMAND} scenario propose {_RUN_FLAG} "
        f"{policy.run_id}, plain words with no shell metacharacter"
    )


def _closes_heredoc(words: Sequence[str], body: str) -> bool:
    """Whether ``words`` end with a quoted here-document operator that ``body`` closes on its
    last line and on no line before (so nothing runs after it)."""
    found = _HEREDOC.fullmatch(words[-1]) if words else None
    if found is None:
        return False
    lines = body.removesuffix("\n").split("\n")
    end = found.group("end")
    return lines[-1] == end and end not in lines[:-1]


def _hub_call(words: Sequence[str], policy: ToolPolicy, *, heredoc: bool) -> bool:
    if words[0] != HUB_COMMAND or len(words) < 3:  # noqa: PLR2004 -- ./hub, group, command
        return False
    command = (words[1], words[2])
    rest = list(words[3:])
    if command == ("scenario", "propose"):
        return rest == [_RUN_FLAG, policy.run_id]
    if heredoc:
        return False
    if command in {("action", "list"), ("action", "plan")}:
        return not any(word.startswith(_RUN_FLAG) for word in rest)
    if command == ("action", "run"):
        flags = [index for index, word in enumerate(rest) if word.startswith(_RUN_FLAG)]
        return (
            len(flags) == 1
            and rest[flags[0]] == _RUN_FLAG
            and rest[flags[0] + 1 : flags[0] + 2] == [policy.run_id]
        )
    return False


def investigation_prompt(*, run_id: str, scenario: str, environment: str, step: str) -> str:
    """The system prompt of the investigation session of ``run_id``, paused after ``step``
    diverged: its role, its read-only means and the proposal's command and schema (AM-3)."""
    run = f"{_RUN_FLAG} {run_id}"
    return "\n".join(
        (
            f"You investigate scenario run {run_id} (scenario {scenario}, environment"
            f" {environment}). Its step {step} diverged and the run is paused until a person"
            " answers. Find out why and propose what to do next. You change nothing in the"
            " environment: your means are read-only.",
            "- Read, Glob and Grep the hub and its repos; a declared env file is refused.",
            f"- {HUB_COMMAND} action list, {HUB_COMMAND} action plan <action> --env"
            f" {environment}, and {HUB_COMMAND} action run <action> {run} --input"
            " name=value: read actions only; the hub gives the action its credentials, which"
            " you never see.",
            "- Write only draft actions under actions/<pack>/; a person commits one before it"
            " can run.",
            "Bash runs only those commands and the proposal below, as plain words: no pipe,"
            " redirection, variable, quote or other shell metacharacter.",
            "When you know enough, record your proposal (JSON, this exact form):",
            f"{HUB_COMMAND} scenario propose {run} <<'PROPOSAL'",
            '{"findings": [{"title": "...", "text": "...", "evidence": "..."}], "options":'
            ' [{"summary": "...", "steps": [{"action": "<pack>/<name>", "with": {"name":'
            ' "value"}}]}]}',
            "PROPOSAL",
            f"At most {MAX_FINDINGS} findings and {MAX_OPTIONS} options of at most {MAX_STEPS}"
            " steps; a new proposal replaces the last. Then wait for the person: they pick an"
            " option, ask for a new proposal, retry the step or stop the run.",
        )
    )
