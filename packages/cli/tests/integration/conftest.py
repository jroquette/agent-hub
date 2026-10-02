"""Fixtures for the cli integration tests: a fake git on ``PATH`` and the ``demo`` inputs.

Also the ``hub.lock`` golden harness (``lock_golden``), a from-scratch child environment
(``child_env``), the process umask (``set_umask``), and for ``hub sync`` a ``DEMO`` hub built
once per session (``demo_hub_template``) and copied per test (``demo_hub``), the same with a
second repo (``demo_two_repo_hub_template``, ``demo_two_repo_hub``) and a synthetic git checkout
next to it (``demo_checkout``), an in-process sync
in a folder (``run_sync``) and the writer calls a test makes (``adapter_calls``); for ``hub doctor``
an in-process run in a folder (``run_doctor``), the paths a run reads (``path_reads``) and their
filters (``reads_in``, ``ancestors``, ``under``).
"""

import builtins
import datetime
import difflib
import io
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.cli.main import app
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document, an_issue
from agent_hub.core.testing.fakes import FakeTrackerBackend, InMemoryTrackerClient, TrackerState
from agent_hub.core.tracker.tracker_client import Issue

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
# Set by the caller (a git hook, a worktree script, a cloud session's config), a variable with
# this prefix would change which repo git reads or how it reads it.
GIT_VARIABLE_PREFIX = "GIT_"


