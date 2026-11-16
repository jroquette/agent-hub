"""The child's environment (L5, AC-165.4, E3): ``hub web``'s own, plus ``AGENT_HUB_WEB_URL``."""

from agent_hub.claude_sessions.environment import WEB_URL_VARIABLE, child_environment
from agent_hub.core.scenarios.credentials import CredentialNames

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


def test_drops_declared_names_when_credential_injection_hidden() -> None:
    # Built at run time from parts: a synthetic value, never a literal secret in the repo.
    secret = "x-sec" + "ret-y"
    environ = {
        **SENTINELS,
        "DEMO_DB_URL": secret,
        "AWS_PROFILE": "demo-staging",
        "DEMO_OTHER": "kept",
    }
    hidden = CredentialNames(
        env=frozenset({"DEMO_DB_URL"}), aws_profiles=frozenset({"demo-staging"})
    )

    child = child_environment(environ, {WEB_URL_VARIABLE: WEB_URL}, hidden=hidden)
    own_profile = child_environment({"AWS_PROFILE": "personal"}, {}, hidden=hidden)

    assert child == {**SENTINELS, "DEMO_OTHER": "kept", WEB_URL_VARIABLE: WEB_URL}
    assert secret not in child.values()
    assert own_profile == {"AWS_PROFILE": "personal"}
    assert environ["DEMO_DB_URL"] == secret
