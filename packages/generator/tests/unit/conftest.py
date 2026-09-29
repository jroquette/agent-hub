"""Synthetic hub configs and render helpers for the generator tests.

TESTING.md: builders only, no real hub.json; a test that writes does so under ``tmp_path``.
"""

import shutil
import stat
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

# The fake uv tools append one line per call: the tool's name, then its arguments.
FAKE_UV_TOOLS = ("uv", "uvx")
FAKE_UV_LOG = "uvx.log"
# Exit codes of the fake uv tools, read from the environment at each call (default 0): the
# resolve step (a call with ``--version``) exits with the first, every other call with the second.
FAKE_UVX_RESOLVE_RC = "FAKE_UVX_RESOLVE_RC"
FAKE_UVX_RC = "FAKE_UVX_RC"
_EXECUTABLE_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

type TreeWriter = Callable[[Iterable[RenderedFile]], Path]


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
def demo_render(demo_config: HubConfig) -> dict[str, RenderedFile]:
    """The demo render, by output path."""
    return {file.path: file for file in render_hub(demo_config)}


@pytest.fixture
def rendered_tree(tmp_path: Path) -> TreeWriter:
    """Write rendered files under ``tmp_path / "hub"`` (executable bit kept); return that folder."""

    def write(rendered: Iterable[RenderedFile]) -> Path:
        root = tmp_path / "hub"
        for file in rendered:
            target = root / file.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(file.content)
            if file.executable:
                target.chmod(target.stat().st_mode | _EXECUTABLE_BITS)
        root.mkdir(exist_ok=True)
        return root

    return write


@pytest.fixture
def fake_uv_bin(tmp_path: Path) -> Path:
    """A folder of executable ``uv`` and ``uvx`` that log their argv to ``uvx.log``.

    Put it first on ``PATH``: the shims then "run" the pinned release without network. A call
    with ``--version`` exits ``$FAKE_UVX_RESOLVE_RC``, any other ``$FAKE_UVX_RC`` (both default 0).
    """
    shell = shutil.which("sh")
    assert shell is not None, "the fake uv tools need sh on PATH"
    bin_dir = tmp_path / "fake-uv-bin"
    bin_dir.mkdir()
    log = bin_dir / FAKE_UV_LOG
    for tool in FAKE_UV_TOOLS:
        script = bin_dir / tool
        script.write_text(
            f"#!{shell}\n"
            f'printf \'%s\\n\' "{tool} $*" >> "{log}"\n'
            'case " $* " in *" --version "*) '
            f'exit "${{{FAKE_UVX_RESOLVE_RC}:-0}}";; esac\n'
            f'exit "${{{FAKE_UVX_RC}:-0}}"\n',
            encoding="utf-8",
        )
        script.chmod(script.stat().st_mode | _EXECUTABLE_BITS)
    return bin_dir
