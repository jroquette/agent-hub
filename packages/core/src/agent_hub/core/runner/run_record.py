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


class RunOutcome(StrEnum):
    """What a run delivered, apart from whether its machinery worked (AGH-140).

    ``no_changes`` (the session left no commit) and ``blocked`` (the session stopped and asked
    for a human) end the run without a PR but are not failures: the run's status stays ``done``.
    """

    DELIVERED = "delivered"
    NO_CHANGES = "no_changes"
    BLOCKED = "blocked"
    FAILED = "failed"


# The outcomes of a run that ended cleanly without a PR.
NOT_DELIVERED: Final = frozenset({RunOutcome.NO_CHANGES, RunOutcome.BLOCKED})
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
    *,
    ok: bool,
    failed_stage: Stage | None,
    total_cost_usd: float,
    pr: str,
    outcome: RunOutcome,
) -> dict[str, JsonValue]:
    """The ``reported`` event's data, as the retro reads it: ``failed_stage`` None unless the
    run failed, then ``outcome`` (added by AGH-140, so older records lack it)."""
    return {
        "ok": ok,
        "total_cost_usd": total_cost_usd,
        "pr": pr,
        "failed_stage": None if failed_stage is None else failed_stage.value,
        "outcome": outcome.value,
    }


def not_delivered_data(*, outcome: RunOutcome, stage: Stage, reason: str) -> dict[str, JsonValue]:
    """The ``not_delivered`` event's data: why a run that did not fail opened no PR."""
    if outcome not in NOT_DELIVERED:
        msg = f"not a not-delivered outcome: {outcome.value!r}"
        raise ValueError(msg)
    return {"outcome": outcome.value, "stage": stage.value, "reason": reason}
