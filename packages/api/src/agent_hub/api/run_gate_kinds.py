"""The engine gates a workflow run's record names, read for Approvals (AM-14, P-6).

``RecordedGateKinds`` reads ``<hub>/.agent-runs/workflows/<run>/records.jsonl`` (the CLI's run
record; never through a link, at most ``MAX_RECORD_BYTES``, a last line without its newline
dropped as a torn write) and folds it with core's ``recorded_gate_kinds``: which gates are
policy gates and which are investigation gates. Anything it cannot read whole names no gate,
so such a gate is never answered here as a policy gate (fail closed).
"""

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.core.scenarios.policy_gates import GateKind, recorded_gate_kinds
from agent_hub.core.workflows.launch import RUN_ID_PATTERN

RUN_FOLDERS: Final = Path(".agent-runs", "workflows")
RECORDS: Final = "records.jsonl"
# The CLI refuses a record past this size too (``workflow_runs.MAX_RECORDS_BYTES``).
MAX_RECORD_BYTES: Final = 64 << 20


class RecordedGateKinds:
    """``RunGateKinds`` over the runs' record files."""

    def gate_kinds(self, hub_path: str, run_id: str) -> Mapping[str, GateKind]:
        if not RUN_ID_PATTERN.fullmatch(run_id):
            return {}
        folder = Path(hub_path) / RUN_FOLDERS / run_id
        records = None if folder.is_symlink() else _records(folder / RECORDS)
        return {} if records is None else recorded_gate_kinds(records)


def _records(path: Path) -> list[dict[str, JsonValue]] | None:
    """The record's lines, or ``None`` when it cannot be read whole."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC)
    except OSError:
        return None
    with os.fdopen(descriptor, "rb") as file:
        data = file.read(MAX_RECORD_BYTES + 1)
    if len(data) > MAX_RECORD_BYTES:
        return None
    records: list[dict[str, JsonValue]] = []
    for line in data.split(b"\n")[:-1]:
        try:
            record = json.loads(line)
        except ValueError:
            return None
        if not isinstance(record, dict):
            return None
        records.append(record)
    return records
