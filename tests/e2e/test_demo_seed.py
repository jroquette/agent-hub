"""``make demo`` (``scripts/seed_demo.py``) against an installed ``hub web``: every screen's data
is there afterwards, and a second run adds no error."""

import subprocess
import sys
from collections.abc import Callable
from typing import Any

import httpx

from scripts.seed_demo import ASK_SESSION, BACKFILL_SESSION, DEMO_PROJECT, LIVE_SESSION
from tests.e2e.conftest import RunningWeb

REQUEST_SECONDS = 10
SEED_SECONDS = 180


def _seed(web: RunningWeb, run: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    result = run(
        [sys.executable, "-m", "scripts.seed_demo", "--url", web.url, "--via", "local"],
        env={**web.env, "PYTHONPATH": "."},
        timeout=SEED_SECONDS,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout


def _items(client: httpx.Client, path: str) -> list[dict[str, Any]]:
    response = client.get(path)
    assert response.status_code == 200, response.text
    items: list[dict[str, Any]] = response.json()["items"]
    return items


def test_fills_every_screen_when_demo_loaded_twice(
    hub_web: RunningWeb, run: Callable[..., subprocess.CompletedProcess[str]]
) -> None:
    assert _seed(hub_web, run) == f"demo data loaded: open {hub_web.url}\n"
    _seed(hub_web, run)

    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS) as client:
        hubs = _items(client, "/api/v1/hubs")
        projects = _items(client, "/api/v1/projects")
        sessions = _items(client, "/api/v1/sessions")
        runs = _items(client, "/api/v1/workflow-runs")
        approvals = _items(client, "/api/v1/approvals")
        features = _items(client, "/api/v1/features")
        findings = client.get("/api/v1/doctor/findings")
        ended = [item["id"] for item in sessions if item["id"].startswith(BACKFILL_SESSION)]
        cost = client.get(f"/api/v1/sessions/{ended[0]}/cost").json()
        live = [item["id"] for item in sessions if item["id"].startswith(LIVE_SESSION)]
        files = _items(client, f"/api/v1/sessions/{live[0]}/files")

    assert len(hubs) == 1
    assert [project["name"] for project in projects] == [DEMO_PROJECT]
    by_kind = {
        prefix: sorted(item["status"] for item in sessions if item["id"].startswith(prefix))
        for prefix in (LIVE_SESSION, ASK_SESSION, BACKFILL_SESSION)
    }
    # Two runs, each with its own three sessions; the run records are the same both times.
    assert by_kind == {
        LIVE_SESSION: ["live", "live"],
        ASK_SESSION: ["waiting", "waiting"],
        BACKFILL_SESSION: ["ended", "ended"],
    }
    assert len(runs) == 1
    assert any(approval["session_id"].startswith(ASK_SESSION) for approval in approvals)
    assert [feature["slug"] for feature in features] == ["export-button"]
    assert findings.status_code == 200, findings.text
    assert cost["total_usd"] is not None
    assert [change["path"] for change in files] == ["src/export.py"]
