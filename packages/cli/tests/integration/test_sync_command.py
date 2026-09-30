"""``hub sync``: its command surface and the load order of ``hub.json`` and ``hub.lock``.

Each load failure exits 1 before anything is written. Those cases copy only ``hub.json`` and
``hub.lock`` into an empty folder (plan O2): the load steps read nothing else. ``--check`` cases
run on a copy of the ``DEMO`` hub and compare their lines with those of the real run.

The other cases also run on a copy of the ``DEMO`` hub: conflicts (a cause line, a symlinked
ancestor, a link resolving outside) that write nothing, pending changes applied in one run,
seeded paths left alone, and unknown entries that are never opened, listed or changed. Then an
apply stopped by an injected I/O error and resumed, its call order (``hub.lock`` last), and a
link planted between the plan and the apply.
"""

import errno
import hashlib
import json
import os
import shutil
import signal
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import sync_command
from agent_hub.cli.main import app
from agent_hub.cli.sync_report import CONFLICT_WAY_OUT
from agent_hub.core.hub_files.hub_lock import ADOPT_POINTER
from agent_hub.core.hub_files.tree_snapshot import is_leftover_name
from agent_hub.core.json_form import dump_json

# The conftest's tree digest and in-process sync (tests cannot import a conftest in importlib
# mode).
type TreeDigest = Callable[[Path], dict[str, Any]]
type SyncRunner = Callable[..., Result]
VERSION = version("agent-hub-cli")
PINNED_COMMAND = (
    "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
    "#subdirectory=packages/agent-hub hub"
)
LOCK_WAY_OUT_LINE = "hub.lock: restore it from git, or run hub sync --adopt"
FIFO_ALARM_SECONDS = 5
SHA256_OF_EMPTY = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"


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


@pytest.fixture
def demo_lock(demo_hub_template: Path) -> dict[str, Any]:
    """The ``DEMO`` hub's ``hub.lock`` as a JSON value, which the test may change."""
    value: dict[str, Any] = json.loads((demo_hub_template / "hub.lock").read_bytes())
    return value


def a_hub(tmp_path: Path, document: dict[str, Any], *, lock: bytes | None) -> Path:
    """A folder holding only ``hub.json`` (``document``) and ``hub.lock`` (``lock``, if any)."""
    root = tmp_path / "hub"
    root.mkdir()
    (root / "hub.json").write_bytes(dump_json(document))
    if lock is not None:
        (root / "hub.lock").write_bytes(lock)
    return root


def assert_load_failed(result: Result) -> list[str]:
    """Exit 1 with nothing on stdout; the stderr lines."""
    assert result.exit_code == 1, result.output
    # An exit, not an exception the runner caught.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.stdout == ""
    return result.stderr.splitlines()


def test_lists_check_option_when_help_requested(
    tmp_path: Path, run_sync: SyncRunner, tree_digest: TreeDigest
) -> None:
    before = tree_digest(tmp_path)

    shown = CliRunner().invoke(app, ["sync", "--help"], env={"COLUMNS": "120"})
    adopt = run_sync(tmp_path, "--adopt")
    unknown = run_sync(tmp_path, "--nope")

    assert shown.exit_code == 0
    help_text = unstyle(shown.stdout)
    assert "--check" in help_text
    assert "--adopt" in help_text
    assert "Plan only: write nothing; exit 4 when changes are pending, 3 on a conflict." in (
        " ".join(help_text.split())
    )
    assert adopt.exit_code == 2
    assert adopt.stderr == "not implemented yet (Phase 1)\n"
    assert adopt.stdout == ""
    assert unknown.exit_code == 2
    assert "Usage:" in unknown.stderr
    assert "not implemented yet" not in unknown.stderr
    assert tree_digest(tmp_path) == before


@pytest.mark.parametrize("case", ["pin-only", "pin-and-schema", "pin-and-lock-absent"])
def test_prints_pinned_command_when_pin_differs(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    case: str,
) -> None:
    demo_document["platform"]["version"] = "0.0.1"
    if case == "pin-and-schema":
        demo_document["schema_version"] = 2
    # An invalid lock: had it been read, its lines would show.
    root = a_hub(tmp_path, demo_document, lock=None if case == "pin-and-lock-absent" else b"[")
    before = tree_digest(root)

    lines = assert_load_failed(run_sync(root))

    assert len(lines) == 1
    assert PINNED_COMMAND in lines[0]
    assert "schema_version" not in lines[0]
    assert "--adopt" not in lines[0]
    assert tree_digest(root) == before


