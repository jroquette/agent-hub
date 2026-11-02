"""The screen reads on the composed app (ADR 0056): ``GET /api/v1/screens/shell`` answers the app
shell's facts in one read, over a registered hub's feature folders, and with no hub registered,
the answer the first-run gate redirects on."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

OWN = {"Origin": "http://127.0.0.1:7420"}
SHELL = "/api/v1/screens/shell"
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
