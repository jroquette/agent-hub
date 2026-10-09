"""Builders of synthetic domain objects for tests; fixtures never come from real transcripts."""

import copy
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from agent_hub.core.events.event import Event
from agent_hub.core.testing.fakes import FakeTrackerBackend, TrackerState
from agent_hub.core.tracker.tracker_client import Issue

# The Example of docs/design/project-config.md, a synthetic project.
_HUB_DOCUMENT: dict[str, Any] = {
    "$schema": "./hub.schema.json",
    "schema_version": 1,
    "platform": {"version": "0.2.0"},
    "project": {
        "name": "demo",
        "hub_repo": "acme/demo-hub",
        "branch_prefix": "jdoe/",
        "author_name": "Jane Doe",
        "author_email": "jane@example.com",
    },
    "tracker": {"kind": "linear", "team": "DEM"},
    "repos": [
        {
            "dir": "demo-api",
            "github": "acme/demo-api",
            "check_fast": "make check-fast",
            "check": "make check",
        }
    ],
    "guard": {"ask_before_edit": ["demo-api/docs/adr"]},
    "modules": {"cloud": {}, "bench": {}},
}


def an_event(**overrides: object) -> Event:
    """Build a valid synthetic event; ``source_id`` is unique per call unless overridden."""
    fields: dict[str, object] = {
        "project": "demo",
        "session": "session-1",
        "type": "tool.call",
        "timestamp": datetime(2026, 9, 27, 10, 0, 0, 123456, tzinfo=UTC),
        "source": "claude_code",
        "source_id": f"evt-{uuid4().hex}",
        "payload": {"tool": "search", "input": {"terms": ["alpha", "beta"], "limit": 3}},
    }
    return Event.model_validate(fields | overrides)


def events_to_jsonl(events: Iterable[Event]) -> str:
    """Write events as JSON Lines: one event per line, each line ending in a newline."""
    return "".join(f"{event.model_dump_json()}\n" for event in events)


def a_hub_document() -> dict[str, Any]:
    """Build a valid synthetic ``hub.json`` document as plain JSON data; a fresh copy per call."""
    return copy.deepcopy(_HUB_DOCUMENT)


def a_two_team_document() -> dict[str, Any]:
    """Build ``a_hub_document`` with the tracker teams ``APP`` and ``OPS``; a fresh copy."""
    document = a_hub_document()
    document["tracker"] = {"kind": "linear", "teams": ["APP", "OPS"]}
    return document


def a_second_repo() -> dict[str, Any]:
    """Build the ``repos`` entry ``demo-web``, a repo next to ``a_hub_document``'s ``demo-api``.

    Plain JSON data, a fresh copy per call: ``contract-sync`` needs two repos to name.
    """
    return {
        "dir": "demo-web",
        "github": "acme/demo-web",
        "check_fast": "make check-fast",
        "check": "make check",
    }


def a_conventions_document() -> dict[str, Any]:
    """Build the mixed hub: ``a_hub_document`` plus ``demo-web``, with conventions; a fresh copy.

    The project sets all three patterns; ``demo-api`` overrides only ``branch`` and
    ``demo-web`` sets none.
    """
    document = a_hub_document()
    document["project"]["conventions"] = {
        "branch": "{prefix}{ISSUE}-{slug}",
        "commit_title": "{ISSUE}: {type}({scope}): {summary}",
        "pr_title": "{ISSUE}: {type}({scope}): {summary}",
    }
    document["repos"][0]["conventions"] = {"branch": "feature/{issue_lower}/{slug}"}
    document["repos"].append(a_second_repo())
    return document


def a_guard_infra() -> dict[str, list[str]]:
    """Build a synthetic ``guard.infra`` value as plain JSON data; a fresh copy per call.

    ``allow`` names one development environment per covered tool's usual flag; ``prod_markers``
    names the production environment and a placeholder account id.
    """
    return {
        "allow": [
            r"--profile[= ]demo-dev\b",
            r"\bAWS_PROFILE=demo-dev\b",
            r"--(kube-)?context[= ]kind-demo\b",
            r"-var-file=dev\.tfvars\b",
            r"--stack[= ]demo/dev\b",
            r"--stage[= ]dev\b",
        ],
        "prod_markers": [r"\bdemo-prod\b", r"\b999999999999\b"],
    }


def an_issue(**overrides: object) -> Issue:
    """Build a synthetic open ``DEM`` issue; ``url`` follows ``id`` unless overridden."""
    fields: dict[str, object] = {
        "id": "DEM-1",
        "title": "Add a synthetic feature",
        "description": "A synthetic description.",
        "state": "Todo",
        "labels": ("agent-ready",),
    } | overrides
    fields.setdefault("url", f"https://linear.app/demo/issue/{fields['id']}")
    return Issue.model_validate(fields)


_OPEN_STATES = (
    TrackerState(name="Todo", closed=False),
    TrackerState(name="In Progress", closed=False),
)
_CLOSED_STATES = (
    TrackerState(name="Done", closed=True),
    TrackerState(name="Canceled", closed=True),
)

# (id, state, labels): ready ones in every state, a repo label, an unlabelled one, another team.
_SEEDED_ISSUES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("DEM-1", "Todo", ("agent-ready", "demo-api")),
    ("DEM-2", "In Progress", ("agent-ready",)),
    ("DEM-3", "Todo", ("agent-ready", "bug")),
    ("DEM-4", "Done", ("agent-ready",)),
    ("DEM-5", "Canceled", ("agent-ready",)),
    ("DEM-6", "Duplicate", ("agent-ready",)),
    ("DEM-7", "Todo", ()),
    ("OPS-1", "Todo", ("agent-ready",)),
)


# Each seeded issue's own description: DEM-2 has none; DEM-1 has several lines of Markdown.
_SEEDED_DESCRIPTIONS: dict[str, str] = {
    "DEM-1": (
        "Add a synthetic feature.\n"
        "\n"
        "Steps:\n"
        "\n"
        "- read the synthetic input\n"
        "- write the synthetic output\n"
        "\n"
        "```sh\n"
        "make check\n"
        "```\n"
    ),
    "DEM-2": "",
    "DEM-3": "Fix the synthetic bug in DEM-3.",
    "DEM-4": "Synthetic work already done in DEM-4.",
    "DEM-5": "Synthetic work dropped in DEM-5.",
    "DEM-6": "Synthetic duplicate of DEM-5.",
    "DEM-7": "Synthetic issue DEM-7 with no label.",
    "OPS-1": "Synthetic issue of another team.",
}


def a_seeded_tracker_backend() -> FakeTrackerBackend:
    """Build the synthetic tracker the contract suite runs on; a fresh backend per call.

    Team ``DEM`` has three open ``agent-ready`` issues (more than one fake page), ready ones in
    Done, Canceled and Duplicate, and an open unlabelled one; team ``OPS`` has one open ready issue.
    """
    return FakeTrackerBackend(
        states={
            "DEM": (*_OPEN_STATES, *_CLOSED_STATES, TrackerState(name="Duplicate", closed=True)),
            "OPS": (*_OPEN_STATES, *_CLOSED_STATES),
        },
        team_labels={"DEM": ("demo-api", "bug"), "OPS": ()},
        workspace_labels=("agent-ready", "agent-failed"),
        issues={
            issue_id: an_issue(
                id=issue_id,
                title=f"Synthetic issue {issue_id}",
                description=_SEEDED_DESCRIPTIONS[issue_id],
                state=state,
                labels=labels,
            )
            for issue_id, state, labels in _SEEDED_ISSUES
        },
    )
