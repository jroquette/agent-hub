import json

import pytest

from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import (
    FeatureFolder,
    RecordHead,
    feature_detail,
    feature_view,
    ticket_ids,
)
from agent_hub.core.features.feature_view import FeatureRecord, GoldenPath
from agent_hub.core.features.golden_path import LINEAR_NOT_CONNECTED, LINEAR_NOT_LOADED
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.testing.tracker_reader_fakes import SNAPSHOT_TIME
from agent_hub.core.tracker.tracker_reader import MAX_READ_IDS, IssueSummary, TicketSnapshot

SPEC = b"""---
type: spec
feature: demo-feature
process_size: bounded
repos: [demo-api, demo-hub]
linear: [DEM-7]
---
# Spec
"""
EVAL = b"""# Evaluation

Some notes first.

**Verdict: SHIP-WITH-OWNER-STEPS.** Two of three ACs pass by command.
"""


def a_record(*, passes: tuple[bool, ...] = (True, True, False), manual_last: bool = True) -> bytes:
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": f"Criterion {index}",
            "repo": "demo-api",
            "verification": "make check" if index < len(passes) or not manual_last else "manual",
            "passes": passed,
            "evidence": "test run" if passed else None,
        }
        for index, passed in enumerate(passes, start=1)
    ]
    return json.dumps(
        {"feature": "demo-feature", "linear": ["DEM-7", "DEM-8"], "acs": acs}
    ).encode()


def a_complete_folder() -> FeatureFolder:
    return FeatureFolder(
        slug="demo-feature",
        files=("spec.md", "research.md", "plan.md", "features.json", "issues.md", "eval.md"),
        features_json=a_record(),
        spec_head=SPEC,
        eval_head=EVAL,
    )


def test_reads_every_part_when_feature_complete() -> None:
    view = feature_view(a_complete_folder(), project="demo")

    assert view.project == "demo"
    assert view.slug == "demo-feature"
    assert view.size == "bounded"
    assert view.repos == ("demo-api", "demo-hub")
    assert view.issues == ("DEM-7", "DEM-8")
    assert view.files == (
        "spec.md",
        "research.md",
        "plan.md",
        "issues.md",
        "features.json",
        "eval.md",
    )
    assert (view.acs.passing, view.acs.total, view.acs.owner_steps) == (2, 3, 1)  # type: ignore[union-attr]
    assert view.verdict == "SHIP-WITH-OWNER-STEPS"
    assert (
        view.verdict_line == "**Verdict: SHIP-WITH-OWNER-STEPS.** Two of three ACs pass by command."
    )
    assert view.phase == "implement"
    assert view.golden_path.phase == "implement"
    assert view.tickets_source == "plan"
    assert view.problem is None
    assert view.sources_missing == (EventSource.GITHUB,)


def test_lists_ac_rows_when_detail_read() -> None:
    detail = feature_detail(a_complete_folder(), project="demo")

    assert [row.id for row in detail.ac_rows] == ["AC-7.1", "AC-7.2", "AC-7.3"]
    last = detail.ac_rows[-1]
    assert (last.manual, last.passes, last.command, last.evidence) == (True, False, "manual", None)
    assert detail.ac_rows[0].command == "make check"


def test_lists_records_when_research_and_eval_missing() -> None:
    folder = FeatureFolder(
        slug="demo-feature",
        files=("spec.md", "plan.md", "features.json"),
        features_json=a_record(),
        spec_head=SPEC,
    )

    detail = feature_detail(folder, project="demo")

    base = "features/demo-feature"
    assert detail.records == (
        FeatureRecord(name="spec", path=f"{base}/spec.md", present=True),
        FeatureRecord(name="research", path=f"{base}/research.md", present=False),
        FeatureRecord(name="plan", path=f"{base}/plan.md", present=True),
        FeatureRecord(name="eval", path=f"{base}/eval.md", present=False),
        FeatureRecord(name="issues", path=f"{base}/issues.md", present=False),
    )
    row = detail.ac_rows[0]
    assert (row.id, row.description, row.passes, row.command, row.evidence, row.manual) == (
        "AC-7.1",
        "Criterion 1",
        True,
        "make check",
        "test run",
        False,
    )
    assert "records" not in feature_view(folder, project="demo").model_dump()