def test_reports_pin_only_when_pin_and_schema_differ(
    tmp_path: Path, demo_document: dict[str, Any], run_sync: SyncRunner
) -> None:
    demo_document["platform"]["version"] = "0.0.1"
    demo_document["schema_version"] = 2
    root = a_hub(tmp_path, demo_document, lock=None)

    lines = assert_load_failed(run_sync(root))

    assert lines == [
        f"hub.json: platform.version: this hub is pinned to 0.0.1 but this hub command is"
        f" {VERSION}; run the pinned release: {PINNED_COMMAND}"
    ]


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ("wrong-schema", "hub.json: schema_version: schema version 2 is not supported"),
        ("model-error", "hub.json: project.name: String should match pattern"),
    ],
    ids=["wrong-schema", "model-error"],
)
def test_reports_config_problems_when_model_invalid(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    case: str,
    expected: str,
) -> None:
    if case == "wrong-schema":
        demo_document["schema_version"] = 2
    else:
        demo_document["project"]["name"] = "Demo"
    root = a_hub(tmp_path, demo_document, lock=b"[")
    before = tree_digest(root)

    lines = assert_load_failed(run_sync(root))

    assert lines[0].startswith(expected), lines
    assert all(line.startswith("hub.json: ") for line in lines)
    assert tree_digest(root) == before


def test_names_hub_json_when_absent(
    tmp_path: Path, run_sync: SyncRunner, tree_digest: TreeDigest
) -> None:
    root = tmp_path / "not-a-hub"
    root.mkdir()
    (root / "hub.lock").write_bytes(b"[")
    before = tree_digest(root)
    path = json.dumps(os.path.join(os.path.realpath(root), "hub.json"))

    lines = assert_load_failed(run_sync(root))

    assert lines == [
        f"hub.json: $: cannot read {path}: No such file or directory",
        "hub.json: run hub sync in the hub folder",
    ]
    assert tree_digest(root) == before


def test_points_to_adopt_when_lock_absent(
    demo_hub: Path, run_sync: SyncRunner, tree_digest: TreeDigest
) -> None:
    (demo_hub / "hub.lock").unlink()
    before = tree_digest(demo_hub)

    lines = assert_load_failed(run_sync(demo_hub))

    assert lines == [ADOPT_POINTER]
    assert "hub sync --adopt" in lines[0]
    assert tree_digest(demo_hub) == before


@pytest.mark.parametrize("pinned", ["running", "other"])
def test_refuses_modules_when_config_selects_them(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    pinned: str,
) -> None:
    demo_document["modules"] = {"cloud": {}, "bench": {}}
    if pinned == "other":
        demo_document["platform"]["version"] = "0.0.1"
    # The modules are refused before the lock is read: an invalid lock prints nothing.
    root = a_hub(tmp_path, demo_document, lock=b"[")
    before = tree_digest(root)

    lines = assert_load_failed(run_sync(root))

    assert len(lines) == 1
    if pinned == "running":
        assert lines == [
            "hub.json: modules: bench, cloud: not supported yet (module templates ship later)"
        ]
    else:
        # The module check runs after the pin: a pin mismatch still reports the pin.
        assert PINNED_COMMAND in lines[0]
        assert "modules" not in lines[0]
    assert tree_digest(root) == before


type LockMaker = Callable[[Path, dict[str, Any]], None]


def _changed_lock(change: Callable[[dict[str, Any]], object]) -> LockMaker:
    """Write the DEMO lock value after ``change``."""

    def make(lock_path: Path, lock: dict[str, Any]) -> None:
        change(lock)
        lock_path.write_bytes(dump_json(lock))

    return make


def _raw(content: bytes) -> LockMaker:
    """Write ``content`` as is."""

    def make(lock_path: Path, _lock: dict[str, Any]) -> None:
        lock_path.write_bytes(content)

    return make


def _link_to_valid_lock(lock_path: Path, lock: dict[str, Any]) -> None:
    valid = lock_path.with_name("valid.lock")
    valid.write_bytes(dump_json(lock))
    lock_path.symlink_to(valid.name)