@pytest.fixture(autouse=True)
def no_git_location(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run every test as if git found the repo from the folder: every ``GIT_*`` variable unset.

    ``AGENT_HUB_ROOT`` is unset too, so a command takes the hub from the folder it runs in.
    """
    for variable in [name for name in os.environ if name.startswith(GIT_VARIABLE_PREFIX)]:
        monkeypatch.delenv(variable)
    monkeypatch.delenv(HUB_ROOT_VARIABLE, raising=False)


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


def init_template(base: Path, document: dict[str, Any]) -> Path:
    """The tree ``hub init --config`` writes for ``document`` in ``base / "hub"``."""
    config = base / "hub.json"
    config.write_bytes(dump_json(document))
    root = base / "hub"
    result = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
    assert result.exit_code == 0, result.stderr
    # A copy must not carry a git folder that points back at the template.
    assert not os.path.lexists(root / ".git")
    return root


@pytest.fixture(scope="session")
def demo_hub_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The tree ``hub init --config DEMO`` writes, built once per session: never change it.

    ``init --config`` reads neither git nor ``HOME``, so the function-scoped fixtures that
    isolate them are not needed here.
    """
    return init_template(tmp_path_factory.mktemp("demo-hub-template"), demo_document_value())


@pytest.fixture
def demo_hub(tmp_path: Path, demo_hub_template: Path) -> Path:
    """A copy of the ``DEMO`` hub for this test: links kept as links, modes kept."""
    root = tmp_path / "hub"
    shutil.copytree(demo_hub_template, root, symlinks=True)
    return root


# The second repo of the two-repo ``DEMO`` (plan E3b), in the generator's ``variant_config`` shape.
DEMO_SECOND_REPO = {
    "dir": "demo-web",
    "github": "acme/demo-web",
    "check_fast": "make check-fast",
    "check": "make check",
}


@pytest.fixture(scope="session")
def demo_two_repo_hub_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``DEMO`` with ``demo-web`` after ``demo-api`` in ``repos``, built once: never change it."""
    document = demo_document_value()
    document["repos"].append(dict(DEMO_SECOND_REPO))
    return init_template(tmp_path_factory.mktemp("demo-two-repo-hub-template"), document)


@pytest.fixture
def demo_two_repo_hub(tmp_path: Path, demo_two_repo_hub_template: Path) -> Path:
    """A copy of the two-repo ``DEMO`` hub at ``tmp_path / "hub"``; its checkouts go next to it."""
    root = tmp_path / "hub"
    shutil.copytree(demo_two_repo_hub_template, root, symlinks=True)
    return root


type CheckoutFactory = Callable[[str], Path]


@pytest.fixture
def demo_checkout(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> CheckoutFactory:
    """``demo_checkout(dir)``: a synthetic git repo at ``tmp_path / dir`` with a committed README.

    Git reads the test's own ``HOME`` and config only, here and in the run (no system or global
    config, no ``XDG_CONFIG_HOME``), and never looks for a repository above ``tmp_path``.
    """
    git = shutil.which("git")
    assert git is not None, "git is needed for a synthetic checkout"
    home = tmp_path / "checkout-home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    def build(name: str) -> Path:
        root = tmp_path / name
        # An empty folder may already stand there (plan E3a).
        root.mkdir(exist_ok=True)
        (root / "README.md").write_bytes(f"# {name}\n".encode())
        author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
        for args in (
            ["-c", "init.defaultBranch=main", "init", "-q"],
            ["add", "-A"],
            [*author, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        ):
            subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
                [git, *args], cwd=root, env=env, check=True, capture_output=True
            )
        return root

    return build


type SyncRunner = Callable[..., Result]


@pytest.fixture
def run_sync(monkeypatch: pytest.MonkeyPatch) -> SyncRunner:
    """Run ``hub sync <args>`` in process with ``root`` as the current folder."""

    def run(root: Path, *args: str) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, ["sync", *args])

    return run


type DoctorRunner = Callable[..., Result]


@pytest.fixture
def run_doctor(monkeypatch: pytest.MonkeyPatch) -> DoctorRunner:
    """Run ``hub doctor <args>`` in process with ``root`` as the current folder."""

    def run(root: Path, *args: str) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, ["doctor", *args])

    return run


class PathRead(NamedTuple):
    """One call that reads a path: its name and the path.

    The path is absolute when the call names it from the current folder, and reads
    ``<fd N>/<name>`` when it is relative to an open folder (or ``<fd N>`` for the folder itself).
    """

    call: str
    path: str


# The calls through which a run looks at a path, each recorded before it goes through.
PATH_READ_CALLS = ("open", "stat", "lstat")


def _read_path(path: Any, dir_fd: int | None) -> str:
    if isinstance(path, int):
        return f"<fd {path}>"
    name = os.fsdecode(path)
    if dir_fd is not None:
        return f"<fd {dir_fd}>/{name}"
    return os.path.join(os.getcwd(), name)


@pytest.fixture
def path_reads(monkeypatch: pytest.MonkeyPatch) -> list[PathRead]:
    """Every path given to ``os.open``, ``os.stat``, ``os.lstat`` and ``os.scandir``, in order.

    The builtin ``open`` (also ``io.open``, which ``Path.read_bytes`` uses) is recorded as
    ``builtin-open`` when given a path, not a descriptor. A ``subprocess.Popen`` is recorded as
    ``Popen`` with the folder it runs in. Each call goes through.
    """
    reads: list[PathRead] = []

    def wrap(call: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def recorded(path: Any, *args: Any, dir_fd: int | None = None, **kwargs: Any) -> Any:
            reads.append(PathRead(call, _read_path(path, dir_fd)))
            return real(path, *args, dir_fd=dir_fd, **kwargs)

        return recorded

    for call in PATH_READ_CALLS:
        monkeypatch.setattr(os, call, wrap(call, getattr(os, call)))
    real_scandir = os.scandir

    def recorded_scandir(path: Any = os.curdir) -> Any:
        reads.append(PathRead("scandir", _read_path(path, None)))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", recorded_scandir)
    real_open = builtins.open

    def recorded_open(file: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(file, int):
            reads.append(PathRead("builtin-open", _read_path(file, None)))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", recorded_open)
    monkeypatch.setattr(io, "open", recorded_open)
    real_popen = subprocess.Popen

    def recorded_popen(*args: Any, **kwargs: Any) -> Any:
        folder = kwargs.get("cwd")
        reads.append(PathRead("Popen", os.fspath(folder) if folder is not None else os.getcwd()))
        return real_popen(*args, **kwargs)

    monkeypatch.setattr(subprocess, "Popen", recorded_popen)
    return reads


def reads_in_folder(reads: list[PathRead], folder: Path) -> set[str]:
    """The paths read inside ``folder`` (itself included), and every read relative to a folder."""
    # Taken before ``realpath``, whose own looks the recorder would add.
    recorded = list(reads)
    real = os.path.realpath(folder)
    return {
        read.path
        for read in recorded
        if read.path.startswith("<fd") or read.path == real or read.path.startswith(real + os.sep)
    }


def folder_ancestors(folder: str, *, up_to: Path) -> set[str]:
    """``folder`` and each folder above it, up to and including ``up_to`` (real paths)."""
    top = os.path.realpath(up_to)
    found = {top}
    while folder != top:
        found.add(folder)
        folder = os.path.dirname(folder)
    return found


def reads_under_folder(reads: list[PathRead], folder: Path) -> set[str]:
    """The paths read at or below ``folder``, named from it (a ``<fd N>`` read is not).

    A path is judged by its normalized form, so ``folder/../other`` is not below ``folder``.
    """
    recorded = list(reads)
    real = os.path.realpath(folder)
    return {
        read.path
        for read in recorded
        if (normal := os.path.normpath(read.path)) == real or normal.startswith(real + os.sep)
    }


@pytest.fixture
def reads_in() -> Callable[[list[PathRead], Path], set[str]]:
    """``reads_in(path_reads, folder)``: the paths read inside ``folder``, and every ``<fd N>``."""
    return reads_in_folder


@pytest.fixture
def ancestors() -> Callable[..., set[str]]:
    """``ancestors(real_folder, up_to=top)``: the folder and each one above it up to ``top``."""
    return folder_ancestors


@pytest.fixture
def under() -> Callable[[list[PathRead], Path], set[str]]:
    """``under(path_reads, folder)``: the recorded paths at or below ``folder``."""
    return reads_under_folder


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


def compare_lock_golden(
    content: bytes, *, golden: Path = DEMO_LOCK_GOLDEN, update: bool | None = None
) -> None:
    """Fail unless the normalized ``content`` equals ``golden``; update mode rewrites it instead.

    Update mode is read (and refused under ``CI``) before anything is compared, unless ``update``
    is given: ``False`` only compares, whatever ``GOLDEN_UPDATE`` says.
    """
    if update is None:
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


# The spec's "DEMO workspace" (AC-15.1 to AC-15.4): a DEMO hub whose default branch is trunk and
# whose two repos are clones of local bare origins, each origin advanced after the clone.
WORKSPACE_BRANCH = "trunk"
WORKSPACE_REPOS = ("demo-api", "demo-web")
_WORKSPACE_IDENTITY = ("-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com")


def _workspace_git_env(home: Path) -> dict[str, str]:
    """Git with this home only: no system or global config, no location variable."""
    return {
        "PATH": os.environ["PATH"],
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def _run_git(folder: Path, env: Mapping[str, str], *args: str) -> str:
    git = shutil.which("git")
    assert git is not None, "git is needed for a DEMO workspace"
    completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [os.path.abspath(git), *_WORKSPACE_IDENTITY, "-c", "commit.gpgsign=false", *args],
        cwd=folder,
        env=dict(env),
        check=True,
        capture_output=True,
    )
    return completed.stdout.decode().strip()


class DemoWorkspace:
    """A ``DEMO`` workspace: ``ws/hub``, one clone per repo, their bare origins in ``origins``."""

    def __init__(self, base: Path, env: Mapping[str, str]) -> None:
        self.base = base
        self.ws = base / "ws"
        self.hub = self.ws / "hub"
        self.origins = base / "origins"
        self.env = dict(env)

    def git(self, folder: Path, *args: str) -> str:
        """Run git in ``folder`` and return its stripped stdout; a failure fails the test."""
        return _run_git(folder, self.env, *args)

    def origin(self, repo: str) -> Path:
        return self.origins / f"{repo}.git"

    def origin_head(self, repo: str) -> str:
        return self.git(self.origin(repo), "rev-parse", WORKSPACE_BRANCH)

    def worktree(self, repo: str, name: str) -> Path:
        return self.ws / repo / ".claude" / "worktrees" / name

    def advance(self, repo: str, files: Mapping[str, tuple[bytes, int]] | None = None) -> str:
        """Push one commit to ``repo``'s origin (``files``: path → content and mode); its sha."""
        pusher = self.base / "pusher"
        shutil.rmtree(pusher, ignore_errors=True)
        self.git(self.base, "clone", "-q", str(self.origin(repo)), str(pusher))
        written = dict(files or {"CHANGES.md": (f"{self.origin_head(repo)}\n".encode(), 0o644)})
        for path, (content, mode) in written.items():
            target = pusher / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
            target.chmod(mode)
        self.git(pusher, "add", "-A")
        self.git(pusher, "commit", "-q", "-m", "advance")
        self.git(pusher, "push", "-q", "origin", WORKSPACE_BRANCH)
        shutil.rmtree(pusher)
        return self.origin_head(repo)


