"""``/features`` on the composed app over a registered hub's ``brain/features/`` (AC-200.36,
D23): counts, verdict and phase come from the files; a malformed record degrades its feature
only. AGH-136 (AC-136.18): the list, the detail and the tickets route carry one golden path.
AGH-613 (AC-33): the list never calls the tracker, on a cold or a warm ticket cache."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from agent_hub.api.local_security import CONTENT_SECURITY_POLICY, UX_MOCKUP_PAGE_POLICY
from agent_hub.core.testing.tracker_reader_fakes import (
    CountingTrackerReader,
    InMemoryTrackerReader,
    a_seeded_issue_board,
)

SPEC = """---
type: spec
process_size: bounded
repos: [demo-api]
linear: [DEM-7]
---
# Spec
"""
EVAL = "# Evaluation\n\n**Verdict: SHIP.** Every AC passes by command.\n"


def _record(passes: tuple[bool, ...]) -> str:
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": f"Criterion {index}",
            "repo": "demo-api",
            "verification": "make check" if index < len(passes) else "manual",
            "passes": passed,
            "evidence": "test run" if passed else None,
        }
        for index, passed in enumerate(passes, start=1)
    ]
    return json.dumps({"feature": "x", "linear": ["DEM-7"], "acs": acs})


def _feature(hub: Path, slug: str, files: dict[str, str]) -> None:
    folder = hub / "brain" / "features" / slug
    folder.mkdir(parents=True)
    for name, text in files.items():
        (folder / name).write_text(text, encoding="utf-8")


def _features_hub(make_hub: Callable[..., Path]) -> Path:
    hub = make_hub()
    base = {"spec.md": SPEC, "research.md": "# Research\n", "plan.md": "# Plan\n"}
    _feature(
        hub,
        "complete",
        base | {"issues.md": "# Issues\n", "features.json": _record((True, True)), "eval.md": EVAL},
    )
    _feature(hub, "no-eval", base | {"features.json": _record((True, False, False))})
    _feature(hub, "malformed", base | {"features.json": '{"acs": [}'})
    return hub


def test_reads_counts_verdict_and_phase_from_files_when_features_listed(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = _features_hub(make_hub)
    assert (
        composed.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
        ).status_code
        == 201
    )

    response = composed.client.get("/api/v1/features", params={"project": "demo"})

    assert response.status_code == 200, response.text
    views = {item["slug"]: item for item in response.json()["items"]}
    assert set(views) == {"complete", "no-eval", "malformed"}
    complete, no_eval, malformed = views["complete"], views["no-eval"], views["malformed"]
    assert complete["acs"] == {"passing": 2, "total": 2, "owner_steps": 0}
    # Its tickets are Linear ids and no Linear is connected: Build is unknown, so the phase
    # stays there.
    assert (complete["verdict"], complete["phase"], complete["problem"]) == (
        "SHIP",
        "build",
        None,
    )
    assert no_eval["acs"] == {"passing": 1, "total": 3, "owner_steps": 1}
    assert (no_eval["verdict"], no_eval["phase"], no_eval["problem"]) == (
        None,
        "build",
        None,
    )
    assert malformed["acs"] is None
    assert malformed["problem"] is not None
    assert "could not be parsed" in malformed["problem"]
    assert malformed["size"] == "bounded"


def test_reads_ac_rows_when_feature_detail_requested(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = _features_hub(make_hub)
    composed.client.post(
        "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
    )

    response = composed.client.get("/api/v1/features/demo/no-eval")

    assert response.status_code == 200, response.text
    rows = response.json()["ac_rows"]
    assert [(row["id"], row["passes"], row["manual"]) for row in rows] == [
        ("AC-7.1", True, False),
        ("AC-7.2", False, False),
        ("AC-7.3", False, True),
    ]


def test_lists_records_and_ac_fields_when_records_partly_present(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = _features_hub(make_hub)
    files = {"spec.md": SPEC, "plan.md": "# Plan\n", "features.json": _record((True, False))}
    _feature(hub, "partial", files)
    composed.client.post(
        "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
    )

    response = composed.client.get("/api/v1/features/demo/partial")

    assert response.status_code == 200, response.text
    detail = response.json()
    records = {record["name"]: record for record in detail["records"]}
    assert {name: record["present"] for name, record in records.items()} == {
        "spec": True,
        "research": False,
        "plan": True,
        "eval": False,
        "issues": False,
    }
    assert records["plan"]["path"] == "features/partial/plan.md"
    assert detail["ac_rows"] == [
        {
            "id": "AC-7.1",
            "description": "Criterion 1",
            "repo": "demo-api",
            "passes": True,
            "signed_off": False,
            "manual": False,
            "evidence": "test run",
            "command": "make check",
        },
        {
            "id": "AC-7.2",
            "description": "Criterion 2",
            "repo": "demo-api",
            "passes": False,
            "signed_off": False,
            "manual": True,
            "evidence": None,
            "command": "manual",
        },
    ]
    plan = composed.client.get(
        "/api/v1/projects/demo/brain/note", params={"path": records["plan"]["path"]}
    )
    research = composed.client.get(
        "/api/v1/projects/demo/brain/note", params={"path": records["research"]["path"]}
    )
    assert (plan.status_code, plan.json()["markdown"]) == (200, "# Plan\n")
    assert research.status_code == 404


def _golden(item: dict[str, Any]) -> tuple[Any, ...]:
    return (item["tickets_source"], item["phase"], item["golden_path"])


def test_carries_golden_path_when_list_and_detail_read(open_tickets: Any) -> None:
    world = open_tickets()
    client = world.app.client

    def read() -> tuple[dict[str, Any], dict[str, Any]]:
        listed = client.get("/api/v1/features", params={"project": "demo"})
        detail = client.get("/api/v1/features/demo/ticket-planning")
        assert (listed.status_code, detail.status_code) == (200, 200), (listed.text, detail.text)
        (item,) = listed.json()["items"]
        return item, detail.json()

    cold_item, cold_detail = read()
    tickets = world.tickets().json()
    warm_item, warm_detail = read()

    # Cold, list and detail serve the plan and never call Linear; warm, they serve the snapshot
    # the tickets route read, and all three agree.
    assert world.linear.count == 1
    assert _golden(cold_item) == _golden(cold_detail)
    assert cold_item["tickets_source"] == "plan"
    assert _golden(warm_item) == _golden(warm_detail)
    assert warm_item["tickets_source"] == "linear"
    assert warm_item["golden_path"] == tickets["golden_path"]
    assert warm_item["phase"] == tickets["golden_path"]["phase"] == "tickets"
    steps = [step["name"] for step in warm_item["golden_path"]["steps"]]
    assert steps == [
        "spec",
        "ux_design",
        "research",
        "plan",
        "tickets",
        "build",
        "acceptance",
        "shipped",
    ]


def test_reads_no_tracker_when_features_listed(
    open_composed: Callable[..., Any], make_hub: Callable[..., Path], tickets_kit: Any
) -> None:
    """AC-33: ``GET /features`` makes no tracker call, cold or warm (``docs/API.md``: list routes
    never call Linear); only the tickets route reads it, once per cache entry."""
    reader = CountingTrackerReader(InMemoryTrackerReader(a_seeded_issue_board()))
    hub = make_hub()
    tickets_kit.write_feature(hub, tickets_kit.a_ticket_record(tickets_kit.planned))
    composed = open_composed(environ={"LINEAR_API_KEY": tickets_kit.key}, tracker_reader=reader)
    registered = composed.client.post(
        "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
    )
    assert registered.status_code == 201, registered.text

    def listed() -> list[dict[str, Any]]:
        response = composed.client.get("/api/v1/features", params={"project": "demo"})
        assert response.status_code == 200, response.text
        items: list[dict[str, Any]] = response.json()["items"]
        return items

    cold = listed()
    calls_cold = reader.count
    tickets = composed.client.get(tickets_kit.path)
    calls_tickets = reader.count
    warm = listed() + listed()

    assert (tickets.status_code, tickets.json()["source"]) == (200, "linear")
    assert [item["tickets_source"] for item in cold + warm] == ["plan", "linear", "linear"]
    assert (calls_cold, calls_tickets, reader.count) == (0, 1, 1)


def test_serves_ux_mockup_beside_its_design_when_html_present(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    _feature(
        hub,
        "designed",
        {
            "spec.md": SPEC,
            "ux-new-orders.md": "---\nstatus: approved\nscreen: orders\n---\n# Orders\n",
            "ux-new-orders.html": "<main data-ux='table'>Orders</main>",
        },
    )
    composed.client.post(
        "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
    )

    detail = composed.client.get("/api/v1/features/demo/designed").json()
    mockup = composed.client.get("/api/v1/features/demo/designed/mockups/ux-new-orders.html")
    refused = composed.client.get("/api/v1/features/demo/designed/mockups/spec.md")
    missing = composed.client.get("/api/v1/features/demo/designed/mockups/ux-new-gone.html")

    assert [d["mockup"] for d in detail["ux_designs"]] == ["ux-new-orders.html"]
    assert mockup.status_code == 200, mockup.text
    assert mockup.json()["html"] == "<main data-ux='table'>Orders</main>"
    assert refused.status_code == 400
    assert missing.status_code == 404


def test_serves_ux_mockup_page_with_own_policy_when_html_present(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    page = "<style>main{color:red}</style><main data-ux='table'>Orders \u00e9</main>"
    _feature(
        hub,
        "designed",
        {
            "spec.md": SPEC,
            "ux-new-orders.md": "---\nstatus: approved\nscreen: orders\n---\n# Orders\n",
            "ux-new-orders.html": page,
        },
    )
    composed.client.post(
        "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
    )
    base = "/api/v1/features/demo/designed/mockups"

    served = composed.client.get(f"{base}/ux-new-orders.html/page")
    refused = composed.client.get(f"{base}/spec.md/page")
    missing = composed.client.get(f"{base}/ux-new-gone.html/page")
    other = composed.client.get("/api/v1/features/demo/designed")

    assert served.status_code == 200, served.text
    assert served.text == page
    assert served.headers["content-type"] == "text/html; charset=utf-8"
    assert served.headers["content-security-policy"] == UX_MOCKUP_PAGE_POLICY
    assert served.headers["x-content-type-options"] == "nosniff"
    assert served.headers["cache-control"] == "no-store"
    assert refused.status_code == 400
    assert missing.status_code == 404
    assert missing.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
    assert other.headers["content-security-policy"] == CONTENT_SECURITY_POLICY
