"""Every write route of ``build_app`` and the checks it gets (AGH-699, audit C-4).

Which checks a write gets is decided by path patterns (``local_security``, ``session_access``); a
write route that none of them names falls back to the basic checks (the ``Host``, and an
``Origin`` only when one is sent), which is how the owner sign-off shipped without the launch
cookie. So ``WRITE_ROUTES`` lists every ``POST``, ``PUT``, ``PATCH`` and ``DELETE`` route with
its class, the inventory fails when the app has a write route the table lacks (or the table one
the app lacks), and each route is probed for its class's answers:

- ``COOKIE``: the launch cookie on top of this server's exact ``Origin``, a same-origin fetch and
  a JSON body: the agent-session routes and a project's discoveries, the run writes, the item
  writes and the owner writes. Without the cookie 401; with it but without an ``Origin`` 403.
- ``EXACT_ORIGIN``: this server's exact ``Origin``, a missing one refused too, and no cookie: the
  hub registry writes, which scripts call (``make connect``, the demo seed).
- ``BASIC``: by design the basic checks only: no ``Origin`` needed (the hook sensor posts with
  ``curl``; a scenario's validate writes nothing), a foreign one refused.

No write takes the strict rule without the cookie: the learning decisions did until AGH-699.
"""

import re
from collections.abc import Callable, Iterable, Mapping
from dataclasses import replace
from enum import StrEnum
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.routing import iter_route_contexts

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings

WRITE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
TOKEN = "synthetic-inventory-launch-token-0123456789abcd"  # noqa: S105 -- synthetic
OWN_ORIGIN = "http://127.0.0.1:7420"
UNAUTHORIZED = "urn:agent-hub:problem:agent-session-unauthorized"
# What the request checks answer when they refuse (the routes themselves never do).
REFUSED_BY_CHECKS = frozenset({401, 403, 415})


class Protection(StrEnum):
    """A write route's class: which checks run before the route does."""

    COOKIE = "cookie+strict"
    EXACT_ORIGIN = "exact-origin"
    BASIC = "basic"


COOKIE = Protection.COOKIE
EXACT_ORIGIN = Protection.EXACT_ORIGIN
BASIC = Protection.BASIC

