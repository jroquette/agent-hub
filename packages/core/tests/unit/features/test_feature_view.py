import pytest
from pydantic import ValidationError

from agent_hub.core.features.feature_view import (
    AcRow,
    EvalRecord,
    FeatureDetail,
    FeatureRecord,
    GoldenPath,
    GoldenStep,
    StepProgress,
)
from agent_hub.core.testing.read_model_builders import a_feature_view


def test_serializes_feature_with_ac_counts_when_dumped() -> None:
    document = a_feature_view().model_dump(mode="json")

    assert document["acs"] == {"passing": 2, "total": 5, "owner_steps": 1}
    assert (document["phase"], document["problem"]) == ("build", None)


def test_serializes_detail_rows_when_detail_dumped() -> None:
    row = AcRow(id="AC-7.1", description="Given x, when y, then z", repo="demo-api", passes=True)
    detail = FeatureDetail.model_validate(a_feature_view().model_dump() | {"ac_rows": (row,)})

    assert detail.model_dump(mode="json")["ac_rows"][0]["id"] == "AC-7.1"


@pytest.mark.parametrize(
    ("field", "value"), [("phase", "design"), ("phase", "implement"), ("verdict", "MAYBE")]
)
def test_rejects_feature_when_value_unknown(field: str, value: str) -> None:
    with pytest.raises(ValidationError, match=field):
        a_feature_view(**{field: value})


def test_serializes_records_when_detail_has_records() -> None:
    records = (
        FeatureRecord(name="spec", path="features/demo-feature/spec.md", present=True),
        FeatureRecord(name="research", path="features/demo-feature/research.md", present=False),
    )
    detail = FeatureDetail.model_validate(a_feature_view().model_dump() | {"records": records})

    assert detail.model_dump(mode="json")["records"][1] == {
        "name": "research",
        "path": "features/demo-feature/research.md",
        "present": False,
    }


def test_rejects_record_when_name_unknown() -> None:
    with pytest.raises(ValidationError, match="name"):
        FeatureRecord.model_validate({"name": "notes", "path": "x.md", "present": True})


def test_serializes_golden_path_when_feature_built() -> None:
    steps = (
        GoldenStep(name="spec", state="done", meta=None, reason=None, progress=None),
        GoldenStep(
            name="build",
            state="current",
            meta="1 of 17 merged",
            reason=None,
            progress=StepProgress(done=1, total=17),
        ),
        GoldenStep(
            name="acceptance",
            state="unrecorded",
            meta="Ticket evals cover 3 of 36 ACs",
            reason="Build is not done",
            progress=StepProgress(done=3, total=36),
        ),
    )
    feature = a_feature_view(
        golden_path=GoldenPath(steps=steps, phase="build"), tickets_source="plan"
    )

    document = feature.model_dump(mode="json")

    assert document["tickets_source"] == "plan"
    assert document["golden_path"]["phase"] == "build"
    assert document["golden_path"]["steps"][1] == {
        "name": "build",
        "state": "current",
        "meta": "1 of 17 merged",
        "reason": None,
        "progress": {"done": 1, "total": 17},
    }
    assert document["golden_path"]["steps"][2]["state"] == "unrecorded"


def test_serializes_evals_when_detail_has_eval_records() -> None:
    record = EvalRecord(
        delivery="acme-1520",
        path="features/demo-feature/evals/acme-1520.md",
        verdict="SHIP",
        tickets=("ACME-1520",),
        acs=("AC-7.1", "AC-7.2"),
        prs=("demo-api#12",),
        commit="abc1234",
        evaluated_at="2026-10-13",
        legacy=False,
        problem=None,
    )
    whole = record.model_copy(update={"delivery": "feature", "acs": "all"})
    detail = FeatureDetail.model_validate(
        a_feature_view().model_dump() | {"evals": (record, whole)}
    )

    document = detail.model_dump(mode="json")

    assert document["evals"][0]["acs"] == ["AC-7.1", "AC-7.2"]
    assert document["evals"][1]["acs"] == "all"


@pytest.mark.parametrize(("field", "value"), [("state", "late"), ("name", "deploy")])
def test_rejects_golden_step_when_value_unknown(field: str, value: str) -> None:
    fields = {"name": "spec", "state": "done", "meta": None, "reason": None, "progress": None}
    with pytest.raises(ValidationError, match=field):
        GoldenStep.model_validate(fields | {field: value})
