import pytest

from agent_hub.claude_sessions.invocations import SessionNames, cli_prompt

NAMES = SessionNames(
    commands=frozenset({"compact", "fix", "hub-workflow:feature", "a:review", "b:review"}),
    agents=frozenset({"Explore", "hub-workflow:researcher"}),
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("/feature add a menu", "/hub-workflow:feature add a menu"),
        ("/fix the bug", "/fix the bug"),
        ("/review it", "/review it"),
        ("/unknown", "/unknown"),
        ("/hub-workflow:feature", "/hub-workflow:feature"),
        ("/agent-researcher find it", "@agent-hub-workflow:researcher find it"),
        ("/agent-Explore", "@agent-Explore"),
        (
            "first /feature, then /agent-researcher",
            "first /feature, then @agent-hub-workflow:researcher",
        ),
        ("a/agent-researcher stays", "a/agent-researcher stays"),
        ("/agent-unknown x", "@agent-unknown x"),
    ],
)
def test_makes_short_names_exact_when_session_knows_them(text: str, expected: str) -> None:
    assert cli_prompt(text, NAMES) == expected


def test_reads_names_when_server_info_lists_them() -> None:
    info = {
        "commands": [{"name": "fix"}, {"description": "no name"}, "x"],
        "agents": [{"name": "researcher"}],
    }

    assert SessionNames.from_server_info(info) == SessionNames(
        commands=frozenset({"fix", "x"}), agents=frozenset({"researcher"})
    )


def test_knows_no_name_when_server_info_missing_or_malformed() -> None:
    assert SessionNames.from_server_info(None) == SessionNames()
    assert SessionNames.from_server_info({"commands": "fix", "agents": 3}) == SessionNames()
