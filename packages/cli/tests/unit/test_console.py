"""``agent_hub.cli.console.main`` as the console script runs it: what its own ``workflow list``
path loads, and when the garbage collector is off (AC-32, AC-33).

Each case runs a launcher file named ``hub`` that calls ``main`` as the console script does, in
a fresh interpreter with an environment built from nothing, so whatever the run imports or
switches off stays in that child.
"""

import errno
import gc
import itertools
import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import NamedTuple, NoReturn

import pytest

from agent_hub.cli import console

ENTRY = "from agent_hub.cli.console import main\n"
# Only stops a child that hangs: no run comes near it.
RUN_TIMEOUT = 120

CHECK_YAML = """\
version: 1
name: check
revision: 1
description: Lint, then test.
nodes:
  - id: lint
    type: shell
    command: [make, lint]
  - id: test
    type: shell
    command: [make, test]
    depends_on: [lint]
"""
# What `workflow list` prints for CHECK_YAML: the sign that a run listed the hub.
CHECK_LINE = b"check  2 nodes  Lint, then test.\n"
BROKEN_YAML = "version: 1\nname: broken\nname: again\n"

# What the console entry's own listing must not load (AC-33): Typer, the read models behind the
# hub, feature and item-version views, and the chain that reads hub.json and hub.local.json.
NOT_FOR_LISTING = (
    "typer",
    "agent_hub.core.workflows.workflow_reads",
    "agent_hub.core.item_versions.capture_item_versions",
    "agent_hub.core.hubs.hub_registry",
    "agent_hub.core.features.output_models",
    "agent_hub.cli.hub_config_reader",
    "agent_hub.core.hub_config.effective_environments",
    "agent_hub.core.hub_config.local_config",
)

# Launcher lines that write to PROBE_OUT, at exit, which of NOT_FOR_LISTING the run loaded, then
# which are loaded once each is imported (so the probe is shown to see every name).
MODULE_PROBE = f"""\
import atexit, importlib, json, os
_NAMES = {NOT_FOR_LISTING!r}
def _loaded():
    return sorted(name for name in _NAMES if name in sys.modules)
def _write_loaded():
    seen = {{"list": _loaded()}}
    for name in _NAMES:
        importlib.import_module(name)
    seen["self-check import"] = _loaded()
    with open(os.environ["PROBE_OUT"], "w", encoding="utf-8") as out:
        json.dump(seen, out)
atexit.register(_write_loaded)
"""

# Launcher lines that append to PROBE_OUT, at each look into the hub's workflows folder (an
# audit hook sees each open and each folder scan), whether the garbage collector is on.
GC_PROBE = """\
import gc, json, os
_WORKFLOWS = os.path.join(os.getcwd(), "workflows")
def _note_gc(event, args):
    if event not in ("open", "os.scandir", "os.listdir") or not args:
        return
    if not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = os.path.join(os.getcwd(), os.fsdecode(os.fspath(args[0])))
    if path == _WORKFLOWS or path.startswith(_WORKFLOWS + os.sep):
        with open(os.environ["PROBE_OUT"], "a", encoding="utf-8") as out:
            out.write(json.dumps(gc.isenabled()) + "\\n")
sys.addaudithook(_note_gc)
"""


class Run(NamedTuple):
    """One launcher run: its exit code and the bytes of its streams."""

    code: int
    stdout: bytes
    stderr: bytes


def child_env(**extra: str) -> dict[str, str]:
    """An environment built from nothing, so no variable of the test's own reaches the run."""
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "GIT_ALLOW_PROTOCOL": "file",
        "_TYPER_FORCE_DISABLE_TERMINAL": "1",
        "TERMINAL_WIDTH": "100",
        "COLUMNS": "100",
        **extra,
    }


def run_console(
    tmp_path: Path, prologue: str, args: Sequence[str], *, cwd: Path, env: Mapping[str, str]
) -> Run:
    """Run ``prologue``, then ``main`` as the console script does, from a file named ``hub``."""
    (tmp_path / "bin").mkdir()
    launcher = tmp_path / "bin" / "hub"
    launcher.write_text(f"import sys\n{prologue}{ENTRY}sys.exit(main())\n", encoding="utf-8")
    result = subprocess.run(  # noqa: S603 - this interpreter and a launcher the test wrote
        [sys.executable, str(launcher), *args],
        cwd=cwd,
        env=dict(env),
        capture_output=True,
        timeout=RUN_TIMEOUT,
        check=False,
    )
    return Run(result.returncode, result.stdout, result.stderr)


def write_hub(tmp_path: Path) -> Path:
    hub = tmp_path / "hub"
    (hub / "workflows" / "demo").mkdir(parents=True)
    (hub / "hub.json").write_text("{}\n", encoding="utf-8")
    (hub / "workflows" / "demo" / "check.yaml").write_text(CHECK_YAML, encoding="utf-8")
    return hub


