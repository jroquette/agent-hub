"""``hub sync --adopt``: its options, its load order and a run with nothing to list (AGH-16).

``--accept`` needs ``--adopt`` (exit 2, nothing read). The load steps are plain sync's, except that
``hub.lock`` may be absent; a broken one exits 1 with adopt's way out. On a ``DEMO`` hub that is
already adopted, adopt is ``up to date``; with its ``hub.lock`` deleted (an unadopted ``DEMO`` hub),
adopt records every path and writes the lock ``hub init`` writes, after which plain sync is
``up to date``. AC-16.4's hub (two managed files differ) exits 3 and keeps both out of the lock;
``--accept`` takes a listed file's template, and with both taken the lock is ``hub init``'s;
``--check`` writes nothing (exit 3 listed, 4 pending); a refused ``--accept`` exits 2 naming each
path, with nothing written. Directory links at ``.claude/skills`` and ``.claude/agents`` are listed
as migrations, their targets never read; accepted, each becomes a folder of the rendered links. A
link resolving outside the hub is a conflict, which ``--accept`` refuses. Adopt leaves unknown
entries alone, never opens ``hub.json`` for writing, runs no ``git`` and writes ``hub.lock`` last;
stopped by an I/O error, it leaves the old lock and no temp entry, and the next adopt ends where an
uninterrupted run does. ``--check`` with ``--accept`` previews the accepted writes.
"""

import json
import os
import shutil
import signal
from collections.abc import Callable, Iterable, Iterator
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.adopt_report import ADOPT_CONFLICT_WAY_OUT, ADOPT_LISTED_WAY_OUT
from agent_hub.cli.main import app
from agent_hub.core.hub_files.plan_adopt import ACCEPT_CONFLICT, ACCEPT_NOT_LISTED
from agent_hub.core.json_form import dump_json

# The conftest's fixtures' types (tests cannot import a conftest in importlib mode).
type TreeDigest = Callable[[Path], dict[str, Any]]
type SyncRunner = Callable[..., Result]
type LockGolden = Callable[..., None]
# The conftest's ``Ac4Hub``: ``make``, ``guard``, ``now``, ``schema`` and ``listing``.
type Ac4Hub = Any
# The conftest's ``fake_git`` factory: a ``FakeGit`` with ``bin_dir`` and ``calls()``.
type FakeGitFactory = Callable[..., Any]
# The conftest's injected I/O error and temp-entry finder.
type FailOnce = Callable[..., None]
type TempEntries = Callable[[Path], list[str]]
ADOPT_LOCK_WAY_OUT_LINE = "hub.lock: restore it from git, or delete it and re-run hub sync --adopt"
SIBLING = ".claude/settings.project.json"
FIFO_ALARM_SECONDS = 5
# A file where a link is rendered: a conflict, which ``--accept`` cannot take.
CLASHING_LINK = ".claude/agents/architect.md"
# AC-16.7: the two link folders, made directory links into their plugin folders, and a project
# skill, which the render links from ``.claude/skills``.
LINKED = (".claude/agents", ".claude/skills")
TARGETS = ("plugin/hub-workflow/agents", "plugin/hub-workflow/skills")
REVIEW = "plugin/demo/skills/review"
REVIEW_LINK = ".claude/skills/review"
# How many links DEMO renders in each folder: 7 base agents; 7 base skills and ``review``.
RENDERED_LINKS = {".claude/agents": 7, ".claude/skills": 8}
# The calls that look at a path without opening or listing it.
LOOKS = frozenset({"lstat", "stat"})
# The conftest's ``ac4.guard`` and ``ac4.schema``, for parameters (fixtures are not set yet).
AC4_GUARD = "plugin/hub-workflow/hooks/guard.py"
AC4_SCHEMA = "hub.schema.json"
# AC-14.13's entries no planned path names, each as a path under the hub.
UNKNOWN_ENTRIES = (
    "notes.txt",
    "brain/pipe",
    "scratch",
    ".claude/skills/mine",
    "scratch2/.x.hub-tmp-0123abcd",
)
# The ``os.open`` flags and builtin ``open`` mode letters that can change a file.
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
WRITE_MODES = frozenset("wax+")
# The verb each change line has with ``--check`` (Q-6).
WOULD = {
    "created": "would create",
    "updated": "would update",
    "recorded": "would record",
    "migrated": "would migrate",
}


