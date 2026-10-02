"""The TrackerClient contract suite, run against the Linear MCP adapter (AC-27.4).

The adapter's runner is ``FakeClaude`` over the suite's ``tracker_backend`` (both from
``tests/conftest.py``): it checks each call's argv, cwd and environment and answers as an honest
model, so every write the suite observes went through a write call allowed one write tool.
"""

from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.testing.contracts import TrackerClientContract
from agent_hub.core.tracker.tracker_client import TrackerClient
from agent_hub.tracker_linear.mcp import McpTrackerClient


@pytest.fixture
def tracker_client(fake_claude: Any, hub_root: Path) -> TrackerClient:
    environ = {"PATH": "/usr/bin", "LINEAR_API_KEY": "lin" + "_api_" + "x" * 40}
    return McpTrackerClient(environ=environ, cwd=hub_root, runner=fake_claude)


class TestMcpTrackerClient(TrackerClientContract):
    """The TrackerClient contract suite, run against the MCP adapter over FakeClaude."""