@pytest.mark.parametrize(
    ("args", "files", "expected"),
    [
        # Off while its own listing reads the hub.
        pytest.param(("workflow", "list"), (), (0, [False]), id="workflow-list"),
        # Off while it reads, then on again for Typer, which it hands a workflow problem to.
        pytest.param(
            ("workflow", "list"),
            (("workflows/demo/broken.yaml", BROKEN_YAML),),
            (1, [False, True]),
            id="workflow-list-handed-over",
        ),
        # Never off for another command.
        pytest.param(("workflow", "validate"), (), (0, [True]), id="workflow-validate"),
    ],
)
def test_turns_gc_off_only_when_fast_path_runs(
    tmp_path: Path,
    *,
    args: tuple[str, ...],
    files: tuple[tuple[str, str], ...],
    expected: tuple[int, list[bool]],
) -> None:
    hub = write_hub(tmp_path)
    for relative, text in files:
        (hub / relative).write_text(text, encoding="utf-8")
    probe = tmp_path / "gc-states.jsonl"
    probe.write_text("", encoding="utf-8")

    run = run_console(tmp_path, GC_PROBE, args, cwd=hub, env=child_env(PROBE_OUT=str(probe)))

    states = [json.loads(line) for line in probe.read_text(encoding="utf-8").splitlines()]
    # The collector's state at each look into the workflows folder, repeats collapsed.
    phases = [state for state, _ in itertools.groupby(states)]
    assert (run.code, phases) == expected, run.stderr


def test_loads_no_typer_or_read_models_when_fast_path_runs(tmp_path: Path) -> None:
    hub = write_hub(tmp_path)
    probe = tmp_path / "modules.json"

    run = run_console(
        tmp_path, MODULE_PROBE, ["workflow", "list"], cwd=hub, env=child_env(PROBE_OUT=str(probe))
    )

    seen = json.loads(probe.read_text(encoding="utf-8"))
    # Self-check: the run listed the hub, and the probe sees each name once it is imported (so a
    # misspelt name cannot pass as "not loaded").
    assert (run.code, CHECK_LINE in run.stdout) == (0, True), run.stderr
    assert seen.pop("self-check import") == sorted(NOT_FOR_LISTING)
    assert seen == {"list": []}


# The cases below call ``main`` in this process, with a stand-in for the Typer app, so that
# coverage measures its branches: it does not follow the children above.


def one_node_workflow(name: str, description: str) -> str:
    """The text of a workflow file ``<name>.json`` of one node, with ``description``."""
    nodes = [{"id": "a", "type": "halt", "reason": "x"}]
    document = {"version": 1, "name": name, "revision": 1, "description": description}
    return json.dumps({**document, "nodes": nodes})


class FakeStdout:
    """Stands in for ``sys.stdout``: keeps what is written; ``flush`` raises ``failure``."""

    def __init__(
        self, *, encoding: str = "utf-8", failure: BaseException | None = None, descriptor: int = -1
    ) -> None:
        self.encoding = encoding
        self.failure = failure
        self.descriptor = descriptor
        self.written: list[str] = []

    def write(self, text: str) -> int:
        self.written.append(text)
        return len(text)

    def flush(self) -> None:
        if self.failure is not None:
            raise self.failure

    def fileno(self) -> int:
        return self.descriptor


@pytest.fixture
def typer_app_runs(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[bool]]:
    """Stands in for the Typer app: each run notes whether the garbage collector was on.

    No hub root or completion variable comes from the test's own environment, and the collector
    is turned back on afterwards, since the listing path leaves it off.
    """
    runs: list[bool] = []
    monkeypatch.setattr("agent_hub.cli.main.app", lambda: runs.append(gc.isenabled()))
    monkeypatch.delenv("AGENT_HUB_ROOT", raising=False)
    monkeypatch.delenv("_HUB_COMPLETE", raising=False)
    enabled = gc.isenabled()
    yield runs
    if enabled:
        gc.enable()


def raise_bug(source: object) -> NoReturn:
    raise RuntimeError("a bug in the catalog")


def raise_interrupt(source: object) -> NoReturn:
    raise KeyboardInterrupt


class HandOver(NamedTuple):
    """An in-process run that ``main`` hands to the Typer app."""

    args: tuple[str, ...] = ("workflow", "list")
    env: tuple[tuple[str, str], ...] = ()
    # More files in the hub, by path.
    files: tuple[tuple[str, str], ...] = ()
    # Whether it runs in the hub, or in a folder beside it with no hub.json.
    in_hub: bool = True
    # The encoding of the stand-in stdout.
    encoding: str = "utf-8"
    # Whether building the catalog raises an error.
    catalog_fails: bool = False


HAND_OVERS = [
    pytest.param(HandOver(args=("workflow", "validate")), id="other-arguments"),
    pytest.param(HandOver(env=(("_HUB_COMPLETE", "complete_bash"),)), id="completion-variable"),
    pytest.param(HandOver(in_hub=False), id="outside-a-hub"),
    pytest.param(
        HandOver(files=(("workflows/demo/broken.yaml", BROKEN_YAML),)), id="workflow-problem"
    ),
    pytest.param(
        HandOver(files=(("workflows/demo/zz-esc.json", one_node_workflow("zz-esc", "\x1b[0m")),)),
        id="escape-in-description",
    ),
    pytest.param(
        HandOver(
            files=(("workflows/demo/zz-cafe.json", one_node_workflow("zz-cafe", "Café")),),
            encoding="ascii",
        ),
        id="ascii-stdout-accented-description",
    ),
    pytest.param(HandOver(catalog_fails=True), id="catalog-error"),
]