# Each case: how ``hub.lock`` is made from the DEMO lock value, and the lines before the way out.
MALFORMED_LOCKS: dict[str, tuple[LockMaker, list[str]]] = {
    "invalid-json": (
        _raw(b'{"files": }'),
        ["hub.lock: $: not valid JSON: Expecting value at line 1 column 11"],
    ),
    "not-utf8": (
        _raw(b'{"files": "\xff"}'),
        ["hub.lock: $: not UTF-8 text: byte 11 cannot be decoded"],
    ),
    "array": (_raw(b"[]\n"), ["hub.lock: $: Input should be a valid dictionary"]),
    "unknown-key": (
        _changed_lock(lambda lock: lock.update(extra=1)),
        ["hub.lock: extra: Extra inputs are not permitted"],
    ),
    "lock-version-2": (
        _changed_lock(lambda lock: lock.update(lock_version=2)),
        ["hub.lock: lock_version: Input should be 1"],
    ),
    "managed-without-sha256": (
        _changed_lock(
            lambda lock: lock["files"].update(
                {"a.md": {"ownership": "managed", "executable": False}}
            )
        ),
        ['hub.lock: files["a.md"].sha256: Field required'],
    ),
    "managed-hub-json": (
        _changed_lock(
            lambda lock: lock["files"].update(
                {
                    "hub.json": {
                        "ownership": "managed",
                        "executable": False,
                        "sha256": SHA256_OF_EMPTY,
                    }
                }
            )
        ),
        ['hub.lock: files["hub.json"]: must be seeded: hub.json is the project\'s'],
    ),
    # Never followed or opened: a valid lock behind a link is still refused.
    "symlink-to-valid-lock": (_link_to_valid_lock, ["hub.lock: not a regular file"]),
    "folder": (lambda lock_path, _lock: lock_path.mkdir(), ["hub.lock: not a regular file"]),
    "fifo": (lambda lock_path, _lock: os.mkfifo(lock_path), ["hub.lock: not a regular file"]),
}


@pytest.mark.parametrize(("make", "expected"), MALFORMED_LOCKS.values(), ids=MALFORMED_LOCKS.keys())
@pytest.mark.usefixtures("alarm")
def test_reports_lock_problem_when_lock_malformed(
    tmp_path: Path,
    demo_document: dict[str, Any],
    demo_lock: dict[str, Any],
    *,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
    make: LockMaker,
    expected: list[str],
) -> None:
    root = a_hub(tmp_path, demo_document, lock=None)
    make(root / "hub.lock", demo_lock)
    before = tree_digest(root)
    # Only the sync's own calls count, not the ones that built the folder.
    adapter_calls.clear()

    lines = assert_load_failed(run_sync(root))

    assert lines == [*expected, LOCK_WAY_OUT_LINE]
    assert tree_digest(root) == before
    assert adapter_calls == []


type PendingMaker = Callable[[Path, dict[str, Any]], list[str]]
OLDER_RENDER = b"# rendered by an older release\n"
LEFTOVER = "plugin/hub-workflow/hooks/.guard.py.hub-tmp-0123abcd"


def _restored(root: Path, _lock: dict[str, Any]) -> list[str]:
    (root / "AGENTS.md").unlink()
    return ["restored AGENTS.md"]


def _created(root: Path, lock: dict[str, Any]) -> list[str]:
    (root / "CLAUDE.md").unlink()
    del lock["files"]["CLAUDE.md"]
    return ["created CLAUDE.md", "updated hub.lock"]


def _updated(root: Path, lock: dict[str, Any]) -> list[str]:
    (root / "Makefile").write_bytes(OLDER_RENDER)
    lock["files"]["Makefile"]["sha256"] = hashlib.sha256(OLDER_RENDER).hexdigest()
    return ["updated Makefile", "updated hub.lock"]


def _deleted(root: Path, lock: dict[str, Any]) -> list[str]:
    (root / "old").mkdir()
    (root / "old" / "file.md").write_bytes(OLDER_RENDER)
    lock["files"]["old/file.md"] = {
        "ownership": "managed",
        "executable": False,
        "sha256": hashlib.sha256(OLDER_RENDER).hexdigest(),
    }
    return ["deleted old/file.md", "updated hub.lock"]


def _header(_root: Path, lock: dict[str, Any]) -> list[str]:
    lock["platform_version"] = "0.0.1"
    return ["updated hub.lock"]


