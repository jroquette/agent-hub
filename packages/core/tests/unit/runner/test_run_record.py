import pytest

from agent_hub.core.runner.run_record import Stage, picked_data, reported_data, run_record

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


def reported(**data_fields: object) -> dict[str, object]:
    return dict(
        run_record(
            ts=TS,
            run_id="ab12cd34",
            issue_id="DEM-1",
            repo="demo-api",
            state=Stage.REPORTED,
            event="reported",
            live=True,
            data=reported_data(**data_fields),  # type: ignore[arg-type]
        )
    )


def test_holds_retro_fields_when_reported_record_built() -> None:
    # scripts/retro_metrics.py (hub) reads event, failed_stage, issue and total_cost_usd.
    url = "https://github.com/acme/demo-api/pull/99"

    success = reported(ok=True, failed_stage=None, total_cost_usd=1.2345, pr=url)
    failure = reported(ok=False, failed_stage=Stage.VERIFYING, total_cost_usd=0.5, pr="")

    assert success == {
        "ts": TS,
        "run": "ab12cd34",
        "issue": "DEM-1",
        "repo": "demo-api",
        "state": "REPORTED",
        "event": "reported",
        "live": True,
        "ok": True,
        "total_cost_usd": 1.2345,
        "pr": url,
        "failed_stage": None,
    }
    assert list(success)[-4:] == ["ok", "total_cost_usd", "pr", "failed_stage"]
    assert failure["failed_stage"] == "VERIFYING"
    assert type(failure["failed_stage"]) is str
