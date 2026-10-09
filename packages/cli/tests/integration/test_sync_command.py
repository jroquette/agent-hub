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

import hashlib
import json
import os
import shutil
import signal
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli import sync_steps
from agent_hub.cli.main import app
from agent_hub.cli.sync_report import CONFLICT_WAY_OUT
from agent_hub.core.doctor.brain_memory_rule import FIX as MEMORY_FIX
from agent_hub.core.doctor.brain_memory_rule import GITIGNORE, IGNORE_MESSAGE
from agent_hub.core.hub_files.hub_lock import ADOPT_POINTER
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_second_repo
from agent_hub.core.testing.platform_repository_cases import CUSTOM_REPOSITORY

# The conftest's tree digest and in-process sync (tests cannot import a conftest in importlib
# mode).
type TreeDigest = Callable[[Path], dict[str, Any]]
type SyncRunner = Callable[..., Result]
# The conftest's in-process doctor.
type DoctorRunner = Callable[..., Result]
# The conftest's injected I/O error and temp-entry finder.
type FailOnce = Callable[..., None]
type TempEntries = Callable[[Path], list[str]]


class PathRead(NamedTuple):
    """The conftest's record of one path a run looked at (``path_reads``)."""

    call: str
    path: str


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
    # Plan G1: --accept without --adopt is a usage error, decided before anything is read.
    accept = run_sync(tmp_path, "--accept", "x")
    unknown = run_sync(tmp_path, "--nope")

    assert shown.exit_code == 0
    help_text = unstyle(shown.stdout)
    assert "--check" in help_text
    assert "--adopt" in help_text
    assert "--accept" in help_text
    assert "Plan only: write nothing; exit 4 when changes are pending, 3 on a conflict." in (
        " ".join(help_text.split())
    )
    assert accept.exit_code == 2
    assert "Usage:" in accept.stderr
    assert accept.stdout == ""
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


