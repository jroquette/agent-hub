"""Small synthetic renders for the ``hub_files`` unit tests.

TESTING.md: builders only, in memory. ``a_rendered_hub`` covers each kind of lock entry once: a
managed file, an executable managed file, a seeded file, a managed link and a seeded link.
"""

from collections.abc import Callable, Sequence

import pytest

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink

type RenderedHubFactory = Callable[..., RenderedHub]


def _file(path: str, content: bytes, *, executable: bool, ownership: Ownership) -> RenderedFile:
    return RenderedFile(
        path=path,
        content=content,
        executable=executable,
        kind=Kind.GENERIC,
        ownership=ownership,
        module=None,
    )


def _link(path: str, target: str, *, ownership: Ownership) -> RenderedLink:
    return RenderedLink(
        path=path, target=target, kind=Kind.GENERIC, ownership=ownership, module=None
    )


DEFAULT_FILES = (
    _file("AGENTS.md", b"# Rules\n", executable=False, ownership=Ownership.MANAGED),
    _file("README.md", b"# Demo\n", executable=False, ownership=Ownership.SEEDED),
    _file("plugin/agents/x.md", b"agent x\n", executable=False, ownership=Ownership.MANAGED),
    _file("scripts/run.sh", b"#!/bin/sh\n", executable=True, ownership=Ownership.MANAGED),
)
DEFAULT_LINKS = (
    _link(".claude/agents/x.md", "../../plugin/agents/x.md", ownership=Ownership.MANAGED),
    _link(".claude/skills/y", "../../plugin/skills/y", ownership=Ownership.SEEDED),
)


@pytest.fixture
def a_rendered_hub() -> RenderedHubFactory:
    """Build a ``RenderedHub``: the default files and links, or the ones given (each sorted)."""

    def build(
        *,
        files: Sequence[RenderedFile] = DEFAULT_FILES,
        links: Sequence[RenderedLink] = DEFAULT_LINKS,
    ) -> RenderedHub:
        return RenderedHub(
            files=tuple(sorted(files, key=lambda file: file.path)),
            links=tuple(sorted(links, key=lambda link: link.path)),
        )

    return build
