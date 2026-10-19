"""``items.leftovers`` (AGH-297): temp-named entries an interrupted item write left beside units."""

from collections.abc import Callable
from dataclasses import replace

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.item_leftovers_rule import FIX, ITEM_LEFTOVERS, MAX_FINDINGS
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity

type SnapshotFactory = Callable[..., DoctorSnapshot]

MESSAGE = "temporary entry left by an interrupted item write"


def test_declares_design_fields_when_rule_read() -> None:
    assert ITEM_LEFTOVERS.id == "items.leftovers"
    assert ITEM_LEFTOVERS.severity is Severity.WARNING
    assert ITEM_LEFTOVERS.reads == frozenset({Read.ITEM_FOLDERS})
    assert ITEM_LEFTOVERS.module is None
    assert RULE_IDS[-1] == "items.leftovers"


def test_warns_each_leftover_when_item_folders_hold_some(snapshot_of: SnapshotFactory) -> None:
    leftovers = (
        "plugin/demo/skills/.alpha.hub-tmp-0123abcd",
        ".claude/agents/.reviewer.md.hub-tmp-89abcdef",
    )
    snapshot = replace(snapshot_of(), item_leftovers=leftovers)

    found = [(f.path, f.message, f.fix, f.severity) for f in ITEM_LEFTOVERS.check(snapshot)]

    assert found == [(path, MESSAGE, FIX, Severity.WARNING) for path in leftovers]


def test_counts_rest_when_leftovers_past_bound(snapshot_of: SnapshotFactory) -> None:
    leftovers = tuple(f"plugin/demo/skills/.s{n}.hub-tmp-0123abcd" for n in range(13))
    snapshot = replace(snapshot_of(), item_leftovers=leftovers)

    found = list(ITEM_LEFTOVERS.check(snapshot))

    assert [f.path for f in found[:MAX_FINDINGS]] == list(leftovers[:MAX_FINDINGS])
    assert found[-1].path == "."
    assert found[-1].message == f"3 more {MESSAGE}s besides the {MAX_FINDINGS} shown"
    assert len(found) == MAX_FINDINGS + 1


def test_finds_nothing_when_folders_not_read(snapshot_of: SnapshotFactory) -> None:
    assert list(ITEM_LEFTOVERS.check(snapshot_of())) == []
