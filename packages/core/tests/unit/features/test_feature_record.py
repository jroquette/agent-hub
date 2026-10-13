import pytest
from pydantic import ValidationError

from agent_hub.core.features.feature_record import (
    MAX_BLOCKED_BY,
    MAX_TICKETS,
    FeatureRecordFile,
    PlannedTicket,
)

_AC = {"id": "AC-7.1", "description": "Given x, when y, then z", "passes": False}


def _ticket(**overrides: object) -> dict[str, object]:
    return {
        "key": "T1",
        "id": "TIP-1520",
        "title": "Read summaries",
        "repo": "demo-api",
    } | overrides


def test_parses_record_when_tickets_absent() -> None:
    record = FeatureRecordFile.model_validate(
        {"linear": ["DEM-7"], "acs": [_AC], "unknown_key": {"kept": "out"}}
    )

    assert record.tickets == ()
    assert record.linear == ("DEM-7",)
    assert (record.acs[0].ticket, record.acs[0].withdrawn) == (None, False)


def test_parses_tickets_when_record_lists_them() -> None:
    record = FeatureRecordFile.model_validate(
        {
            "tickets": [
                _ticket(order=0),
                _ticket(key="T2", id=None, blocked_by=["T1", "TIP-9"], order=1),
            ],
            "acs": [_AC | {"ticket": "T2"}, _AC | {"id": "AC-7.2", "withdrawn": True}],
        }
    )

    assert record.tickets[1] == PlannedTicket(
        key="T2",
        id=None,
        title="Read summaries",
        repo="demo-api",
        blocked_by=("T1", "TIP-9"),
        order=1,
    )
    assert record.tickets[0].blocked_by == ()
    assert (record.acs[0].ticket, record.acs[1].withdrawn) == ("T2", True)


@pytest.mark.parametrize(
    "ticket",
    [
        _ticket(key="1st"),
        _ticket(key="T" * 33),
        _ticket(id="tip-1520"),
        _ticket(title="x" * 201),
        _ticket(order=-1),
        _ticket(blocked_by=["T 1"]),
        _ticket(blocked_by=[f"T{n}" for n in range(MAX_BLOCKED_BY + 1)]),
        _ticket(order="1"),
    ],
    ids=[
        "key-digit",
        "key-long",
        "id-lower",
        "title-long",
        "order-negative",
        "blocker-bad",
        "blockers-many",
        "order-text",
    ],
)
def test_refuses_ticket_when_over_bounds(ticket: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="tickets"):
        FeatureRecordFile.model_validate({"tickets": [ticket], "acs": []})


def test_refuses_tickets_when_over_bounds_in_count() -> None:
    tickets = [_ticket(key=f"T{n}", id=None) for n in range(MAX_TICKETS + 1)]

    with pytest.raises(ValidationError, match="tickets"):
        FeatureRecordFile.model_validate({"tickets": tickets, "acs": []})


def test_refuses_withdrawn_when_not_bool() -> None:
    with pytest.raises(ValidationError, match="withdrawn"):
        FeatureRecordFile.model_validate({"acs": [_AC | {"withdrawn": "yes"}]})
