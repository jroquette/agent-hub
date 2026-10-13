"""The child's environment (L5, AC-165.4, E3): ``hub web``'s own, plus ``AGENT_HUB_WEB_URL``."""

from agent_hub.claude_sessions.environment import WEB_URL_VARIABLE, child_environment

SENTINELS = {
    "ANTHROPIC_API_KEY": "sentinel-api-key-0000",
    "CLAUDE_CODE_OAUTH_TOKEN": "sentinel-oauth-token-0000",
    "PATH": "/usr/bin:/bin",
}
WEB_URL = "http://127.0.0.1:7420"
TOKEN = "synthetic-session-token-" + "0" * 20  # noqa: S105 - synthetic, never a real token


def test_passes_environment_unchanged_when_sentinels_present() -> None:
    child = child_environment(SENTINELS, {WEB_URL_VARIABLE: WEB_URL})

    assert child == {**SENTINELS, WEB_URL_VARIABLE: WEB_URL}


def test_omits_token_and_cookie_name_when_child_built() -> None:
    extra = {WEB_URL_VARIABLE: WEB_URL, "agent_hub_7420": TOKEN, "AGENT_HUB_TOKEN": TOKEN}

    child = child_environment(SENTINELS, extra)

    assert TOKEN not in child.values()
    assert not any(key.lower().startswith("agent_hub_7420") for key in child)
    assert set(child) == {*SENTINELS, WEB_URL_VARIABLE}


def test_keeps_parent_untouched_when_child_built() -> None:
    parent = dict(SENTINELS)

    child_environment(parent, {WEB_URL_VARIABLE: WEB_URL})

    assert parent == SENTINELS