@pytest.mark.parametrize("case", HAND_OVERS)
def test_runs_typer_app_with_nothing_printed_when_listing_not_clean(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typer_app_runs: list[bool], *, case: HandOver
) -> None:
    hub = write_hub(tmp_path)
    for relative, text in case.files:
        (hub / relative).write_text(text, encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(hub if case.in_hub else elsewhere)
    for name, value in case.env:
        monkeypatch.setenv(name, value)
    if case.catalog_fails:
        monkeypatch.setattr("agent_hub.core.workflows.catalog.check_workflows", raise_bug)
    stdout = FakeStdout(encoding=case.encoding)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "argv", ["hub", *case.args])

    console.main()

    # The Typer app ran once, with the collector on, and nothing was printed before it.
    assert (typer_app_runs, stdout.written) == ([True], [])


@pytest.mark.parametrize("named_by_variable", [False, True], ids=["cwd-is-hub", "hub-in-variable"])
def test_prints_listing_with_collector_off_when_hub_lists_cleanly(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    typer_app_runs: list[bool],
    *,
    capsys: pytest.CaptureFixture[str],
    named_by_variable: bool,
) -> None:
    hub = write_hub(tmp_path)
    if named_by_variable:
        # The cwd is a hub with no workflow of its own: the variable wins over it.
        other = tmp_path / "other-hub"
        other.mkdir()
        (other / "hub.json").write_text("{}\n", encoding="utf-8")
        monkeypatch.chdir(other)
        monkeypatch.setenv("AGENT_HUB_ROOT", str(hub))
    else:
        monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "argv", ["hub", "workflow", "list"])

    console.main()

    collector_on = gc.isenabled()
    printed = capsys.readouterr().out.splitlines(keepends=True)
    assert (typer_app_runs, collector_on) == ([], False)
    assert CHECK_LINE.decode() in printed


def test_exits_like_typer_when_listing_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    typer_app_runs: list[bool],
    *,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.chdir(write_hub(tmp_path))
    monkeypatch.setattr("agent_hub.core.workflows.catalog.check_workflows", raise_interrupt)
    monkeypatch.setattr(sys, "argv", ["hub", "workflow", "list"])

    with pytest.raises(SystemExit) as stop:
        console.main()

    assert (stop.value.code, typer_app_runs, capsys.readouterr().out) == (130, [], "")


def open_descriptors() -> int:
    """How many descriptors the process holds (``/dev/fd`` lists them on Linux and macOS)."""
    return len(os.listdir("/dev/fd"))


@pytest.mark.parametrize(
    ("failure", "code"),
    [
        pytest.param(KeyboardInterrupt(), 130, id="interrupted"),
        pytest.param(BrokenPipeError(errno.EPIPE, "Broken pipe"), 1, id="pipe-closed"),
    ],
)
def test_exits_like_typer_when_print_interrupted_or_pipe_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    typer_app_runs: list[bool],
    *,
    failure: BaseException,
    code: int,
) -> None:
    monkeypatch.chdir(write_hub(tmp_path))
    # A file of the test's own stands in for fd 1, which a closed pipe sends to /dev/null.
    descriptor = os.open(tmp_path / "stdout", os.O_WRONLY | os.O_CREAT, 0o600)
    stdout = FakeStdout(failure=failure, descriptor=descriptor)
    monkeypatch.setattr(sys, "stdout", stdout)
    monkeypatch.setattr(sys, "argv", ["hub", "workflow", "list"])

    try:
        before = open_descriptors()
        with pytest.raises(SystemExit) as stop:
            console.main()
        opened = open_descriptors() - before
        to_null = os.path.samestat(os.fstat(descriptor), os.stat(os.devnull))
    finally:
        os.close(descriptor)

    # The whole listing went out in one write, and no run was handed to the Typer app.
    assert (stop.value.code, len(stdout.written), typer_app_runs) == (code, 1, [])
    assert CHECK_LINE.decode() in stdout.written[0].splitlines(keepends=True)
    assert to_null == (code == 1)
    # Sending fd 1 to /dev/null leaves no other descriptor open.
    assert opened == 0


def test_raises_when_print_fails_without_closed_pipe(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, typer_app_runs: list[bool]
) -> None:
    monkeypatch.chdir(write_hub(tmp_path))
    monkeypatch.setattr(sys, "stdout", FakeStdout(failure=OSError(errno.EIO, "I/O error")))
    monkeypatch.setattr(sys, "argv", ["hub", "workflow", "list"])

    with pytest.raises(OSError, match="I/O error") as raised:
        console.main()

    # Any other error is raised as under Typer, with the same exit code and last line, but shown
    # as a plain traceback, not Typer's boxed one; once printing started, nothing is handed over.
    assert (raised.value.errno, typer_app_runs) == (errno.EIO, [])