def test_reads_no_verdict_when_no_eval() -> None:
    folder = FeatureFolder(
        slug="planned",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=a_record(passes=(False, False)),
        spec_head=SPEC,
    )

    view = feature_view(folder, project="demo")

    assert view.verdict is None
    assert view.verdict_line is None
    assert view.phase == "implement"


def test_reaches_implement_phase_when_an_ac_passes_without_eval() -> None:
    folder = FeatureFolder(
        slug="moving",
        files=("spec.md", "plan.md", "issues.md", "features.json"),
        features_json=a_record(passes=(True, False)),
    )

    assert feature_view(folder, project="demo").phase == "implement"


@pytest.mark.parametrize(
    ("record", "reason"),
    [
        (b'{"acs": [}', "could not be parsed"),
        (b'{"acs": "none"}', "could not be parsed"),
        (b'{"acs": [{"id": 3}]}', "could not be parsed"),
        ("cannot read: not a regular file", "could not be read"),
    ],
    ids=["bad-json", "acs-not-list", "ac-wrong-shape", "unread"],
)
def test_carries_problem_when_record_malformed(record: bytes | str, reason: str) -> None:
    folder = FeatureFolder(
        slug="broken",
        files=("spec.md", "features.json"),
        features_json=record,
        spec_head=SPEC,
    )

    detail = feature_detail(folder, project="demo")

    assert detail.problem is not None
    assert reason in detail.problem
    assert "\n" not in detail.problem
    assert detail.acs is None
    assert detail.ac_rows == ()
    assert detail.size == "bounded"
    assert detail.issues == ("DEM-7",)


def test_ignores_frontmatter_when_spec_has_none() -> None:
    folder = FeatureFolder(
        slug="bare", files=("spec.md",), spec_head=b"# Spec\nprocess_size: huge\n"
    )

    view = feature_view(folder, project="demo")

    assert view.size is None
    assert view.repos == ()
    assert view.phase == "research"


def test_ignores_unknown_size_when_frontmatter_odd() -> None:
    folder = FeatureFolder(
        slug="odd", files=("spec.md",), spec_head=b"---\nprocess_size: huge\nrepos: demo-api\n---\n"
    )

    view = feature_view(folder, project="demo")

    assert view.size is None
    assert view.repos == ("demo-api",)


@pytest.mark.parametrize(
    ("line", "verdict"),
    [
        (b"## Verdict: SHIP", "SHIP"),
        (b"**Verdict: NO-SHIP.** 31 of 33 ACs pass.", "NO-SHIP"),
        (b"**Verdict: SHIP** (PR 1 only).", "SHIP"),
        (b"Verdict SHIP-WITH-OWNER-STEPS", "SHIP-WITH-OWNER-STEPS"),
    ],
)
def test_reads_verdict_when_eval_names_one(line: bytes, verdict: str) -> None:
    folder = FeatureFolder(slug="done", files=("eval.md",), eval_head=b"# Eval\n\n" + line + b"\n")

    assert feature_view(folder, project="demo").verdict == verdict


def test_keeps_eval_and_review_heads_when_folder_built() -> None:
    head = RecordHead(name="demo-1520.md", head=b"---\ntype: eval\n---\n", problem=None)
    folder = FeatureFolder(slug="demo", files=(), evals=(head,), evals_skipped=2)

    assert (folder.evals, folder.reviews, folder.evals_skipped, folder.reviews_skipped) == (
        (head,),
        (),
        2,
        0,
    )


def a_summary(issue_id: str, *, state_type: str = "started") -> IssueSummary:
    return IssueSummary.model_validate(
        {
            "id": issue_id,
            "title": f"Synthetic {issue_id}",
            "state": {"name": state_type.title(), "type": state_type},
            "assignee": None,
            "url": f"https://linear.app/demo/issue/{issue_id}",
            "priority": 2,
            "estimate": None,
            "blocks": (),
            "blocked_by": (),
        }
    )


