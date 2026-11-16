"""The engine gates a run's record names, as hub web reads them (AGH-359, AM-14, P-6)."""

import json
import os
from pathlib import Path

from agent_hub.api.run_gate_kinds import MAX_RECORD_BYTES, RecordedGateKinds


def records_at(hub: Path, run_id: str, *lines: object) -> Path:
    folder = hub / ".agent-runs" / "workflows" / run_id
    folder.mkdir(parents=True)
    path = folder / "records.jsonl"
    path.write_text("".join(json.dumps(line) + "\n" for line in lines))
    return path


def test_names_policy_and_investigation_gates_when_record_holds_them(tmp_path: Path) -> None:
    records_at(
        tmp_path,
        "r1",
        {"event": "start", "policy_gates": ["send"]},
        {"event": "gate", "node": "grp__ask"},
        {"event": "policy_asks", "steps": ["g__ship"]},
        {"event": "investigation", "gate": "check__investigation"},
    )

    kinds = RecordedGateKinds().gate_kinds(str(tmp_path), "r1")

    assert kinds == {
        "send__ask": "policy",
        "g__ship__ask": "policy",
        "check__investigation": "investigation",
    }


def test_names_nothing_when_record_unreadable_or_linked(tmp_path: Path) -> None:
    path = records_at(tmp_path / "a", "r1", {"event": "start", "policy_gates": ["send"]})
    (tmp_path / "b" / ".agent-runs" / "workflows" / "r1").mkdir(parents=True)
    os.symlink(path, tmp_path / "b" / ".agent-runs" / "workflows" / "r1" / "records.jsonl")
    big = records_at(tmp_path / "c", "r1", {"event": "start", "policy_gates": ["send"]})
    big.write_text(big.read_text() + "x" * MAX_RECORD_BYTES)
    torn = records_at(tmp_path / "d", "r1", {"event": "start", "policy_gates": ["send"]})
    torn.write_text(torn.read_text() + '{"event": "policy_asks", "steps": ["late"]}')
    garbled = records_at(tmp_path / "e", "r1", {"event": "start", "policy_gates": ["send"]})
    garbled.write_text(garbled.read_text() + "not json\n")

    read = RecordedGateKinds()

    assert read.gate_kinds(str(tmp_path / "missing"), "r1") == {}
    assert read.gate_kinds(str(tmp_path / "b"), "r1") == {}
    assert read.gate_kinds(str(tmp_path / "c"), "r1") == {}
    assert read.gate_kinds(str(tmp_path / "d"), "r1") == {"send__ask": "policy"}
    assert read.gate_kinds(str(tmp_path / "e"), "r1") == {}
    assert read.gate_kinds(str(tmp_path / "a"), "../r1") == {}
