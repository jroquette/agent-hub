from agent_hub.core.errors import AgentHubError
from agent_hub.hub_git.errors import HubGitError


def test_derives_from_root_error_when_hub_git_error_raised() -> None:
    error = HubGitError("git is not installed")

    assert isinstance(error, AgentHubError)
    assert str(error) == "git is not installed"