def _build_workspace(base: Path) -> DemoWorkspace:
    home = base / "home"
    home.mkdir()
    workspace = DemoWorkspace(base, _workspace_git_env(home))
    document = demo_document_value()
    document["project"]["default_branch"] = WORKSPACE_BRANCH
    document["repos"].append(dict(DEMO_SECOND_REPO))
    config = base / "workspace-hub.json"
    config.write_bytes(dump_json(document))
    result = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(workspace.hub)])
    assert result.exit_code == 0, result.stderr
    config.unlink()
    for repo in WORKSPACE_REPOS:
        seed = base / "seed" / repo
        seed.mkdir(parents=True)
        workspace.git(seed, "-c", f"init.defaultBranch={WORKSPACE_BRANCH}", "init", "-q")
        (seed / "README.md").write_bytes(f"# {repo}\n".encode())
        workspace.git(seed, "add", "-A")
        workspace.git(seed, "commit", "-q", "-m", "init")
        workspace.git(base, "clone", "-q", "--bare", str(seed), str(workspace.origin(repo)))
        workspace.git(base, "clone", "-q", str(workspace.origin(repo)), str(workspace.ws / repo))
        workspace.advance(repo)
    shutil.rmtree(base / "seed")
    return workspace


@pytest.fixture(scope="session")
def demo_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The ``DEMO`` workspace built once per session: never change it."""
    return _build_workspace(tmp_path_factory.mktemp("demo-workspace-template")).base


@pytest.fixture
def demo_workspace(
    tmp_path: Path, demo_workspace_template: Path, monkeypatch: pytest.MonkeyPatch
) -> DemoWorkspace:
    """A copy of the ``DEMO`` workspace in ``tmp_path``, each clone's origin pointed at its copy.

    The command's git reads no system or global config and finds no repo above ``tmp_path``.
    """
    base = tmp_path / "workspace"
    shutil.copytree(demo_workspace_template, base, symlinks=True)
    workspace = DemoWorkspace(base, _workspace_git_env(base / "home"))
    for repo in WORKSPACE_REPOS:
        workspace.git(
            workspace.ws / repo, "remote", "set-url", "origin", str(workspace.origin(repo))
        )
    for name, value in workspace.env.items():
        if name != "PATH":
            monkeypatch.setenv(name, value)
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    return workspace


type CommandRunner = Callable[..., Result]


@pytest.fixture
def run_command(monkeypatch: pytest.MonkeyPatch) -> CommandRunner:
    """Run ``hub <args>`` in process with ``root`` as the current folder; ``env`` as CliRunner's."""

    def run(root: Path, *args: str, env: Mapping[str, str | None] | None = None) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, list(args), env=env)

    return run