def test_names_custom_source_when_pin_differs_and_hub_sets_repository(
    tmp_path: Path, demo_document: dict[str, Any], run_sync: SyncRunner
) -> None:
    demo_document["platform"] = {"version": "0.0.1", "repository": CUSTOM_REPOSITORY}
    root = a_hub(tmp_path, demo_document, lock=None)

    lines = assert_load_failed(run_sync(root))

    assert lines == [
        f"hub.json: platform.version: this hub is pinned to 0.0.1 but this hub command is"
        f" {VERSION}; run the pinned release: uvx --from"
        " git+https://git.acme.test/tools/agent-hub@v0.0.1#subdirectory=packages/agent-hub hub"
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


# AGH-17 AC-17.6: the four module ids; each subset is a module set a hub may select.
MODULE_IDS = ("bench", "cloud", "contract-sync", "marketplace")
MODULE_SETS = [
    tuple(module for bit, module in enumerate(MODULE_IDS) if mask >> bit & 1)
    for mask in range(1 << len(MODULE_IDS))
]


def a_moduled_document(document: dict[str, Any], modules: Iterable[str]) -> dict[str, Any]:
    """``document`` with a second repo and ``modules`` selected (``contract-sync`` api → web)."""
    document["repos"].append(a_second_repo())
    source, target = (repo["dir"] for repo in document["repos"])
    settings: dict[str, dict[str, str]] = {"contract-sync": {"source": source, "target": target}}
    document["modules"] = {module: settings.get(module, {}) for module in modules}
    return document


class TestModules:
    """Spec D5: ``hub sync`` accepts every module set (no module set is refused)."""

    @pytest.mark.parametrize("pinned", ["running", "other"])
    def test_accepts_modules_when_lock_invalid_or_pin_other(
        self,
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
        # Modules pass the load: the lock is read next, and its problem is what fails.
        root = a_hub(tmp_path, demo_document, lock=b"[")
        before = tree_digest(root)

        lines = assert_load_failed(run_sync(root))

        if pinned == "running":
            assert lines[0].startswith("hub.lock: $: not valid JSON"), lines
            assert lines[-1] == LOCK_WAY_OUT_LINE
            assert not [line for line in lines if "modules" in line]
        else:
            # The pin is checked first: a pin mismatch still reports the pin, alone.
            assert len(lines) == 1
            assert PINNED_COMMAND in lines[0]
            assert "modules" not in lines[0]
        assert tree_digest(root) == before

    @pytest.mark.parametrize(
        "modules", MODULE_SETS, ids=["-".join(s) or "none" for s in MODULE_SETS]
    )
    def test_accepts_every_module_set_when_synced(
        self,
        tmp_path: Path,
        demo_document: dict[str, Any],
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        modules: tuple[str, ...],
    ) -> None:
        config = tmp_path / "hub.json"
        config.write_bytes(dump_json(a_moduled_document(demo_document, modules)))
        root = tmp_path / "hub"
        created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
        assert created.exit_code == 0, created.stderr
        before = tree_digest(root)

        synced = run_sync(root)

        assert synced.exit_code == 0, synced.stderr
        assert synced.stderr == ""
        assert synced.stdout == "up to date\n"
        assert tree_digest(root) == before
        lock = json.loads((root / "hub.lock").read_bytes())
        assert lock["modules"] == sorted(modules)
        for module in modules:
            assert f"mk/{module}.mk" in lock["files"], module

    # AC-17.12 (ADR 0009): a module added or removed after the first sync.

    def test_reports_pending_when_module_added_and_checked(
        self, demo_hub: Path, run_sync: SyncRunner, *, tree_digest: TreeDigest
    ) -> None:
        select_modules(demo_hub, {"bench": {}})
        before = tree_digest(demo_hub)

        checked = run_sync(demo_hub, "--check")

        assert (checked.exit_code, checked.stderr) == (4, ""), checked.output
        # AGENTS.md names the selected modules' files, so it changes with them.
        assert checked.stdout.splitlines() == [
            "would update AGENTS.md",
            "would update Makefile",
            "would create mk/bench.mk",
            "would update hub.lock",
        ]
        assert tree_digest(demo_hub) == before

    def test_creates_module_files_when_module_added(
        self, demo_hub: Path, run_sync: SyncRunner
    ) -> None:
        select_modules(demo_hub, {"bench": {}})

        synced = run_sync(demo_hub)

        assert (synced.exit_code, synced.stderr) == (0, ""), synced.output
        assert synced.stdout.splitlines() == [
            "updated AGENTS.md",
            "updated Makefile",
            "created mk/bench.mk",
            "updated hub.lock",
        ]
        assert b"include mk/bench.mk\n" in (demo_hub / "Makefile").read_bytes()
        lock = json.loads((demo_hub / "hub.lock").read_bytes())
        assert lock["modules"] == ["bench"]
        assert lock["files"]["mk/bench.mk"]["ownership"] == "managed"
        assert run_sync(demo_hub, "--check").stdout == "up to date\n"

    def test_deletes_unmodified_files_when_modules_removed(
        self,
        demo_hub: Path,
        demo_hub_template: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
    ) -> None:
        select_modules(demo_hub, {"bench": {}, "marketplace": {}})
        assert run_sync(demo_hub).exit_code == 0
        select_modules(demo_hub, {})

        synced = run_sync(demo_hub)

        assert (synced.exit_code, synced.stderr) == (0, ""), synced.output
        assert synced.stdout.splitlines() == [
            f"deleted {MARKETPLACE}",
            "updated AGENTS.md",
            "updated Makefile",
            "deleted mk/bench.mk",
            "deleted mk/marketplace.mk",
            "updated hub.lock",
        ]
        # The seeded sibling is the project's: it stays on disk and leaves the lock.
        assert (demo_hub / MARKETPLACE_SIBLING).read_bytes() == b"{}\n"
        lock = json.loads((demo_hub / "hub.lock").read_bytes())
        assert lock["modules"] == []
        assert not [path for path in lock["files"] if path.startswith((".claude-plugin/", "mk/"))]
        assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
        # Besides ``modules: {}`` in ``hub.json``, the tree is a fresh one plus the sibling (and
        # the folders a deleted path leaves, empty).
        after = tree_digest(demo_hub)
        fresh = tree_digest(demo_hub_template)
        assert {
            path for path in after.keys() | fresh.keys() if after.get(path) != fresh.get(path)
        } == {
            ".claude-plugin",
            MARKETPLACE_SIBLING,
            "hub.json",
            "mk",
        }

    def test_conflicts_when_removed_module_file_edited(
        self, demo_hub: Path, run_sync: SyncRunner, *, tree_digest: TreeDigest
    ) -> None:
        select_modules(demo_hub, {"bench": {}})
        assert run_sync(demo_hub).exit_code == 0
        with (demo_hub / "mk" / "bench.mk").open("ab") as makefile:
            makefile.write(b"local: ; @true\n")
        select_modules(demo_hub, {})
        before = tree_digest(demo_hub)

        synced = run_sync(demo_hub)

        assert (synced.exit_code, synced.stdout) == (3, ""), synced.output
        assert "mk/bench.mk" in synced.stderr
        assert tree_digest(demo_hub) == before


def select_modules(root: Path, modules: dict[str, Any]) -> None:
    """Rewrite the hub's ``hub.json`` with ``modules`` selected."""
    document = json.loads((root / "hub.json").read_bytes())
    document["modules"] = modules
    (root / "hub.json").write_bytes(dump_json(document))


MARKETPLACE = ".claude-plugin/marketplace.json"
MARKETPLACE_SIBLING = ".claude-plugin/marketplace.project.json"
OWNED = "refused: the managed marketplace.json owns this"
TWICE = "refused: the sibling lists this plugin name more than once"
UNNAMED = "refused: a plugin entry is an object with a string name"


def a_pin(name: str) -> dict[str, Any]:
    return {"name": name, "source": {"source": "url", "url": f"https://example.com/{name}.git"}}


def a_marketplace_hub(tmp_path: Path, document: dict[str, Any]) -> Path:
    """A hub ``hub init`` wrote with module ``marketplace`` selected (and a second repo)."""
    config = tmp_path / "hub.json"
    config.write_bytes(dump_json(a_moduled_document(document, ["marketplace"])))
    root = tmp_path / "hub"
    created = CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(root)])
    assert created.exit_code == 0, created.stderr
    return root


