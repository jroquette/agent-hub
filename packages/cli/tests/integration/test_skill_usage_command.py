"""``hub skill-usage``: the hub's skills and agents with their runs, never used first (AGH-482).

Every run is in process, in a synthetic hub checkout (``knowledge_hub``: project ``demo``); the
events go in through ``hub collect`` to the default database under the test's own
``XDG_DATA_HOME`` (the cli conftest).
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.events.event import Event
from agent_hub.core.testing.builders import an_event, events_to_jsonl

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run and hub factory (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type KnowledgeHubFactory = Callable[..., Path]

TABLE_HEAD = (
    "| Project | Kind | Name | 7 d | 30 d | 90 d | Last used |\n"
    "| --- | --- | --- | --- | --- | --- | --- |\n"
)


def _skill(name: str) -> bytes:
    return f"---\nname: {name}\ndescription: The {name} flow.\n---\nGo.\n".encode()


def _hub(knowledge_hub: KnowledgeHubFactory, *names: str) -> Path:
    return knowledge_hub({f".claude/skills/{name}/SKILL.md": _skill(name) for name in names})


def _prompt(command: str, *, session: str, days_ago: float) -> Event:
    return an_event(
        session=session,
        type="message",
        timestamp=datetime.now(UTC) - timedelta(days=days_ago),
        payload={"role": "user", "chars": 8, "slash_command": command},
    )


def _collect(events: list[Event]) -> None:
    result = CliRunner().invoke(app, ["collect"], input=events_to_jsonl(events))
    assert result.exit_code == 0, result.output


def _day(days_ago: float) -> str:
    return (datetime.now(UTC) - timedelta(days=days_ago)).date().isoformat()


def test_prints_unused_refactor_before_feature_when_usage_listed(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = _hub(knowledge_hub, "feature", "refactor")
    _collect(
        [
            _prompt("/feature", session="s-1", days_ago=0.1),
            _prompt("/feature", session="s-2", days_ago=0.1),
        ]
    )

    result = run_command(hub, "skill-usage")

    assert result.exit_code == 0, result.output
    assert result.stdout == (
        "Skills and agents: runs in the last 30 days, never used first.\n\n"
        + TABLE_HEAD
        + "| demo | skill | /refactor | 0 | 0 | 0 | never |\n"
        + f"| demo | skill | /feature | 2 | 2 | 2 | {_day(0.1)} |\n"
    )
    assert result.stderr == ""


def test_orders_usage_by_seven_days_when_days_option_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = _hub(knowledge_hub, "feature", "refactor", "review")
    _collect(
        [
            _prompt("/feature", session="s-1", days_ago=1),
            *(_prompt("/refactor", session=f"s-r{n}", days_ago=10) for n in range(3)),
        ]
    )

    def names(*args: str) -> list[str]:
        result = run_command(hub, "skill-usage", *args)
        assert result.exit_code == 0, result.output
        return [line.split(" | ")[2] for line in result.stdout.splitlines() if "| demo |" in line]

    assert names() == ["/review", "/refactor", "/feature"]
    assert names("--days", "7") == ["/refactor", "/review", "/feature"]


def test_exits_two_when_usage_days_not_a_window(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner
) -> None:
    hub = _hub(knowledge_hub, "feature")

    result = run_command(hub, "skill-usage", "--days", "14")

    assert result.exit_code == 2
    assert result.stdout == ""


def test_exits_one_when_usage_database_unreadable(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = _hub(knowledge_hub, "feature")
    blocker = tmp_path / "a-file"
    blocker.write_bytes(b"not a folder\n")

    result = run_command(hub, "skill-usage", "--db", str(blocker / "events.db"))

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.startswith("hub skill-usage: cannot create the directory ")
    assert result.stderr.count("\n") == 1
