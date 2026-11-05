"""The screen reads on the composed app (ADR 0056): ``GET /api/v1/screens/shell`` answers the app
shell's facts in one read, over a registered hub's feature folders, and with no hub registered,
the answer the first-run gate redirects on. ``GET /api/v1/screens/portfolio`` answers Home's
three parts exactly as their resource routes answer them for the same scope, since the web
writes each under that route's query key. ``GET /api/v1/screens/project-overview/{project}``
answers the overview's resource parts as their routes do, the sessions of the issues worked on
in the last 7 days by the server's clock, and the same 404 problem as ``/projects/{project}``.
``GET /api/v1/screens/sessions`` answers the inbox's four sections, the cards and the features as
their routes answer them, and the agent sessions and the driver's capabilities only for a request
that the agent-session routes would answer (the launch cookie, this server's own pages, the
sessions on); for any other request those two parts are null.
``GET /api/v1/screens/session-detail/{session_id}`` answers the session, its first 1,000 events,
its summary, its problems and its project's features as their routes answer them, the driver's
capabilities only for a request the agent-session routes would answer, and the same 404 problem
as ``/sessions/{session_id}``."""

import json
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api import composition
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.events.event import Event
from agent_hub.core.screens.screen_reads import ScreenReads
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
from agent_hub.core.testing.session_scenarios import (
    DEFAULT_TOOLS,
    a_run_events,
    a_session_events,
    learning_events,
)

OWN = {"Origin": "http://127.0.0.1:7420"}
SHELL = "/api/v1/screens/shell"
PORTFOLIO = "/api/v1/screens/portfolio"
OVERVIEW = "/api/v1/screens/project-overview"
SESSIONS = "/api/v1/screens/sessions"
DETAIL = "/api/v1/screens/session-detail"
AGENT_SESSIONS = "/api/v1/agent-sessions"
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


INBOX = ("waiting", "live", "idle", "ended")
# The inbox's period starts here, before the composed app's clock: the idle session started
# before it, the other unended ones and one finished one after it.
PERIOD = timedelta(minutes=15)


def _stamp(at: datetime) -> str:
    return at.isoformat().replace("+00:00", "Z")


def _inbox_events(now: datetime) -> list[Event]:
    """Sessions of each section before ``now``: in demo one waiting on a gate, one live, one
    idle started before the period, one finished in it and one finished a day before; in
    other one live and one finished."""
    waiting = a_session_events("demo-waiting", ended=False, start=now - timedelta(minutes=13))
    gate = an_event(
        session="demo-waiting",
        type="gate.request",
        timestamp=waiting[-1].timestamp + timedelta(seconds=5),
        source_id="demo-waiting:gate.request",
        payload={"gate_id": "toolu_ask", "kind": "plan", "feature": "demo"},
    )
    events = [*waiting, gate]
    for session, project, minutes_ago, ended in (
        ("demo-live", "demo", 8, False),
        ("demo-idle", "demo", 18, False),
        ("demo-ended", "demo", 14, True),
        ("demo-ended-before", "demo", 24 * 60, True),
        ("other-live", "other", 9, False),
        ("other-ended", "other", 20 * 60, True),
    ):
        start = now - timedelta(minutes=minutes_ago)
        events += a_session_events(session, project=project, start=start, ended=ended)
    return events


def _register_inbox_hubs(composed: Any, make_hub: Callable[..., Path]) -> None:
    """``demo`` and ``other`` registered, each with a feature folder."""
    for project, slug in (("demo", "shipping"), ("other", "refused")):
        hub = make_hub(project)
        _feature(hub, slug, BASE | {"eval.md": _eval("SHIP" if project == "demo" else "NO-SHIP")})
        registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
        assert registered.status_code == 201, registered.text


# Each section as GET /sessions?status=<s>&limit=50 with the read's scope and sort, the period's
# from on Finished only, every card and every project's features: the parts the web writes under
# those routes' keys.
@pytest.mark.parametrize("in_period", [False, True], ids=["all-projects", "one-project-in-period"])
def test_answers_sections_like_session_lists_when_sessions_screen_read(
    composed: Any, make_hub: Callable[..., Path], *, in_period: bool
) -> None:
    _register_inbox_hubs(composed, make_hub)
    now = composed.settings.clock()
    composed.store.append(_inbox_events(now))
    since = _stamp(now - PERIOD)
    params: dict[str, Any] = (
        {"project": "demo", "sort": "-last_activity_at", "from": since} if in_period else {}
    )
    shared = {key: value for key, value in params.items() if key != "from"}
    sections = {
        status: composed.client.get(
            "/api/v1/sessions",
            params=shared
            | {"status": status, "limit": 50}
            | ({"from": since} if in_period and status == "ended" else {}),
        ).json()
        for status in INBOX
    }
    projects = composed.client.get("/api/v1/projects").json()
    features = composed.client.get("/api/v1/features").json()
    shown = {status: {item["id"] for item in page["items"]} for status, page in sections.items()}
    assert shown == {
        "waiting": {"demo-waiting"},
        "live": {"demo-live"} | (set() if in_period else {"other-live"}),
        "idle": {"demo-idle"},
        "ended": {"demo-ended"} | (set() if in_period else {"demo-ended-before", "other-ended"}),
    }
    assert sorted(card["name"] for card in projects["items"]) == ["demo", "other"]
    assert sorted(item["project"] for item in features["items"]) == ["demo", "other"]

    response = composed.client.get(SESSIONS, params=params)

    assert response.status_code == 200, response.text
    body = response.json()
    assert {status: body[status] for status in INBOX} == sections
    assert (body["projects"], body["features"]) == (projects, features)


