"""The records of a run: its stages and one ``.agent-runs/<date>.jsonl`` line per transition.

A record keeps the old runner's fields and order (the retro reads them): ``ts``, ``run``,
``issue``, ``repo``, ``state``, ``event``, ``live``, then the event's data. The timestamp and the
run id come from the caller (E20: no clock or random source in core).
"""

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from agent_hub.core.json_form import JsonValue


class Stage(StrEnum):
    """A state of the run's machine; any stage before ``REPORTED`` can end in ``FAILED``."""

    PICKED = "PICKED"
    WORKTREE = "WORKTREE"
    IMPLEMENTING = "IMPLEMENTING"
    VERIFYING = "VERIFYING"
    PR_OPEN = "PR_OPEN"
    REPORTED = "REPORTED"
    FAILED = "FAILED"


RECORD_FIELDS: Final = ("ts", "run", "issue", "repo", "state", "event", "live")


def run_record(
    *,
    ts: str,
    run_id: str,
    issue_id: str,
    repo: str,
    state: Stage,
    event: str,
    live: bool,
    data: Mapping[str, JsonValue],
) -> dict[str, JsonValue]:
    """One transition's record; ``data`` naming a record field raises ``ValueError``."""
    clashing = sorted(set(data) & set(RECORD_FIELDS))
    if clashing:
        msg = f"event data names record fields: {', '.join(map(repr, clashing))}"
        raise ValueError(msg)
    record: dict[str, JsonValue] = {
        "ts": ts,
        "run": run_id,
        "issue": issue_id,
        "repo": repo,
        "state": state.value,
        "event": event,
        "live": live,
    }
    record.update(data)
    return record


def picked_data(
    *, budget: float, max_turns: int, model: str, transport: str
) -> dict[str, JsonValue]:
    """The ``picked`` event's data: the old runner's caps, then the tracker's transport (D16)."""
    return {"budget": budget, "max_turns": max_turns, "model": model, "transport": transport}


def reported_data(
    *, ok: bool, failed_stage: Stage | None, total_cost_usd: float, pr: str
) -> dict[str, JsonValue]:
    """The ``reported`` event's data, as the retro reads it: ``failed_stage`` None on success."""
    return {
        "ok": ok,
        "total_cost_usd": total_cost_usd,
        "pr": pr,
        "failed_stage": None if failed_stage is None else failed_stage.value,
    }