# The hub's brief workspace (hub ``tests/characterization/support/{fixtures,workspace}.py`` at
# hub commit 8eaebae), rebuilt so that ``hub brief`` reproduces the hub's brief goldens: the same
# frozen instant, identity, files, commit dates and fake ``gh`` answers. Only ``hub.json`` differs:
# it is made model-valid (``schema_version``, ``platform``, ``check_fast``/``check``, the author).
BRIEF_INSTANT = 1768473000  # 2026-01-15T10:30:00Z
BRIEF_HUB = "demo-hub"
BRIEF_SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
_BRIEF_IDENTITY = ("Test User", "t@example.com")
_REPO_IGNORES = (".claude/worktrees/", ".venv/", "node_modules/", "__pycache__/")
_HUB_IGNORES = (
    *_REPO_IGNORES,
    ".agent-runs/",
    "brain/_inbox/sessions/",
    "brain/auto/workspace/session-snapshot.md",
)
# Newer git runs auto-maintenance after commits; its lock files would come and go in a copy.
_NO_MAINTENANCE = (
    ("maintenance.auto", "false"),
    ("maintenance.autoDetach", "false"),
    ("gc.auto", "0"),
    ("gc.autoDetach", "false"),
)
BRIEF_NOW = "---\nlast_verified: 2026-01-12\n---\n# Now\nShip the collector.\nThen the CLI.\n"


def _brief_titles(day: int, count: int, width: int) -> str:
    return "".join(
        f"## Day {day} topic {index}: " + "x" * width + "\n" for index in range(1, count + 1)
    )


BRIEF_JOURNAL = {
    "brain/journal/2026/01/14.md": (
        "---\ntype: journal\n---\n# 2026-01-14\n"
        + _brief_titles(14, 4, 80)
        + "### not a title\nbody text\n"
    ),
    "brain/journal/2026/01/13.md": (
        "# 2026-01-13\n## Fixed the loader\nnotes\n## Reviewed slice A\n"
    ),
    "brain/journal/2026/01/10.md": "## Older day in the week\n",
    "brain/journal/2026/01/06.md": "## Outside the week\n",
}
BRIEF_PRS = (
    "\n".join(
        [
            "#41 Add login endpoint",
            "#40 Refactor the session storage layer so that every adapter shares one connection"
            " pool and retry policy",
            "#38 Fix pagination",
            "#37 Bump dependencies",
            "#35 Fifth PR is never shown",
        ]
    )
    + "\n"
)
# The hub repo's calls match no rule: the fake prints nothing and exits 1.
BRIEF_GH: list[dict[str, Any]] = [
    {"argv_has": ["pr", "acme/api"], "stdout": BRIEF_PRS},
    {"argv_has": ["run", "acme/api"], "stdout": "lint\nbuild\nlint\n"},
    {"argv_has": ["acme/web"], "stdout": ""},
]
# The fake gh: logs each call as one JSON line, sleeps a rule's delay, then answers. Written to
# the case's bin/ at test time (a tests tree holds no helper module).
_FAKE_GH = """import json, os, sys, time
answers, log, invoked, args = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:]
call = {"tool": "gh", "cwd": os.getcwd(), "argv": [invoked, *args]}
with open(log, "a", encoding="utf-8") as stream:
    stream.write(json.dumps(call, ensure_ascii=False) + "\\n")
with open(answers, encoding="utf-8") as stream:
    rules = json.load(stream)
rule = next((r for r in rules if all(a in args for a in r.get("argv_has", []))), None)
if rule is None:
    sys.exit(1)
barrier = rule.get("barrier")
if barrier:  # wait until `count` calls have arrived, so only calls made at once can all pass
    open(os.path.join(barrier["dir"], f"started.{os.getpid()}"), "w").close()
    end = time.monotonic() + barrier["wait"]
    while len(os.listdir(barrier["dir"])) < barrier["count"]:
        if time.monotonic() > end:
            sys.exit(1)
        time.sleep(0.01)
if "group_file" in rule:
    with open(rule["group_file"], "w", encoding="utf-8") as stream:
        stream.write(str(os.getpgid(0)))
time.sleep(rule.get("delay", 0))
sys.stdout.buffer.write(rule.get("stdout", "").encode())
sys.stderr.buffer.write(rule.get("stderr", "").encode())
sys.exit(rule.get("rc", 0))
"""


def brief_at(days_before: int = 0, hhmm: str = "10:30") -> str:
    """An ISO instant ``days_before`` days before the frozen day, at ``hhmm`` UTC."""
    day = datetime.datetime.fromtimestamp(BRIEF_INSTANT, datetime.UTC) - datetime.timedelta(
        days=days_before
    )
    return f"{day:%Y-%m-%d}T{hhmm}:00Z"


def brief_hub_json() -> dict[str, Any]:
    """The hub's brief ``hub.json`` (repos ``api``, ``web`` and the absent ``ui``), model-valid."""
    checks = {"check_fast": "true", "check": "true"}
    return {
        "schema_version": 1,
        "platform": {"version": version("agent-hub-cli")},
        "project": {
            "name": "demo",
            "hub_repo": "acme/demo-hub",
            "branch_prefix": "dev/",
            "default_branch": "trunk",
            "author_name": _BRIEF_IDENTITY[0],
            "author_email": _BRIEF_IDENTITY[1],
        },
        "tracker": {"kind": "linear", "team": "TST"},
        "repos": [
            {"dir": "api", "github": "acme/api", **checks},
            {"dir": "web", "github": "acme/web", **checks},
            {"dir": "ui", "github": "acme/ui", **checks},
        ],
    }