@pytest.fixture
def alarm() -> Iterator[None]:
    """Fail a test that blocks (a FIFO opened by mistake) instead of hanging the run."""

    def timed_out(_signal: int, _frame: object) -> None:
        pytest.fail("the command blocked")

    previous = signal.signal(signal.SIGALRM, timed_out)
    signal.alarm(FIFO_ALARM_SECONDS)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)


def unadopted(hub: Path) -> Path:
    """``hub`` with its ``hub.lock`` deleted."""
    (hub / "hub.lock").unlink()
    return hub


def assert_failed(result: Result, *, code: int = 1) -> list[str]:
    """Exit ``code`` with nothing on stdout; the stderr lines."""
    assert result.exit_code == code, result.output
    # An exit, not an exception the runner caught.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    return result.stderr.splitlines()


def lock_files(root: Path) -> dict[str, Any]:
    files: dict[str, Any] = json.loads((root / "hub.lock").read_bytes())["files"]
    return files


class TestUsage:
    """AC-16.1, Q-3: ``--accept PATH`` is listed, repeatable, and only taken with ``--adopt``."""

    def test_lists_accept_when_help_requested(self) -> None:
        shown = CliRunner().invoke(app, ["sync", "--help"], env={"COLUMNS": "120"})

        assert shown.exit_code == 0, shown.output
        help_text = " ".join(unstyle(shown.stdout).split())
        assert "--adopt" in help_text
        assert "--accept PATH" in help_text
        assert "repeatable" in help_text
        assert "not implemented yet" not in shown.output

    @pytest.mark.parametrize("folder", ["demo-hub", "empty-folder"])
    def test_exits_two_when_accept_without_adopt(
        self,
        tmp_path: Path,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        folder: str,
    ) -> None:
        # An empty folder has no hub.json: a run that read anything would exit 1 instead.
        root = demo_hub if folder == "demo-hub" else tmp_path / "empty"
        root.mkdir(exist_ok=True)
        before = tree_digest(root)
        adapter_calls.clear()

        for args in (["--accept", "Makefile"], ["--check", "--accept", "a", "--accept", "b"]):
            lines = assert_failed(run_sync(root, *args), code=2)

            assert any("Usage:" in line for line in lines), lines
            assert "--adopt" in "\n".join(lines)
        assert tree_digest(root) == before
        assert adapter_calls == []


