"""Fixtures for the cli integration tests: a fake git on ``PATH`` and the ``demo`` inputs."""

import os
import shlex
import stat
from collections.abc import Callable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest

from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document

GIT_TOPLEVEL_ARGS = "rev-parse --show-toplevel"
# The spec's DEMO_FLAGS: every value given, so git is never called.
DEMO_FLAGS = (
    "demo",
    "--repos",
    "acme/demo-api",
    "--tracker",
    "linear:DEM",
    "--branch-prefix",
    "jdoe/",
    "--author-name",
    "Jane Doe",
    "--author-email",
    "jane@example.com",
    "--hub-repo",
    "acme/demo-hub",
)
# Exit code of git when a folder is not in a work tree.
NOT_A_REPO = 128


class FakeGit(NamedTuple):
    """A ``/bin/sh`` script named ``git`` in ``bin_dir`` that logs each call to ``log_path``."""

    bin_dir: Path
    log_path: Path

    def calls(self) -> list[tuple[str, str]]:
        """``(physical working directory, arguments)`` of each call, in order."""
        if not self.log_path.exists():
            return []
        lines = self.log_path.read_text(encoding="utf-8").splitlines()
        return [(cwd, arguments) for cwd, arguments in (line.split("\t") for line in lines)]


type FakeGitFactory = Callable[..., FakeGit]


@pytest.fixture
def fake_git(tmp_path: Path) -> FakeGitFactory:
    """Build a fake git answering ``answers`` (its arguments joined by spaces → one output line).

    ``toplevel`` answers ``rev-parse --show-toplevel``; without it that call exits 128 as outside
    a work tree. Any other call exits 1 with no output, as ``git config --get`` of an unset key.
    ``hangs`` makes every call spin (in a child shell that also holds stdout) until killed.
    The script runs only shell builtins, so it works with ``PATH`` set to its folder alone.
    """

    def build(
        answers: Mapping[str, str], *, toplevel: Path | None = None, hangs: bool = False
    ) -> FakeGit:
        bin_dir = tmp_path / "fake-git-bin"
        bin_dir.mkdir()
        log_path = tmp_path / "fake-git.log"
        cases = dict(answers)
        if toplevel is not None:
            cases[GIT_TOPLEVEL_ARGS] = str(toplevel)
        branches = "".join(
            f"  {shlex.quote(arguments)}) printf '%s\\n' {shlex.quote(output)} ;;\n"
            for arguments, output in cases.items()
        )
        no_repo = (
            ""
            if toplevel is not None
            else f"  {shlex.quote(GIT_TOPLEVEL_ARGS)}) exit {NOT_A_REPO} ;;\n"
        )
        spin = "( while :; do :; done ) &\nwait\n" if hangs else ""
        script = bin_dir / "git"
        script.write_text(
            "#!/bin/sh\n"
            f'printf \'%s\\t%s\\n\' "$(pwd -P)" "$*" >> {shlex.quote(str(log_path))}\n'
            f"{spin}"
            f'case "$*" in\n{branches}{no_repo}  *) exit 1 ;;\nesac\n',
            encoding="utf-8",
        )
        script.chmod(0o755)
        return FakeGit(bin_dir=bin_dir, log_path=log_path)

    return build


@pytest.fixture
def no_git_path(tmp_path: Path) -> Path:
    """An empty folder to use as the whole ``PATH``, so no ``git`` is found."""
    folder = tmp_path / "no-git-bin"
    folder.mkdir()
    return folder


@pytest.fixture
def demo_document() -> dict[str, Any]:
    """The spec's ``DEMO``: the example config with no modules (D3), pinned to the running CLI."""
    document = a_hub_document()
    del document["modules"]
    document["platform"]["version"] = version("agent-hub-cli")
    return document


@pytest.fixture
def demo_config_file(tmp_path: Path, demo_document: dict[str, Any]) -> Path:
    """``DEMO`` written in the one JSON form, outside any target folder."""
    folder = tmp_path / "config"
    folder.mkdir()
    path = folder / "hub.json"
    path.write_bytes(dump_json(demo_document))
    return path


@pytest.fixture
def demo_flags() -> list[str]:
    """The ``init`` arguments of the spec's ``DEMO_FLAGS``."""
    return list(DEMO_FLAGS)


# One entry of a digest: the type, the permission bits, and the bytes or the link target.
type DigestEntry = tuple[str, int, bytes | str | None]
type TreeDigest = Callable[[Path], dict[str, DigestEntry]]


def _digest_entry(path: Path) -> DigestEntry:
    status = path.lstat()
    mode = stat.S_IMODE(status.st_mode)
    if stat.S_ISLNK(status.st_mode):
        return ("link", mode, os.readlink(path))
    if stat.S_ISREG(status.st_mode):
        return ("file", mode, path.read_bytes())
    if stat.S_ISDIR(status.st_mode):
        return ("folder", mode, None)
    return ("other", mode, None)


@pytest.fixture
def tree_digest() -> TreeDigest:
    """Digest a path: every entry under it (itself as ``.``), never following a link.

    Each entry is its type, permission bits, and a file's bytes or a link's target, so two
    trees with equal digests hold the same paths, bytes, modes and links.
    """

    def digest(root: Path) -> dict[str, DigestEntry]:
        found = {".": _digest_entry(root)}
        if found["."][0] != "folder":
            return found
        for folder, folders, files in os.walk(root):
            for name in [*folders, *files]:
                path = Path(folder) / name
                found[path.relative_to(root).as_posix()] = _digest_entry(path)
        return found

    return digest