def brief_env(root: Path) -> dict[str, str]:
    """The case environment, built from scratch: the fakes, system tools, a fixed git."""
    name, email = _BRIEF_IDENTITY
    env = {
        "PATH": os.pathsep.join([str(root / "bin"), *BRIEF_SYSTEM_PATH]),
        "HOME": str(root / "home"),
        "XDG_CONFIG_HOME": str(root / "home" / ".config"),
        "TZ": "UTC",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": str(root / "home" / ".gitconfig"),
        "GIT_AUTHOR_NAME": name,
        "GIT_AUTHOR_EMAIL": email,
        "GIT_AUTHOR_DATE": brief_at(),
        "GIT_COMMITTER_NAME": name,
        "GIT_COMMITTER_EMAIL": email,
        "GIT_COMMITTER_DATE": brief_at(),
        "GIT_ALLOW_PROTOCOL": "file",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CEILING_DIRECTORIES": str(root),
        "GIT_CONFIG_COUNT": str(len(_NO_MAINTENANCE)),
    }
    for index, (key, value) in enumerate(_NO_MAINTENANCE):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return env


class BriefWorkspace:
    """A case root: ``ws/demo-hub`` (the hub), ``ws/api``, ``ws/web``, ``origins/``, ``bin/gh``."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.ws = root / "ws"
        self.hub = self.ws / BRIEF_HUB
        self.env = brief_env(root)
        self.log = root / "log" / "calls.jsonl"

    def git(self, *args: str, cwd: Path, date: str | None = None) -> str:
        """Run git with the case environment; ``date`` sets both commit dates."""
        env = dict(self.env)
        if date is not None:
            env["GIT_AUTHOR_DATE"] = env["GIT_COMMITTER_DATE"] = date
        git = shutil.which("git", path=env["PATH"])
        assert git is not None, "git is needed for the brief workspace"
        completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
            [git, *args], cwd=cwd, env=env, check=True, capture_output=True
        )
        return completed.stdout.decode().strip()

    def write(self, base: Path, files: Mapping[str, str | bytes | None]) -> None:
        """Write (text or bytes) or delete (None) ``files`` under ``base``."""
        for relative, content in files.items():
            path = base / relative
            if content is None:
                path.unlink()
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content if isinstance(content, bytes) else content.encode())

    def make_repo(
        self,
        path: Path,
        files: Mapping[str, str],
        commits: tuple[tuple[int, str, Mapping[str, str]], ...] = (),
        *,
        ignores: tuple[str, ...] = _REPO_IGNORES,
    ) -> Path:
        """An ``init`` commit at T-30 (``files`` and ``.gitignore``), then each commit in order."""
        path.mkdir(parents=True, exist_ok=True)
        self.git("init", "-q", "-b", "trunk", cwd=path)
        self.write(path, {**files, ".gitignore": "".join(f"{line}\n" for line in ignores)})
        for index, (days_before, message, more) in enumerate([(30, "init", {}), *commits]):
            self.write(path, more)
            self.git("add", "-A", cwd=path)
            self.git(
                "commit",
                "-q",
                "-m",
                message,
                cwd=path,
                date=brief_at(days_before, f"09:{index:02d}"),
            )
        return path

    def bare_origin(self, repo: Path) -> None:
        bare = self.root / "origins" / f"{repo.name}.git"
        self.git("clone", "-q", "--bare", str(repo), str(bare), cwd=self.root)
        self.git("remote", "add", "origin", str(bare), cwd=repo)
        self.git("fetch", "-q", "origin", cwd=repo)

    def commit_hub(self, files: Mapping[str, str | bytes | None]) -> None:
        """Write or delete ``files`` in the hub, committed at T-0 09:30 (the hub stays clean)."""
        self.write(self.hub, files)
        self.git("add", "-A", cwd=self.hub)
        self.git("commit", "-q", "-m", "case change", cwd=self.hub, date=brief_at(0, "09:30"))

    def answer(self, rules: list[dict[str, Any]]) -> None:
        """Set the fake gh's rules: the first whose ``argv_has`` items are all arguments answers."""
        (self.root / "bin" / "answers.json").write_text(json.dumps(rules, indent=2) + "\n")

    def calls(self) -> bytes:
        """The fake gh's call log, the root shown as ``<ROOT>``."""
        return normalized(self.log.read_bytes() if self.log.exists() else b"", self.root)

    def install_gh(self) -> None:
        bin_dir = self.root / "bin"
        (bin_dir / "fake_gh.py").write_text(_FAKE_GH)
        gh = bin_dir / "gh"
        gh.write_text(
            f'#!/bin/sh\nexec "{sys.executable}" -I -S "{bin_dir / "fake_gh.py"}"'
            f' "{bin_dir / "answers.json"}" "{self.log}" "$0" "$@"\n'
        )
        gh.chmod(0o755)
        self.answer(BRIEF_GH)