def a_linear_read(*summaries: IssueSummary) -> SnapshotRead:
    return SnapshotRead(
        snapshot=TicketSnapshot(summaries=summaries, missing=(), external=()),
        source="linear",
        stale=False,
        as_of=SNAPSHOT_TIME,
        failure=None,
        detail=None,
        http_status=None,
    )


COLD_READ = SnapshotRead(
    snapshot=None,
    source="plan",
    stale=False,
    as_of=None,
    failure=None,
    detail=None,
    http_status=None,
)


def a_ticket_record() -> bytes:
    return json.dumps(
        {
            "linear": ["DEM-7"],
            "tickets": [
                {"key": "T1", "id": "DEM-7", "title": "Collector", "order": 1},
                {"key": "T2", "title": "Reader", "blocked_by": ["T1"], "order": 2},
            ],
            "acs": [
                {"id": "AC-7.1", "description": "d", "passes": True, "ticket": "T1"},
                {"id": "AC-7.2", "description": "d", "passes": False, "ticket": "T2"},
            ],
        }
    ).encode()


def _states(path: GoldenPath) -> dict[str, str]:
    return {step.name: step.state for step in path.steps}


def _meta(path: GoldenPath, name: str) -> str | None:
    return next(step.meta for step in path.steps if step.name == name)


def test_parses_record_when_tickets_and_ticket_per_ac() -> None:
    folder = FeatureFolder(
        slug="planned",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=a_ticket_record(),
        spec_head=SPEC,
    )

    detail = feature_detail(folder, project="demo")

    assert detail.problem is None
    assert [row.id for row in detail.ac_rows] == ["AC-7.1", "AC-7.2"]
    assert detail.issues == ("DEM-7",)
    assert detail.tickets_source == "plan"
    assert detail.phase == detail.golden_path.phase == "tickets"
    assert _meta(detail.golden_path, "tickets") == "1 of 2 created"
    assert _meta(detail.golden_path, "shipped") == LINEAR_NOT_CONNECTED


def test_reads_ticket_ids_when_record_plans_tickets() -> None:
    folder = FeatureFolder(
        slug="planned", files=("features.json",), features_json=a_ticket_record()
    )

    assert ticket_ids(folder) == ("DEM-7",)
    assert ticket_ids(FeatureFolder(slug="none", files=())) == ()
    assert ticket_ids(FeatureFolder(slug="bad", files=(), features_json=b"{")) == ()


def test_reads_plan_external_blockers_when_plan_names_tracker_ids() -> None:
    record = json.dumps(
        {
            "linear": ["DEM-7"],
            "tickets": [
                {"key": "T1", "id": "DEM-1", "blocked_by": ["OPS-7", "T2", "DEM-7"]},
                {"key": "T2", "blocked_by": ["OPS-3", "draft-key"]},
                {"key": "AB-1", "id": "DEM-2", "blocked_by": ["AB-1"]},
            ],
            "acs": [],
        }
    ).encode()
    folder = FeatureFolder(slug="planned", files=("features.json",), features_json=record)

    assert ticket_ids(folder) == ("DEM-1", "DEM-2", "DEM-7", "OPS-3", "OPS-7")


def test_keeps_own_ids_within_read_bound_when_external_blockers_overflow() -> None:
    tickets = [
        {"key": f"T{n}", "id": f"DEM-{n}", "blocked_by": [f"OPS-{n}"]}
        for n in range(1, MAX_READ_IDS)
    ]
    record = json.dumps({"tickets": tickets, "acs": []}).encode()
    folder = FeatureFolder(slug="big", files=("features.json",), features_json=record)

    ids = ticket_ids(folder)

    assert len(ids) == MAX_READ_IDS
    assert set(ids) == {f"DEM-{n}" for n in range(1, MAX_READ_IDS)} | {"OPS-1"}