def _leftover(root: Path, _lock: dict[str, Any]) -> list[str]:
    (root / LEFTOVER).write_bytes(b"half written\n")
    return ["removed 1 leftover temporary files"]


# Each case makes a DEMO hub pending one way and returns the lines the real run prints.
PENDING_CASES: dict[str, PendingMaker] = {
    "restored": _restored,
    "created": _created,
    "updated": _updated,
    "deleted": _deleted,
    "header-only": _header,
    "leftover-alone": _leftover,
}


def make_pending(root: Path, make: PendingMaker) -> list[str]:
    """Apply ``make`` to the hub at ``root`` and its lock; the real run's lines."""
    lock: dict[str, Any] = json.loads((root / "hub.lock").read_bytes())
    expected = make(root, lock)
    (root / "hub.lock").write_bytes(dump_json(lock))
    return expected


def would(line: str) -> str:
    """A real run's line as ``--check`` prints it."""
    verb, rest = line.split(" ", 1)
    base = {"restored": "restore", "created": "create", "updated": "update"}.get(verb)
    return f"would {base or verb.removesuffix('d')} {rest}"


class TestCheck:
    """``hub sync --check`` writes nothing: exit 0 up to date, 4 pending, 3 on a conflict."""

    def test_prints_up_to_date_when_fresh(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        result = run_sync(demo_hub, "--check")

        assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
        assert adapter_calls == []
        assert tree_digest(demo_hub) == before

    @pytest.mark.parametrize("make", PENDING_CASES.values(), ids=PENDING_CASES.keys())
    def test_exits_four_when_pending(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
        make: PendingMaker,
    ) -> None:
        expected = make_pending(demo_hub, make)
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        checked = run_sync(demo_hub, "--check")

        assert (checked.exit_code, checked.stderr) == (4, ""), checked.output
        assert checked.stdout.splitlines() == [would(line) for line in expected]
        assert adapter_calls == []
        assert tree_digest(demo_hub) == before
        # The real run prints the same lines without ``would``, applies them, and exits 0.
        applied = run_sync(demo_hub)
        assert (applied.exit_code, applied.stderr) == (0, ""), applied.output
        assert applied.stdout.splitlines() == expected
        assert adapter_calls != []
        assert run_sync(demo_hub, "--check").stdout == "up to date\n"
        # The applied hub is a fresh one (a deleted path's folder stays, empty).
        after = tree_digest(demo_hub)
        after.pop("old", None)
        assert after == tree_digest(demo_hub_template)
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()

    def test_prints_only_conflicts_when_conflict_and_pending(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        make_pending(demo_hub, _restored)
        with (demo_hub / "Makefile").open("ab") as makefile:
            makefile.write(b"local: ; @true\n")
        before = tree_digest(demo_hub)
        adapter_calls.clear()

        for args in [("--check",), ()]:
            result = run_sync(demo_hub, *args)

            assert (result.exit_code, result.stdout) == (3, ""), result.output
            lines = result.stderr.splitlines()
            assert lines[:2] == ["--- Makefile (on disk)", "+++ Makefile (render)"]
            assert "-local: ; @true" in lines
            assert lines[-1].startswith("move the change to an extension file")
            assert not [line for line in lines if "AGENTS.md" in line or "would" in line]
        assert adapter_calls == []
        assert tree_digest(demo_hub) == before


def test_applies_pending_changes_when_not_checking(
    demo_hub: Path,
    demo_hub_template: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
) -> None:
    make_pending(demo_hub, _restored)
    make_pending(demo_hub, _leftover)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout == "restored AGENTS.md\nremoved 1 leftover temporary files\n"
    assert tree_digest(demo_hub) == tree_digest(demo_hub_template)


@pytest.mark.parametrize("case", ["bit", "link"])
def test_reports_cause_when_bit_or_link_differs(
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
    case: str,
) -> None:
    if case == "bit":
        guard = demo_hub / "plugin/hub-workflow/hooks/guard.py"
        guard.chmod(guard.stat().st_mode & ~0o111)
        cause = "plugin/hub-workflow/hooks/guard.py: executable bit differs (on disk -x, render +x)"
    else:
        link = demo_hub / ".claude/skills/feature"
        link.unlink()
        link.symlink_to("../../plugin/hub-workflow/skills/kickoff")
        cause = (
            ".claude/skills/feature: link target differs (on disk -> "
            "../../plugin/hub-workflow/skills/kickoff, render -> "
            "../../plugin/hub-workflow/skills/feature)"
        )
    before = tree_digest(demo_hub)
    adapter_calls.clear()

    for args in [(), ("--check",)]:
        result = run_sync(demo_hub, *args)

        assert (result.exit_code, result.stdout) == (3, ""), result.output
        assert result.stderr.splitlines() == [cause, CONFLICT_WAY_OUT]
    assert adapter_calls == []
    assert tree_digest(demo_hub) == before


def _restored_link(root: Path, _lock: dict[str, Any]) -> list[str]:
    (root / ".claude/skills/feature").unlink()
    return ["restored .claude/skills/feature"]


def _restored_hook(root: Path, _lock: dict[str, Any]) -> list[str]:
    (root / "plugin/hub-workflow/hooks/guard.py").unlink()
    return ["restored plugin/hub-workflow/hooks/guard.py"]


class TestPendingChanges:
    """Each AC-14.9 case applied alone: ``TestCheck::test_exits_four_when_pending`` (the real run).

    Here all of them at once: one line per path in path order, not in apply order.
    """

    def test_applies_every_case_when_all_pending_at_once(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
    ) -> None:
        for make in [_restored_link, _created, _updated, _deleted, _header, _restored_hook]:
            make_pending(demo_hub, make)

        result = run_sync(demo_hub)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        # A delete is applied first and a link last, but the lines go by path.
        assert result.stdout.splitlines() == [
            "restored .claude/skills/feature",
            "created CLAUDE.md",
            "updated Makefile",
            "deleted old/file.md",
            "restored plugin/hub-workflow/hooks/guard.py",
            "updated hub.lock",
        ]
        after = tree_digest(demo_hub)
        # The folder of a deleted path stays, empty (spec Q-13).
        assert after.pop("old")[0] == "folder"
        assert not list((demo_hub / "old").iterdir())
        assert after == tree_digest(demo_hub_template)
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
        assert run_sync(demo_hub).stdout == "up to date\n"


def test_keeps_seeded_when_deleted_or_edited(
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
) -> None:
    (demo_hub / "brain/now.md").unlink()
    (demo_hub / "README.md").write_bytes(b"# Our hub\n")
    with (demo_hub / "AGENTS.project.md").open("ab") as rules:
        rules.write(b"- Our own rule.\n")
    before = tree_digest(demo_hub)
    adapter_calls.clear()

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
    assert adapter_calls == []
    assert tree_digest(demo_hub) == before


def test_records_seeded_when_managed_becomes_seeded(
    demo_hub: Path,
    demo_hub_template: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
) -> None:
    lock: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    content = (demo_hub / "Makefile.project").read_bytes()
    lock["files"]["Makefile.project"] = {
        "ownership": "managed",
        "executable": False,
        "sha256": hashlib.sha256(content).hexdigest(),
    }
    (demo_hub / "hub.lock").write_bytes(dump_json(lock))
    before = tree_digest(demo_hub)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (0, "updated hub.lock\n", "")
    after = tree_digest(demo_hub)
    assert after.pop("hub.lock") != before.pop("hub.lock")
    assert after == before
    assert (demo_hub / "Makefile.project").read_bytes() == content
    assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()


def outside_copy(tmp_path: Path, source: Path) -> Path:
    """A copy of ``source`` in a folder outside the hub, links kept as links."""
    outside = tmp_path / "outside" / source.name
    shutil.copytree(source, outside, symlinks=True)
    return outside


def test_exits_conflict_when_ancestor_symlinked(
    tmp_path: Path,
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
) -> None:
    skills = demo_hub / "plugin/hub-workflow/skills"
    outside = outside_copy(tmp_path, skills)
    rendered = sorted(
        path.relative_to(demo_hub).as_posix() for path in skills.rglob("*") if path.is_file()
    )
    shutil.rmtree(skills)
    skills.symlink_to(outside, target_is_directory=True)
    before, outside_before = tree_digest(demo_hub), tree_digest(outside)
    adapter_calls.clear()

    for args in [(), ("--check",)]:
        result = run_sync(demo_hub, *args)

        assert (result.exit_code, result.stdout) == (3, ""), result.output
        lines = result.stderr.splitlines()
        # Every skill file below the link, and every skill link that now resolves through it.
        linked = [f"{path}: symlinked ancestor plugin/hub-workflow/skills" for path in rendered]
        links = [
            f".claude/skills/{name}: resolves outside the hub"
            for name in sorted(os.listdir(demo_hub / ".claude/skills"))
        ]
        assert lines == [*links, *linked, CONFLICT_WAY_OUT]
    assert adapter_calls == []
    assert tree_digest(demo_hub) == before
    assert tree_digest(outside) == outside_before


def test_exits_conflict_when_link_resolves_outside(
    tmp_path: Path,
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
) -> None:
    outside = outside_copy(tmp_path, demo_hub / "plugin/hub-workflow/agents")
    link = demo_hub / ".claude/agents/planner.md"
    link.unlink()
    link.symlink_to(outside / "planner.md")
    before, outside_before = tree_digest(demo_hub), tree_digest(outside)
    adapter_calls.clear()

    for args in [(), ("--check",)]:
        result = run_sync(demo_hub, *args)

        assert (result.exit_code, result.stdout) == (3, ""), result.output
        assert result.stderr.splitlines() == [
            ".claude/agents/planner.md: resolves outside the hub",
            CONFLICT_WAY_OUT,
        ]
    assert adapter_calls == []
    assert tree_digest(demo_hub) == before
    assert tree_digest(outside) == outside_before


# AC-14.13's entries no planned path names, each as a path under the hub.
UNKNOWN_ENTRIES = (
    "notes.txt",
    "brain/pipe",
    "scratch",
    ".claude/skills/mine",
    "scratch2/.x.hub-tmp-0123abcd",
)


@dataclass
class TreeCalls:
    """The names ``os.open`` and ``os.stat`` got, and the folders ``os.scandir`` listed."""

    named: list[str]
    listed: list[tuple[int, int]]


def record_tree_calls(monkeypatch: pytest.MonkeyPatch) -> TreeCalls:
    """Record the reads and opens of the sync (plan erratum E14: root reads a mode-0 folder)."""
    calls = TreeCalls(named=[], listed=[])
    real_open, real_stat, real_scandir = os.open, os.stat, os.scandir

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        calls.named.append(os.fsdecode(path))
        return real_open(path, flags, mode, **kwargs)

    def looked(path: Any, **kwargs: Any) -> os.stat_result:
        if not isinstance(path, int):
            calls.named.append(os.fsdecode(path))
        return real_stat(path, **kwargs)

    def listed(path: Any) -> Any:
        if isinstance(path, int):
            info = os.fstat(path)
            calls.listed.append((info.st_dev, info.st_ino))
        return real_scandir(path)

    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "stat", looked)
    monkeypatch.setattr(os, "scandir", listed)
    return calls


@pytest.mark.usefixtures("alarm")
def test_leaves_unknown_entries_when_syncing(
    demo_hub: Path,
    demo_hub_template: Path,
    run_sync: SyncRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tree_digest: TreeDigest,
) -> None:
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
    make_pending(demo_hub, _restored)
    make_pending(demo_hub, _deleted)
    (demo_hub / "scratch").chmod(0)
    try:
        # ``scratch/secret.md`` is in the digest only when the tests run as root: otherwise
        # ``os.walk`` cannot list the mode-0 folder, and ``scratch`` is compared alone.
        before = {path: tree_digest(demo_hub / path) for path in UNKNOWN_ENTRIES}
        with monkeypatch.context() as patch:
            calls = record_tree_calls(patch)

            result = run_sync(demo_hub)

        after = {path: tree_digest(demo_hub / path) for path in UNKNOWN_ENTRIES}
    finally:
        (demo_hub / "scratch").chmod(0o755)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "restored AGENTS.md",
        "deleted old/file.md",
        "updated hub.lock",
    ]
    assert after == before
    names = {Path(name).name for name in calls.named}
    assert not names & {"notes.txt", "pipe", "scratch", "secret.md", "mine", "scratch2"}
    assert ".x.hub-tmp-0123abcd" not in names
    assert not set(calls.listed) & folders
    unknown = {*UNKNOWN_ENTRIES, "brain/pipe", "scratch/secret.md", "scratch2"}
    fresh = {path: entry for path, entry in tree_digest(demo_hub).items() if path not in unknown}
    fresh.pop("old")
    assert fresh == tree_digest(demo_hub_template)


