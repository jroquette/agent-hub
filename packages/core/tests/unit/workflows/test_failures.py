"""Failure kinds and the retry decision: the kind decides, never the text (AC-213.7)."""

import random
from collections.abc import Callable
from datetime import timedelta
from typing import get_args

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.workflows.failures import (
    DurationError,
    ExecutableType,
    FailureKind,
    NodeFailedError,
    RetryDecision,
    RetryRecord,
    kind_for_exit,
    parse_duration,
    retry_decision,
)
from agent_hub.core.workflows.nodes import Retry

TRANSIENT: tuple[FailureKind, ...] = ("transient", "timeout", "rate_limited", "overloaded")
OPT_IN: tuple[FailureKind, ...] = ("exec_failed", "output_contract", "max_iterations", "unknown")
NEVER: tuple[FailureKind, ...] = ("config", "auth", "cancelled", "fatal")
ALL = Retry(max_attempts=5, on_error="all")


def no_jitter() -> float:
    """The middle of the jitter range: the factor is exactly 1."""
    return 0.5


def decide(
    kind: FailureKind,
    policy: Retry | None = None,
    *,
    node_type: ExecutableType = "agent",
    retries_done: int = 0,
    jitter: Callable[[], float] = no_jitter,
) -> RetryDecision:
    return retry_decision(
        kind, policy, node_type=node_type, retries_done=retries_done, jitter=jitter
    )


def test_lists_the_twelve_contract_kinds_when_kinds_are_read() -> None:
    assert set(get_args(FailureKind.__value__)) == {*TRANSIENT, *OPT_IN, *NEVER}


def test_carries_kind_and_detail_when_executor_raises_node_failure() -> None:
    failure = NodeFailedError("auth", "the provider refused the key")

    assert isinstance(failure, AgentHubError)
    assert (failure.kind, failure.detail) == ("auth", "the provider refused the key")


def test_reads_only_the_kind_when_failure_text_sounds_transient() -> None:
    failure = NodeFailedError("fatal", "rate limit exceeded, try again later")

    assert decide(failure.kind, ALL).retry is False


@pytest.mark.parametrize(
    ("exit_code", "timed_out", "kind"),
    [
        (0, False, None),
        (1, False, "exec_failed"),
        (-9, False, "exec_failed"),
        (-9, True, "timeout"),
    ],
)
def test_maps_exit_to_exec_failed_or_timeout_when_shell_or_script_ends(
    exit_code: int,
    timed_out: bool,  # noqa: FBT001 - a parametrized case
    kind: FailureKind | None,
) -> None:
    assert kind_for_exit(exit_code, timed_out=timed_out) == kind


@pytest.mark.parametrize(
    ("text", "delta"),
    [
        ("2s", timedelta(seconds=2)),
        ("5m", timedelta(minutes=5)),
        ("1h", timedelta(hours=1)),
        ("1d", timedelta(days=1)),
        ("999999d", timedelta(days=999999)),
    ],
)
def test_reads_a_timedelta_when_duration_is_well_formed(text: str, delta: timedelta) -> None:
    assert parse_duration(text) == delta


@pytest.mark.parametrize("text", ["1000000s", "9999999999999999999999d"])
def test_refuses_duration_when_it_has_more_than_six_digits(text: str) -> None:
    with pytest.raises(DurationError):
        parse_duration(text)


@pytest.mark.parametrize("kind", TRANSIENT)
def test_retries_by_default_when_kind_is_transient_class(kind: FailureKind) -> None:
    assert decide(kind).retry is True


@pytest.mark.parametrize("kind", OPT_IN)
def test_does_not_retry_by_default_when_kind_needs_opt_in(kind: FailureKind) -> None:
    assert decide(kind, Retry(max_attempts=5)) == RetryDecision(retry=False, delay=timedelta(0))


@pytest.mark.parametrize("kind", OPT_IN)
def test_retries_when_agent_opts_in_with_on_error_all(kind: FailureKind) -> None:
    assert decide(kind, ALL).retry is True


@pytest.mark.parametrize("kind", NEVER)
def test_never_retries_when_kind_is_fatal_class_even_with_on_error_all(kind: FailureKind) -> None:
    assert decide(kind, ALL).retry is False


