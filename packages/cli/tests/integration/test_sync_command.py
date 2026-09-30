"""``hub sync``: its command surface and the load order of ``hub.json`` and ``hub.lock``.

Each load failure exits 1 before anything is written. Those cases copy only ``hub.json`` and
``hub.lock`` into an empty folder (plan O2): the load steps read nothing else. ``--check`` cases
run on a copy of the ``DEMO`` hub and compare their lines with those of the real run.
"""

import hashlib
import json
import os
import signal
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.hub_files.hub_lock import ADOPT_POINTER
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
