"""The ``hub`` console script against the Typer app, the entry it replaces (AC-31, AC-32).

Each case runs two launcher files, both named ``hub`` so that Click names the program alike,
with this interpreter, in the same folder and the same environment built from nothing: one
calls the console entry ``agent_hub.cli.console.main``, the other the Typer app
``agent_hub.cli.main.app``. The console entry lists workflows on a path of its own when the
arguments are exactly ``workflow list``; whatever the case, both must print the same bytes and
exit with the same code.
"""

import json
import os
import subprocess
import sys
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

import pytest

from agent_hub.generator import parsed_builtins

CONSOLE_ENTRY = "from agent_hub.cli.console import main\n"
TYPER_ENTRY = "from agent_hub.cli.main import app as main\n"
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
TABLE_ERROR = b"hub: the pre-parsed built-in workflows table "


class Run(NamedTuple):
    """One launcher run: its exit code and the bytes of its streams (``None``: not captured)."""

    code: int
    stdout: bytes | None
    stderr: bytes


def child_env(**extra: str) -> dict[str, str]:
    """The same environment for both launchers, built from nothing.

    An inherited ``PYTHONUNBUFFERED`` (some machines export it) would hide a flush that fails at
    exit, and Click reads the terminal width and the completion variables from here.
    """
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "GIT_ALLOW_PROTOCOL": "file",
        "_TYPER_FORCE_DISABLE_TERMINAL": "1",
        "TERMINAL_WIDTH": "100",
        "COLUMNS": "100",
        **extra,
    }


def write_launcher(folder: Path, entry: str, prologue: str) -> Path:
    """A file named ``hub`` that runs ``prologue``, then ``main`` as a console script does."""
    folder.mkdir()
    launcher = folder / "hub"
    launcher.write_text(f"import sys\n{prologue}{entry}sys.exit(main())\n", encoding="utf-8")
    return launcher


def run_launcher(
    launcher: Path, args: Sequence[str], *, cwd: Path, env: Mapping[str, str], stdout: int
) -> Run:
    result = subprocess.run(  # noqa: S603 - this interpreter and a launcher the test wrote
        [sys.executable, str(launcher), *args],
        cwd=cwd,
        env=dict(env),
        stdout=stdout,
        stderr=subprocess.PIPE,
        timeout=RUN_TIMEOUT,
        check=False,
    )
    return Run(result.returncode, result.stdout, result.stderr)


def run_both(
    tmp_path: Path,
    args: Sequence[str],
    *,
    cwd: Path,
    env: Mapping[str, str],
    prologue: str = "",
    stdout: int = subprocess.PIPE,
) -> tuple[Run, Run]:
    """The Typer launcher's run, then the console launcher's, alike but for the entry."""
    typer = write_launcher(tmp_path / "typer-bin", TYPER_ENTRY, prologue)
    console = write_launcher(tmp_path / "console-bin", CONSOLE_ENTRY, prologue)
    return (
        run_launcher(typer, args, cwd=cwd, env=env, stdout=stdout),
        run_launcher(console, args, cwd=cwd, env=env, stdout=stdout),
    )


