"""Root conftest: loads the plugin that turns test folders into level markers."""

import pytest

pytest_plugins = ("scripts.pytest_levels",)

# The contract suites live in core, outside the test trees pytest rewrites by default; rewrite
# their asserts too so a failing contract shows the compared values.
pytest.register_assert_rewrite("agent_hub.core.testing.contracts")

# The one git transport a test below e2e may use: local bare repositories. e2e keeps the network
# for its ``uv tool install`` and ``uvx`` runs.
GIT_PROTOCOL_VARIABLE = "GIT_ALLOW_PROTOCOL"
LOCAL_GIT_PROTOCOL = "file"
NETWORK_LEVEL = "e2e"


@pytest.fixture(autouse=True)
def git_stays_local(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """Below e2e, git may only reach ``file`` remotes, so no test reaches github.com.

    ``hub sync`` looks the pinned release's tag up with ``git ls-remote`` (ADR 0054): a test
    whose platform URL is not rewritten to a local bare repository fails the lookup offline
    instead of reading the real tag.
    """
    # The level ``scripts.pytest_levels`` reads from the test's folder. Imported here, once the
    # plugin is registered: a module-level import would come first and keep pytest from
    # rewriting the plugin's asserts.
    from scripts.pytest_levels import level_of  # noqa: PLC0415

    if level_of(str(request.node.path)) != NETWORK_LEVEL:
        monkeypatch.setenv(GIT_PROTOCOL_VARIABLE, LOCAL_GIT_PROTOCOL)


@pytest.fixture
def anyio_backend() -> str:
    """Async tests (``@pytest.mark.anyio``) run on asyncio only: ``hub web``'s event loop."""
    return "asyncio"
