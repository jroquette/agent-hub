"""What a session is about (S1, L4): issue, workflow, repo and branch, derived from its events.

``label_signals`` reads the events (pure, order-independent); ``session_label`` builds the label
with ``issue`` left ``None``; ``with_issue`` finds the issue with the hub's ``LabelRules`` at read
time, so a ``hub.json`` change needs no refold. No match gives ``None``, never a guess.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final

from agent_hub.core.events.event import EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events
from agent_hub.core.sessions.session import SessionLabel
from agent_hub.core.workspace.worktree_name import issue_of_worktree

# Slash commands that run around the work, never the session's workflow when another exists.
ROUTINE_COMMANDS: Final = frozenset(
    {
        "/kickoff",
        "/handoff",
        "/clear",
        "/compact",
        "/resume",
        "/model",
        "/help",
        "/config",
        "/cost",
        "/status",
        "/exit",
    }
)
SKILL_TOOL: Final = "Skill"
_WORKTREES: Final = (".claude", "worktrees")


@dataclass(frozen=True, slots=True)
class LabelRules:
    """The hub's rules for finding an issue: its tracker team keys and branch prefix."""

    teams: tuple[str, ...]
    branch_prefix: str = ""


@dataclass(frozen=True, slots=True)
class LabelSignals:
    """What a session's events say about it: latest branch, ``cwd``, repo and workflows."""

    branch: str | None
    cwd: str | None
    repo: str | None
    workflows: tuple[str, ...]


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value.strip() else None


def workflow_name(name: str) -> str:
    """``name`` shown as a slash command: ``/<name>``, a ``<plugin>:`` prefix dropped."""
    bare = name.strip().removeprefix("/")
    return f"/{bare.rpartition(':')[2]}"


def _workflow_of(stored: StoredEvent) -> str | None:
    event = stored.event
    if event.type == EventType.MESSAGE and event.payload.get("role") == "user":
        command = _text(event.payload.get("slash_command"))
        return None if command is None else workflow_name(command)
    if event.type == EventType.TOOL_CALL and event.payload.get("tool") == SKILL_TOOL:
        skill = _text(event.payload.get("skill"))
        return None if skill is None else workflow_name(skill)
    return None


def label_signals(events: Iterable[StoredEvent]) -> LabelSignals:
    """The label signals of one session's events (any order, repeats allowed)."""
    ordered = canonical_events(events)
    branches = [b for s in ordered if (b := _text(s.event.payload.get("git_branch")))]
    starts = [
        cwd
        for stored in ordered
        if stored.event.type == EventType.SESSION_START
        and (cwd := _text(stored.event.payload.get("cwd")))
    ]
    workflows = [name for stored in ordered if (name := _workflow_of(stored))]
    return LabelSignals(
        branch=branches[-1] if branches else None,
        cwd=starts[-1] if starts else None,
        repo=next((stored.event.repo for stored in ordered if stored.event.repo), None),
        workflows=tuple(dict.fromkeys(workflows)),
    )


def worktree_of(cwd: str | None) -> str | None:
    """The folder name under ``.claude/worktrees/`` in ``cwd``, or None."""
    if cwd is None:
        return None
    parts = PurePosixPath(cwd).parts
    for index in range(len(parts) - 2):
        if parts[index : index + 2] == _WORKTREES:
            return parts[index + 2]
    return None


def main_workflow(workflows: Sequence[str]) -> str | None:
    """The first workflow that is not a routine command, else the first, else None."""
    return next((name for name in workflows if name not in ROUTINE_COMMANDS), None) or next(
        iter(workflows), None
    )


def session_label(signals: LabelSignals) -> SessionLabel:
    """The label of a session from its signals, ``issue`` left for ``with_issue``."""
    return SessionLabel(
        issue=None,
        workflow=main_workflow(signals.workflows),
        workflows=signals.workflows,
        repo=signals.repo,
        branch=signals.branch,
        worktree=worktree_of(signals.cwd),
    )


def _issue_of_branch(branch: str, rules: LabelRules) -> str | None:
    teams = "|".join(re.escape(team) for team in rules.teams)
    prefix = re.escape(rules.branch_prefix)
    found = re.match(rf"(?:{prefix})?({teams})-([1-9]\d*)\b", branch, flags=re.IGNORECASE)
    return None if found is None else f"{found.group(1).upper()}-{found.group(2)}"


def with_issue(label: SessionLabel, rules: LabelRules) -> SessionLabel:
    """``label`` with the issue its branch, else its worktree, names for ``rules``' teams."""
    issue = None
    if rules.teams:
        if label.branch is not None:
            issue = _issue_of_branch(label.branch, rules)
        if issue is None and label.worktree is not None:
            issue = issue_of_worktree(label.worktree, teams=rules.teams)
    return label.model_copy(update={"issue": issue})