def _created_link(root: Path, lock: dict[str, Any]) -> list[str]:
    (root / ".claude/skills/feature").unlink()
    del lock["files"][".claude/skills/feature"]
    return ["created .claude/skills/feature"]


def temp_entries(root: Path) -> list[str]:
    """The paths under ``root`` whose name has the temp shape."""
    return [
        (Path(folder) / name).relative_to(root).as_posix()
        for folder, folders, files in os.walk(root)
        for name in [*folders, *files]
        if is_leftover_name(name)
    ]


def fail_once(patch: pytest.MonkeyPatch, *, call: str, name: str) -> None:
    """Make the first ``os.<call>`` (``replace`` or ``unlink``) of ``name`` raise ``EIO``."""
    real = getattr(os, call)
    failed: list[str] = []

    def failing(*args: Any, **kwargs: Any) -> Any:
        destination = os.fsdecode(args[1] if call == "replace" else args[0])
        if destination == name and not failed:
            failed.append(destination)
            raise OSError(errno.EIO, os.strerror(errno.EIO))
        return real(*args, **kwargs)

    patch.setattr(os, call, failing)


# Each failure point (spec AC-14.14): the call that fails, the name it is given, the path shown.
FAILURE_POINTS = {
    "first-delete": ("unlink", "file.md", "old/file.md"),
    "middle-file": ("replace", "CLAUDE.md", "CLAUDE.md"),
    "first-link": ("replace", "feature", ".claude/skills/feature"),
    "hub-lock": ("replace", "hub.lock", "hub.lock"),
}


