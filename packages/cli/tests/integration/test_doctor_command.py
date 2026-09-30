"""``hub doctor``: its command surface, the root and ``hub.json`` steps, and the exit codes.

A failed config runs only the config rules and reads no other file, so those cases copy only
``hub.json`` into an empty folder (plan O6); the others run on a copy of the ``DEMO`` hub. On
this release no rule reads a listing, so a run starts no git (plan E21 e).
"""

import errno
import json
import os
import shutil
import signal
import subprocess
from collections.abc import Callable, Iterator
from importlib.metadata import version
from pathlib import Path
from typing import Any, NamedTuple

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.json_form import dump_json

# The conftest's in-process doctor run and its path recorder (tests cannot import a conftest in
# importlib mode).
type DoctorRunner = Callable[..., Result]


class PathRead(NamedTuple):
    call: str
    path: str


VERSION = version("agent-hub-cli")
PINNED_COMMAND = (
    "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
    "#subdirectory=packages/agent-hub hub"
)
SCHEMA_FIX = "Fix: fix hub.json (docs/design/project-config.md)"
CLEAN = "0 errors, 0 warnings, 0 infos"
ONE_ERROR = "1 error, 0 warnings, 0 infos"
NOT_A_HUB = (
    ": not a hub: no hub.json in this folder (hub doctor runs in the hub folder, never a parent)"
)
FIFO_ALARM_SECONDS = 5
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"


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


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout.

    Typer draws the error in a box whose width, colors and borders follow the terminal (CI sets
    ``FORCE_TERMINAL``), so the box is stripped and only the message line is pinned.
    """
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "not a hub" not in shown
    assert "Usage: hub doctor" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if text == message] == [message], shown
    assert [text for text in texts if message in text] == [message], shown


def config_only_hub(tmp_path: Path, content: bytes) -> Path:
    """A folder holding only ``hub.json`` with ``content``."""
    root = tmp_path / "hub"
    root.mkdir()
    (root / "hub.json").write_bytes(content)
    return root


def lines_of(result: Result, *, exit_code: int) -> list[str]:
    """The stdout lines of a run that exited ``exit_code`` with nothing on stderr."""
    assert result.exit_code == exit_code, result.output
    # An exit, not an exception the runner caught.
    assert result.exception is None or isinstance(result.exception, SystemExit)
    assert result.stderr == ""
    return result.stdout.splitlines()


def schema_line(message: str) -> str:
    return f"error config.schema hub.json: {message} {SCHEMA_FIX}"


def reads_in(reads: list[PathRead], folder: Path) -> set[str]:
    """The paths read inside ``folder`` (itself included), and every read relative to a folder."""
    # Taken before ``realpath``, whose own looks the recorder would add.
    recorded = list(reads)
    real = os.path.realpath(folder)
    return {
        read.path
        for read in recorded
        if read.path.startswith("<fd") or read.path == real or read.path.startswith(real + os.sep)
    }


def ancestors(folder: str, *, up_to: Path) -> set[str]:
    """``folder`` and each folder above it, up to and including ``up_to`` (real paths)."""
    top = os.path.realpath(up_to)
    found = {top}
    while folder != top:
        found.add(folder)
        folder = os.path.dirname(folder)
    return found


def commit_all(root: Path) -> None:
    """Make ``root`` a git work tree with every file committed, with a hermetic git."""
    git = shutil.which("git")
    assert git is not None
    env = {"HOME": str(root.parent), "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}
    author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    for args in (
        ["init", "-q"],
        ["add", "-A"],
        [*author, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
    ):
        subprocess.run([git, *args], cwd=root, env=env, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def test_lists_options_when_help_requested(demo_hub: Path, run_doctor: DoctorRunner) -> None:
    shown = CliRunner().invoke(app, ["doctor", "--help"], env={"COLUMNS": "120"})
    ran = run_doctor(demo_hub)
    unknown = run_doctor(demo_hub, "--nope")

    assert shown.exit_code == 0
    help_text = " ".join(unstyle(shown.stdout).split())
    assert "--only RULE" in help_text
    assert "Run only this rule (and config.schema); repeatable." in help_text
    assert "--json" in help_text
    assert "Print one JSON object instead of lines." in help_text
    assert "not implemented yet" not in ran.output
    assert lines_of(ran, exit_code=0) == [CLEAN]
    assert unknown.exit_code == 2
    assert "Usage:" in unknown.stderr
    assert unknown.stdout == ""


@pytest.mark.parametrize("case", ["empty-folder", "hub-subfolder"])
def test_exits_two_when_cwd_not_hub(
    tmp_path: Path,
    demo_hub: Path,
    run_doctor: DoctorRunner,
    *,
    path_reads: list[PathRead],
    case: str,
) -> None:
    if case == "empty-folder":
        folder = tmp_path / "empty"
        folder.mkdir()
    else:
        folder = demo_hub / "brain"
        assert (demo_hub / "hub.json").is_file()
    real = os.path.realpath(folder)
    allowed = ancestors(real, up_to=tmp_path) | {os.path.join(real, "hub.json")}
    path_reads.clear()

    result = run_doctor(folder)

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert result.stderr == f"{real}{NOT_A_HUB}\n"
    assert reads_in(path_reads, tmp_path) <= allowed


@pytest.mark.usefixtures("alarm")
@pytest.mark.parametrize(
    ("case", "reason"),
    [
        ("folder", "not a regular file"),
        ("fifo", "not a regular file"),
        ("dangling-link", "No such file or directory"),
        ("unreadable", "Permission denied"),
        ("lstat-refused", "Permission denied"),
    ],
    ids=["folder", "fifo", "dangling-link", "unreadable", "lstat-refused"],
)
def test_reports_config_schema_when_hub_json_not_regular(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    reason: str,
) -> None:
    root = tmp_path / "hub"
    root.mkdir()
    config = root / "hub.json"
    if case == "folder":
        config.mkdir()
    elif case == "fifo":
        os.mkfifo(config)
    elif case == "dangling-link":
        config.symlink_to("gone.json")
    else:
        config.write_bytes(dump_json(demo_document))
        # "unreadable" refuses the open alone; "lstat-refused" refuses every look at hub.json,
        # as an unsearchable folder does: the lstat error is not "absent", so it is no exit 2.
        calls = ("open",) if case == "unreadable" else ("open", "stat", "lstat")
        for call in calls:
            monkeypatch.setattr(os, call, refusing_hub_json(getattr(os, call)))
    shown = json.dumps(os.path.join(os.path.realpath(root), "hub.json"))

    lines = lines_of(run_doctor(root), exit_code=1)

    assert lines == [schema_line(f"$: cannot read {shown}: {reason}"), ONE_ERROR]


def refusing_hub_json(real: Callable[..., Any]) -> Callable[..., Any]:
    """``real``, except that a path ending in ``hub.json`` raises ``EACCES``."""

    def refusing(path: Any, *args: Any, **kwargs: Any) -> Any:
        if not isinstance(path, int) and os.fsdecode(path).endswith("hub.json"):
            raise PermissionError(errno.EACCES, os.strerror(errno.EACCES), path)
        return real(path, *args, **kwargs)

    return refusing


def invalid_config(case: str, document: dict[str, Any]) -> tuple[bytes, str]:
    """The ``hub.json`` bytes of an invalid case and the start of its one problem."""
    if case == "invalid-json":
        return b'{"schema_version": 1,', "$: "
    if case == "missing-key":
        del document["project"]
        return dump_json(document), "project: "
    if case == "unknown-key":
        document["surprise"] = True
        return dump_json(document), "surprise: "
    document["project"]["name"] = "Demo"
    return dump_json(document), "project.name: String should match pattern"


@pytest.mark.parametrize("only", [(), ("--only", "lock.drift")], ids=["all", "only-lock-drift"])
@pytest.mark.parametrize("case", ["invalid-json", "missing-key", "unknown-key", "bad-name"])
def test_runs_only_config_schema_when_config_invalid(
    tmp_path: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    case: str,
    only: tuple[str, ...],
) -> None:
    content, problem = invalid_config(case, demo_document)
    # No hub.lock: had lock.drift run, it would report the hub as not adopted.
    root = config_only_hub(tmp_path, content)

    lines = lines_of(run_doctor(root, *only), exit_code=1)

    assert len(lines) == 2, lines
    assert lines[0].startswith(f"error config.schema hub.json: {problem}"), lines
    assert lines[0].endswith(f" {SCHEMA_FIX}")
    assert lines[1] == ONE_ERROR


@pytest.mark.parametrize("schema_version", [1, 2], ids=["schema-ok", "schema-wrong"])
def test_reports_pin_only_when_pin_differs(
    demo_hub: Path,
    demo_document: dict[str, Any],
    run_doctor: DoctorRunner,
    *,
    schema_version: int,
) -> None:
    demo_document["platform"]["version"] = "0.0.1"
    demo_document["schema_version"] = schema_version
    (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

    lines = lines_of(run_doctor(demo_hub), exit_code=1)

    assert lines == [
        f"error platform.version hub.json: this hub is pinned to 0.0.1 but this hub command is"
        f" {VERSION}. Fix: run the pinned release: {PINNED_COMMAND}",
        ONE_ERROR,
    ]


class TestExitCodes:
    def test_exits_one_when_error_found(
        self, demo_hub: Path, demo_document: dict[str, Any], run_doctor: DoctorRunner
    ) -> None:
        demo_document["surprise"] = True
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))

        lines = lines_of(run_doctor(demo_hub), exit_code=1)

        assert [line.split(" ")[:3] for line in lines[:-1]] == [
            ["error", "config.schema", "hub.json:"]
        ]
        assert lines[-1] == ONE_ERROR

    def test_exits_two_when_only_names_unknown_rule(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        path_reads: list[PathRead],
    ) -> None:
        # Outside any hub: the refusal comes before the root and hub.json are looked at.
        monkeypatch.chdir(tmp_path)
        path_reads.clear()

        result = CliRunner().invoke(app, ["doctor", "--only", "nope"], env={"COLUMNS": "80"})

        assert_refused(result, "unknown rule in --only: nope")
        assert reads_in(path_reads, tmp_path) == set()

    @pytest.mark.parametrize(
        ("modules", "message"),
        [
            (None, "module bench is not selected"),
            ({"bench": {}}, "bench.tasks is not in this release"),
        ],
        ids=["unselected", "selected"],
    )
    def test_exits_two_when_only_names_module_rule(
        self,
        demo_hub: Path,
        demo_document: dict[str, Any],
        monkeypatch: pytest.MonkeyPatch,
        *,
        modules: dict[str, Any] | None,
        message: str,
    ) -> None:
        if modules is not None:
            demo_document["modules"] = modules
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
        monkeypatch.chdir(demo_hub)

        result = CliRunner().invoke(app, ["doctor", "--only", "bench.tasks"], env={"COLUMNS": "80"})

        assert_refused(result, message)


def test_runs_no_git_when_no_rule_needs_listing(
    demo_hub: Path, run_doctor: DoctorRunner, path_reads: list[PathRead]
) -> None:
    commit_all(demo_hub)
    path_reads.clear()

    lines = lines_of(run_doctor(demo_hub, "--only", "platform.version"), exit_code=0)

    assert lines == [CLEAN]
    assert [read for read in path_reads if read.call == "Popen"] == []


@pytest.mark.parametrize("case", ["clean", "error"])
def test_prints_one_json_object_when_json_given(
    tmp_path: Path,
    demo_hub: Path,
    demo_document: dict[str, Any],
    *,
    run_doctor: DoctorRunner,
    case: str,
) -> None:
    if case == "error":
        demo_document["surprise"] = True
        del demo_document["project"]
        (demo_hub / "hub.json").write_bytes(dump_json(demo_document))
    empty = tmp_path / "empty"
    empty.mkdir()

    text = run_doctor(demo_hub)
    shown = run_doctor(demo_hub, "--json")
    not_hub = run_doctor(empty, "--json")

    assert shown.exit_code == text.exit_code
    assert shown.exit_code == (1 if case == "error" else 0)
    assert shown.stderr == ""
    document = json.loads(shown.stdout)
    # One object in the one JSON form, and nothing else.
    assert shown.stdout == dump_json(document).decode()
    assert list(document) == ["findings", "totals"]
    text_lines = text.stdout.splitlines()
    assert [
        f"{finding['severity']} {finding['rule']} {finding['path']}: {finding['message']}"
        f" Fix: {finding['fix']}"
        for finding in document["findings"]
    ] == text_lines[:-1]
    assert all(finding["line"] is None for finding in document["findings"])
    errors = len(document["findings"])
    assert document["totals"] == {"errors": errors, "warnings": 0, "infos": 0}
    assert (case == "error") == (errors == 2)
    assert not_hub.exit_code == 2
    assert not_hub.stdout == ""
    assert not_hub.stderr == f"{os.path.realpath(empty)}{NOT_A_HUB}\n"
