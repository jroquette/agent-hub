"""The eval scope rules shared by the eval readers and the agent output checks."""

import re

import pytest

from agent_hub.core.features.feature_record import PlannedTicket, RecordAc
from agent_hub.core.features.scope_rules import (
    AC_ID_PATTERN,
    COMMIT_PATTERN,
    RERUN_PATTERN,
    named_scope,
    ticket_aliases,
)


def an_ac(ac_id: str, *, ticket: str | None = None) -> RecordAc:
    return RecordAc.model_validate(
        {"id": ac_id, "description": "Given x, when y, then z", "passes": False, "ticket": ticket}
    )


LIVE = (an_ac("AC-7.1", ticket="T1"), an_ac("AC-7.2", ticket="DEM-12"), an_ac("AC-7.3"))


@pytest.mark.parametrize(
    ("pattern", "accepted", "refused"),
    [
        (AC_ID_PATTERN, ("AC-139.1", "a" * 64, "7_x.y"), ("a" * 65, "-AC-1", "AC 1", "")),
        (COMMIT_PATTERN, ("81551fb", "0" * 40), ("81551f", "0" * 41, "81551FB", "81551fz")),
    ],
)
def test_matches_ids_as_feature_evals_did_when_patterns_used(
    pattern: re.Pattern[str], accepted: tuple[str, ...], refused: tuple[str, ...]
) -> None:
    assert [text for text in accepted if pattern.fullmatch(text) is None] == []
    assert [text for text in refused if pattern.fullmatch(text) is not None] == []


@pytest.mark.parametrize(
    ("delivery", "rerun"),
    [("dem-1-r2", "2"), ("dem-1-r9999", "9999"), ("dem-1-r0", None), ("dem-1-r10000", None)],
)
def test_matches_rerun_suffix_when_rerun_pattern_used(delivery: str, rerun: str | None) -> None:
    found = RERUN_PATTERN.search(delivery)

    assert (found.group(1) if found else None) == rerun


def test_maps_key_and_id_when_ticket_aliases_built() -> None:
    aliases = ticket_aliases(
        (PlannedTicket(key="t1", id="DEM-12"), PlannedTicket(key="T2", id=None))
    )

    assert aliases == {
        "T1": frozenset({"T1", "DEM-12"}),
        "DEM-12": frozenset({"T1", "DEM-12"}),
        "T2": frozenset({"T2"}),
    }


def test_expands_scope_when_named_scope_given_all_list_or_tickets() -> None:
    aliases = ticket_aliases((PlannedTicket(key="T1", id="DEM-12"),))

    assert named_scope(acs="all", tickets=(), live=LIVE, aliases=aliases) == (
        "AC-7.1",
        "AC-7.2",
        "AC-7.3",
    )
    assert named_scope(acs=("AC-9.9",), tickets=("T1",), live=LIVE, aliases=aliases) == ("AC-9.9",)
    assert named_scope(acs=(), tickets=("dem-12",), live=LIVE, aliases=aliases) == (
        "AC-7.1",
        "AC-7.2",
    )
    assert named_scope(acs=(), tickets=("T5",), live=LIVE, aliases=aliases) == ()


def test_returns_none_when_named_scope_given_nothing() -> None:
    assert named_scope(acs=(), tickets=(), live=LIVE, aliases={}) is None