def _build_brief_workspace(root: Path) -> None:
    for folder in ("ws", "origins", "home/.config", "bin", "log", "elsewhere"):
        (root / folder).mkdir(parents=True)
    workspace = BriefWorkspace(root)
    hub_files = {
        **BRIEF_JOURNAL,
        "brain/now.md": BRIEF_NOW,
        "hub.json": json.dumps(brief_hub_json(), indent=2) + "\n",
    }
    workspace.make_repo(workspace.hub, hub_files, ignores=_HUB_IGNORES)
    workspace.bare_origin(workspace.hub)
    api = workspace.make_repo(
        workspace.ws / "api", {"README.md": "api\n"}, ((3, "add app", {"app.py": "x = 1\n"}),)
    )
    workspace.bare_origin(api)
    pusher = root / "elsewhere" / "api-pusher"
    workspace.git("clone", "-q", str(root / "origins" / "api.git"), str(pusher), cwd=root)
    workspace.write(pusher, {"app.py": "x = 2\n"})
    workspace.git("commit", "-q", "-am", "upstream change", cwd=pusher, date=brief_at(1, "09:00"))
    workspace.git("push", "-q", "origin", "trunk", cwd=pusher)
    workspace.git("fetch", "-q", "origin", cwd=api)
    workspace.write(api, {"README.md": "api, edited\n", "notes.txt": "untracked\n"})
    web = workspace.make_repo(
        workspace.ws / "web", {"index.html": "<p>web</p>\n"}, ((2, "style", {"a.css": "p{}\n"}),)
    )
    workspace.git("checkout", "-q", "--detach", cwd=web)


@pytest.fixture(scope="session")
def brief_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The brief workspace built once per session: never change it."""
    root = tmp_path_factory.mktemp("brief-workspace-template").resolve()
    _build_brief_workspace(root)
    return root


@pytest.fixture
def brief_workspace(
    tmp_path: Path, brief_workspace_template: Path, monkeypatch: pytest.MonkeyPatch
) -> BriefWorkspace:
    """A copy of the brief workspace at ``tmp_path/root``, its environment set for the run.

    Each origin URL is pointed at the copy; the fake ``gh`` answers ``BRIEF_GH``.
    """
    root = (tmp_path / "root").resolve()
    shutil.copytree(brief_workspace_template, root, symlinks=True)
    workspace = BriefWorkspace(root)
    for checkout in (workspace.hub, workspace.ws / "api"):
        url = workspace.git("remote", "get-url", "origin", cwd=checkout)
        copied = str(root) + url.removeprefix(str(brief_workspace_template))
        workspace.git("remote", "set-url", "origin", copied, cwd=checkout)
    workspace.install_gh()
    for name in [name for name in os.environ if name.startswith(GIT_VARIABLE_PREFIX)]:
        monkeypatch.delenv(name)
    for name, value in workspace.env.items():
        monkeypatch.setenv(name, value)
    return workspace


def normalized(data: bytes, root: Path) -> bytes:
    """``data`` with the case root shown as ``<ROOT>``."""
    return data.replace(str(root).encode(), b"<ROOT>")


_GOLDEN_HEADER = re.compile(rb"--- (\w+) \((\d+) bytes\) ---\n")


def _golden_sections(path: Path) -> dict[str, bytes]:
    """The sections of a hub characterization golden: ``{stream: bytes}``, in file order."""
    data = path.read_bytes()
    sections: dict[str, bytes] = {}
    position = 0
    while position < len(data):
        header = _GOLDEN_HEADER.match(data, position)
        assert header is not None, f"{path}: no section header at byte {position}"
        start = header.end()
        end = start + int(header.group(2))
        assert data[end : end + 1] == b"\n", f"{path}: no separator after {header.group(1)!r}"
        sections[header.group(1).decode()] = data[start:end]
        position = end + 1
    return sections


@pytest.fixture
def golden_sections() -> Callable[[Path], dict[str, bytes]]:
    """Parse a hub characterization golden into ``{stream: bytes}``."""
    return _golden_sections


# ``hub agent``'s workspace (AC-15.8): a DEMO hub listing repos ``a``, ``b`` and ``c``.
AGENT_REPOS = ("a", "b", "c")


def agent_document() -> dict[str, Any]:
    document = demo_document_value()
    document["repos"] = [
        {"dir": name, "github": f"acme/{name}", "check_fast": "true", "check": "true"}
        for name in AGENT_REPOS
    ]
    document["guard"] = {"ask_before_edit": []}
    return document


@pytest.fixture(scope="session")
def agent_workspace_template(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """``ws/hub``: the hub ``hub init --config`` writes for the agent document, built once."""
    workspace = tmp_path_factory.mktemp("agent-workspace-template") / "ws"
    workspace.mkdir()
    hub = init_template(workspace, agent_document())
    (workspace / "hub.json").unlink()
    return hub.parent


@pytest.fixture
def agent_workspace(tmp_path: Path, agent_workspace_template: Path) -> Path:
    """A copy at ``tmp_path/ws``: the hub, ``a`` with an ``AGENTS.md``, ``b`` without, no ``c``."""
    workspace = tmp_path / "ws"
    shutil.copytree(agent_workspace_template, workspace, symlinks=True)
    (workspace / "a").mkdir()
    (workspace / "a" / "AGENTS.md").write_bytes(b"# a\nRun make check.\n")
    (workspace / "b").mkdir()
    return workspace


# hub run's workspace (AGH-27 PR 3): the DEMO workspace with a PATH of fakes. ``claude``, ``gh``
# and ``make`` are Python scripts behind /bin/sh wrappers that log each call as one JSON line
# (argv, cwd, the environment's names, never its values, and the process group); ``git`` and
# ``bash`` are the real ones, linked, and so is the interpreter (``python3``).
RUN_PR_URL = "https://github.com/acme/demo-api/pull/99"
RUN_SUMMARY = "Adds the synthetic change."
RUN_COST_USD = 0.42
# The environment values a fake may log as they are: none can hold a secret.
_LOGGED_VALUES = ("OTEL_RESOURCE_ATTRIBUTES",)
_FAKE_LOG = """import json, os, sys
def log(tool, **extra):
    record = {
        "argv": sys.argv[1:],
        "cwd": os.getcwd(),
        "env": sorted(os.environ),
        "values": {name: os.environ[name] for name in LOGGED if name in os.environ},
        "pgid": os.getpgid(0),
        **extra,
    }
    with open(os.path.join(os.environ["FAKE_RUN_LOGS"], tool + ".jsonl"), "a") as file:
        file.write(json.dumps(record) + "\\n")
