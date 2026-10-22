from agent_hub.core.environment_discovery.prompt import TITLE, discovery_prompt


# AC-418.3
def test_names_repos_environments_and_rules_when_built() -> None:
    prompt = discovery_prompt(
        workspace="/work",
        repos=("api", "web"),
        environments=("local", "staging"),
        suggest_environments=False,
    )

    assert prompt.splitlines()[0] == TITLE
    assert "- api: /work/api\n- web: /work/web" in prompt
    assert "Look for these environments only: local, staging." in prompt
    assert "Do not propose any other environment." in prompt
    assert "Never open .env files" in prompt
    assert prompt.count("```json\n{") == 1


# AC-418.3
def test_allows_new_environments_when_suggestions_on() -> None:
    prompt = discovery_prompt(
        workspace="/work", repos=("api",), environments=(), suggest_environments=True
    )

    assert "No environment was picked. You may also propose other environments" in prompt
