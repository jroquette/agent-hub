"""The screen reads on the composed app (ADR 0056): ``GET /api/v1/screens/shell`` answers the app
shell's facts in one read, over a registered hub's feature folders, and with no hub registered,
the answer the first-run gate redirects on. ``GET /api/v1/screens/portfolio`` answers Home's
three parts exactly as their resource routes answer them for the same scope, since the web
writes each under that route's query key."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.testing.session_scenarios import a_run_events, learning_events

OWN = {"Origin": "http://127.0.0.1:7420"}
SHELL = "/api/v1/screens/shell"
PORTFOLIO = "/api/v1/screens/portfolio"
SPEC = "---\ntype: spec\nprocess_size: bounded\nrepos: [demo-api]\nlinear: [DEM-7]\n---\n# Spec\n"
RECORD = json.dumps(
    {
        "feature": "x",
        "linear": ["DEM-7"],
        "acs": [
            {
                "id": "AC-7.1",
                "description": "Criterion 1",
                "repo": "demo-api",
                "verification": "make check",
                "passes": True,
                "evidence": "test run",
            }
        ],
    }
)
BASE = {
    "spec.md": SPEC,
    "research.md": "# Research\n",
    "plan.md": "# Plan\n",
    "features.json": RECORD,
}


def _eval(verdict: str) -> str:
    return f"# Evaluation\n\n**Verdict: {verdict}.** Read by command.\n"


def _feature(hub: Path, slug: str, files: dict[str, str]) -> None:
    folder = hub / "brain" / "features" / slug
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def test_answers_shell_facts_when_hub_registered(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    _feature(hub, "shipping", BASE | {"eval.md": _eval("SHIP")})
    _feature(hub, "refused", BASE | {"eval.md": _eval("NO-SHIP")})
    _feature(hub, "malformed", BASE | {"features.json": '{"acs": [}'})
    registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
    assert registered.status_code == 201, registered.text
    listed = composed.client.get("/api/v1/features", params={"project": "demo"}).json()["items"]
    # What the badge reads: a NO-SHIP and a problem need you; the SHIP feature does not.
    assert {
        item["slug"]: (item["verdict"], item["problem"] is not None, item["waiting_on_owner"])
        for item in listed
        if item["phase"] != "shipped"
    } == {
        "shipping": ("SHIP", False, None),
        "refused": ("NO-SHIP", False, None),
        "malformed": (None, True, None),
    }

    response = composed.client.get(SHELL)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "hub_count": 1,
        "projects": [{"name": "demo", "live_sessions": 0}],
        "features_needing_you": 2,
        "has_workflow_runs": False,
    }


def test_answers_no_hub_when_registry_empty(composed: Any) -> None:
    hubs = composed.client.get("/api/v1/hubs")
    assert (hubs.status_code, hubs.json()["items"]) == (200, [])

    response = composed.client.get(SHELL)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "hub_count": 0,
        "projects": [],
        "features_needing_you": 0,
        "has_workflow_runs": False,
    }


# Before the composed app's clock (2026-10-11 12:00 UTC), on its day.
PORTFOLIO_EVENTS_AT = datetime(2026, 10, 11, 9, 0, tzinfo=UTC)


def _portfolio_events() -> list[Event]:
    """A failed run in ``demo``, 2 learnings proposed in ``other`` and 25 in ``demo``: something
    needs you in both projects, and each scope has more activity than one page of 20."""
    events = a_run_events("1a2b3c4d", fails=True, start=PORTFOLIO_EVENTS_AT)
    for number in range(27):
        events += learning_events(
            f"learning-{number:02d}",
            project="other" if number < 2 else "demo",
            session=f"session-{number:02d}",
            start=PORTFOLIO_EVENTS_AT + timedelta(minutes=number),
        )
    return events


@pytest.mark.parametrize("scope", [None, "demo"], ids=["all-projects", "one-project"])
def test_answers_portfolio_like_its_three_resources_when_read(
    composed: Any, make_hub: Callable[..., Path], scope: str | None
) -> None:
    for project in ("demo", "other"):
        hub = make_hub(project)
        registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
        assert registered.status_code == 201, registered.text
    composed.store.append(_portfolio_events())
    params: dict[str, Any] = {} if scope is None else {"project": scope}
    # What Home's queries read for the scope: the cards (every project, whatever the scope),
    # what needs you, and the first activity page of 20, which more items follow.
    projects = composed.client.get("/api/v1/projects", params=params).json()
    needs_you = composed.client.get("/api/v1/needs-you", params=params).json()
    activity = composed.client.get("/api/v1/activity", params=params | {"limit": 20}).json()
    assert sorted(card["name"] for card in projects["items"]) == ["demo", "other"]
    needing = {"demo", "other"} if scope is None else {"demo"}
    assert {item["project"] for item in needs_you["items"]} == needing
    assert (len(activity["items"]), activity["next_cursor"] is not None) == (20, True)

    response = composed.client.get(PORTFOLIO, params=params)

    assert response.status_code == 200, response.text
    assert response.json() == {"projects": projects, "needs_you": needs_you, "activity": activity}