class TestLoad:
    """AC-16.2, Q-5: adopt loads as plain sync does, but without needing ``hub.lock``."""

    def test_runs_without_lock_when_adopt_given(
        self, demo_hub: Path, run_sync: SyncRunner, tree_digest: TreeDigest
    ) -> None:
        before = tree_digest(unadopted(demo_hub))

        result = run_sync(demo_hub, "--adopt")

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        after = tree_digest(demo_hub)
        # Only the lock is new: every other path was already its render.
        assert after.pop("hub.lock")[0] == "file"
        assert after == before

    @pytest.mark.parametrize("case", ["pin", "schema", "model"])
    def test_exits_one_when_pin_schema_or_model_wrong(
        self,
        demo_hub: Path,
        demo_document: dict[str, Any],
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        case: str,
    ) -> None:
        if case == "pin":
            demo_document["platform"]["version"] = "0.0.1"
        elif case == "schema":
            demo_document["schema_version"] = 2
        else:
            demo_document["project"]["name"] = "Demo"
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
        # An invalid lock: had it been read, its lines would show.
        (demo_hub / "hub.lock").write_bytes(b"[")
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        adopted = assert_failed(run_sync(demo_hub, "--adopt"))
        synced = assert_failed(run_sync(demo_hub))

        assert adopted == synced
        assert all(line.startswith("hub.json: ") for line in adopted), adopted
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []

    @pytest.mark.parametrize(
        ("case", "expected"),
        [
            ("invalid-json", "hub.lock: $: not valid JSON: Expecting value at line 1 column 11"),
            ("unknown-key", "hub.lock: extra: Extra inputs are not permitted"),
            ("symlink-to-valid-lock", "hub.lock: not a regular file"),
            ("folder", "hub.lock: not a regular file"),
            ("fifo", "hub.lock: not a regular file"),
        ],
    )
    @pytest.mark.usefixtures("alarm")
    def test_exits_one_naming_way_out_when_lock_malformed_or_not_regular(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        case: str,
        expected: str,
    ) -> None:
        lock_path = demo_hub / "hub.lock"
        valid = lock_path.read_bytes()
        lock_path.unlink()
        if case == "invalid-json":
            lock_path.write_bytes(b'{"files": }')
        elif case == "unknown-key":
            lock_path.write_bytes(dump_json({**json.loads(valid), "extra": 1}))
        elif case == "symlink-to-valid-lock":
            (demo_hub / "valid.lock").write_bytes(valid)
            lock_path.symlink_to("valid.lock")
        elif case == "folder":
            lock_path.mkdir()
        else:
            os.mkfifo(lock_path)
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        lines = assert_failed(run_sync(demo_hub, "--adopt"))

        assert lines == [expected, ADOPT_LOCK_WAY_OUT_LINE]
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []

    def test_writes_nothing_when_sibling_refused(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        (unadopted(demo_hub) / SIBLING).write_bytes(b"{")
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        lines = assert_failed(run_sync(demo_hub, "--adopt"))

        assert lines == [
            f"{SIBLING}: $: not valid JSON: Expecting property name enclosed in double quotes"
            " at line 1 column 2"
        ]
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []


class TestNoOp:
    """AC-16.5: adopting an adopted ``DEMO`` hub does nothing; an unadopted one gets its lock."""

    def test_prints_up_to_date_when_hub_adopted(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        result = run_sync(demo_hub, "--adopt")

        assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []

    def test_writes_init_lock_when_unadopted_demo_adopted(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        lock_golden: LockGolden,
    ) -> None:
        result = run_sync(unadopted(demo_hub), "--adopt")

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        lock = (demo_hub / "hub.lock").read_bytes()
        lock_golden(lock)
        assert lock == (demo_hub_template / "hub.lock").read_bytes()
        # Q-7: every path joined to the lock is named (hub.json is the project's), the lock last.
        recorded = [
            f"recorded {path}" for path in sorted(lock_files(demo_hub)) if path != "hub.json"
        ]
        assert result.stdout.splitlines() == [*recorded, "updated hub.lock"]

    def test_syncs_up_to_date_when_adopted(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        assert run_sync(unadopted(demo_hub), "--adopt").exit_code == 0
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        for args in ((), ("--adopt",), ("--check",), ("--adopt", "--check")):
            result = run_sync(demo_hub, *args)

            assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", ""), args
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []


class TestAccept:
    """AC-16.6, Q-3: ``--accept`` takes only a path this run lists; any other refuses the run."""

    def test_takes_template_when_listed_path_accepted(
        self,
        tmp_path: Path,
        demo_hub: Path,
        *,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        tree_digest: TreeDigest,
        ac4: Ac4Hub,
    ) -> None:
        template = tree_digest(demo_hub_template)
        fresh_lock = (demo_hub_template / "hub.lock").read_bytes()
        before = tree_digest(ac4.make(demo_hub))

        makefile = run_sync(demo_hub, "--adopt", "--accept", "Makefile")

        # The accepted file is rewritten with its render and recorded managed; guard.py waits.
        assert makefile.exit_code == 3, makefile.output
        verbs = {"Makefile": "updated", ac4.schema: "created"}
        joined = sorted(set(lock_files(demo_hub_template)) - {ac4.guard, "hub.json"})
        expected = [f"{verbs.get(path, 'recorded')} {path}" for path in joined]
        assert makefile.stdout.splitlines() == [*expected, "updated hub.lock"]
        assert makefile.stderr.splitlines() == [ac4.listing[1], ADOPT_LISTED_WAY_OUT]
        after = tree_digest(demo_hub)
        assert after["Makefile"] == template["Makefile"]
        assert after[ac4.guard] == before[ac4.guard]
        files = lock_files(demo_hub)
        assert files["Makefile"] == lock_files(demo_hub_template)["Makefile"]
        assert files["Makefile"]["ownership"] == "managed"
        assert ac4.guard not in files

        guard = run_sync(demo_hub, "--adopt", "--accept", ac4.guard)

        assert (guard.exit_code, guard.stderr) == (0, ""), guard.output
        assert guard.stdout.splitlines() == [f"updated {ac4.guard}", "updated hub.lock"]
        assert tree_digest(demo_hub)[ac4.guard] == template[ac4.guard]
        assert (demo_hub / "hub.lock").read_bytes() == fresh_lock
        # Both accepted in one run end the same way.
        both = tmp_path / "both"
        shutil.copytree(demo_hub_template, both, symlinks=True)
        accepts = ("--accept", "Makefile", "--accept", ac4.guard)

        result = run_sync(ac4.make(both), "--adopt", *accepts)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert (both / "hub.lock").read_bytes() == fresh_lock
        adopted = tree_digest(both)
        assert adopted.pop(ac4.now) != template[ac4.now]
        assert adopted == {path: entry for path, entry in template.items() if path != ac4.now}

    def test_refuses_each_path_when_accept_not_listed_or_conflict(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
    ) -> None:
        (ac4.make(demo_hub) / CLASHING_LINK).unlink()
        (demo_hub / CLASHING_LINK).write_bytes(b"# my architect\n")
        refused = [
            # A path not listed (equal to its render), a conflict, one outside the render, and
            # forms of a listed path that are not as listed.
            ("AGENTS.md", ACCEPT_NOT_LISTED),
            (CLASHING_LINK, ACCEPT_CONFLICT),
            ("nowhere.md", ACCEPT_NOT_LISTED),
            ("./Makefile", ACCEPT_NOT_LISTED),
            ("Makefile/", ACCEPT_NOT_LISTED),
        ]
        expected = [f"--accept {path}: {reason}" for path, reason in sorted(refused)]
        accepts = [arg for path, _ in refused for arg in ("--accept", path)]

        def assert_refused() -> None:
            before = tree_digest(demo_hub)
            adapter_calls.clear()
            for check in ((), ("--check",)):
                lines = assert_failed(
                    run_sync(demo_hub, "--adopt", *check, *accepts, "--accept", "Makefile"), code=2
                )

                assert lines == expected
            assert tree_digest(demo_hub) == before
            assert adapter_calls == []

        # With no lock and writes pending (hub.schema.json, hub.lock): none is made.
        assert_refused()
        before = tree_digest(demo_hub)
        first = run_sync(demo_hub, "--adopt")
        # Q-4: the settled paths and the partial lock are saved; the listed and the conflict wait.
        assert first.exit_code == 3, first.output
        assert first.stderr.splitlines()[-1] == ADOPT_CONFLICT_WAY_OUT
        assert {"Makefile", ac4.guard, CLASHING_LINK}.isdisjoint(lock_files(demo_hub))
        after = tree_digest(demo_hub)
        for path in ("Makefile", ac4.guard, CLASHING_LINK):
            assert after[path] == before[path], path
        assert after[ac4.schema] == tree_digest(demo_hub_template)[ac4.schema]
        adapter_calls.clear()
        # A rerun has nothing to write: no ``up to date`` over the same listing, still exit 3.
        again = run_sync(demo_hub, "--adopt")
        assert (again.exit_code, again.stdout, again.stderr) == (3, "", first.stderr)
        assert adapter_calls == []
        # With the partial lock: its bytes stay.
        assert_refused()


def linked_plugin_folders(hub: Path, *, target: str = "plugin/hub-workflow") -> Path:
    """AC-16.7's hub: unadopted, ``.claude/skills`` and ``.claude/agents`` directory links into
    ``target``, and a project skill ``review`` in ``plugin/demo/skills/``."""
    unadopted(hub)
    for folder in LINKED:
        shutil.rmtree(hub / folder)
        (hub / folder).symlink_to(f"../{target}/{folder.rpartition('/')[2]}")
    (hub / REVIEW).mkdir()
    (hub / REVIEW / "SKILL.md").write_bytes(b"---\nname: review\n---\n")
    return hub


def migration_lines(*, target: str = "plugin/hub-workflow") -> list[str]:
    """The listing of both links of ``linked_plugin_folders``."""
    return [
        f"{folder}: migration: directory link -> ../{target}/{folder.rpartition('/')[2]},"
        f" rendered as {count} links"
        for folder, count in RENDERED_LINKS.items()
    ]


def under_links(paths: Iterable[str]) -> list[str]:
    return [path for path in paths if path.startswith(tuple(f"{each}/" for each in LINKED))]


class TestMigration:
    """AC-16.7, E7: a directory link where per-entry links are rendered is listed as a migration;
    accepted, the link (never its target) becomes a folder of the rendered links."""

    def test_lists_both_links_when_directory_links_found(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
    ) -> None:
        counts = migration_lines()
        targets = {each: tree_digest(demo_hub / each) for each in TARGETS}
        before = tree_digest(linked_plugin_folders(demo_hub))

        result = run_sync(demo_hub, "--adopt")

        assert result.exit_code == 3, result.output
        assert result.stderr.splitlines() == [*counts, ADOPT_LISTED_WAY_OUT]
        # Nothing under either link is named, written or recorded; the lock is saved last.
        assert result.stdout.splitlines()[-1] == "updated hub.lock"
        assert under_links(line.partition(" ")[2] for line in result.stdout.splitlines()) == []
        assert under_links(lock_files(demo_hub)) == []
        assert not set(LINKED) & set(lock_files(demo_hub))
        after = tree_digest(demo_hub)
        for path in (*LINKED, REVIEW, f"{REVIEW}/SKILL.md"):
            assert after[path] == before[path], path
        assert {each: tree_digest(demo_hub / each) for each in TARGETS} == targets

    def test_keeps_link_target_unread_when_migration_listed(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        path_reads: list[Any],
    ) -> None:
        # Targets of their own, which nothing else in the hub reaches: a look into either one
        # can only have gone through a link.
        for each in TARGETS:
            shutil.copytree(demo_hub / each, demo_hub / "legacy" / each.rpartition("/")[2])
        linked_plugin_folders(demo_hub, target="legacy")
        legacy = demo_hub / "legacy"
        before = tree_digest(legacy)
        inside = {
            (found.st_dev, found.st_ino)
            for folder, _, _ in os.walk(legacy)
            for found in [os.stat(folder)]
        }
        # ``tmp_path`` (so ``demo_hub``) is already a real path, as the run's current folder is:
        # the recorded absolute paths start with it. A link and its target may be looked at
        # (to tell whether it leaves the hub), never opened or listed, and nothing below either.
        targets = (f"legacy/{each.rpartition('/')[2]}" for each in LINKED)
        tops = tuple(str(demo_hub / each) for each in (*LINKED, *targets))
        below = tuple(f"{top}/" for top in tops)
        path_reads.clear()

        result = run_sync(demo_hub, "--adopt")

        assert result.exit_code == 3, result.output
        assert result.stderr.splitlines() == [
            *migration_lines(target="legacy"),
            ADOPT_LISTED_WAY_OUT,
        ]
        identities = {read.identity for read in path_reads if read.identity is not None}
        assert identities, "the recorder saw no descriptor"
        assert identities.isdisjoint(inside)
        through = [
            read
            for read in path_reads
            if read.path.startswith(below) or (read.path in tops and read.call not in LOOKS)
        ]
        assert through == []
        assert tree_digest(legacy) == before

    def test_replaces_links_with_folders_when_migrations_accepted(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        template = tree_digest(demo_hub_template)
        fresh = lock_files(demo_hub_template)
        targets = {each: tree_digest(demo_hub / each) for each in TARGETS}
        before = tree_digest(linked_plugin_folders(demo_hub))
        accepts = [arg for each in LINKED for arg in ("--accept", each)]

        result = run_sync(demo_hub, "--adopt", *accepts)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        # E15: each link migrated, then every link under it created, in path order.
        created = [*under_links(fresh), REVIEW_LINK]
        recorded = sorted(set(fresh) - set(created) - {"hub.json"})
        expected = sorted(
            [
                *(f"migrated {each}" for each in LINKED),
                *(f"created {path}" for path in created),
                *(f"recorded {path}" for path in recorded),
            ],
            key=lambda line: line.partition(" ")[2],
        )
        assert result.stdout.splitlines() == [*expected, "updated hub.lock"]
        # The links are real folders of managed links, ``review`` included, all recorded; the
        # targets are untouched.
        after = tree_digest(demo_hub)
        assert after.pop(REVIEW_LINK)[::2] == ("link", f"../../{REVIEW}")
        for path in (REVIEW, f"{REVIEW}/SKILL.md"):
            assert after.pop(path) == before[path], path
        # The lock is compared entry by entry below: it holds one more link.
        assert after.pop("hub.lock")[:2] == template.pop("hub.lock")[:2]
        assert after == template
        files = lock_files(demo_hub)
        assert files.pop(REVIEW_LINK) == {"ownership": "managed", "symlink": f"../../{REVIEW}"}
        assert files == fresh
        assert {each: tree_digest(demo_hub / each) for each in TARGETS} == targets
        # Adopted: a rerun has nothing to do (an ``--accept`` now names no listed path).
        adapter_calls.clear()
        rerun = run_sync(demo_hub, "--adopt")
        assert (rerun.exit_code, rerun.stdout, rerun.stderr) == (0, "up to date\n", "")
        assert adapter_calls == []
        again = assert_failed(run_sync(demo_hub, "--adopt", *accepts), code=2)
        assert again == [f"--accept {each}: {ACCEPT_NOT_LISTED}" for each in LINKED]
        assert adapter_calls == []

    def test_refuses_accept_when_link_resolves_outside(
        self,
        tmp_path: Path,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        outside = tmp_path / "outside"
        shutil.copytree(demo_hub / TARGETS[1], outside)
        shutil.rmtree(unadopted(demo_hub) / LINKED[1])
        (demo_hub / LINKED[1]).symlink_to(os.path.relpath(outside, demo_hub / ".claude"))
        before = (tree_digest(demo_hub), tree_digest(outside))
        adapter_calls.clear()

        for check in ((), ("--check",)):
            lines = assert_failed(
                run_sync(demo_hub, "--adopt", *check, "--accept", LINKED[1]), code=2
            )

            assert lines == [f"--accept {LINKED[1]}: {ACCEPT_CONFLICT}"]
        assert (tree_digest(demo_hub), tree_digest(outside)) == before
        assert adapter_calls == []
        # Without ``--accept``: a conflict, never a migration; nothing reaches outside.
        listed = run_sync(demo_hub, "--adopt")
        assert listed.exit_code == 3, listed.output
        assert listed.stderr.splitlines() == [
            f"{LINKED[1]}: resolves outside the hub",
            ADOPT_CONFLICT_WAY_OUT,
        ]
        assert tree_digest(outside) == before[1]
        assert [path for path in lock_files(demo_hub) if path.startswith(f"{LINKED[1]}/")] == []


def would(line: str) -> str:
    """A change line as ``--check`` prints it."""
    verb, _, path = line.partition(" ")
    return f"{WOULD[verb]} {path}"


def basename(read_path: str) -> str:
    return read_path.rpartition("/")[2]


def opens_for_writing(flags: int | str | None) -> bool:
    """Whether an open with ``flags`` (``os.open``'s flags or ``open``'s mode) can change a file."""
    if isinstance(flags, int):
        return bool(flags & WRITE_FLAGS)
    return flags is not None and bool(WRITE_MODES & set(flags))


# Where an interrupted adopt stops (AC-16.8): the hub, the run's ``--accept`` paths, the
# ``os.replace`` that fails (``None``: the first one) and the path its error line names.
INTERRUPTIONS = {
    # No lock yet: the first write is the deleted hub.schema.json.
    "first-write": ("ac4", (), None, AC4_SCHEMA),
    # Both links deleted and their folders made: the first link written under them fails.
    "migration": ("linked", LINKED, None, ".claude/agents/architect.md"),
    # A partial lock from an earlier run; Makefile is written, then the lock's rename fails.
    "hub-lock": ("ac4-partial", ("Makefile",), "hub.lock", "hub.lock"),
}


class TestSafety:
    """AC-16.8: hub-sync's invariants hold for adopt."""

    @pytest.mark.usefixtures("alarm")
    def test_leaves_unknown_entries_when_adopt_runs(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        path_reads: list[Any],
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
    ) -> None:
        (unadopted(demo_hub) / ac4.schema).unlink()
        (demo_hub / "notes.txt").write_bytes(b"our notes\n")
        os.mkfifo(demo_hub / "brain/pipe")
        (demo_hub / "scratch").mkdir()
        (demo_hub / "scratch/secret.md").write_bytes(b"secret\n")
        (demo_hub / ".claude/skills/mine").symlink_to("../../scratch")
        (demo_hub / "scratch2").mkdir()
        (demo_hub / "scratch2/.x.hub-tmp-0123abcd").write_bytes(b"temp-shaped\n")
        folders = {
            (info.st_dev, info.st_ino)
            for info in map(os.stat, [demo_hub / "scratch", demo_hub / "scratch2"])
        }
        (demo_hub / "scratch").chmod(0)
        try:
            # ``scratch/secret.md`` is in the digest only when the tests run as root: otherwise
            # ``os.walk`` cannot list the mode-0 folder, and ``scratch`` is compared alone.
            before = {path: tree_digest(demo_hub / path) for path in UNKNOWN_ENTRIES}
            path_reads.clear()
            adapter_calls.clear()

            result = run_sync(demo_hub, "--adopt")

            reads = list(path_reads)
            after = {path: tree_digest(demo_hub / path) for path in UNKNOWN_ENTRIES}
        finally:
            (demo_hub / "scratch").chmod(0o755)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        lines = result.stdout.splitlines()
        assert f"created {ac4.schema}" in lines
        assert not any(basename(line) in {"notes.txt", "pipe", "mine"} for line in lines)
        assert after == before
        # Never opened, looked at or listed, by name or through a descriptor.
        assert reads, "the recorder saw nothing"
        names = {basename(read.path) for read in reads}
        assert not names & {"notes.txt", "pipe", "scratch", "secret.md", "mine", "scratch2"}
        assert ".x.hub-tmp-0123abcd" not in names
        assert not {read.identity for read in reads} & folders
        # The lock is written last, once, and records none of them.
        assert adapter_calls[-1] == ("replace", "hub.lock")
        assert [call for call in adapter_calls if call[1] == "hub.lock"] == [adapter_calls[-1]]
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
        unknown = {*UNKNOWN_ENTRIES, "scratch/secret.md", "scratch2"}
        fresh = {
            path: entry for path, entry in tree_digest(demo_hub).items() if path not in unknown
        }
        assert fresh == tree_digest(demo_hub_template)

    def test_never_writes_hub_json_when_adopt_runs(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        path_reads: list[Any],
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
    ) -> None:
        hub_json = demo_hub / "hub.json"
        before = (tree_digest(hub_json), hub_json.stat().st_ino)
        ac4.make(demo_hub)
        path_reads.clear()
        adapter_calls.clear()

        # A listing, then a run that writes (an accepted file, a created one, the lock).
        checked = run_sync(demo_hub, "--adopt", "--check")
        written = run_sync(demo_hub, "--adopt", "--accept", "Makefile")

        assert (checked.exit_code, written.exit_code) == (3, 3), written.output
        assert ("replace", "Makefile") in adapter_calls
        opened = [read for read in path_reads if basename(read.path) == "hub.json"]
        # Each run reads it: the recorder saw it.
        assert opened, "hub.json was never read"
        assert [read for read in opened if opens_for_writing(read.flags)] == []
        assert [call for call in adapter_calls if basename(call[1]) == "hub.json"] == []
        assert (tree_digest(hub_json), hub_json.stat().st_ino) == before

    def test_runs_no_git_when_adopt_runs(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        fake_git: FakeGitFactory,
        path_reads: list[Any],
        ac4: Ac4Hub,
    ) -> None:
        git = fake_git({}, toplevel=demo_hub)
        monkeypatch.setenv("PATH", os.pathsep.join([str(git.bin_dir), os.environ["PATH"]]))
        assert shutil.which("git") == str(git.bin_dir / "git")
        ac4.make(demo_hub)

        runs = [
            run_sync(demo_hub, "--adopt", "--check"),
            run_sync(demo_hub, "--adopt", "--accept", "Makefile"),
            run_sync(demo_hub, "--adopt", "--check", "--accept", ac4.guard),
            run_sync(demo_hub, "--adopt", "--accept", ac4.guard),
        ]

        assert [run.exit_code for run in runs] == [3, 3, 4, 0], [run.output for run in runs]
        assert git.calls() == []
        # Nor any process at all: a git named by its absolute path would bypass the fake.
        assert [read for read in path_reads if read.call == "Popen"] == []

    @pytest.mark.parametrize(
        ("hub", "accepts", "failing", "path"), INTERRUPTIONS.values(), ids=INTERRUPTIONS.keys()
    )
    def test_keeps_old_lock_when_first_write_fails(
        self,
        tmp_path: Path,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tree_digest: TreeDigest,
        ac4: Ac4Hub,
        fail_once: FailOnce,
        temp_entries: TempEntries,
        hub: str,
        accepts: tuple[str, ...],
        failing: str | None,
        path: str,
    ) -> None:
        if hub == "linked":
            linked_plugin_folders(demo_hub)
        else:
            ac4.make(demo_hub)
        if hub == "ac4-partial":
            assert run_sync(demo_hub, "--adopt").exit_code == 3
        lock_path = demo_hub / "hub.lock"
        old_lock = lock_path.read_bytes() if lock_path.exists() else None
        args = ["--adopt", *(arg for each in accepts for arg in ("--accept", each))]
        # The same run, never stopped, on a copy: where the resumed hub must end.
        clean = tmp_path / "clean"
        shutil.copytree(demo_hub, clean, symlinks=True)
        uninterrupted = run_sync(clean, *args)
        assert uninterrupted.exit_code in {0, 3}, uninterrupted.output

        with monkeypatch.context() as patch:
            fail_once(patch, call="replace", name=failing)

            stopped = run_sync(demo_hub, *args)

        assert (stopped.exit_code, stopped.stdout) == (1, ""), stopped.output
        assert stopped.stderr.splitlines() == [f"{path}: Input/output error"]
        # The lock's old state: absent, or its prior bytes even when its own rename failed.
        assert (lock_path.read_bytes() if lock_path.exists() else None) == old_lock
        assert temp_entries(demo_hub) == []

        # Plain adopt: a file written before the error equals its render and is recorded.
        resumed = run_sync(demo_hub, "--adopt")

        assert resumed.exit_code == uninterrupted.exit_code, resumed.output
        assert resumed.stderr == uninterrupted.stderr
        assert tree_digest(demo_hub) == tree_digest(clean)
        assert lock_path.read_bytes() == (clean / "hub.lock").read_bytes()


class TestCheck:
    """AC-16.9, Q-6: ``--adopt --check`` writes nothing; exit 3 listed, 4 pending, else 0."""

    def test_writes_nothing_and_exits_three_when_differences_listed(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
    ) -> None:
        before = tree_digest(ac4.make(demo_hub))
        adapter_calls.clear()

        result = run_sync(demo_hub, "--adopt", "--check")

        assert result.exit_code == 3, result.output
        lines = result.stdout.splitlines()
        assert "would create hub.schema.json" in lines
        assert "would record brain/now.md" in lines
        assert lines[-1] == "would update hub.lock"
        assert all(line.startswith("would ") for line in lines)
        assert result.stderr.splitlines() == [*ac4.listing, ADOPT_LISTED_WAY_OUT]
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []

    def test_exits_four_when_unadopted_demo_clean(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        before = tree_digest(unadopted(demo_hub))
        adapter_calls.clear()

        result = run_sync(demo_hub, "--adopt", "--check")

        assert (result.exit_code, result.stderr) == (4, ""), result.output
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []
        # The lines of the real run, each with ``would``.
        adopted = run_sync(demo_hub, "--adopt")
        assert adopted.exit_code == 0, adopted.output
        expected = [
            line.replace("recorded ", "would record ", 1).replace("updated ", "would update ", 1)
            for line in adopted.stdout.splitlines()
        ]
        assert result.stdout.splitlines() == expected

    def test_prints_up_to_date_when_adopted(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
    ) -> None:
        # AC-16.4's hub adopted by taking both templates; the edited seeded file stays as edited.
        accepts = ("--accept", "Makefile", "--accept", ac4.guard)
        assert run_sync(ac4.make(demo_hub), "--adopt", *accepts).exit_code == 0
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        result = run_sync(demo_hub, "--adopt", "--check")

        assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []

    @pytest.mark.parametrize(
        ("hub", "accepts", "code"),
        [
            # guard.py stays listed: exit 3 over the accepted writes.
            ("ac4", ("Makefile",), 3),
            # Nothing left listed: only writes pending, exit 4.
            ("ac4", ("Makefile", AC4_GUARD), 4),
            ("linked", LINKED, 4),
        ],
        ids=["one-of-two-listed", "both-listed", "migrations"],
    )
    def test_previews_accepted_writes_when_accept_given_with_check(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        ac4: Ac4Hub,
        hub: str,
        accepts: tuple[str, ...],
        code: int,
    ) -> None:
        assert (ac4.guard, ac4.schema) == (AC4_GUARD, AC4_SCHEMA)
        if hub == "linked":
            linked_plugin_folders(demo_hub)
        else:
            ac4.make(demo_hub)
        args = ["--adopt", *(arg for each in accepts for arg in ("--accept", each))]
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        preview = run_sync(demo_hub, *args, "--check")

        assert preview.exit_code == code, preview.output
        lines = preview.stdout.splitlines()
        assert all(line.startswith("would ") for line in lines), lines
        # Each accepted path is previewed as written (Q-6): its file updated or its link migrated.
        previewed = {line.split(" ", 2)[2]: line.split(" ", 2)[1] for line in lines}
        assert {path: previewed.get(path) for path in accepts} == {
            path: "migrate" if hub == "linked" else "update" for path in accepts
        }
        assert lines[-1] == "would update hub.lock"
        assert tree_digest(demo_hub) == before
        assert adapter_calls == []
        # The run itself prints the same lines without ``would``, and the same listing.
        applied = run_sync(demo_hub, *args)

        assert applied.exit_code == (3 if code == 3 else 0), applied.output
        assert applied.stderr == preview.stderr
        assert lines == [would(line) for line in applied.stdout.splitlines()]
