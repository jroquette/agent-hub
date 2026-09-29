"""Synthetic hub configs and the tree writer shared by every generator test level.

TESTING.md: builders only, no real hub.json; a test that writes does so under ``tmp_path``.
"""

import os
import stat
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document

_EXECUTABLE_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

type TreeWriter = Callable[..., Path]


@pytest.fixture
def demo_config() -> HubConfig:
    """The builder's demo project: one repo, modules ``cloud`` and ``bench``."""
    return HubConfig.model_validate(a_hub_document())


@pytest.fixture
def variant_config() -> HubConfig:
    """A second project whose run-time values are sentinels no rendered file may contain.

    No module, two repos, a non-``main`` default branch; ``check_fast``, ``check``,
    ``platform.version`` and ``author_name`` hold values that are never rendered (AC-3.9).
    """
    document = a_hub_document()
    document["platform"]["version"] = "9.8.7"
    document["project"]["default_branch"] = "trunk"
    document["project"]["author_name"] = "Sentinel Author Q7"
    document["repos"] = [
        {
            "dir": repo_dir,
            "github": f"acme/{repo_dir}",
            "check_fast": "make sentinel-fast-q7",
            "check": "make sentinel-full-q7",
        }
        for repo_dir in ("demo-api", "demo-web")
    ]
    document["modules"] = {}
    return HubConfig.model_validate(document)


@pytest.fixture
def rendered_tree(tmp_path: Path) -> TreeWriter:
    """Write a rendered hub under ``tmp_path / "hub"``, or the keyword ``root``; return that folder.

    Files keep their executable bit; each link becomes a symlink to its relative target. Files go
    first: ``RenderedHub`` puts no path under a link, so nothing is ever written through one.
    """

    def write(rendered: RenderedHub, *, root: Path | None = None) -> Path:
        root = tmp_path / "hub" if root is None else root
        for file in rendered.files:
            target = root / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.content)
            if file.executable:
                target.chmod(target.stat().st_mode | _EXECUTABLE_BITS)
        for link in rendered.links:
            path = root / link.path
            path.parent.mkdir(parents=True, exist_ok=True)
            os.symlink(link.target, path)
        root.mkdir(exist_ok=True)
        return root

    return write
