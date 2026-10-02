"""The demo render for the generator unit tests.

TESTING.md: builders only, no real hub.json; a test that writes does so under ``tmp_path``.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.generator.render_hub import render_hub


@pytest.fixture
def demo_render(demo_config: HubConfig) -> dict[str, RenderedFile]:
    """The demo render, by output path."""
    return {file.path: file for file in render_hub(demo_config).files}
