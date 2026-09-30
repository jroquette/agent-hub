"""Fixtures for the cli integration tests: a fake git on ``PATH`` and the ``demo`` inputs.

Also the ``hub.lock`` golden harness (``lock_golden``), a from-scratch child environment
(``child_env``), the process umask (``set_umask``), and for ``hub sync`` a ``DEMO`` hub built
once per session (``demo_hub_template``) and copied per test (``demo_hub``), an in-process sync
in a folder (``run_sync``) and the writer calls a test makes (``adapter_calls``).
"""

import difflib
import json
import os
import shlex
import shutil
import stat
import sys
from collections.abc import Callable, Iterator, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
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
# Set by the caller (a git hook, a worktree script), they would make init skip the remote.
GIT_LOCATION_VARIABLES = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR")


@pytest.fixture(autouse=True)
def no_git_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as if git found the repo from the folder: the caller's variables unset."""
    for variable in GIT_LOCATION_VARIABLES:
        monkeypatch.delenv(variable, raising=False)


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


def demo_document_value() -> dict[str, Any]:
    """The spec's ``DEMO``: the example config with no modules (D3), pinned to the running CLI."""
    document = a_hub_document()
    del document["modules"]
    document["platform"]["version"] = version("agent-hub-cli")
    return document


@pytest.fixture
def demo_document() -> dict[str, Any]:
    """A fresh ``DEMO`` document, which the test may change."""
    return demo_document_value()


@pytest.fixture(scope="session")
def demo_hub_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The tree ``hub init --config DEMO`` writes, built once per session: never change it.

    ``init --config`` reads neither git nor ``HOME``, so the function-scoped fixtures that
    isolate them are not needed here.
    """
    base = tmp_path_factory.mktemp("demo-hub-template")
    config = base / "hub.json"
    config.write_bytes(dump_json(demo_document_value()))
    root = base / "hub"
    result = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
    assert result.exit_code == 0, result.stderr
    # A copy must not carry a git folder that points back at the template.
    assert not os.path.lexists(root / ".git")
    return root


@pytest.fixture
def demo_hub(tmp_path: Path, demo_hub_template: Path) -> Path:
    """A copy of the ``DEMO`` hub for this test: links kept as links, modes kept."""
    root = tmp_path / "hub"
    shutil.copytree(demo_hub_template, root, symlinks=True)
    return root


type SyncRunner = Callable[..., Result]


@pytest.fixture
def run_sync(monkeypatch: pytest.MonkeyPatch) -> SyncRunner:
    """Run ``hub sync <args>`` in process with ``root`` as the current folder."""

    def run(root: Path, *args: str) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, ["sync", *args])

    return run


# The calls through which the writer changes a tree, each recorded by the name it changes.
ADAPTER_CALLS = ("replace", "unlink", "mkdir")


@pytest.fixture
def adapter_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, str]]:
    """``(call, name)`` of every ``os.replace``, ``os.unlink`` and ``os.mkdir``, in order.

    ``name`` is the destination as given (relative to its ``dir_fd``); each call goes through.
    """
    calls: list[tuple[str, str]] = []

    def wrap(call: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(*args: Any, **kwargs: Any) -> Any:
            destination = args[1] if call == "replace" else args[0]
            calls.append((call, os.fsdecode(destination)))
            return real(*args, **kwargs)

        return recorded

    for call in ADAPTER_CALLS:
        monkeypatch.setattr(os, call, wrap(call, getattr(os, call)))
    return calls


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


@pytest.fixture
def set_umask() -> Iterator[Callable[[int], None]]:
    """Set the process umask for the test; the original one is restored afterwards."""
    original = os.umask(0o022)
    os.umask(original)
    try:
        yield lambda mask: os.umask(mask) and None
    finally:
        os.umask(original)


# The golden harness of the init lock (AC-12.28). Its twin is ``update_mode`` in
# packages/generator/tests/integration/conftest.py, which a conftest cannot import: same variable,
# same refusal under CI, same message.
UPDATE_VARIABLE = "GOLDEN_UPDATE"
DEMO_LOCK_GOLDEN = Path(__file__).parent / "golden" / "init" / "demo.hub.lock"
VERSION_MARK = "<VERSION>"
UPDATE_HINT = (
    f"Update: {UPDATE_VARIABLE}=1 uv run --locked --all-packages pytest -m integration "
    "packages/cli/tests/integration/test_synthetic_demo.py -q, "
    "then review and commit the golden diff"
)
# A child never rewrites goldens, keeps roots or runs as CI because this run does.
CHILD_DROPPED = frozenset({UPDATE_VARIABLE, "GOLDEN_KEEP", "CI"})


def golden_update_mode() -> bool:
    """Whether ``GOLDEN_UPDATE=1`` asks to rewrite goldens; fails the test when ``CI`` is set."""
    if os.environ.get(UPDATE_VARIABLE) != "1":
        return False
    if os.environ.get("CI"):
        pytest.fail(
            f"{UPDATE_VARIABLE}=1 is refused when CI is set: goldens are regenerated locally, "
            "reviewed and committed"
        )
    return True


def normalized_lock(content: bytes) -> bytes:
    """``content`` with its one ``platform_version`` value replaced by ``<VERSION>``."""
    field = f'"platform_version": {json.dumps(version("agent-hub-cli"))}'.encode()
    if content.count(field) != 1:
        pytest.fail(f"the lock holds {content.count(field)} of {field!r}, not one")
    return content.replace(field, f'"platform_version": "{VERSION_MARK}"'.encode())


def compare_lock_golden(content: bytes, *, golden: Path = DEMO_LOCK_GOLDEN) -> None:
    """Fail unless the normalized ``content`` equals ``golden``; update mode rewrites it instead.

    Update mode is read (and refused under ``CI``) before anything is compared.
    """
    update = golden_update_mode()
    new = normalized_lock(content)
    old = golden.read_bytes() if golden.is_file() else None
    if old == new:
        return
    if update:
        golden.parent.mkdir(parents=True, exist_ok=True)
        golden.write_bytes(new)
        sys.stderr.write(f"wrote {golden}\n")
        return
    if old is None:
        pytest.fail(f"missing golden {golden}\n{UPDATE_HINT}")
    diff = difflib.unified_diff(
        old.decode(errors="replace").splitlines(),
        new.decode(errors="replace").splitlines(),
        "golden",
        "actual",
        lineterm="",
    )
    pytest.fail("\n".join([f"{golden} differs from the lock:", *diff, UPDATE_HINT]))


@pytest.fixture
def lock_golden() -> Callable[..., None]:
    """Compare a ``hub.lock`` with its golden (``demo.hub.lock`` by default) or rewrite it."""
    return compare_lock_golden


@pytest.fixture
def child_env() -> Callable[[Mapping[str, str]], dict[str, str]]:
    """Build a child's environment from ``values`` alone, the harness mode variables dropped."""

    def build(values: Mapping[str, str]) -> dict[str, str]:
        return {name: value for name, value in values.items() if name not in CHILD_DROPPED}

    return build
