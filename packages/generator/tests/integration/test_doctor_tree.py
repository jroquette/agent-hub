"""The doctor's tree reader on real folders, git work trees and fake gits (spec AC-11.3, E7-E9).

Every ``GIT_*`` variable of the caller is removed and ``HOME`` is a folder of the test, so no
test's git reads the user's config, the system config or a location set by a git hook (E20).
"""

import errno
import os
import shutil
import signal
import subprocess
import time
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from agent_hub.core.doctor.snapshot import HubFiles
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, OtherEntry
from agent_hub.generator.doctor_tree import read_doctor_tree

# Found before any test puts a fake first on PATH.
REAL_GIT = shutil.which("git")
REAL_PS = shutil.which("ps")
COMMIT_CONFIG = (
    "-c",
    "user.name=Doctor Test",
    "-c",
    "user.email=doctor@example.com",
    "-c",
    "commit.gpgsign=false",
)
CHILD_TIMEOUT = 60.0
FIFO_ALARM_SECONDS = 5


@pytest.fixture(autouse=True)
def no_caller_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove every ``GIT_*`` variable and give git a home and config of its own, no system one.

    The user's global config and excludes (``~/.gitconfig``, ``$XDG_CONFIG_HOME/git``) never
    reach a test's git.
    """
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))


@pytest.fixture
def alarm() -> Iterator[None]:
    """Fail a test that blocks (a FIFO opened by mistake) instead of hanging the run."""

    def timed_out(_signal: int, _frame: object) -> None:
        pytest.fail("the read blocked")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(FIFO_ALARM_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def git(args: Sequence[str], *, cwd: Path) -> bytes:
    assert REAL_GIT is not None, "git is needed for the work tree cases"
    completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [REAL_GIT, *args],
        cwd=cwd,
        env={
            name: os.environ[name] for name in ("HOME", "GIT_CONFIG_NOSYSTEM", "GIT_CONFIG_GLOBAL")
        },
        capture_output=True,
        check=True,
        timeout=CHILD_TIMEOUT,
    )
    return completed.stdout


def write(root: Path, files: dict[str, str]) -> Path:
    for path, text in files.items():
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def plain_hub(tmp_path: Path) -> Path:
    """A folder that is no git work tree, with the dot and vendor folders the old walk dropped."""
    return write(
        tmp_path / "hub",
        {
            "AGENTS.md": "# Agents\n",
            ".github/workflows/ci.yml": "on: push\n",
            "node_modules/x.json": "{}\n",
        },
    )


@pytest.mark.usefixtures("alarm")
def test_walks_every_file_when_not_work_tree(plain_hub: Path, tmp_path: Path) -> None:
    os.mkfifo(plain_hub / "pipe")
    write(plain_hub, {"sub/.git/config": "[core]\n", "sub/x.md": "x\n"})
    (plain_hub / "CLAUDE.md").symlink_to("AGENTS.md")
    (plain_hub / "docs").symlink_to(write(tmp_path / "outside", {"secret.md": "outside\n"}))

    tree = read_doctor_tree(plain_hub, by_path=(), listing=True)

    assert tree.problem is None
    # Files and links are listed, as git lists them; folders, the FIFO and a nested repo are not.
    assert tree.listed == (
        ".github/workflows/ci.yml",
        "AGENTS.md",
        "CLAUDE.md",
        "docs",
        "node_modules/x.json",
    )
    assert tree.entries["node_modules/x.json"] == FileEntry(executable=False, content=b"{}\n")
    assert tree.entries["CLAUDE.md"] == LinkEntry(target="AGENTS.md", outside=False)
    # The FIFO is recorded, never opened (the alarm fails the test if it blocks).
    assert tree.entries["pipe"] == OtherEntry(kind="fifo")
    assert [path for path in tree.entries if path.startswith(("sub", "docs/"))] == []


@pytest.fixture
def work_tree(tmp_path: Path) -> Path:
    """A committed git work tree with an ignored, an untracked and a tracked file."""
    root = write(
        tmp_path / "repo",
        {".gitignore": "ignored.txt\n", "AGENTS.md": "# Agents\n", "docs/a.md": "a\n"},
    )
    git(["init", "-q", "-b", "main"], cwd=root)
    git(["add", "-A"], cwd=root)
    git([*COMMIT_CONFIG, "commit", "-q", "-m", "init"], cwd=root)
    write(root, {"ignored.txt": "no\n", "notes.md": "untracked\n"})
    return root


def test_lists_like_git_when_work_tree(work_tree: Path) -> None:
    raw = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=work_tree)

    tree = read_doctor_tree(work_tree, by_path=(), listing=True)

    assert tree.problem is None
    assert tree.listed == (".gitignore", "AGENTS.md", "docs/a.md", "notes.md")
    assert tree.listed == tuple(sorted(os.fsdecode(path) for path in raw.split(b"\0") if path))
    assert tree.entries["notes.md"] == FileEntry(executable=False, content=b"untracked\n")
    assert "ignored.txt" not in tree.entries
    assert [path for path in tree.entries if path.startswith(".git/")] == []


def test_sorts_listing_when_git_prints_others_first(work_tree: Path) -> None:
    write(work_tree, {"0-untracked.md": "0\n", "zz-untracked.md": "z\n"})
    raw = git(["ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=work_tree)
    printed = [os.fsdecode(path) for path in raw.split(b"\0") if path]
    assert printed != sorted(printed)

    tree = read_doctor_tree(work_tree, by_path=(), listing=True)

    assert tree.listed == tuple(sorted(printed))
    assert list(tree.entries) == sorted(tree.entries)


def test_skips_nested_repository_when_listed(work_tree: Path) -> None:
    nested = write(work_tree / "nested", {"inner.md": "inner\n"})
    git(["init", "-q"], cwd=nested)
    assert b"nested/\0" in git(["ls-files", "-z", "--others", "--exclude-standard"], cwd=work_tree)

    tree = read_doctor_tree(work_tree, by_path=(), listing=True)

    assert tree.listed == (".gitignore", "AGENTS.md", "docs/a.md", "notes.md")
    assert [path for path in tree.entries if path.startswith("nested")] == []


def test_records_link_without_following_when_listed(work_tree: Path, tmp_path: Path) -> None:
    outside = write(tmp_path / "outside", {"secret.md": "outside\n"})
    (work_tree / "shared").symlink_to(outside)
    (work_tree / "CLAUDE.md").symlink_to("AGENTS.md")
    git(["add", "shared", "CLAUDE.md"], cwd=work_tree)

    tree = read_doctor_tree(work_tree, by_path=("shared/secret.md",), listing=True)

    assert tree.entries["shared"] == LinkEntry(target=str(outside), outside=True)
    assert tree.entries["CLAUDE.md"] == LinkEntry(target="AGENTS.md", outside=False)
    assert {"shared", "CLAUDE.md"} <= set(tree.listed)
    assert [path for path in tree.entries if path.startswith("shared/")] == []


def test_looks_at_lock_paths_when_git_ignores_them(work_tree: Path) -> None:
    write(work_tree, {".gitignore": "ignored.txt\nhub.lock\n", "hub.lock": "{}\n"})

    tree = read_doctor_tree(
        work_tree, by_path=("hub.lock", "ignored.txt", "absent.md"), listing=True
    )

    assert tree.entries["hub.lock"] == FileEntry(executable=False, content=b"{}\n")
    assert tree.entries["ignored.txt"] == FileEntry(executable=False, content=b"no\n")
    assert "absent.md" not in tree.entries
    assert "hub.lock" not in tree.listed
    assert "ignored.txt" not in tree.listed


def test_walks_when_root_is_subfolder_of_work_tree(work_tree: Path) -> None:
    hub = write(work_tree / "hub", {"AGENTS.md": "# Hub\n", "ignored.txt": "walked\n"})

    tree = read_doctor_tree(hub, by_path=(), listing=True)

    # The outer repo ignores ignored.txt, but the hub is no work tree top: it is walked.
    assert tree.problem is None
    assert tree.listed == ("AGENTS.md", "ignored.txt")


def test_ignores_caller_git_variables_when_listing(
    work_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    other = write(tmp_path / "other", {"elsewhere.md": "other\n", "excludes": "notes.md\n"})
    git(["init", "-q"], cwd=other)
    git(["add", "-A"], cwd=other)
    # Git's repository-local variables (``git rev-parse --local-env-vars``), each pointing at
    # the other repo or changing how the tree is read.
    for variable, value in {
        "GIT_DIR": other / ".git",
        "GIT_WORK_TREE": other,
        "GIT_COMMON_DIR": other / ".git",
        "GIT_INDEX_FILE": other / ".git" / "index",
        "GIT_OBJECT_DIRECTORY": other / ".git" / "objects",
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": other / ".git" / "objects",
        "GIT_CONFIG": other / ".git" / "config",
        # Either one alone would hide the untracked notes.md behind another excludes file.
        "GIT_CONFIG_PARAMETERS": f"'core.excludesfile'='{other / 'excludes'}'",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.excludesfile",
        "GIT_CONFIG_VALUE_0": other / "excludes",
        "GIT_IMPLICIT_WORK_TREE": "0",
        "GIT_GRAFT_FILE": other / "grafts",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_REPLACE_REF_BASE": "refs/other/",
        "GIT_PREFIX": "docs/",
        "GIT_SHALLOW_FILE": other / "shallow",
    }.items():
        monkeypatch.setenv(variable, str(value))

    tree = read_doctor_tree(work_tree, by_path=(), listing=True)

    assert tree.problem is None
    assert tree.listed == (".gitignore", "AGENTS.md", "docs/a.md", "notes.md")


def fake_git(bin_dir: Path, body: str) -> Path:
    """A ``/bin/sh`` script named ``git`` in ``bin_dir`` running ``body`` (shell builtins only)."""
    bin_dir.mkdir()
    script = bin_dir / "git"
    script.write_text(f"#!/bin/sh\n{body}", encoding="utf-8")
    script.chmod(0o755)
    return bin_dir


def test_disables_fsmonitor_when_git_runs(
    plain_hub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (plain_hub / ".git").mkdir()
    log = tmp_path / "git.log"
    bin_dir = fake_git(
        tmp_path / "bin",
        f'printf \'%s|%s\\n\' "$*" "$GIT_OPTIONAL_LOCKS" >> "{log}"\n'
        'case "$*" in\n'
        f"  *rev-parse*) printf '%s\\n' '{plain_hub}' ;;\n"
        "  *ls-files*) printf 'AGENTS.md\\000' ;;\n"
        "esac\n",
    )
    monkeypatch.setenv("PATH", str(bin_dir))

    tree = read_doctor_tree(plain_hub, by_path=(), listing=True)

    assert tree.listed == ("AGENTS.md",)
    assert log.read_text(encoding="utf-8").splitlines() == [
        "-c core.fsmonitor=false rev-parse --show-toplevel|0",
        "-c core.fsmonitor=false ls-files -z --cached --others --exclude-standard|0",
    ]


def test_reads_only_fixed_paths_when_listing_not_asked(
    work_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    log = tmp_path / "git.log"
    monkeypatch.setenv("PATH", str(fake_git(tmp_path / "bin", f'echo "$*" >> "{log}"\nexit 1\n')))

    tree = read_doctor_tree(work_tree, by_path=("AGENTS.md", "absent.md"), listing=False)

    assert tree == HubFiles(
        entries={"AGENTS.md": FileEntry(executable=False, content=b"# Agents\n")},
        listed=(),
        problem=None,
        paths_read=True,
    )
    assert not log.exists()


def gone(pid: int) -> bool:
    """Whether ``pid`` ends within a few seconds; a zombie (dead, not yet reaped) counts as gone."""
    assert REAL_PS is not None, "ps is needed to see the killed child"
    deadline = time.monotonic() + FIFO_ALARM_SECONDS / 2
    while time.monotonic() < deadline:
        completed = subprocess.run(  # noqa: S603 - absolute ps, fixed arguments
            [REAL_PS, "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
        )
        state = completed.stdout.strip()
        if not state or state.startswith("Z"):
            return True
        time.sleep(0.05)
    return False


GIT_CASES = ("missing", "not starting", "failing", "hanging", "other top")


def break_git(case: str, *, root: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """Make git fail as ``case`` says for the work tree ``root``; return the expected cause."""
    if case == "missing":
        monkeypatch.setenv("PATH", str(tmp_path / "no-git-here"))
        return "git not found"
    if case == "not starting":
        (tmp_path / "bin").mkdir()
        (tmp_path / "bin" / "git").write_text("#!/no/such/shell\n", encoding="utf-8")
        (tmp_path / "bin" / "git").chmod(0o755)
        monkeypatch.setenv("PATH", str(tmp_path / "bin"))
        return "git could not run: No such file or directory"
    if case == "failing":
        body = "printf 'fatal: dubious \\033[31m ownership\\nsecond line\\n' >&2\nexit 128\n"
        monkeypatch.setenv("PATH", str(fake_git(tmp_path / "bin", body)))
        return "git exited with 128: fatal: dubious \\x1b[31m ownership"
    if case == "hanging":
        pid_file = tmp_path / "spinner.pid"
        body = f'( while :; do :; done ) &\necho $! > "{pid_file}"\nwait\n'
        monkeypatch.setenv("PATH", str(fake_git(tmp_path / "bin", body)))
        monkeypatch.setattr("agent_hub.generator.doctor_tree.GIT_TIMEOUT_SECONDS", 0.5)
        return "git timed out after 0.5 s"
    # An empty .git folder is no repository: git finds the one above, whose top is not the root.
    shutil.rmtree(root / ".git")
    (root / ".git").mkdir()
    return f"git puts this folder in the work tree {root.parent}"


@pytest.mark.usefixtures("alarm")
@pytest.mark.parametrize("case", GIT_CASES)
def test_reports_problem_when_git_missing_or_failing(
    work_tree: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, case: str
) -> None:
    if case == "other top":
        git(["init", "-q"], cwd=work_tree.parent)
    cause = break_git(case, root=work_tree, tmp_path=tmp_path, monkeypatch=monkeypatch)

    tree = read_doctor_tree(work_tree, by_path=("AGENTS.md",), listing=True)

    assert tree.problem == f"could not list the files: {cause}"
    assert tree.listed == ()
    # The fixed paths are still looked at.
    assert tree.entries == {"AGENTS.md": FileEntry(executable=False, content=b"# Agents\n")}
    if case == "hanging":
        spinner = int((tmp_path / "spinner.pid").read_text(encoding="utf-8"))
        assert gone(spinner)


@pytest.mark.parametrize("tree_kind", ["walked", "listed", "git entry"])
def test_reports_problem_when_folder_unreadable(
    work_tree: Path, monkeypatch: pytest.MonkeyPatch, *, tree_kind: str
) -> None:
    if tree_kind == "walked":
        shutil.rmtree(work_tree / ".git")
    write(work_tree, {"hub.lock": "{}\n"})
    refused = ".git" if tree_kind == "git entry" else "docs"
    refuse(refused, call="lstat" if tree_kind == "git entry" else "open", monkeypatch=monkeypatch)

    tree = read_doctor_tree(work_tree, by_path=("hub.lock", "AGENTS.md"), listing=True)

    assert tree.problem == f"could not list the files: {refused}: Permission denied"
    assert tree.listed == ()
    assert tree.paths_read is True
    # Only the listing is lost: the fixed paths are still read.
    assert tree.entries["hub.lock"] == FileEntry(executable=False, content=b"{}\n")
    assert tree.entries["AGENTS.md"] == FileEntry(executable=False, content=b"# Agents\n")


def test_keeps_other_fixed_paths_when_one_unreadable(
    work_tree: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write(work_tree, {"hub.lock": "{}\n", ".claude/settings.json": "{}\n"})
    refuse(".claude", call="open", monkeypatch=monkeypatch)

    tree = read_doctor_tree(work_tree, by_path=(".claude/settings.json", "hub.lock"), listing=False)

    # No listing was asked: the problem says read, never list.
    assert tree.problem == "could not read the files: .claude: Permission denied"
    assert tree.paths_read is False
    assert tree.entries == {"hub.lock": FileEntry(executable=False, content=b"{}\n")}
    assert tree.listed == ()


@pytest.mark.parametrize("sibling", ["a/z.md", "a/.a.md"], ids=["read-after", "read-before"])
def test_keeps_fixed_entry_when_other_path_lists_its_folder(work_tree: Path, sibling: str) -> None:
    # Reading the sibling lists a/ and records its leftover-shaped names unread: never over the
    # fixed path's own read, whichever comes first.
    leftover = "a/.x.hub-tmp-0123abcd"
    write(work_tree, {leftover: "partial\n", sibling: "# Z\n"})

    tree = read_doctor_tree(work_tree, by_path=(leftover, sibling), listing=False)

    assert tree.entries[leftover] == FileEntry(executable=False, content=b"partial\n")
    assert tree.entries[sibling] == FileEntry(executable=False, content=b"# Z\n")
    assert tree.problem is None
    assert tree.paths_read is True


def refuse(name: str, *, call: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Make ``os.<call>`` of any path named ``name`` fail with ``EACCES`` (root reads all)."""
    real = getattr(os, call)

    def refusing(path: str | bytes | Path, *args: object, **kwargs: object) -> object:
        if os.path.basename(os.fsdecode(path)) == name:
            raise PermissionError(errno.EACCES, "Permission denied")
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, call, refusing)


