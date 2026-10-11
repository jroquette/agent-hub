"""Estimated cost from transcript usage: per turn, per session and per run (D15, E5).

Usage is counted once per transcript message id (several transcript lines share one), and
priced with the dated table in ``pricing``. Amounts are exact ``Decimal`` sums; only the API
rounds them, to 4 places, when it writes them. A model without a price makes the cost unknown
(``None`` with a reason), never zero.
"""

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from agent_hub.core.events.event import EventSource, EventType
from agent_hub.core.events.stored_event import StoredEvent
from agent_hub.core.readmodels.fact_keys import canonical_events, usage_key
from agent_hub.core.sessions.pricing import PRICES, PRICES_AS_OF, PerMillion, price_for
from agent_hub.core.sessions.session import SessionCost, TokenUsage, TurnCost

_MILLION = Decimal(1_000_000)
_TOKEN_KEYS = ("input_tokens", "output_tokens", "cache_read_tokens", "cache_write_tokens")


class UsageRecord(BaseModel):
    """The token usage of one transcript message."""

    model_config = ConfigDict(frozen=True)

    turn: int
    model: str | None
    input: int
    output: int
    cache_read: int
    cache_write: int


def _count(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return 0
    return value


def _has_usage(stored: StoredEvent) -> bool:
    event = stored.event
    return (
        event.type == EventType.MESSAGE
        and event.source == EventSource.TRANSCRIPT
        and any(key in event.payload for key in _TOKEN_KEYS)
    )


def usage_records(events: Iterable[StoredEvent]) -> list[UsageRecord]:
    """One record per message with usage, in canonical order; repeats of a message id dropped."""
    seen: set[str] = set()
    records: list[UsageRecord] = []
    for stored in canonical_events(events):
        if not _has_usage(stored):
            continue
        key = usage_key(stored.event) or stored.event.source_id
        if key in seen:
            continue
        seen.add(key)
        payload = stored.event.payload
        model = payload.get("model")
        records.append(
            UsageRecord(
                turn=_count(payload.get("turn")),
                model=model if isinstance(model, str) and model else None,
                input=_count(payload.get("input_tokens")),
                output=_count(payload.get("output_tokens")),
                cache_read=_count(payload.get("cache_read_tokens")),
                cache_write=_count(payload.get("cache_write_tokens")),
            )
        )
    return records


def usage_tokens(records: Sequence[UsageRecord]) -> TokenUsage | None:
    """The tokens of ``records`` added up, or None when there is no usage."""
    if not records:
        return None
    return TokenUsage(
        input=sum(record.input for record in records),
        output=sum(record.output for record in records),
        cache_read=sum(record.cache_read for record in records),
        cache_write=sum(record.cache_write for record in records),
    )


def record_cost(record: UsageRecord, price: PerMillion) -> Decimal:
    """The exact USD cost of one message's usage at ``price``."""
    total = (
        record.input * price.input
        + record.output * price.output
        + record.cache_read * price.cache_read
        + record.cache_write * price.cache_write
    )
    return total / _MILLION


def unknown_cost_reason(
    records: Sequence[UsageRecord], prices: Mapping[str, PerMillion]
) -> str | None:
    """Why the usage cannot be priced (the first model without a price), or None."""
    for record in records:
        if record.model is None:
            return "Cost unknown: usage names no model"
        if price_for(record.model, prices) is None:
            return f"Cost unknown: model {record.model} has no price"
    return None


def _turn_cost(
    turn: int, records: Sequence[UsageRecord], prices: Mapping[str, PerMillion]
) -> TurnCost:
    known = unknown_cost_reason(records, prices) is None
    cost: Decimal | None = None
    if known:
        cost = Decimal(0)
        for record in records:
            price = price_for(record.model or "", prices)
            if price is not None:
                cost += record_cost(record, price)
    return TurnCost(
        turn=turn,
        input=sum(record.input for record in records),
        output=sum(record.output for record in records),
        cache_read=sum(record.cache_read for record in records),
        cache_write=sum(record.cache_write for record in records),
        cost_usd=cost,
    )


def fold_session_cost(
    session_id: str,
    events: Iterable[StoredEvent],
    *,
    prices: Mapping[str, PerMillion] = PRICES,
    prices_as_of: date = PRICES_AS_OF,
) -> SessionCost:
    """The Cost tab of a session from its events: per-turn series and total."""
    records = usage_records(events)
    by_turn: dict[int, list[UsageRecord]] = {}
    for record in records:
        by_turn.setdefault(record.turn, []).append(record)
    series = tuple(_turn_cost(turn, by_turn[turn], prices) for turn in sorted(by_turn))
    reason = unknown_cost_reason(records, prices)
    total: Decimal | None = None
    if records and reason is None:
        total = sum((turn.cost_usd or Decimal(0) for turn in series), Decimal(0))
    models = [record.model for record in records if record.model is not None]
    return SessionCost(
        session_id=session_id,
        model=models[-1] if models else None,
        series=series,
        total_usd=total,
        unknown_reason=reason,
        prices_as_of=prices_as_of,
    )


def run_cost(
    session_costs: Sequence[Decimal | None], *, executor_cost: Decimal | None
) -> tuple[Decimal | None, Literal["sessions", "executor"] | None]:
    """A run's cost: the sum of its sessions' costs when all are known, else ``hub run``'s own.

    ``session_costs`` holds the costs of the run's sessions that have usage (None = unknown).
    """
    if session_costs and all(cost is not None for cost in session_costs):
        return sum((cost or Decimal(0) for cost in session_costs), Decimal(0)), "sessions"
    if executor_cost is not None:
        return executor_cost, "executor"
    return None, None
