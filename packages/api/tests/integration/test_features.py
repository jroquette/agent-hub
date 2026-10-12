"""``/features`` on the composed app over a registered hub's ``brain/features/`` (AC-200.36,
D23): counts, verdict and phase come from the files; a malformed record degrades its feature
only."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

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
    assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201

    response = composed.client.get("/api/v1/features", params={"project": "demo"})

    assert response.status_code == 200, response.text
    views = {item["slug"]: item for item in response.json()["items"]}
    assert set(views) == {"complete", "no-eval", "malformed"}
    complete, no_eval, malformed = views["complete"], views["no-eval"], views["malformed"]
    assert complete["acs"] == {"passing": 2, "total": 2, "owner_steps": 0}
    assert (complete["verdict"], complete["phase"], complete["problem"]) == (
        "SHIP",
        "evaluate",
        None,
    )
    assert no_eval["acs"] == {"passing": 1, "total": 3, "owner_steps": 1}
    assert (no_eval["verdict"], no_eval["phase"], no_eval["problem"]) == (
        None,
        "implement",
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
    composed.client.post("/api/v1/hubs", json={"path": str(hub)})

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
    composed.client.post("/api/v1/hubs", json={"path": str(hub)})

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
            "manual": False,
            "evidence": "test run",
            "command": "make check",
        },
        {
            "id": "AC-7.2",
            "description": "Criterion 2",
            "repo": "demo-api",
            "passes": False,
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
