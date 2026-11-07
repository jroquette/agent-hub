"""Who may sign off a feature's owner steps, on the app as ``hub web`` composes it.

Regression: AGH-695. ``POST /features/{project}/{slug}/owner-signoff`` writes the owner's SHIP
eval (``provenance: owner``) into the hub. It took only the basic Origin check, so a request with
no cookie and no ``Origin`` (an agent session knows ``AGENT_HUB_WEB_URL``) wrote it. It is now a
strict item write: this server's ``Origin``, a JSON body and the launch cookie, else nothing is
written.
"""

import json
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings

TOKEN = "synthetic-signoff-token-0123456789abcdefghijk"  # noqa: S105 -- synthetic
OWN = {"Origin": "http://127.0.0.1:7420"}
SLUG = "demo-feature"
SIGNOFF = f"/api/v1/features/demo/{SLUG}/owner-signoff"
WAITING_EVAL = (
    "---\ntype: eval\nverdict: SHIP-WITH-OWNER-STEPS\nacs: all\nevaluated_at: 2026-10-08\n---\n"
)


def _signed(open_composed: Callable[..., Any], settings: ApiSettings) -> Any:
    """The composed app with a launch token, its client holding no cookie yet."""
    return open_composed(replace(settings, session_token=TOKEN))


def _waiting_feature(app: Any, make_hub: Callable[..., Path]) -> Path:
    """A registered hub whose feature waits on the owner's sign-off; its ``evals/`` folder."""
    hub = make_hub()
    evals = hub / "brain" / "features" / SLUG / "evals"
    evals.mkdir(parents=True)
    acs = [
        {"id": f"AC-7.{n}", "description": "Given x, when y, then z", "passes": True}
        for n in (1, 2)
    ]
    (evals.parent / "features.json").write_text(json.dumps({"acs": acs}), encoding="utf-8")
    (evals / "dem-7.md").write_text(WAITING_EVAL, encoding="utf-8")
    registered = app.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=OWN)
    assert registered.status_code == 201, registered.text
    return evals


def _waits_on_owner(app: Any) -> bool:
    detail = app.client.get(f"/api/v1/features/demo/{SLUG}")
    assert detail.status_code == 200, detail.text
    waiting = detail.json()["waiting_on_owner"]
    return waiting is not None and waiting["kind"] == "owner_signoff"


def _names(folder: Path) -> list[str]:
    return sorted(path.name for path in folder.iterdir())


@pytest.mark.parametrize(
    ("cookie", "status"),
    [(None, 401), ("synthetic-wrong-token-0123456789abcdefghijkl", 401)],
    ids=["no-cookie", "wrong-cookie"],
)
def test_refuses_and_writes_nothing_when_signoff_has_no_launch_cookie(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    cookie: str | None,
    status: int,
) -> None:
    app = _signed(open_composed, composed_settings)
    evals = _waiting_feature(app, make_hub)
    if cookie is not None:
        app.client.cookies.set(cookie_name(app.settings.port), cookie)

    response = app.client.post(SIGNOFF, json={}, headers=OWN)

    assert response.status_code == status, response.text
    assert response.json()["type"] == "urn:agent-hub:problem:agent-session-unauthorized"
    assert _names(evals) == ["dem-7.md"]
    assert _waits_on_owner(app)


# The audit's own request: no cookie, no Origin, no body. The strict Origin check refuses it
# before the cookie is read.
def test_refuses_and_writes_nothing_when_signoff_sent_bare(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    app = _signed(open_composed, composed_settings)
    evals = _waiting_feature(app, make_hub)

    response = app.client.post(SIGNOFF)

    assert response.status_code == 403, response.text
    assert response.json()["title"] == "Forbidden origin"
    assert _names(evals) == ["dem-7.md"]
    assert _waits_on_owner(app)


# Hub web's own page holds the cookie and sends its Origin and a JSON body: the sign-off works.
def test_writes_owner_eval_when_signoff_sent_with_launch_cookie(
    open_composed: Callable[..., Any],
    composed_settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    app = _signed(open_composed, composed_settings)
    evals = _waiting_feature(app, make_hub)
    app.client.cookies.set(cookie_name(app.settings.port), TOKEN)

    response = app.client.post(
        SIGNOFF, json={"delivery": "dem-7", "decision": "done", "note": "Checked."}, headers=OWN
    )

    assert response.status_code == 201, response.text
    assert (response.json()["verdict"], response.json()["provenance"]) == ("SHIP", "owner")
    assert _names(evals) == ["dem-7.md", "owner-signoff.md"]
    text = (evals / "owner-signoff.md").read_text(encoding="utf-8")
    assert "verdict: SHIP\n" in text
    assert "provenance: owner\n" in text
    assert not _waits_on_owner(app)
