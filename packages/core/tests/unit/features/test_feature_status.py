import json

import pytest

from agent_hub.core.events.event import EventSource
from agent_hub.core.features.feature_status import FeatureFolder, feature_detail, feature_view

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
    assert view.phase == "evaluate"
    assert view.problem is None
    assert view.sources_missing == (EventSource.GITHUB,)


def test_lists_ac_rows_when_detail_read() -> None:
    detail = feature_detail(a_complete_folder(), project="demo")

    assert [row.id for row in detail.ac_rows] == ["AC-7.1", "AC-7.2", "AC-7.3"]
    last = detail.ac_rows[-1]
    assert (last.manual, last.passes, last.command, last.evidence) == (True, False, "manual", None)
    assert detail.ac_rows[0].command == "make check"


def test_stops_at_plan_phase_when_no_eval() -> None:
    folder = FeatureFolder(
        slug="planned",
        files=("spec.md", "research.md", "plan.md", "features.json"),
        features_json=a_record(passes=(False, False)),
        spec_head=SPEC,
    )

    view = feature_view(folder, project="demo")

    assert view.verdict is None
    assert view.verdict_line is None
    assert view.phase == "plan"


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
    assert view.phase == "spec"


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