def write_hubs(tmp_path: Path) -> Path:
    """``hub`` (one workflow of its own), ``other-hub`` (none) and ``elsewhere`` (not a hub)."""
    hub = tmp_path / "hub"
    (hub / "workflows" / "demo").mkdir(parents=True)
    (hub / "hub.json").write_text("{}\n", encoding="utf-8")
    (hub / "workflows" / "demo" / "check.yaml").write_text(CHECK_YAML, encoding="utf-8")
    (tmp_path / "other-hub").mkdir()
    (tmp_path / "other-hub" / "hub.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "elsewhere").mkdir()
    return hub


def workflow_json(name: str, description: str) -> str:
    """A one-node workflow file ``<name>.json`` with ``description``."""
    nodes = [{"id": "a", "type": "halt", "reason": "x"}]
    document = {"version": 1, "name": name, "revision": 1, "description": description}
    return json.dumps({**document, "nodes": nodes})


class ListCase(NamedTuple):
    """One ``hub workflow list`` run, and what its Typer run shows when it is set up so."""

    # More files in the hub, by path.
    files: tuple[tuple[str, str], ...] = ()
    # The folder it runs in, under tmp_path: hub, other-hub or elsewhere.
    cwd: str = "hub"
    # Whether AGENT_HUB_ROOT names the hub.
    hub_in_variable: bool = False
    # The pre-parsed built-in table: shipped, missing or broken.
    table: str = "shipped"
    # More environment.
    env: tuple[tuple[str, str], ...] = ()
    # The Typer run's exit code, and a stream of it holding the text.
    sign: tuple[int, str, bytes] = (0, "stdout", CHECK_LINE)


def list_env(case: ListCase, hub: Path) -> dict[str, str]:
    named = {"AGENT_HUB_ROOT": str(hub)} if case.hub_in_variable else {}
    return child_env(**named, **dict(case.env))


def table_prologue(tmp_path: Path, table: str) -> str:
    """Launcher lines that point the table lookup at a folder without the table, or with a
    broken one (both launchers get them); none for the table as shipped."""
    if table == "shipped":
        return ""
    folder = tmp_path / f"table-{table}"
    folder.mkdir()
    if table == "broken":
        (folder / parsed_builtins.TABLE_FILE).write_text("not json\n", encoding="utf-8")
    return (
        "from pathlib import Path\n"
        "from agent_hub.generator import parsed_builtins\n"
        f"parsed_builtins.files = lambda package: Path({str(folder)!r})\n"
    )


LIST_CASES = [
    pytest.param(ListCase(), id="clean-hub"),
    # A console entry that read the cwd first would list other-hub, without the check line.
    pytest.param(ListCase(cwd="other-hub", hub_in_variable=True), id="hub-named-by-variable"),
    pytest.param(
        ListCase(cwd="elsewhere", sign=(2, "stderr", b": not a hub: no hub.json")),
        id="outside-a-hub",
    ),
    pytest.param(
        ListCase(
            files=(("workflows/demo/broken.yaml", BROKEN_YAML),),
            sign=(1, "stderr", b"workflows/demo/broken.yaml:3: $: "),
        ),
        id="workflow-problem",
    ),
    pytest.param(ListCase(table="missing", sign=(1, "stderr", TABLE_ERROR)), id="table-missing"),
    pytest.param(ListCase(table="broken", sign=(1, "stderr", TABLE_ERROR)), id="table-broken"),
    # Click drops the escape sequence when stdout is not a terminal.
    pytest.param(
        ListCase(
            files=(("workflows/demo/zz-esc.json", workflow_json("zz-esc", "\x1b[31mred\x1b[0m!")),),
            sign=(0, "stdout", b"zz-esc  1 nodes  red!\n"),
        ),
        id="escape-in-description",
    ),
    # Click writes UTF-8 when stdout's encoding is ASCII; the last line is the accented one, so
    # a line written before a hand-over would show twice.
    pytest.param(
        ListCase(
            files=(("workflows/demo/zz-cafe.json", workflow_json("zz-cafe", "Café au lait")),),
            env=(("PYTHONIOENCODING", "ascii"),),
            sign=(0, "stdout", "zz-cafe  1 nodes  Café au lait\n".encode()),
        ),
        id="ascii-stdout-accented-description",
    ),
    # The same with an error handler set: Click still writes UTF-8, so a check that used the
    # handler would print "Caf? au lait" where the Typer app prints the accented line.
    pytest.param(
        ListCase(
            files=(("workflows/demo/zz-cafe.json", workflow_json("zz-cafe", "Café au lait")),),
            env=(("PYTHONIOENCODING", "ascii:replace"),),
            sign=(0, "stdout", "zz-cafe  1 nodes  Café au lait\n".encode()),
        ),
        id="ascii-replace-stdout-accented-description",
    ),
]


@pytest.mark.parametrize("case", LIST_CASES)
def test_matches_typer_path_when_workflow_list_runs(tmp_path: Path, case: ListCase) -> None:
    hub = write_hubs(tmp_path)
    for relative, text in case.files:
        (hub / relative).write_text(text, encoding="utf-8")
    prologue = table_prologue(tmp_path, case.table)

    typer, console = run_both(
        tmp_path,
        ["workflow", "list"],
        cwd=tmp_path / case.cwd,
        env=list_env(case, hub),
        prologue=prologue,
    )

    code, stream, text = case.sign
    # Self-check: the Typer run shows that the case is what its id says.
    assert (typer.code, text in getattr(typer, stream)) == (code, True), typer
    assert console == typer


COMPLETION = (
    ("_HUB_COMPLETE", "complete_bash"),
    ("COMP_WORDS", "hub workflow li"),
    ("COMP_CWORD", "2"),
)


@pytest.mark.parametrize(
    ("args", "env"),
    [
        pytest.param(("--help",), (), id="help"),
        pytest.param(("workflow", "list", "--help"), (), id="workflow-list-help"),
        pytest.param(("workflow", "list", "x"), (), id="extra-argument"),
        pytest.param(("repo", "list"), (), id="another-command"),
        pytest.param(("workflow", "list"), COMPLETION, id="completion-variable"),
    ],
)
def test_hands_over_to_typer_when_argv_is_not_workflow_list(
    tmp_path: Path, *, args: tuple[str, ...], env: tuple[tuple[str, str], ...]
) -> None:
    hub = write_hubs(tmp_path)

    typer, console = run_both(tmp_path, args, cwd=hub, env=child_env(**dict(env)))

    # Self-check: Typer lists no workflow for any of these, so a console entry that took its own
    # listing path for one of them cannot match.
    assert CHECK_LINE not in typer.stdout, typer
    assert console == typer


# Launcher lines for one Ctrl-C: KeyboardInterrupt at the first look into the hub's workflows
# folder (an audit hook sees each open and each folder scan), as when a listing is stopped.
INTERRUPT_PROLOGUE = """\
import os
_WORKFLOWS = os.path.join(os.getcwd(), "workflows")
_interrupted = []
def _interrupt_once(event, args):
    if _interrupted or event not in ("open", "os.scandir", "os.listdir") or not args:
        return
    if not isinstance(args[0], (str, bytes, os.PathLike)):
        return
    path = os.path.join(os.getcwd(), os.fsdecode(os.fspath(args[0])))
    if path == _WORKFLOWS or path.startswith(_WORKFLOWS + os.sep):
        _interrupted.append(path)
        raise KeyboardInterrupt
sys.addaudithook(_interrupt_once)
"""


@contextmanager
def stdout_target(kind: str) -> Iterator[int]:
    """Where a child's stdout goes: a pipe the test reads, or one whose reader is already gone."""
    if kind == "pipe":
        yield subprocess.PIPE
        return
    read_end, write_end = os.pipe()
    os.close(read_end)
    try:
        yield write_end
    finally:
        os.close(write_end)


@pytest.mark.parametrize(
    ("prologue", "stdout_kind", "expected"),
    [
        pytest.param(INTERRUPT_PROLOGUE, "pipe", Run(130, b"", b""), id="interrupted"),
        pytest.param("", "closed-pipe", Run(1, None, b""), id="stdout-pipe-closed"),
    ],
)
def test_exits_like_typer_when_interrupted_or_pipe_closed(
    tmp_path: Path, *, prologue: str, stdout_kind: str, expected: Run
) -> None:
    hub = write_hubs(tmp_path)

    with stdout_target(stdout_kind) as stdout:
        typer, console = run_both(
            tmp_path,
            ["workflow", "list"],
            cwd=hub,
            env=child_env(),
            prologue=prologue,
            stdout=stdout,
        )

    # Self-check: the Typer app ends this case so (130 and nothing printed on a Ctrl-C; 1 and an
    # empty stderr on a closed pipe), so the case is set up as named.
    assert typer == expected
    assert console == expected
