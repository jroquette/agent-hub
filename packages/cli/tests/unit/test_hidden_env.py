import pytest

import agent_hub.cli.hidden_env as hidden_env
import agent_hub.cli.run_children as run_children
import agent_hub.cli.tracker_client as tracker_client


@pytest.mark.parametrize("name", ["KEY_VARIABLE", "CHILD_HIDDEN", "SESSION_HIDDEN", "without"])
def test_shares_one_definition_when_run_children_reexports_name(name: str) -> None:
    assert getattr(run_children, name) is getattr(hidden_env, name)


def test_shares_tracker_key_name_when_tracker_client_reads_it() -> None:
    assert tracker_client.KEY_VARIABLE is hidden_env.KEY_VARIABLE


def test_hides_tracker_key_and_github_tokens_when_lists_read() -> None:
    assert hidden_env.KEY_VARIABLE == "LINEAR_API_KEY"
    assert hidden_env.CHILD_HIDDEN == ("LINEAR_API_KEY",)
    assert hidden_env.SESSION_HIDDEN == ("LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")
