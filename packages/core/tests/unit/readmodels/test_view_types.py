from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from agent_hub.core.readmodels.view_types import (
    ApiTimestamp,
    DerivedView,
    Money,
    ViewModel,
    money_text,
    timestamp_text,
)


class Priced(ViewModel):
    cost: Money
    at: ApiTimestamp


@pytest.mark.parametrize(
    ("value", "text"),
    [("1.2734", "1.2734"), ("2", "2.0000"), ("0.00005", "0.0000"), ("0.00015", "0.0002")],
)
def test_serializes_money_with_four_places_when_written_as_text(value: str, text: str) -> None:
    assert money_text(Decimal(value)) == text


def test_serializes_timestamp_in_utc_with_milliseconds_when_written_as_text() -> None:
    at = datetime(2026, 10, 9, 16, 5, 41, 882999, tzinfo=timezone(timedelta(hours=2)))

    assert timestamp_text(at.astimezone(UTC)) == "2026-10-09T14:05:41.882Z"


def test_serializes_money_and_timestamp_as_strings_when_dumped_to_json() -> None:
    priced = Priced(cost=Decimal("1.5"), at=datetime(2026, 10, 9, 14, 0, tzinfo=UTC))

    assert priced.model_dump_json() == '{"cost":"1.5000","at":"2026-10-09T14:00:00.000Z"}'


def test_serializes_schema_as_strings_when_json_schema_built() -> None:
    definitions = Priced.model_json_schema(mode="serialization")["$defs"]

    assert definitions["Money"]["type"] == "string"
    assert definitions["ApiTimestamp"] == {"type": "string", "format": "date-time"}


def test_reads_money_back_when_json_round_trips() -> None:
    priced = Priced(cost=Decimal("1.2734"), at=datetime(2026, 10, 9, tzinfo=UTC))

    assert Priced.model_validate_json(priced.model_dump_json()) == priced


def test_rejects_unknown_key_when_view_validated() -> None:
    with pytest.raises(ValidationError, match="extra"):
        Priced.model_validate({"cost": "1", "at": "2026-10-09T00:00:00Z", "other": 1})


def test_serializes_defaults_when_derived_view_dumped() -> None:
    assert DerivedView().model_dump(mode="json") == {"derived": True, "sources_missing": []}