def digest(root: Path) -> dict[str, tuple[int, bytes | str | None]]:
    """Every entry under ``root``: mode and bytes or link target, links never followed."""
    found: dict[str, tuple[int, bytes | str | None]] = {}
    for folder, folders, files in os.walk(root):
        for name in [*folders, *files]:
            path = Path(folder) / name
            content = path.read_bytes() if path.is_file() else None
            if path.is_symlink():
                content = os.readlink(path)
            found[path.relative_to(root).as_posix()] = (path.lstat().st_mode, content)
    return found


WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND


def test_writes_nothing_when_tree_read(work_tree: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    before = digest(work_tree)
    index_time = (work_tree / ".git" / "index").stat().st_mtime_ns
    writes: list[str] = []
    real_open = os.open

    def recording_open(path: str | bytes, flags: int, *args: object, **kwargs: object) -> int:
        # subprocess opens the null device for git's stdin; nothing in the tree is written.
        if flags & WRITE_FLAGS and os.fsdecode(path) != os.devnull:
            writes.append(f"open {os.fsdecode(path)}")
        return real_open(path, flags, *args, **kwargs)

    def recording(call: str) -> object:
        def record(*args: object, **kwargs: object) -> None:
            writes.append(call)

        return record

    monkeypatch.setattr(os, "open", recording_open)
    for call in ("rename", "replace", "unlink", "mkdir"):
        monkeypatch.setattr(os, call, recording(call))

    tree = read_doctor_tree(work_tree, by_path=("hub.lock",), listing=True)

    assert tree.problem is None
    assert tree.listed != ()
    assert writes == []
    assert digest(work_tree) == before
    assert (work_tree / ".git" / "index").stat().st_mtime_ns == index_time