class TestInterruptedSync:
    """A sync stopped by an I/O error leaves no temp entry, and the next sync finishes it."""

    @pytest.mark.parametrize(
        ("call", "name", "path"), FAILURE_POINTS.values(), ids=FAILURE_POINTS.keys()
    )
    def test_resumes_when_apply_fails(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        monkeypatch: pytest.MonkeyPatch,
        tree_digest: TreeDigest,
        call: str,
        name: str,
        path: str,
    ) -> None:
        # One delete, three file writes (CLAUDE.md is the middle one), one link, then hub.lock.
        for make in [_deleted, _restored, _created, _restored_hook, _restored_link]:
            make_pending(demo_hub, make)
        old_lock = (demo_hub / "hub.lock").read_bytes()

        with monkeypatch.context() as patch:
            fail_once(patch, call=call, name=name)

            stopped = run_sync(demo_hub)

        assert (stopped.exit_code, stopped.stdout) == (1, ""), stopped.output
        assert stopped.stderr.splitlines() == [f"{path}: Input/output error"]
        # Even when its own rename fails, hub.lock keeps the old bytes.
        assert (demo_hub / "hub.lock").read_bytes() == old_lock
        assert temp_entries(demo_hub) == []

        resumed = run_sync(demo_hub)

        # A file written before the error equals its render: clean, not a conflict (E5).
        assert (resumed.exit_code, resumed.stderr) == (0, ""), resumed.output
        # A clean sync's hub (TestPendingChanges): a fresh one plus the emptied ``old/``.
        after = tree_digest(demo_hub)
        assert after.pop("old")[0] == "folder"
        assert not list((demo_hub / "old").iterdir())
        assert after == tree_digest(demo_hub_template)
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
        assert run_sync(demo_hub).stdout == "up to date\n"

    def test_removes_leftovers_when_planted_in_planned_folder(
        self,
        tmp_path: Path,
        demo_hub: Path,
        demo_hub_template: Path,
        *,
        run_sync: SyncRunner,
        tree_digest: TreeDigest,
    ) -> None:
        hooks = demo_hub / "plugin/hub-workflow/hooks"
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "kept.md").write_bytes(b"outside\n")
        (hooks / ".guard.py.hub-tmp-0123abcd").write_bytes(b"half written\n")
        # A leftover link to a file outside the hub: the link goes, never what it points to.
        (hooks / ".hubhooks.py.hub-tmp-4567cdef").symlink_to(outside / "kept.md")
        outside_before = tree_digest(outside)

        result = run_sync(demo_hub)

        assert (result.exit_code, result.stderr) == (0, ""), result.output
        assert result.stdout == "removed 2 leftover temporary files\n"
        assert tree_digest(demo_hub) == tree_digest(demo_hub_template)
        # Never recorded: the lock is the fresh one, not even rewritten.
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
        assert tree_digest(outside) == outside_before


