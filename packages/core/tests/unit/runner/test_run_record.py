import pytest

from agent_hub.core.runner.run_record import Stage, picked_data, run_record

TS = "2026-10-02T09:30:00+00:00"


def test_names_stages_in_order_when_listed() -> None:
    assert [stage.value for stage in Stage] == [
        "PICKED",
        "WORKTREE",
        "IMPLEMENTING",
        "VERIFYING",
        "PR_OPEN",
        "REPORTED",
        "FAILED",
    ]


def test_keeps_field_order_when_record_built() -> None:
    record = run_record(
        ts=TS,
        run_id="ab12cd34",
        issue_id="DEM-1",
        repo="demo-api",
        state=Stage.VERIFYING,
        event="gate_ok",
        live=True,
        data={"gate": "make check"},
    )

    assert list(record.items()) == [
        ("ts", TS),
        ("run", "ab12cd34"),
        ("issue", "DEM-1"),
        ("repo", "demo-api"),
        ("state", "VERIFYING"),
        ("event", "gate_ok"),
        ("live", True),
        ("gate", "make check"),
    ]
    assert type(record["state"]) is str


def test_adds_transport_when_picked() -> None:
    data = picked_data(budget=3.0, max_turns=40, model="sonnet", transport="mcp")

    record = run_record(
        ts=TS,
        run_id="ab12cd34",
        issue_id="DEM-1",
        repo="demo-api",
        state=Stage.PICKED,
        event="picked",
        live=False,
        data=data,
    )

    assert list(record.items())[-4:] == [
        ("budget", 3.0),
        ("max_turns", 40),
        ("model", "sonnet"),
        ("transport", "mcp"),
    ]


def test_refuses_data_when_it_names_a_record_field() -> None:
    with pytest.raises(ValueError, match="'state'"):
        run_record(
            ts=TS,
            run_id="ab12cd34",
            issue_id="DEM-1",
            repo="demo-api",
            state=Stage.FAILED,
            event="failed",
            live=True,
            data={"state": "PICKED"},
        )
