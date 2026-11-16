"""``sandbox.workflow``: the hub's own commands work inside the sandbox it turns on (AGH-134).

``.claude/settings.json`` is read as ``settings.weakening`` reads it; a missing or unreadable file
is that rule's finding, not this one's. With ``sandbox.enabled`` not ``true`` there is nothing to
check: one info says so. With it on, an error names each of ``WORKFLOW_EXCLUDED_COMMANDS``
missing from ``sandbox.excludedCommands`` (without them ``hub worktree``'s fetch, pushes and
``gh`` fail inside the sandbox). When the snapshot carries remote probes (``hub doctor`` run from
a Claude Code session, so sandboxed itself), each repo whose ``git ls-remote origin`` failed
gets a warning: a ``hub worktree`` that runs sandboxed fails the same way, so the fix names the
bare call and the ``--no-fetch`` path.
"""

from collections.abc import Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.settings_rules import SETTINGS_PATH, load_settings
from agent_hub.core.doctor.snapshot import DoctorSnapshot, RemoteProbe
from agent_hub.core.hub_config.doctor_rules import (
    RULE_MODULES,
    SANDBOX_WORKFLOW_RULE,
    Severity,
)
from agent_hub.core.hub_files.sandbox_settings import WORKFLOW_EXCLUDED_COMMANDS
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.json_form import InvalidJsonError, JsonValue

OFF: Final = "sandbox.enabled is not true: the sandbox is off, nothing to check"
OFF_FIX: Final = "none needed; hub sync's base settings turn the sandbox on"
MISSING: Final = (
    "sandbox.excludedCommands lacks {commands}: inside the sandbox the hub's own fetch, push,"
    " gh and worktree commands fail"
)
SYNC_FIX: Final = "run hub sync"
UNREACHABLE: Final = (
    "git ls-remote origin fails inside this sandboxed session ({problem}); a hub worktree that"
    " runs sandboxed fails the same way"
)
UNREACHABLE_FIX: Final = (
    "run ./hub worktree <name> as a Bash call of its own (no cd &&, pipe or redirect), or a bare"
    " git fetch origin <branch> with ../{dir} as the cwd, then ./hub worktree --no-fetch <name>"
)


def _sandbox_workflow(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    sandbox = _sandbox(snapshot)
    if sandbox is None:
        return
    if sandbox.get("enabled") is not True:
        yield _finding(Severity.INFO, path=SETTINGS_PATH, message=OFF, fix=OFF_FIX)
        return
    excluded = sandbox.get("excludedCommands")
    held = excluded if isinstance(excluded, list) else []
    missing = [command for command in WORKFLOW_EXCLUDED_COMMANDS if command not in held]
    if missing:
        message = MISSING.format(commands=", ".join(missing))
        yield _finding(Severity.ERROR, path=SETTINGS_PATH, message=message, fix=SYNC_FIX)
    for probe in snapshot.remote_probes or ():
        if probe.problem is not None:
            yield _unreachable(probe)


def _sandbox(snapshot: DoctorSnapshot) -> dict[str, JsonValue] | None:
    """The ``sandbox`` object of ``settings.json`` (empty when absent); ``None`` when the file
    is missing, not a regular file or not JSON: ``settings.weakening`` reports those."""
    entry = snapshot.hub.entries.get(SETTINGS_PATH)
    if not isinstance(entry, FileEntry) or entry.content is None:
        return None
    try:
        document = load_settings(entry.content)
    except InvalidJsonError:
        return None
    if not isinstance(document, dict):
        return None
    sandbox = document.get("sandbox")
    return sandbox if isinstance(sandbox, dict) else {}


def _unreachable(probe: RemoteProbe) -> Finding:
    return _finding(
        Severity.WARNING,
        path=f"../{probe.dir}",
        message=UNREACHABLE.format(problem=probe.problem),
        fix=UNREACHABLE_FIX.format(dir=probe.dir),
    )


def _finding(severity: Severity, *, path: str, message: str, fix: str) -> Finding:
    return Finding(
        rule=SANDBOX_WORKFLOW_RULE,
        severity=severity,
        path=path,
        line=None,
        message=message,
        fix=fix,
    )


SANDBOX_WORKFLOW: Final = Rule(
    id=SANDBOX_WORKFLOW_RULE,
    severity=Severity.ERROR,
    summary="settings.json lets the hub's own commands out of the sandbox, and the remotes answer",
    module=RULE_MODULES.get(SANDBOX_WORKFLOW_RULE),
    reads=frozenset({Read.REMOTES}),
    check=_sandbox_workflow,
)
