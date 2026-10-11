from agent_hub.core.readmodels.fold_memo import FoldMemo


def test_reuses_value_when_high_water_mark_unchanged() -> None:
    memo: FoldMemo[str, int] = FoldMemo()
    calls: list[int] = []

    def compute() -> int:
        calls.append(1)
        return len(calls)

    assert memo.get("demo", hwm=5, compute=compute) == 1
    assert memo.get("demo", hwm=5, compute=compute) == 1
    assert len(calls) == 1


def test_recomputes_value_when_high_water_mark_moves() -> None:
    memo: FoldMemo[str, int] = FoldMemo()
    values = iter([10, 20])

    assert memo.get("demo", hwm=5, compute=lambda: next(values)) == 10
    assert memo.get("demo", hwm=6, compute=lambda: next(values)) == 20


def test_evicts_least_recent_key_when_full() -> None:
    memo: FoldMemo[str, str] = FoldMemo(max_entries=2)
    memo.get("a", hwm=1, compute=lambda: "a1")
    memo.get("b", hwm=1, compute=lambda: "b1")
    memo.get("a", hwm=1, compute=lambda: "unused")
    memo.get("c", hwm=1, compute=lambda: "c1")

    assert memo.get("a", hwm=1, compute=lambda: "recomputed") == "a1"
    assert memo.get("b", hwm=1, compute=lambda: "recomputed") == "recomputed"
