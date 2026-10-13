import pytest

from agent_hub.core.agent_sessions.delta_ring import DeltaRing
from agent_hub.core.agent_sessions.records import DeltaFrame


def _texts(frames: list[DeltaFrame] | None) -> list[str]:
    assert frames is not None
    return [frame.text for frame in frames]


def test_returns_deltas_when_ring_holds_block() -> None:
    ring = DeltaRing(10)
    for text in ("a", "b", "c"):
        ring.push(4, 0, text)

    assert _texts(ring.since(4)) == ["a", "b", "c"]
    assert _texts(ring.since(4, 0)) == ["b", "c"]
    assert _texts(ring.since(4, 2)) == []


def test_numbers_deltas_when_blocks_share_seq() -> None:
    ring = DeltaRing(10)

    first = ring.push(4, 0, "a")
    second = ring.push(4, 1, "b")
    after_record = ring.push(5, 2, "c")

    assert (first.index, second.index, after_record.index) == (0, 1, 0)
    assert (second.after_seq, second.block) == (4, 1)


def test_returns_none_when_ring_moved_on() -> None:
    ring = DeltaRing(3)
    for text in ("a", "b", "c", "d", "e"):
        ring.push(4, 0, text)

    assert ring.since(4) is None
    assert ring.since(4, 0) is None
    assert _texts(ring.since(4, 1)) == ["c", "d", "e"]


def test_returns_none_when_later_block_evicted_older_one() -> None:
    ring = DeltaRing(2)
    ring.push(4, 0, "a")
    ring.push(6, 0, "b")
    ring.push(6, 0, "c")

    assert ring.since(4) is None
    assert _texts(ring.since(6)) == ["b", "c"]


def test_returns_empty_when_block_has_no_delta_yet() -> None:
    ring = DeltaRing(3)
    ring.push(4, 0, "a")

    assert ring.since(5) == []


def test_refuses_push_when_seq_goes_back() -> None:
    ring = DeltaRing(3)
    ring.push(5, 0, "a")

    with pytest.raises(ValueError, match="after_seq"):
        ring.push(4, 0, "b")


def test_refuses_ring_when_capacity_zero() -> None:
    with pytest.raises(ValueError, match="at least one"):
        DeltaRing(0)
