"""Root conftest: loads the plugin that turns test folders into level markers."""

import pytest

pytest_plugins = ("scripts.pytest_levels",)

# The contract suites live in core, outside the test trees pytest rewrites by default; rewrite
# their asserts too so a failing contract shows the compared values.
pytest.register_assert_rewrite("agent_hub.core.testing.contracts")