def plugin_names(root: Path) -> list[str]:
    value = json.loads((root / MARKETPLACE).read_bytes())
    return [plugin["name"] for plugin in value["plugins"]]


class TestMarketplace:
    """AGH-17 D4 (AC-17.11): the seeded sibling merges after the managed marketplace."""

    def test_orders_plugins_managed_first_when_sibling_adds_two(
        self, tmp_path: Path, demo_document: dict[str, Any], run_sync: SyncRunner
    ) -> None:
        root = a_marketplace_hub(tmp_path, demo_document)
        sibling = dump_json({"plugins": [a_pin("superpowers"), a_pin("aaa")]})
        (root / MARKETPLACE_SIBLING).write_bytes(sibling)

        synced = run_sync(root)

        assert (synced.exit_code, synced.stderr) == (0, ""), synced.output
        assert synced.stdout.splitlines() == [f"updated {MARKETPLACE}", "updated hub.lock"]
        # Q-1: no sort; the managed entries first, then the sibling's in its own order.
        assert plugin_names(root) == ["hub-workflow", "demo", "superpowers", "aaa"]
        assert (root / MARKETPLACE_SIBLING).read_bytes() == sibling
        assert run_sync(root).stdout == "up to date\n"

    @pytest.mark.parametrize(
        ("sibling", "line"),
        [
            ({"plugins": [a_pin("hub-workflow")]}, f"plugins[0].name: {OWNED} entry"),
            ({"plugins": [a_pin("aaa"), a_pin("demo")]}, f"plugins[1].name: {OWNED} entry"),
            ({"name": "other"}, f"name: {OWNED} key"),
            ({"owner": {"name": "Someone Else"}}, f"owner: {OWNED} key"),
            (
                {"plugins": [{"name": "x", "source": "./a"}, {"name": "x", "source": "./b"}]},
                f"plugins[1].name: {TWICE}",
            ),
            ({"plugins": ["superpowers"]}, f"plugins[0]: {UNNAMED}"),
            ({"plugins": [{"source": "./a"}]}, f"plugins[0]: {UNNAMED}"),
            ({"plugins": [{"name": 1, "source": "./a"}]}, f"plugins[0]: {UNNAMED}"),
        ],
        ids=[
            "base-plugin",
            "project-plugin",
            "name",
            "owner",
            "repeated-name",
            "not-object",
            "missing-name",
            "number-name",
        ],
    )
    def test_writes_nothing_when_sibling_takes_managed_name(
        self,
        tmp_path: Path,
        demo_document: dict[str, Any],
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        sibling: dict[str, Any],
        line: str,
    ) -> None:
        root = a_marketplace_hub(tmp_path, demo_document)
        (root / MARKETPLACE_SIBLING).write_bytes(dump_json(sibling))
        before = tree_digest(root)

        synced = run_sync(root)

        assert synced.exit_code == 1, synced.output
        assert synced.stdout == ""
        assert synced.stderr.splitlines() == [f"{MARKETPLACE_SIBLING}: {line}"]
        assert tree_digest(root) == before

    def test_creates_sibling_once_when_synced_twice(
        self, demo_hub: Path, run_sync: SyncRunner
    ) -> None:
        document = json.loads((demo_hub / "hub.json").read_bytes())
        document["modules"] = {"marketplace": {}}
        (demo_hub / "hub.json").write_bytes(dump_json(document))

        first = run_sync(demo_hub)

        assert (first.exit_code, first.stderr) == (0, ""), first.output
        assert f"created {MARKETPLACE_SIBLING}" in first.stdout.splitlines()
        assert f"created {MARKETPLACE}" in first.stdout.splitlines()
        assert (demo_hub / MARKETPLACE_SIBLING).read_bytes() == b"{}\n"
        assert plugin_names(demo_hub) == ["hub-workflow", "demo"]
        # The project's pins stay: the next sync merges the sibling and never writes it again.
        sibling = dump_json({"plugins": [a_pin("superpowers")]})
        (demo_hub / MARKETPLACE_SIBLING).write_bytes(sibling)

        second = run_sync(demo_hub)

        assert (second.exit_code, second.stderr) == (0, ""), second.output
        assert MARKETPLACE_SIBLING not in second.stdout
        assert (demo_hub / MARKETPLACE_SIBLING).read_bytes() == sibling
        assert plugin_names(demo_hub) == ["hub-workflow", "demo", "superpowers"]
        assert run_sync(demo_hub).stdout == "up to date\n"


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


