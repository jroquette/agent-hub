import pytest

from agent_hub.core.workspace.worktree_name import worktree_branch, worktree_name_problem


@pytest.mark.parametrize("name", ["dem-7", "dem-7-collector", "dem-12-a.b_c"])
def test_accepts_name_when_issue_shaped(name: str) -> None:
    assert worktree_name_problem(name, team="DEM") is None


@pytest.mark.parametrize("name", ["DEM-7", "dem7", "xyz-7", "dem-7/x", "dem-7-", ""])
def test_names_expected_shape_when_name_malformed(name: str) -> None:
    problem = worktree_name_problem(name, team="DEM")

    assert problem == "name must be the issue, dem-<n>[-<desc>] (e.g. dem-7-collector)"


def test_lowercases_team_when_checking() -> None:
    assert worktree_name_problem("dem-7", team="Dem") is None
    assert worktree_name_problem("dem-7", team="dem") is None


def test_refuses_trailing_newline_when_name_ends_with_one() -> None:
    assert worktree_name_problem("dem-7\n", team="DEM") is not None


def test_joins_prefix_when_branch_built() -> None:
    assert worktree_branch("dem-7-x", prefix="jdoe/") == "jdoe/dem-7-x"
    assert worktree_branch("dem-7-x", prefix="") == "dem-7-x"