def test_writes_lock_last_when_sync_applies(
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    adapter_calls: list[tuple[str, str]],
) -> None:
    make_pending(demo_hub, _leftover)
    make_pending(demo_hub, _deleted)
    make_pending(demo_hub, _updated)
    make_pending(demo_hub, _created_link)
    lock: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    del lock["files"][".github/workflows/ci.yml"]
    (demo_hub / "hub.lock").write_bytes(dump_json(lock))
    shutil.rmtree(demo_hub / ".github")
    hub_json = (demo_hub / "hub.json").stat()
    real_open = os.open
    hub_json_flags: list[int] = []

    def opened(path: Any, flags: int, mode: int = 0o777, **kwargs: Any) -> int:
        if os.fsdecode(path).rpartition("/")[2] == "hub.json":
            hub_json_flags.append(flags)
        return real_open(path, flags, mode, **kwargs)

    monkeypatch.setattr(os, "open", opened)
    adapter_calls.clear()

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "created .claude/skills/feature",
        "created .github/workflows/ci.yml",
        "updated Makefile",
        "deleted old/file.md",
        "removed 1 leftover temporary files",
        "updated hub.lock",
    ]
    # Leftovers, deletes, folders (parents first), files, links, then hub.lock (spec Q-13).
    assert adapter_calls == [
        ("unlink", LEFTOVER.rpartition("/")[2]),
        ("unlink", "file.md"),
        ("mkdir", ".github"),
        ("mkdir", "workflows"),
        ("replace", "ci.yml"),
        ("replace", "Makefile"),
        ("replace", "feature"),
        ("replace", "hub.lock"),
    ]
    written = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
    assert not [flags for flags in hub_json_flags if flags & written]
    after = (demo_hub / "hub.json").stat()
    assert (after.st_ino, after.st_mtime_ns) == (hub_json.st_ino, hub_json.st_mtime_ns)