LOCAL_IDENTITY = (
    '{"project": {"branch_prefix": "me/", "author_name": "Jane Roe",'
    ' "author_email": "jane.doe@example.com"}, "tracker": {"transport": "mcp"}}\n'
)
# A developer's hub.local.json as the test plants it: valid, malformed or a FIFO.
LOCAL_FILES: dict[str, Callable[[Path], None]] = {
    "valid": lambda path: path.write_text(LOCAL_IDENTITY, encoding="utf-8"),
    "malformed": lambda path: path.write_text("[", encoding="utf-8"),
    "fifo": os.mkfifo,
}


@pytest.mark.usefixtures("alarm")
@pytest.mark.parametrize("local", list(LOCAL_FILES))
def test_renders_same_bytes_when_local_file_and_git_identity_present(
    tmp_path: Path,
    demo_hub_template: Path,
    run_sync: SyncRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    tree_digest: TreeDigest,
    path_reads: list[PathRead],
    local: str,
) -> None:
    # The render reads hub.json only: never hub.local.json or git (AC-65.6).
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    plain = tmp_path / "plain"
    shutil.copytree(demo_hub_template, plain, symlinks=True)
    make_pending(plain, _restored)
    assert run_sync(plain).exit_code == 0
    expected = tree_digest(plain)
    hub = tmp_path / "hub"
    shutil.copytree(demo_hub_template, hub, symlinks=True)
    make_pending(hub, _restored)
    LOCAL_FILES[local](hub / "hub.local.json")
    gitconfig = tmp_path / "gitconfig"
    gitconfig.write_text("[user]\n\tname = Jane Roe\n\temail = jane.doe@example.com\n")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(gitconfig))
    planted = tree_digest(hub / "hub.local.json")
    path_reads.clear()

    result = run_sync(hub)

    reads = list(path_reads)
    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout == "restored AGENTS.md\n"
    assert tree_digest(hub / "hub.local.json") == planted
    after = tree_digest(hub)
    del after["hub.local.json"]
    assert after == expected
    assert [read for read in reads if read.path.endswith("hub.local.json")] == []
    assert [read for read in reads if read.call == "Popen"] == []


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


