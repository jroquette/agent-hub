"""The screen reads on the composed app (ADR 0056): ``GET /api/v1/screens/shell`` answers the app
shell's facts in one read, over a registered hub's feature folders, and with no hub registered,
the answer the first-run gate redirects on. ``GET /api/v1/screens/portfolio`` answers Home's
three parts exactly as their resource routes answer them for the same scope, since the web
writes each under that route's query key. ``GET /api/v1/screens/project-overview/{project}``
answers the overview's resource parts as their routes do, the sessions of the issues worked on
in the last 7 days by the server's clock, and the same 404 problem as ``/projects/{project}``."""

import json
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.events.event import Event
from agent_hub.core.testing.session_scenarios import (
    a_run_events,
    a_session_events,
    learning_events,
)

OWN = {"Origin": "http://127.0.0.1:7420"}
SHELL = "/api/v1/screens/shell"
PORTFOLIO = "/api/v1/screens/portfolio"
OVERVIEW = "/api/v1/screens/project-overview"
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


# Each resource the overview's regions read, with the parameters the web asks it with.
OVERVIEW_RESOURCES: dict[str, tuple[str, dict[str, Any]]] = {
    "project": ("/api/v1/projects/demo", {}),
    "findings": ("/api/v1/doctor/findings", {"project": "demo"}),
    "projects": ("/api/v1/projects", {"project": "demo"}),
    "needs_you": ("/api/v1/needs-you", {"project": "demo"}),
    "runs": ("/api/v1/workflow-runs", {"project": "demo", "limit": 200}),
    "now": ("/api/v1/projects/demo/now", {}),
    "features": ("/api/v1/features", {"project": "demo"}),
    "repos": ("/api/v1/projects/demo/repos", {}),
    "config": ("/api/v1/projects/demo/config", {}),
}


def test_answers_overview_like_its_resources_when_read(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    demo = make_hub()
    # A drifted managed file gives demo findings; a feature folder, a feature.
    (demo / "AGENTS.md").write_text("# edited by hand\n", encoding="utf-8")
    _feature(demo, "shipping", BASE | {"eval.md": _eval("SHIP")})
    for hub in (demo, make_hub("other")):
        registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
        assert registered.status_code == 201, registered.text
    composed.store.append(a_run_events("1a2b3c4d", fails=True, start=PORTFOLIO_EVENTS_AT))
    composed.refresh()
    read = {
        part: composed.client.get(path, params=params)
        for part, (path, params) in OVERVIEW_RESOURCES.items()
    }
    assert {part: answer.status_code for part, answer in read.items()} == dict.fromkeys(read, 200)
    answers = {part: answer.json() for part, answer in read.items()}
    # What the regions show: the findings of a check, both cards, and demo's need, run, feature
    # and repo.
    assert answers["findings"]["items"] != [] and answers["findings"]["checked_at"] is not None
    assert sorted(card["name"] for card in answers["projects"]["items"]) == ["demo", "other"]
    parts = ("needs_you", "runs", "features", "repos")
    assert [answers[part]["items"] != [] for part in parts] == [True] * len(parts)

    response = composed.client.get(f"{OVERVIEW}/demo")

    assert response.status_code == 200, response.text
    assert {part: response.json()[part] for part in OVERVIEW_RESOURCES} == answers


def _overview_sessions(now: datetime) -> list[Event]:
    """Sessions of ``demo`` before ``now``: on DEM-1 two days and 20 days before, on DEM-2 ten
    days before only, and one a day before on a branch that names no issue."""
    events: list[Event] = []
    for session, days, branch in (
        ("dem-1-week", 2, "jdoe/dem-1-export-button"),
        ("no-issue-week", 1, "main"),
        ("dem-2-older", 10, "jdoe/dem-2-import-orders"),
        ("dem-1-older", 20, "jdoe/dem-1-export-button"),
    ):
        events += a_session_events(session, start=now - timedelta(days=days), git_branch=branch)
    return events


# The composed app's clock is weeks behind the real one, so a read that judged "this week" by
# the real clock would carry no session.
def test_carries_sessions_of_issues_worked_on_this_week_when_overview_read(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    registered = composed.client.post("/api/v1/hubs", json={"path": str(make_hub())}, headers=OWN)
    assert registered.status_code == 201, registered.text
    composed.store.append(_overview_sessions(composed.settings.clock()))
    params = {"project": "demo", "limit": 200, "sort": "-last_activity_at"}
    page = composed.client.get("/api/v1/sessions", params=params).json()["items"]
    assert [(item["id"], item["label"]["issue"]) for item in page] == [
        ("no-issue-week", None),
        ("dem-1-week", "DEM-1"),
        ("dem-2-older", "DEM-2"),
        ("dem-1-older", "DEM-1"),
    ]

    response = composed.client.get(f"{OVERVIEW}/demo")

    assert response.status_code == 200, response.text
    by_id = {item["id"]: item for item in page}
    body = response.json()
    assert body["recent_sessions"]["items"] == [by_id["dem-1-week"], by_id["dem-1-older"]]
    assert body["has_sessions"] is True


def _without_instance(problem: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in problem.items() if key != "instance"}


def test_answers_project_not_found_when_overview_project_unknown(composed: Any) -> None:
    project = composed.client.get("/api/v1/projects/nobody")
    assert project.status_code == 404, project.text

    response = composed.client.get(f"{OVERVIEW}/nobody")

    assert response.status_code == 404, response.text
    assert _without_instance(response.json()) == _without_instance(project.json())