WRITE_ROUTES: Mapping[tuple[str, str], Protection] = {
    # The agent sessions (ADR 0031): start, drive and end Claude Code sessions.
    ("POST", "/api/v1/agent-sessions"): COOKIE,
    ("POST", "/api/v1/agent-sessions/cloud"): COOKIE,
    ("POST", "/api/v1/agent-sessions/cloud/{cloud_id}/messages"): COOKIE,
    ("DELETE", "/api/v1/agent-sessions/{agent_session_id}"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/close"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/interrupt"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/messages"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/permissions/{request_id}"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/settings"): COOKIE,
    ("POST", "/api/v1/agent-sessions/{agent_session_id}/tasks/{task_id}/stop"): COOKIE,
    # A project's discoveries start read-only sessions (ADR 0046).
    ("POST", "/api/v1/projects/{project}/environment-discoveries"): COOKIE,
    ("DELETE", "/api/v1/projects/{project}/environment-discoveries/{discovery_id}"): COOKIE,
    # The run writes (RUN_WRITES): they start, stop or answer a child process.
    ("POST", "/api/v1/workflow-runs"): COOKIE,
    ("POST", "/api/v1/workflow-runs/{run_id}/abandon"): COOKIE,
    ("POST", "/api/v1/workflow-runs/{run_id}/cancel"): COOKIE,
    ("POST", "/api/v1/workflow-runs/{run_id}/resume"): COOKIE,
    ("POST", "/api/v1/approvals/{approval_id}/decision"): COOKIE,
    ("POST", "/api/v1/features/{project}/{slug}/acs/{ac}/check-runs"): COOKIE,
    ("POST", "/api/v1/features/{project}/{slug}/change-requests/{n}/decision"): COOKIE,
    ("POST", "/api/v1/scenarios/{project}/{name}/plan"): COOKIE,
    ("POST", "/api/v1/scenarios/{project}/{name}/runs"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/answer"): COOKIE,
    ("PUT", "/api/v1/scenario-runs/{run_id}/breakpoints"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/continue"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/findings/{finding_id}/inbox"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/findings/{finding_id}/issue"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/investigation"): COOKIE,
    ("POST", "/api/v1/scenario-runs/{run_id}/step"): COOKIE,
    # The item writes (ITEM_WRITES): they write into a hub's tree.
    ("POST", "/api/v1/projects/{project}/actions"): COOKIE,
    ("PUT", "/api/v1/projects/{project}/actions/{pack}/{name}"): COOKIE,
    ("POST", "/api/v1/projects/{project}/skills/drafts/{draft_id}/publish"): COOKIE,
    (
        "POST",
        "/api/v1/projects/{project}/skills/{kind}/{source}/{name}/versions/{version_id}/restore",
    ): COOKIE,
    ("POST", "/api/v1/workflows/{project}/{name}/versions/{version_id}/restore"): COOKIE,
    ("PUT", "/api/v1/scenarios/{project}/{name}"): COOKIE,
    ("DELETE", "/api/v1/scenarios/{project}/{name}"): COOKIE,
    ("POST", "/api/v1/scenarios/{project}/{name}/migrate"): COOKIE,
    ("POST", "/api/v1/scenarios/{project}/{name}/proposal/dismiss"): COOKIE,
    ("POST", "/api/v1/features/{project}/{slug}/owner-signoff"): COOKIE,
    # The owner writes (OWNER_WRITES, AGH-699): only the owner's own page makes them.
    ("PUT", "/api/v1/projects/{project}/config/local"): COOKIE,
    ("POST", "/api/v1/projects/{project}/config/environments"): COOKIE,
    ("POST", "/api/v1/projects/{project}/config/repos"): COOKIE,
    ("POST", "/api/v1/hubs/{hub_id}/platform-sync"): COOKIE,
    ("POST", "/api/v1/hubs/{hub_id}/doctor-fix"): COOKIE,
    ("POST", "/api/v1/learnings/{learning_id}/accept"): COOKIE,
    ("POST", "/api/v1/learnings/{learning_id}/reject"): COOKIE,
    ("POST", "/api/v1/learnings/decisions"): COOKIE,
    ("PUT", "/api/v1/tracker/linear"): COOKIE,
    ("DELETE", "/api/v1/tracker/linear"): COOKIE,
    ("PUT", "/api/v1/feature-names"): COOKIE,
    # The hub registry writes (A11): scripts register a hub with this server's Origin.
    ("POST", "/api/v1/hubs"): EXACT_ORIGIN,
    ("DELETE", "/api/v1/hubs/{hub_id}"): EXACT_ORIGIN,
    # Basic by design: the hook sensor (curl, no Origin) and a validate that writes nothing.
    ("POST", "/api/v1/events/hooks"): BASIC,
    ("POST", "/api/v1/projects/{project}/scenarios/validate"): BASIC,
}


def write_routes(app: FastAPI) -> set[tuple[str, str]]:
    """Every (method, path template) of ``app`` that writes."""
    return {
        (method, str(context.path_format))
        for context in iter_route_contexts(app.routes)
        for method in context.methods or ()
        if method in WRITE_METHODS
    }


def inventory_gaps(
    routes: Iterable[tuple[str, str]], table: Mapping[tuple[str, str], Protection]
) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """The write routes the table lacks, and the table's routes the app lacks."""
    found = set(routes)
    return sorted(found - table.keys()), sorted(table.keys() - found)


def _routes_of(protection: Protection) -> list[tuple[str, str]]:
    return sorted(route for route, found in WRITE_ROUTES.items() if found is protection)


def _sample(path: str) -> str:
    """The path with each parameter filled in."""
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.fixture
def guarded(open_composed: Callable[..., Any], composed_settings: ApiSettings) -> Any:
    """The composed app with a launch token, as ``hub web`` starts; its client holds no cookie,
    so a probe sends the cookie only when it means to."""
    return open_composed(replace(composed_settings, session_token=TOKEN))


def _probe(
    app: Any, method: str, path: str, *, origin: str | None = None, cookie: bool = False
) -> Any:
    headers = {"Content-Type": "application/json"}
    if origin is not None:
        headers["Origin"] = origin
    if cookie:
        headers["Cookie"] = f"{cookie_name(app.settings.port)}={TOKEN}"
    return app.client.request(method, _sample(path), content=b"{}", headers=headers)


def test_lists_every_write_route_when_app_built(composed: Any) -> None:
    routes = write_routes(composed.client.app)

    assert inventory_gaps(routes, WRITE_ROUTES) == ([], [])
    assert len(routes) == len(WRITE_ROUTES)


HOOKS = ("POST", "/api/v1/events/hooks")
UNLISTED = ("POST", "/api/v1/unlisted")


# The checker itself: a write route added without a table entry (or an entry dropped) is
# reported, so the inventory above fails; a table entry the app lacks is reported too.
def test_reports_route_when_write_route_missing_from_table(composed: Any) -> None:
    app: FastAPI = composed.client.app

    def unlisted() -> None:
        """A new write route nobody classified."""

    app.add_api_route(UNLISTED[1], unlisted, methods=[UNLISTED[0]])
    listed = write_routes(app)
    without_hooks = {route: found for route, found in WRITE_ROUTES.items() if route != HOOKS}

    assert inventory_gaps(listed, WRITE_ROUTES) == ([UNLISTED], [])
    assert inventory_gaps(listed, without_hooks) == ([HOOKS, UNLISTED], [])
    assert inventory_gaps(listed - {UNLISTED, HOOKS}, WRITE_ROUTES) == ([], [HOOKS])


@pytest.mark.parametrize(("method", "path"), _routes_of(COOKIE))
def test_answers_unauthorized_when_cookie_route_probed_without_cookie(
    guarded: Any, method: str, path: str
) -> None:
    response = _probe(guarded, method, path, origin=OWN_ORIGIN)

    assert response.status_code == 401, response.text
    assert response.json()["type"] == UNAUTHORIZED


@pytest.mark.parametrize(("method", "path"), _routes_of(COOKIE))
def test_answers_forbidden_when_cookie_route_probed_without_origin(
    guarded: Any, method: str, path: str
) -> None:
    response = _probe(guarded, method, path, cookie=True)

    assert response.status_code == 403, response.text
    assert response.json()["title"] == "Forbidden origin"


@pytest.mark.parametrize(("method", "path"), _routes_of(EXACT_ORIGIN))
def test_needs_exact_origin_only_when_exact_origin_route_probed(
    guarded: Any, method: str, path: str
) -> None:
    missing = _probe(guarded, method, path)
    own = _probe(guarded, method, path, origin=OWN_ORIGIN)

    assert missing.status_code == 403, missing.text
    assert missing.json()["title"] == "Forbidden origin"
    assert own.status_code not in REFUSED_BY_CHECKS, own.text


@pytest.mark.parametrize(("method", "path"), _routes_of(BASIC))
def test_passes_without_origin_when_basic_route_probed(
    guarded: Any, method: str, path: str
) -> None:
    missing = _probe(guarded, method, path)
    foreign = _probe(guarded, method, path, origin="http://attacker.example")

    assert missing.status_code not in REFUSED_BY_CHECKS, missing.text
    assert foreign.status_code == 403, foreign.text