APP_REPO_AGENTS = "docs/app-repo-AGENTS.md"


def test_creates_app_repo_agents_when_sync_finds_no_entry(
    demo_hub: Path, demo_hub_template: Path, run_sync: SyncRunner
) -> None:
    # A hub from before the starter existed: no file and no lock entry.
    (demo_hub / APP_REPO_AGENTS).unlink()
    lock: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    del lock["files"][APP_REPO_AGENTS]
    (demo_hub / "hub.lock").write_bytes(dump_json(lock))

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (
        0,
        f"created {APP_REPO_AGENTS}\nupdated hub.lock\n",
        "",
    )
    assert (demo_hub / APP_REPO_AGENTS).read_bytes() == (
        demo_hub_template / APP_REPO_AGENTS
    ).read_bytes()
    after: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    assert after["files"][APP_REPO_AGENTS] == {"ownership": "seeded"}


ONBOARD_SKILL = "plugin/hub-workflow/skills/onboard/SKILL.md"
ONBOARD_REFERENCE = "plugin/hub-workflow/skills/onboard/reference.md"
ONBOARD_LINK = ".claude/skills/onboard"


@pytest.mark.parametrize("older", ["placeholder", "absent"])
def test_creates_onboard_skill_when_older_hub_synced(
    demo_hub: Path, demo_hub_template: Path, run_sync: SyncRunner, *, older: str
) -> None:
    # AGH-108: a hub from a release with the placeholder skill (no reference.md yet), or from
    # before the skill.
    lock: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    if older == "placeholder":
        (demo_hub / ONBOARD_SKILL).write_bytes(OLDER_RENDER)
        lock["files"][ONBOARD_SKILL]["sha256"] = hashlib.sha256(OLDER_RENDER).hexdigest()
        (demo_hub / ONBOARD_REFERENCE).unlink()
        del lock["files"][ONBOARD_REFERENCE]
        expected = [f"updated {ONBOARD_SKILL}", f"created {ONBOARD_REFERENCE}"]
    else:
        (demo_hub / ONBOARD_LINK).unlink()
        shutil.rmtree(demo_hub / os.path.dirname(ONBOARD_SKILL))
        for path in (ONBOARD_LINK, ONBOARD_SKILL, ONBOARD_REFERENCE):
            del lock["files"][path]
        expected = [
            f"created {ONBOARD_LINK}",
            f"created {ONBOARD_SKILL}",
            f"created {ONBOARD_REFERENCE}",
        ]
    (demo_hub / "hub.lock").write_bytes(dump_json(lock))

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (
        0,
        "".join(f"{line}\n" for line in [*expected, "updated hub.lock"]),
        "",
    )
    for path in (ONBOARD_SKILL, ONBOARD_REFERENCE):
        assert (demo_hub / path).read_bytes() == (demo_hub_template / path).read_bytes(), path
    assert os.readlink(demo_hub / ONBOARD_LINK) == "../../plugin/hub-workflow/skills/onboard"
    assert (demo_hub / "hub.lock").read_bytes() == (demo_hub_template / "hub.lock").read_bytes()
    again = run_sync(demo_hub)
    assert (again.exit_code, again.stdout, again.stderr) == (0, "up to date\n", "")


@pytest.mark.parametrize("change", ["edited", "deleted"])
def test_keeps_app_repo_agents_when_sync_runs_after_edit_or_delete(
    demo_hub: Path, run_sync: SyncRunner, change: str, *, tree_digest: TreeDigest
) -> None:
    starter = demo_hub / APP_REPO_AGENTS
    if change == "edited":
        starter.write_bytes(b"# Ours\n")
    else:
        starter.unlink()
    before = tree_digest(demo_hub)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
    assert tree_digest(demo_hub) == before
    if change == "edited":
        assert starter.read_bytes() == b"# Ours\n"
    else:
        assert not starter.exists()


