import pytest

from agent_hub.core.runner.ready_list import (
    ReadyRow,
    issue_number,
    no_ready_line,
    ready_rows,
    repo_of,
    team_failure_line,
)
from agent_hub.core.testing.builders import an_issue

REPOS = ("demo-api", "demo-web")


def test_orders_by_number_when_ids_listed() -> None:
    issues = [an_issue(id=issue_id) for issue_id in ("DEM-12", "DEM-3", "DEM-7", "DEM-9")]

    rows = ready_rows(issues, repos=REPOS)

    assert [row.id for row in rows] == ["DEM-3", "DEM-7", "DEM-9", "DEM-12"]
    assert [issue_number(issue_id) for issue_id in ("DEM-12", "DEM-3")] == [12, 3]


def test_names_repo_when_one_label_matches() -> None:
    issue = an_issue(id="DEM-12", title="A title", labels=("agent-ready", "demo-api", "bug"))

    rows = ready_rows([issue], repos=REPOS)

    assert rows == [
        ReadyRow(id="DEM-12", repo="demo-api", title="A title", url=issue.url),
    ]
    assert repo_of(("demo-web", "agent-ready", "demo-web"), repos=REPOS) == "demo-web"


@pytest.mark.parametrize(
    "labels",
    [(), ("agent-ready",), ("agent-ready", "demo-api", "demo-web"), ("api", "web")],
    ids=["no-label", "no-repo-label", "both-repos", "near-names"],
)
def test_prints_question_mark_when_none_or_several_match(labels: tuple[str, ...]) -> None:
    assert repo_of(labels, repos=REPOS) == "?"


def test_names_team_and_label_when_none_ready() -> None:
    assert no_ready_line(teams=("DEM",), label="agent-ready") == (
        "no ready issues (team DEM, label agent-ready)"
    )


def test_names_every_team_when_none_ready() -> None:
    assert no_ready_line(teams=("APP", "OPS"), label="agent-ready") == (
        "no ready issues (teams APP, OPS, label agent-ready)"
    )


def test_prefixes_team_when_several_teams_listed() -> None:
    line = team_failure_line(team="OPS", reason="list_ready: outage", team_count=2)

    assert line == "team OPS: list_ready: outage"


def test_keeps_reason_when_one_team_listed() -> None:
    line = team_failure_line(team="DEM", reason="list_ready: outage", team_count=1)

    assert line == "list_ready: outage"