""".replace("LOGGED", repr(_LOGGED_VALUES))
_FAKE_CLAUDE = (
    _FAKE_LOG
    + """import subprocess, time
argv = sys.argv[1:]
allowed = argv[argv.index("--allowedTools") + 1:] if "--allowedTools" in argv else []
if "--disallowedTools" in allowed:
    allowed = allowed[:allowed.index("--disallowedTools")]
def answer(result, *, is_error=False, cost=RUN_COST):
    print(json.dumps({"type": "result", "is_error": is_error, "subtype": "success",
                      "result": result, "total_cost_usd": cost, "num_turns": 3}))
if any(tool.startswith("mcp__") for tool in allowed):
    # A tracker call of the MCP adapter: only get_issue is answered, from FAKE_CLAUDE_ISSUE.
    log("claude", tracker=True)
    with open(os.environ["FAKE_CLAUDE_ISSUE"]) as file:
        answer(json.dumps({"issue": json.load(file)}), cost=0.01)
    sys.exit(0)
mode = os.environ.get("FAKE_CLAUDE_MODE", "done")
log("claude", tracker=False, mode=mode)
def commit():
    with open("synthetic_change.txt", "a") as file:
        file.write("change\\n")
    identity = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    subprocess.run(["git", "add", "synthetic_change.txt"], check=True)
    subprocess.run(["git", *identity, "commit", "-q", "-m", "feat(api): synthetic change (DEM-1)"],
                   check=True)
verdict = {"status": "done", "summary": RUN_SUMMARY, "tests": "make check-fast"}
if mode == "hang":
    time.sleep(600)
if mode in ("done", "prose", "done-dirty"):
    commit()
if mode == "done-dirty":
    with open("notes.txt", "w") as file:
        file.write("left behind\\n")
if mode in ("done", "done-no-commit", "done-dirty"):
    answer("Done.\\n" + json.dumps(verdict))
elif mode == "blocked":
    answer("Stopping.\\n" + json.dumps({"status": "blocked", "summary": "needs a plan"}))
elif mode == "blocked-text":
    answer("BLOCKED: the issue has an open question")
elif mode == "error":
    answer("ran out of turns", is_error=True)
elif mode == "prose":
    answer("I made the change and ran the tests.")
""".replace("RUN_COST", repr(RUN_COST_USD)).replace("RUN_SUMMARY", repr(RUN_SUMMARY))
)
_RUN_FAKE_GH = (
    _FAKE_LOG
    + """mode = os.environ.get("FAKE_GH_MODE", "url")
log("gh", mode=mode)
if sys.argv[1:3] == ["pr", "view"]:
    # The branch's PR: open in mode "exists", none otherwise.
    if mode != "exists":
        print("no pull requests found for branch", file=sys.stderr)
        sys.exit(1)
    print(json.dumps({"url": PR_URL, "state": "OPEN"}))
    sys.exit(0)
if mode in ("fail", "exists"):
    print("gh: a pull request already exists" if mode == "exists" else "gh: synthetic failure",
          file=sys.stderr)
    sys.exit(1)
print("Creating pull request" if mode == "no-url" else PR_URL)
""".replace("PR_URL", repr(RUN_PR_URL))
)
_FAKE_MAKE = (
    _FAKE_LOG
    + """log("make")
code = int(os.environ.get("FAKE_MAKE_EXIT", "0"))
print("synthetic gate output", file=sys.stderr if code else sys.stdout)
sys.exit(code)
"""
)


# A git that logs each call (argv, cwd, environment names) and then runs the real git.
_FAKE_GIT = (
    _FAKE_LOG
    + """if "FAKE_RUN_LOGS" in os.environ:  # a fixture's own git call has no log folder
    log("git")
