"""``agent_hub.cli.console.main`` as the console script runs it: what its own ``workflow list``
path loads, and when the garbage collector is off (AC-32, AC-33).

Each case runs a launcher file named ``hub`` that calls ``main`` as the console script does, in
a fresh interpreter with an environment built from nothing, so whatever the run imports or
switches off stays in that child.
"""

import itertools
import json
import os
import subprocess
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import NamedTuple

import pytest

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