LEARN_SKILL = "plugin/hub-workflow/skills/learn/SKILL.md"
MEMORY_GITKEEP = "brain/auto/workspace/.gitkeep"
# Deepest first, as an older render lacks both.
MEMORY_FOLDERS = ("brain/auto/workspace", "brain/auto")
# The two lines a fresh init's .gitignore ends with (AGH-48); an older render lacks them.
MEMORY_IGNORE_LINES = b"brain/auto/workspace/*\n!brain/auto/workspace/.gitkeep\n"
MEMORY_IGNORE_WARNING = f"warning brain.memory {GITIGNORE}: {IGNORE_MESSAGE} Fix: {MEMORY_FIX}"


def test_creates_personal_memory_folder_when_sync_runs_on_older_hub(
    demo_hub: Path, demo_hub_template: Path, run_sync: SyncRunner, *, run_doctor: DoctorRunner
) -> None:
    # A hub from the release before personal memory (AC-48.14): older AGENTS.md and learn
    # skill, no seeded .gitkeep, its folders or lock entry, a .gitignore without the two lines.
    lock: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    for managed in ["AGENTS.md", LEARN_SKILL]:
        (demo_hub / managed).write_bytes(OLDER_RENDER)
        lock["files"][managed]["sha256"] = hashlib.sha256(OLDER_RENDER).hexdigest()
    (demo_hub / MEMORY_GITKEEP).unlink()
    # Nor the folders: rmdir, so a file the render ever adds there fails here loudly.
    for folder in MEMORY_FOLDERS:
        (demo_hub / folder).rmdir()
    del lock["files"][MEMORY_GITKEEP]
    (demo_hub / "hub.lock").write_bytes(dump_json(lock))
    gitignore = demo_hub / GITIGNORE
    content = gitignore.read_bytes()
    assert content.endswith(MEMORY_IGNORE_LINES)
    older_gitignore = content.removesuffix(MEMORY_IGNORE_LINES)
    gitignore.write_bytes(older_gitignore)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "updated AGENTS.md",
        f"created {MEMORY_GITKEEP}",
        f"updated {LEARN_SKILL}",
        "updated hub.lock",
    ]
    assert gitignore.read_bytes() == older_gitignore
    assert [(demo_hub / folder).is_dir() for folder in MEMORY_FOLDERS] == [True, True]
    for rendered in ["AGENTS.md", MEMORY_GITKEEP, LEARN_SKILL]:
        assert (demo_hub / rendered).read_bytes() == (demo_hub_template / rendered).read_bytes()
    after: dict[str, Any] = json.loads((demo_hub / "hub.lock").read_bytes())
    assert after["files"][MEMORY_GITKEEP] == {"ownership": "seeded"}
    # demo_hub has no demo-api checkout, so the doctor also reports it (plan E12).
    lines = unstyle(run_doctor(demo_hub).stdout).splitlines()
    assert [line for line in lines if " brain.memory " in line] == [MEMORY_IGNORE_WARNING]
    assert not [line for line in lines if "instructions.refs" in line]


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
        fail_once: FailOnce,
        temp_entries: TempEntries,
        call: str,
        name: str,
        path: str,
    ) -> None:
        # One delete, four file writes (CLAUDE.md is the second), one link, then hub.lock.
        # Makefile is updated from an older lock hash: once written it differs from its lock
        # entry until hub.lock is, so the stops after it (first-link, hub-lock) pin E5.
        for make in [_deleted, _restored, _created, _updated, _restored_hook, _restored_link]:
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
    assert hub_json_flags
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
    real_apply = sync_steps.apply_sync
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

    monkeypatch.setattr(sync_steps, "apply_sync", plant_then_apply)

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr.splitlines() == [f"{path}: symlinked ancestor plugin/hub-workflow/skills"]
    assert path in planned[0]
    [(copy, copy_before)] = outside
    assert tree_digest(copy) == copy_before
    assert (demo_hub / "hub.lock").read_bytes() == lock