SESSION_TOKEN = "s" * 43
# How long the composed screen reads wait here for the driver's capabilities. The in-memory
# driver answers at once, but production's 50 ms is wall-clock time, which a loaded runner can
# spend before the event loop takes that answer.
CAPABILITIES_WAIT = 10.0


@pytest.fixture
def sessions_on(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> Any:
    """The composed app with this launch's token and the in-memory driver, ``demo`` and
    ``other`` registered; no cookie yet. ``build_app`` builds its screen reads as in production,
    but waiting ``CAPABILITIES_WAIT`` for the driver's capabilities."""
    monkeypatch.setattr(
        composition, "ScreenReads", partial(ScreenReads, capabilities_wait=CAPABILITIES_WAIT)
    )
    app = open_composed(
        replace(composed_settings, session_token=SESSION_TOKEN),
        session_driver=InMemorySessionDriver(),
    )
    _register_inbox_hubs(app, make_hub)
    return app


def _sign_in(app: Any) -> None:
    """The launch URL's token exchange: the cookie it sets goes with every later request."""
    exchanged = app.client.get("/", params={"token": SESSION_TOKEN}, follow_redirects=False)
    assert exchanged.status_code == 303, exchanged.text
    assert app.client.cookies.get(cookie_name(app.settings.port)) == SESSION_TOKEN


def _start_agent_session(app: Any, project: str) -> str:
    """An idle agent session of ``project`` in its first workdir."""
    workdirs = app.client.get(f"{AGENT_SESSIONS}/workdirs", params={"project": project})
    assert workdirs.status_code == 200, workdirs.text
    workdir = workdirs.json()["items"][0]["workdir_id"]
    created = app.client.post(
        AGENT_SESSIONS, json={"project": project, "workdir_id": workdir}, headers=OWN
    )
    assert created.status_code == 201, created.text
    session_id: str = created.json()["id"]
    return session_id


def test_answers_agent_parts_when_request_has_session_cookie(sessions_on: Any) -> None:
    _sign_in(sessions_on)
    started = {project: _start_agent_session(sessions_on, project) for project in ("demo", "other")}
    every = sessions_on.client.get(AGENT_SESSIONS).json()["items"]
    assert sorted(item["id"] for item in every) == sorted(started.values())
    agent_sessions = sessions_on.client.get(AGENT_SESSIONS, params={"project": "demo"})
    capabilities = sessions_on.client.get(f"{AGENT_SESSIONS}/capabilities")
    assert (agent_sessions.status_code, capabilities.status_code) == (200, 200)
    assert [item["id"] for item in agent_sessions.json()["items"]] == [started["demo"]]

    response = sessions_on.client.get(SESSIONS, params={"project": "demo"})

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["agent_sessions"], body["capabilities"]) == (
        agent_sessions.json(),
        capabilities.json(),
    )


def test_answers_no_agent_parts_when_request_has_no_session_cookie(sessions_on: Any) -> None:
    refused = sessions_on.client.get(f"{AGENT_SESSIONS}/capabilities")
    assert refused.status_code == 401, refused.text

    response = sessions_on.client.get(SESSIONS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["agent_sessions"], body["capabilities"]) == (None, None)


# The cookie goes with each of these, as a browser sends it; the agent-session routes refuse
# them all (another loopback port is same-site and carries the Strict cookie).
@pytest.mark.parametrize(
    "headers",
    [
        {"Sec-Fetch-Site": "cross-site"},
        {"Origin": "http://attacker.example"},
        {"Origin": "http://127.0.0.1:7421", "Sec-Fetch-Site": "same-site"},
    ],
    ids=["cross-site", "foreign-origin", "other-loopback-port"],
)
def test_answers_no_agent_parts_when_request_comes_from_another_site(
    sessions_on: Any, headers: dict[str, str]
) -> None:
    _sign_in(sessions_on)
    refused = sessions_on.client.get(f"{AGENT_SESSIONS}/capabilities", headers=headers)
    assert refused.status_code == 403, refused.text

    response = sessions_on.client.get(SESSIONS, headers=headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["agent_sessions"], body["capabilities"]) == (None, None)


