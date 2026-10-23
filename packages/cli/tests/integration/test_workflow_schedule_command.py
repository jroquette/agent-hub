"""``hub workflow schedule list`` (AGH-481): each schedule of ``hub.json`` and its next start."""

from importlib.metadata import version
from pathlib import Path
from typing import Any

from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import an_environments_document


def a_hub(tmp_path: Path, **starts: list[dict[str, Any]]) -> Path:
    document = an_environments_document()
    document.update(starts)
    # The hub pins the running release, as a hub this command serves does.
    document["platform"]["version"] = version("agent-hub-cli")
    (tmp_path / "hub.json").write_bytes(dump_json(document))
    return tmp_path


def listed(hub: Path, *args: str) -> Result:
    return CliRunner().invoke(
        app, ["workflow", "schedule", "list", *args], env={"AGENT_HUB_ROOT": str(hub)}
    )


def test_prints_next_start_of_each_schedule_when_listed_after_a_time(tmp_path: Path) -> None:
    hub = a_hub(
        tmp_path,
        schedules=[
            {"workflow": "retro", "cron": "0 9 * * 1"},
            {"workflow": "sweep", "cron": "30 2 1 * *", "environment": "staging"},
        ],
    )

    # 2026-10-22T12:00+02:00 is 10:00Z, a Thursday.
    result = listed(hub, "--after", "2026-10-22T12:00:00+02:00")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "retro  0 9 * * 1  next 2026-10-26T09:00Z",
        "sweep  30 2 1 * *  next 2026-11-01T02:30Z  env staging",
    ]


def test_says_no_schedules_when_hub_json_declares_none(tmp_path: Path) -> None:
    result = listed(a_hub(tmp_path))

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["no schedules in hub.json"]


def test_exits_two_when_schedule_list_after_is_not_a_time(tmp_path: Path) -> None:
    hub = a_hub(tmp_path, schedules=[{"workflow": "retro", "cron": "0 9 * * 1"}])

    for given in ("next monday", "2026-10-22T12:00:00"):
        result = listed(hub, "--after", given)

        assert result.exit_code == 2, result.output
        assert "--after" in unstyle(result.stderr)
        assert result.stdout == ""