@pytest.mark.parametrize("node_type", ["shell", "script"])
def test_never_retries_output_contract_when_node_is_shell_or_script(
    node_type: ExecutableType,
) -> None:
    decision = decide("output_contract", ALL, node_type=node_type)

    assert decision.retry is False


def test_retries_exec_failed_when_shell_opts_in() -> None:
    assert decide("exec_failed", ALL, node_type="shell").retry is True


def test_gives_one_transient_retry_of_two_seconds_when_node_has_no_retry_key() -> None:
    assert decide("transient", node_type="shell") == RetryDecision(
        retry=True, delay=timedelta(seconds=2)
    )
    assert decide("transient", node_type="shell", retries_done=1).retry is False


def test_stops_when_retries_reach_max_attempts() -> None:
    policy = Retry(max_attempts=3)

    decisions = [decide("timeout", policy, retries_done=n) for n in range(4)]

    assert [decision.retry for decision in decisions] == [True, True, True, False]


def test_never_retries_when_max_attempts_is_zero() -> None:
    decision = decide("transient", Retry(max_attempts=0))

    assert decision == RetryDecision(retry=False, delay=timedelta(0))


def test_doubles_the_delay_when_each_retry_follows_another() -> None:
    policy = Retry(max_attempts=4, delay="3s")

    delays = [decide("transient", policy, retries_done=n).delay for n in range(4)]

    assert delays == [timedelta(seconds=seconds) for seconds in (3, 6, 12, 24)]


@pytest.mark.parametrize(("delay", "retries_done"), [("1d", 4), ("1d", 0), ("31m", 1)])
def test_clamps_to_one_hour_when_backoff_would_wait_longer(delay: str, retries_done: int) -> None:
    decision = decide("transient", Retry(max_attempts=5, delay=delay), retries_done=retries_done)

    assert decision == RetryDecision(retry=True, delay=timedelta(hours=1))


def test_keeps_the_five_minute_cap_when_provider_pushes_back_with_a_long_delay() -> None:
    policy = Retry(max_attempts=5, delay="1d")

    assert decide("overloaded", policy, retries_done=4).delay == timedelta(minutes=5)


@pytest.mark.parametrize(("draw", "seconds"), [(-3.0, 22.5), (1.0, 67.5), (7.0, 67.5)])
def test_clamps_the_draw_when_jitter_source_leaves_its_range(draw: float, seconds: float) -> None:
    decision = decide("rate_limited", jitter=lambda: draw)

    assert decision.delay == timedelta(seconds=seconds)


def test_ignores_the_jitter_source_when_kind_is_transient_or_timeout() -> None:
    def fail() -> float:
        raise AssertionError

    assert decide("timeout", jitter=fail).delay == timedelta(seconds=2)


@pytest.mark.parametrize("kind", ["rate_limited", "overloaded"])
def test_waits_at_least_45_seconds_doubling_when_provider_pushes_back(kind: FailureKind) -> None:
    policy = Retry(max_attempts=5)

    delays = [decide(kind, policy, retries_done=n).delay for n in range(5)]

    assert delays == [timedelta(seconds=seconds) for seconds in (45, 90, 180, 300, 300)]


def test_keeps_a_longer_author_delay_when_provider_pushes_back() -> None:
    policy = Retry(max_attempts=2, delay="1m")

    assert decide("rate_limited", policy).delay == timedelta(minutes=1)


@pytest.mark.parametrize(("draw", "seconds"), [(0.0, 22.5), (0.999, 67.455)])
def test_spreads_the_delay_by_half_either_way_when_jitter_draws_its_bounds(
    draw: float, seconds: float
) -> None:
    decision = decide("rate_limited", jitter=lambda: draw)

    assert decision.delay == timedelta(seconds=seconds)


def test_repeats_the_same_delays_when_jitter_source_has_the_same_seed() -> None:
    def run(seed: int) -> list[timedelta]:
        source = random.Random(seed)  # noqa: S311 - a seeded jitter source, not cryptography
        return [
            decide("overloaded", ALL, retries_done=n, jitter=source.random).delay for n in range(5)
        ]

    assert run(7) == run(7)


def test_records_attempt_kind_and_delay_when_a_retry_is_scheduled() -> None:
    decision = decide("transient")

    record = RetryRecord(attempt=3, kind="transient", delay=decision.delay)

    assert (record.attempt, record.kind, record.delay) == (3, "transient", timedelta(seconds=2))