os.execv(REAL_GIT, [REAL_GIT, *sys.argv[1:]])
"""
)


class RunWorkspace:
    """The DEMO workspace for ``hub run``: its fakes' ``bin`` and their call logs."""

    def __init__(self, workspace: Any, bin_dir: Path, logs: Path) -> None:
        self.workspace = workspace
        self.bin = bin_dir
        self.logs = logs

    def calls(self, tool: str) -> list[dict[str, Any]]:
        """The logged calls of ``tool`` (``claude``, ``gh`` or ``make``), in order."""
        path = self.logs / f"{tool}.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines()]


def _write_fake(bin_dir: Path, name: str, script: str) -> None:
    source = bin_dir.parent / "fakes" / f"{name}.py"
    source.parent.mkdir(exist_ok=True)
    source.write_text(script)
    wrapper = bin_dir / name
    wrapper.write_text(f"#!/bin/sh\nexec '{sys.executable}' '{source}' \"$@\"\n")
    wrapper.chmod(0o755)


def _link_tool(bin_dir: Path, name: str, target: str | None) -> None:
    assert target is not None, f"{name} is needed for a run workspace"
    (bin_dir / name).symlink_to(os.path.abspath(target))


@pytest.fixture
def run_workspace(
    demo_workspace: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> RunWorkspace:
    """``demo_workspace`` with ``PATH`` = only the fakes, ``git``, ``bash`` and ``python3``.

    ``HOME`` stays under ``tmp_path`` (``demo_workspace``); ``CLAUDECODE`` is unset.
    """
    bin_dir = tmp_path / "run-bin"
    bin_dir.mkdir()
    logs = tmp_path / "run-logs"
    logs.mkdir()
    _write_fake(bin_dir, "claude", _FAKE_CLAUDE)
    _write_fake(bin_dir, "gh", _RUN_FAKE_GH)
    _write_fake(bin_dir, "make", _FAKE_MAKE)
    _link_tool(bin_dir, "git", shutil.which("git"))
    _link_tool(bin_dir, "bash", shutil.which("bash"))
    _link_tool(bin_dir, "python3", sys.executable)
    monkeypatch.setenv("PATH", str(bin_dir))
    monkeypatch.setenv("FAKE_RUN_LOGS", str(logs))
    monkeypatch.delenv("CLAUDECODE", raising=False)
    return RunWorkspace(demo_workspace, bin_dir, logs)


RUN_DESCRIPTION = "Add a synthetic change.\n\n- touch one file\n- keep the gate green\n"


def tracker_backend_for_run(*, failed: bool = True) -> FakeTrackerBackend:
    """DEM-1 open, ``agent-ready`` and ``demo-api`` (and ``agent-failed`` unless ``failed`` is
    False); the team's states include ``In Review``."""
    labels = ("agent-ready", "demo-api", *(("agent-failed",) if failed else ()))
    issue = an_issue(
        id="DEM-1", title="Synthetic run issue", description=RUN_DESCRIPTION, labels=labels
    )
    return FakeTrackerBackend(
        states={
            "DEM": (
                TrackerState(name="Todo", closed=False),
                TrackerState(name="In Progress", closed=False),
                TrackerState(name="In Review", closed=False),
                TrackerState(name="Done", closed=True),
            )
        },
        team_labels={"DEM": ("demo-api", "demo-web")},
        workspace_labels=("agent-ready", "agent-failed"),
        issues={issue.id: issue},
    )


class RecordingTracker:
    """An ``InMemoryTrackerClient`` that records every port call: ``(operation, *arguments)``."""

    def __init__(self, backend: FakeTrackerBackend) -> None:
        self.backend = backend
        self._client = InMemoryTrackerClient(backend)
        self.calls: list[tuple[str, ...]] = []

    def list_ready(self, team: str, label: str) -> list[Issue]:
        self.calls.append(("list_ready", team, label))
        return self._client.list_ready(team, label)

    def get_issue(self, issue_id: str) -> Issue:
        self.calls.append(("get_issue", issue_id))
        return self._client.get_issue(issue_id)

    def move_state(self, issue_id: str, state_name: str) -> None:
        self.calls.append(("move_state", issue_id, state_name))
        self._client.move_state(issue_id, state_name)

    def add_label(self, issue_id: str, name: str) -> None:
        self.calls.append(("add_label", issue_id, name))
        self._client.add_label(issue_id, name)

    def remove_label(self, issue_id: str, name: str) -> None:
        self.calls.append(("remove_label", issue_id, name))
        self._client.remove_label(issue_id, name)

    def comment(self, issue_id: str, body: str) -> None:
        self.calls.append(("comment", issue_id, body))
        self._client.comment(issue_id, body)


@pytest.fixture
def run_tracker() -> RecordingTracker:
    """A recording tracker over ``tracker_backend_for_run()``."""
    return RecordingTracker(tracker_backend_for_run())


@pytest.fixture
def logged_git(run_workspace: RunWorkspace) -> RunWorkspace:
    """The run workspace with its ``git`` replaced by one that logs each call, then runs git."""
    real = os.path.realpath(run_workspace.bin / "git")
    (run_workspace.bin / "git").unlink()
    _write_fake(run_workspace.bin, "git", _FAKE_GIT.replace("REAL_GIT", repr(real)))
    return run_workspace
