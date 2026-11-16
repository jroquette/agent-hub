from decimal import Decimal

from agent_hub.core.sessions.pricing import PerMillion
from agent_hub.core.sessions.session_cost import (
    fold_session_cost,
    run_cost,
    usage_records,
    usage_tokens,
)
from agent_hub.core.testing.session_scenarios import as_stored, shuffled, usage_events

PRICES = {
    "claude-test-1": PerMillion(
        input=Decimal(3),
        output=Decimal(15),
        cache_read=Decimal("0.30"),
        cache_write=Decimal("3.75"),
    )
}


def _cost(*tokens: int) -> Decimal:
    input_tokens, output, cache_read, cache_write = tokens
    return (
        input_tokens * Decimal(3)
        + output * Decimal(15)
        + cache_read * Decimal("0.30")
        + cache_write * Decimal("3.75")
    ) / Decimal(1_000_000)


TURNS = ((1000, 200, 5000, 300), (2500, 900, 7000, 0), (10, 1, 0, 0))


def test_sums_per_turn_costs_when_model_known() -> None:
    events = as_stored(usage_events(turns=TURNS, model="claude-test-1"))

    cost = fold_session_cost("session-1", events, prices=PRICES)

    expected = [_cost(*turn) for turn in TURNS]
    assert [turn.cost_usd for turn in cost.series] == expected
    assert cost.total_usd == sum(expected, Decimal(0))
    assert isinstance(cost.total_usd, Decimal)
    assert cost.model == "claude-test-1"
    assert cost.unknown_reason is None


def test_keeps_exact_decimal_when_cost_has_more_than_four_places() -> None:
    events = as_stored(usage_events(turns=((1, 1, 1, 1),), model="claude-test-1"))

    cost = fold_session_cost("session-1", events, prices=PRICES)

    assert cost.total_usd == Decimal("0.00002205")


def test_counts_usage_once_per_message_id_when_blocks_repeat_it() -> None:
    once = as_stored(usage_events(turns=TURNS, model="claude-test-1"))
    split = as_stored(usage_events(turns=TURNS, model="claude-test-1", split_blocks=3))

    assert fold_session_cost("session-1", split, prices=PRICES) == fold_session_cost(
        "session-1", once, prices=PRICES
    )
    assert usage_tokens(usage_records(split)) == usage_tokens(usage_records(once))


def test_gives_same_cost_when_usage_events_shuffled() -> None:
    events = as_stored(usage_events(turns=TURNS, model="claude-test-1", split_blocks=2))
    expected = fold_session_cost("session-1", events, prices=PRICES)

    for seed in range(20):
        noisy = shuffled([*events, *events[:2]], seed)
        assert fold_session_cost("session-1", noisy, prices=PRICES) == expected


def test_gives_null_cost_with_reason_when_model_unknown() -> None:
    events = as_stored(usage_events(turns=TURNS, model="claude-unknown-9"))

    cost = fold_session_cost("session-1", events, prices=PRICES)

    assert cost.total_usd is None
    assert cost.unknown_reason == "Cost unknown: model claude-unknown-9 has no price"
    assert all(turn.cost_usd is None for turn in cost.series)
    assert [turn.input for turn in cost.series] == [turn[0] for turn in TURNS]


def test_gives_null_cost_when_session_has_no_usage() -> None:
    cost = fold_session_cost("session-1", [], prices=PRICES)

    assert cost.total_usd is None
    assert cost.series == ()
    assert cost.unknown_reason is None


def test_sums_tokens_when_usage_folded() -> None:
    tokens = usage_tokens(usage_records(as_stored(usage_events(turns=TURNS))))

    assert tokens is not None
    assert (tokens.input, tokens.output, tokens.cache_read, tokens.cache_write) == (
        3510,
        1101,
        12000,
        300,
    )
    assert usage_tokens([]) is None


def test_sums_session_costs_when_run_total_folded() -> None:
    assert run_cost([Decimal("1.5"), Decimal("0.25")], executor_cost=Decimal(9)) == (
        Decimal("1.75"),
        "sessions",
    )


def test_uses_executor_cost_when_no_session_cost_known() -> None:
    assert run_cost([], executor_cost=Decimal("2.5")) == (Decimal("2.5"), "executor")
    assert run_cost([None], executor_cost=Decimal("2.5")) == (Decimal("2.5"), "executor")
    assert run_cost([], executor_cost=None) == (None, None)
