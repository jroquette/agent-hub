"""``hub sync --adopt``: its options, its load order and a run with nothing to list (AGH-16).

``--accept`` needs ``--adopt`` (exit 2, nothing read). The load steps are plain sync's, except that
``hub.lock`` may be absent; a broken one exits 1 with adopt's way out. On a ``DEMO`` hub that is
already adopted, adopt is ``up to date``; with its ``hub.lock`` deleted (an unadopted ``DEMO`` hub),
adopt records every path and writes the lock ``hub init`` writes, after which plain sync is
``up to date``. AC-16.4's hub (two managed files differ) exits 3 and keeps both out of the lock;
``--check`` writes nothing (exit 3 listed, 4 pending); a refused ``--accept`` exits 2 naming each
path, with nothing written.
"""

import json
import os
import signal
from collections.abc import Callable, Iterator
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
ADOPT_LOCK_WAY_OUT_LINE = "hub.lock: restore it from git, or delete it and re-run hub sync --adopt"
SIBLING = ".claude/settings.project.json"
FIFO_ALARM_SECONDS = 5
GUARD = "plugin/hub-workflow/hooks/guard.py"
# AC-16.4's listing of the two managed files it changes.
AC4_LISTING = [
    "Makefile: +0 -1 lines",
    f"{GUARD}: +0 -0 lines, executable bit differs (on disk -x, render +x)",
]
# A file where a link is rendered: a conflict, which ``--accept`` cannot take.
CLASHING_LINK = ".claude/agents/architect.md"


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


def ac4_hub(hub: Path) -> Path:
    """AC-16.4's hub: unadopted, ``Makefile`` gained a line, ``guard.py`` lost ``u+x``,
    ``brain/now.md`` edited (seeded: recorded as is) and ``hub.schema.json`` deleted."""
    unadopted(hub)
    with (hub / "Makefile").open("ab") as makefile:
        makefile.write(b"local:\n")
    os.chmod(hub / GUARD, 0o644)
    (hub / "brain/now.md").write_bytes(b"# Now\nShip the adopt.\n")
    (hub / "hub.schema.json").unlink()
    return hub


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

    def test_refuses_each_path_when_accept_not_listed_or_conflict(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        (ac4_hub(demo_hub) / CLASHING_LINK).unlink()
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
        first = run_sync(demo_hub, "--adopt")
        # Q-4: the settled paths and the partial lock are saved; the listed and the conflict wait.
        assert first.exit_code == 3, first.output
        assert first.stderr.splitlines()[-1] == ADOPT_CONFLICT_WAY_OUT
        assert {"Makefile", GUARD, CLASHING_LINK}.isdisjoint(lock_files(demo_hub))
        adapter_calls.clear()
        # A rerun has nothing to write: no ``up to date`` over the same listing, still exit 3.
        again = run_sync(demo_hub, "--adopt")
        assert (again.exit_code, again.stdout, again.stderr) == (3, "", first.stderr)
        assert adapter_calls == []
        # With the partial lock: its bytes stay.
        assert_refused()


class TestCheck:
    """AC-16.9, Q-6: ``--adopt --check`` writes nothing; exit 3 listed, 4 pending, else 0."""

    def test_writes_nothing_and_exits_three_when_differences_listed(
        self,
        demo_hub: Path,
        run_sync: SyncRunner,
        *,
        tree_digest: TreeDigest,
        adapter_calls: list[tuple[str, str]],
    ) -> None:
        before = tree_digest(ac4_hub(demo_hub))
        adapter_calls.clear()

        result = run_sync(demo_hub, "--adopt", "--check")

        assert result.exit_code == 3, result.output
        lines = result.stdout.splitlines()
        assert "would create hub.schema.json" in lines
        assert "would record brain/now.md" in lines
        assert lines[-1] == "would update hub.lock"
        assert all(line.startswith("would ") for line in lines)
        assert result.stderr.splitlines() == [*AC4_LISTING, ADOPT_LISTED_WAY_OUT]
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
