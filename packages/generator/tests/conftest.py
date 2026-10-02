"""Synthetic hub configs, the tree writer and the fake uv tools shared by every test level.

TESTING.md: builders only, no real hub.json; a test that writes does so under ``tmp_path``.
"""

import os
import re
import shutil
import stat
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

_EXECUTABLE_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH

type TreeWriter = Callable[..., Path]
type ShellScripts = Callable[[Iterable[RenderedFile]], list[str]]

# A sh or bash ``#!`` line: the ``hub`` and ``agent`` shims carry one and no ``.sh`` suffix.
_SHELL_SHEBANG = re.compile(rb"^#!\s*/(?:usr/)?bin/(?:env\s+)?(?:ba)?sh\b")

# The fake uv tools append one line per call: the tool's name, then its arguments.
FAKE_UV_TOOLS = ("uv", "uvx")
FAKE_UV_LOG = "uvx.log"
# Exit codes of the fake uv tools, read from the environment at each call (default 0): the
# resolve step (a call with ``--version``) exits with the first, every other call with the second.
FAKE_UVX_RESOLVE_RC = "FAKE_UVX_RESOLVE_RC"
FAKE_UVX_RC = "FAKE_UVX_RC"


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
def all_modules_config() -> HubConfig:
    """The spec's ALL: the demo with a second repo and the four modules selected.

    ``contract-sync`` goes from ``demo-api`` (source) to ``demo-web`` (target).
    """
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    document["modules"] = {
        "bench": {},
        "cloud": {},
        "contract-sync": {"source": "demo-api", "target": "demo-web"},
        "marketplace": {},
    }
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


@pytest.fixture
def shell_scripts() -> ShellScripts:
    """Return the paths of the rendered shell scripts: each ``.sh`` file and each sh/bash ``#!``
    file (the shims), in render order. Make recipes are not scripts: make runs them on /bin/sh.
    """

    def scripts(rendered: Iterable[RenderedFile]) -> list[str]:
        return [
            file.path
            for file in rendered
            if file.path.endswith(".sh") or _SHELL_SHEBANG.match(file.content)
        ]

    return scripts