def _restored_skill(root: Path, _lock: dict[str, Any]) -> list[str]:
    (root / "plugin/hub-workflow/skills/feature/SKILL.md").unlink()
    return ["restored plugin/hub-workflow/skills/feature/SKILL.md"]


def _deleted_skill(root: Path, lock: dict[str, Any]) -> list[str]:
    (root / "plugin/hub-workflow/skills/old.md").write_bytes(OLDER_RENDER)
    lock["files"]["plugin/hub-workflow/skills/old.md"] = {
        "ownership": "managed",
        "executable": False,
        "sha256": hashlib.sha256(OLDER_RENDER).hexdigest(),
    }
    return ["deleted plugin/hub-workflow/skills/old.md", "updated hub.lock"]


@pytest.mark.parametrize(
    ("make", "path"),
    [
        (_restored_skill, "plugin/hub-workflow/skills/feature/SKILL.md"),
        (_deleted_skill, "plugin/hub-workflow/skills/old.md"),
    ],
    ids=["write", "delete"],
)
def test_exits_one_when_adapter_meets_planted_ancestor(
    tmp_path: Path,
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tree_digest: TreeDigest,
    make: PendingMaker,
    path: str,
) -> None:
    make_pending(demo_hub, make)
    lock = (demo_hub / "hub.lock").read_bytes()
    skills = demo_hub / "plugin/hub-workflow/skills"
    real_apply = sync_command.apply_sync
    planned: list[list[str]] = []
    outside: list[tuple[Path, dict[str, Any]]] = []

    def plant_then_apply(root: Path, **plan: Any) -> None:
        # The plan was made with a real folder; a link to an outside copy replaces it now.
        planned.append([*plan["deletes"], *(write.path for write in plan["writes"])])
        copy = outside_copy(tmp_path, skills)
        shutil.rmtree(skills)
        skills.symlink_to(copy, target_is_directory=True)
        outside.append((copy, tree_digest(copy)))
        real_apply(root, **plan)

    monkeypatch.setattr(sync_command, "apply_sync", plant_then_apply)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr.splitlines() == [f"{path}: symlinked ancestor plugin/hub-workflow/skills"]
    assert path in planned[0]
    [(copy, copy_before)] = outside
    assert tree_digest(copy) == copy_before
    assert (demo_hub / "hub.lock").read_bytes() == lock