def test_uses_warm_snapshot_when_read_from_linear() -> None:
    folder = FeatureFolder(
        slug="planned",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=a_ticket_record(),
    )

    detail = feature_detail(
        folder, project="demo", read=a_linear_read(a_summary("DEM-7", state_type="completed"))
    )

    assert detail.tickets_source == "linear"
    assert _meta(detail.golden_path, "shipped") == "1/2 Done"


def test_says_not_loaded_when_cache_cold_with_tickets() -> None:
    folder = FeatureFolder(
        slug="planned",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=a_ticket_record(),
    )

    detail = feature_detail(folder, project="demo", read=COLD_READ)

    assert detail.tickets_source == "plan"
    assert _meta(detail.golden_path, "shipped") == LINEAR_NOT_LOADED


def test_lists_every_eval_when_detail_read() -> None:
    head = RecordHead(
        name="demo-1520.md",
        head=b"---\ntype: eval\ndelivery: demo-1520\nverdict: SHIP\nacs: [AC-7.1]\n---\n",
        problem=None,
    )
    folder = FeatureFolder(
        slug="demo-feature",
        files=("features.json", "eval.md"),
        features_json=a_record(),
        eval_head=EVAL,
        evals=(head,),
    )

    detail = feature_detail(folder, project="demo")

    assert [(record.delivery, record.legacy) for record in detail.evals] == [
        ("legacy", True),
        ("demo-1520", False),
    ]
    assert "evals" not in feature_view(folder, project="demo").model_dump()


def _owner_record() -> bytes:
    tickets = [
        {"key": f"T{number}", "id": f"TIP-{1519 + number}", "order": number}
        for number in range(1, 18)
    ]
    acs = [
        {
            "id": f"AC-9.{index}",
            "description": "Given x, when y, then z",
            "passes": index <= 3,
            "ticket": f"T{(index - 1) % 17 + 1}",
        }
        for index in range(1, 37)
    ]
    return json.dumps({"tickets": tickets, "acs": acs}).encode()


def test_never_marks_evaluate_done_when_ship_covers_part() -> None:
    """AGH-136 owner report: a SHIP over 3 of 36 ACs showed the feature as Evaluate done.

    17 tickets, 1 Done in Linear, 3/36 ACs passing, one ``evals/demo-1520.md`` SHIP covering
    three ACs and no review records: the feature is still implementing.
    """
    ship = RecordHead(
        name="demo-1520.md",
        head=(
            b"---\ntype: eval\ndelivery: demo-1520\nverdict: SHIP\ntickets: [DEMO-1520]\n"
            b"acs: [AC-9.1, AC-9.2, AC-9.3]\nevaluated_at: 2026-10-09\n---\n# Eval\n"
        ),
        problem=None,
    )
    folder = FeatureFolder(
        slug="ups-native-client",
        files=("spec.md", "research.md", "plan.md", "issues.md", "features.json"),
        features_json=_owner_record(),
        spec_head=SPEC,
        evals=(ship,),
    )
    summaries = (
        a_summary("DEMO-1520", state_type="completed"),
        *(a_summary(f"TIP-{1519 + number}") for number in range(2, 18)),
    )

    detail = feature_detail(folder, project="demo", read=a_linear_read(*summaries))

    path = detail.golden_path
    assert detail.phase == path.phase == "implement"
    assert _states(path) == {
        "spec": "done",
        "research": "done",
        "plan": "done",
        "tickets": "done",
        "implement": "current",
        "review": "pending",
        "evaluate": "partial",
        "shipped": "pending",
    }
    assert _meta(path, "implement") == "1/17 tickets · 3/36 ACs"
    assert _meta(path, "review") == "1/17 reviewed"
    assert _meta(path, "evaluate") == "partial: covers 3 of 36 ACs"
    assert [record.delivery for record in detail.evals] == ["demo-1520"]
    assert feature_view(folder, project="demo", read=a_linear_read(*summaries)).golden_path == path
