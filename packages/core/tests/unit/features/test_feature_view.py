import pytest
from pydantic import ValidationError

from agent_hub.core.features.feature_view import AcRow, FeatureDetail, FeatureRecord
from agent_hub.core.testing.read_model_builders import a_feature_view


def test_serializes_feature_with_ac_counts_when_dumped() -> None:
    document = a_feature_view().model_dump(mode="json")

    assert document["acs"] == {"passing": 2, "total": 5, "owner_steps": 1}
    assert (document["phase"], document["problem"]) == ("implement", None)


def test_serializes_detail_rows_when_detail_dumped() -> None:
    row = AcRow(id="AC-7.1", description="Given x, when y, then z", repo="demo-api", passes=True)
    detail = FeatureDetail.model_validate(a_feature_view().model_dump() | {"ac_rows": (row,)})

    assert detail.model_dump(mode="json")["ac_rows"][0]["id"] == "AC-7.1"


@pytest.mark.parametrize(("field", "value"), [("phase", "design"), ("verdict", "MAYBE")])
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
