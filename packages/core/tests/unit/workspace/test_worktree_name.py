import pytest

from agent_hub.core.workspace.worktree_name import (
    worktree_branch,
    worktree_name_example,
    worktree_name_problem,
)


@pytest.mark.parametrize("name", ["dem-7", "dem-7-collector", "dem-12-a.b_c"])
def test_accepts_name_when_issue_shaped(name: str) -> None:
    assert worktree_name_problem(name, teams=("DEM",)) is None


@pytest.mark.parametrize("name", ["DEM-7", "dem7", "xyz-7", "dem-7/x", "dem-7-", ""])
def test_names_expected_shape_when_name_malformed(name: str) -> None:
    problem = worktree_name_problem(name, teams=("DEM",))

    assert problem == "name must be the issue, dem-<n>[-<desc>] (e.g. dem-7-collector)"


def test_lowercases_team_when_checking() -> None:
    assert worktree_name_problem("dem-7", teams=("Dem",)) is None
    assert worktree_name_problem("dem-7", teams=("dem",)) is None


def test_refuses_trailing_newline_when_name_ends_with_one() -> None:
    assert worktree_name_problem("dem-7\n", teams=("DEM",)) is not None


def test_joins_prefix_when_branch_built() -> None:
    assert worktree_branch("dem-7-x", prefix="jdoe/") == "jdoe/dem-7-x"
    assert worktree_branch("dem-7-x", prefix="") == "dem-7-x"


def test_lowercases_team_when_example_built() -> None:
    assert worktree_name_example("DEM") == "dem-7-collector"


@pytest.mark.parametrize("name", ["app-1", "ops-12-x"])
def test_accepts_name_of_any_team_when_several_listed(name: str) -> None:
    assert worktree_name_problem(name, teams=("APP", "OPS")) is None


def test_lists_teams_when_name_matches_none() -> None:
    problem = worktree_name_problem("xyz-1-x", teams=("APP", "OPS"))

    assert problem == (
        "name must be the issue, <team>-<n>[-<desc>] in lowercase (e.g. app-7-collector);"
        " use one of: APP, OPS"
    )


def test_accepts_names_when_keys_share_prefix() -> None:
    assert worktree_name_problem("ap-1-x", teams=("AP", "APP")) is None
    assert worktree_name_problem("app-1-x", teams=("AP", "APP")) is None
    assert worktree_name_problem("apx-1-x", teams=("AP", "APP")) is not None


@pytest.mark.parametrize("teams", [("App",), ("app",)])
def test_ignores_key_case_when_matching(teams: tuple[str, ...]) -> None:
    assert worktree_name_problem("app-1", teams=teams) is None
    assert worktree_name_problem("APP-1", teams=teams) is not None