def test_answers_no_agent_sessions_when_sessions_off(
    open_composed: Callable[..., Any], composed_settings: ApiSettings
) -> None:
    app = open_composed(replace(composed_settings, session_token=SESSION_TOKEN, sessions_off=True))
    app.client.cookies.set(cookie_name(composed_settings.port), SESSION_TOKEN)
    off = app.client.get(AGENT_SESSIONS)
    assert (off.status_code, off.json()["type"]) == (
        404,
        "urn:agent-hub:problem:agent-sessions-off",
    )

    response = app.client.get(SESSIONS)

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["agent_sessions"], body["capabilities"]) == (None, None)


# Validated as on /sessions: a bad parameter is a 400 naming it (docs/API.md "Errors").
def test_refuses_unknown_sort_when_sessions_screen_read(composed: Any) -> None:
    resource = composed.client.get("/api/v1/sessions", params={"sort": "fastest"})
    assert resource.status_code == 400, resource.text
    assert [error["parameter"] for error in resource.json()["errors"]] == ["sort"]

    response = composed.client.get(SESSIONS, params={"sort": "fastest"})

    assert response.status_code == 400, response.text
    assert _without_instance(response.json()) == _without_instance(resource.json())


# 501 tool calls: with its start, its prompt and its end, the session has 1,005 events, more than
# the detail's first events page of 1,000.
DETAIL_TOOLS = DEFAULT_TOOLS * 167
# Each resource the detail's regions read for the session, with the parameters the web asks it
# with.
DETAIL_RESOURCES: dict[str, tuple[str, dict[str, Any]]] = {
    "session": ("/api/v1/sessions/detail-ended", {}),
    "events": ("/api/v1/sessions/detail-ended/events", {"limit": 1000}),
    "summary": ("/api/v1/sessions/detail-ended/summary", {}),
    "problems": ("/api/v1/sessions/detail-ended/problems", {}),
    "features": ("/api/v1/features", {"project": "demo"}),
    "capabilities": (f"{AGENT_SESSIONS}/capabilities", {}),
}


def _ended_session(now: datetime) -> list[Event]:
    """Session ``detail-ended`` of ``demo``, two days before ``now``: 501 tool calls, the first
    ``make check-fast`` failed, then its end."""
    return a_session_events(
        "detail-ended",
        start=now - timedelta(days=2),
        tools=DETAIL_TOOLS,
        failed_tools=frozenset({2}),
    )


def test_answers_detail_like_its_resources_when_session_ended(sessions_on: Any) -> None:
    _sign_in(sessions_on)
    sessions_on.store.append(_ended_session(sessions_on.settings.clock()))
    read = {
        part: sessions_on.client.get(path, params=params)
        for part, (path, params) in DETAIL_RESOURCES.items()
    }
    assert {part: answer.status_code for part, answer in read.items()} == dict.fromkeys(read, 200)
    answers = {part: answer.json() for part, answer in read.items()}
    # What the regions show: an ended session that counts a problem, a full first events page
    # with more to come, its summary lines and its problem, and demo's feature alone.
    session = answers["session"]
    assert (session["status"], sum(session["problems"].values()) > 0) == ("ended", True)
    page = answers["events"]
    assert (len(page["items"]), page["next_cursor"] is not None) == (1000, True)
    assert (answers["summary"]["lines"] != [], answers["problems"]["items"] != []) == (True, True)
    every = sessions_on.client.get("/api/v1/features").json()["items"]
    assert sorted(item["project"] for item in every) == ["demo", "other"]
    assert [item["project"] for item in answers["features"]["items"]] == ["demo"]

    response = sessions_on.client.get(f"{DETAIL}/detail-ended")

    assert response.status_code == 200, response.text
    assert {part: response.json()[part] for part in DETAIL_RESOURCES} == answers


def test_answers_no_capabilities_when_request_has_no_session_cookie(sessions_on: Any) -> None:
    now = sessions_on.settings.clock()
    sessions_on.store.append(a_session_events("detail-ended", start=now - timedelta(days=2)))
    refused = sessions_on.client.get(f"{AGENT_SESSIONS}/capabilities")
    assert refused.status_code == 401, refused.text
    session = sessions_on.client.get("/api/v1/sessions/detail-ended")
    assert session.status_code == 200, session.text

    response = sessions_on.client.get(f"{DETAIL}/detail-ended")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["session"], body["capabilities"]) == (session.json(), None)


def test_answers_session_not_found_when_detail_session_unknown(composed: Any) -> None:
    session = composed.client.get("/api/v1/sessions/nobody")
    assert session.status_code == 404, session.text

    response = composed.client.get(f"{DETAIL}/nobody")

    assert response.status_code == 404, response.text
    assert _without_instance(response.json()) == _without_instance(session.json())
