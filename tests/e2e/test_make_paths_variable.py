"""``make check-changed`` reads ``PATHS`` from make's command line only, and as plain text.

make expands a command-line variable when it hands it to a recipe, so ``$(shell …)`` in it would
run, in make and again in each make a recipe starts (those get the variable back through
``MAKEFLAGS``). A ``PATHS`` exported by the shell would reach the recipes too, and win over the
Stop gate's ``HUB_CHANGED_FILES``. The probe adds one target to the repo's Makefile, which prints
the ``PATHS`` its recipe's environment holds. ``check-changed`` itself runs with a command-line
``RUN`` that starts a probe in place of the script, which prints what the script would get.
"""

import json
import os
import shlex
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from subprocess import CompletedProcess

import pytest

PROBE = """\
.PHONY: probe
probe:
\t@{python} -c 'import json, os; print(json.dumps(os.environ.get("PATHS")))'
"""
# Stands in for ``uv run`` in check-changed's recipe: prints its environment's MAKEFLAGS and
# PATHS, and the command it was asked to run.
RECIPE_PROBE = """\
import json, os, sys
seen = {"MAKEFLAGS": os.environ.get("MAKEFLAGS", ""), "PATHS": os.environ.get("PATHS")}
print(json.dumps({**seen, "argv": sys.argv[1:]}))
"""
# What a make that runs this test (make check) hands down to the makes it starts.
PARENT_MAKE_VARIABLES = frozenset({"MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "PATHS"})


@dataclass(frozen=True)
class PathsCase:
    """make's command-line variables, what its environment adds, and the PATHS the recipe sees;
    ``{tmp}`` stands for the test's own folder."""

    arguments: tuple[str, ...]
    environment: Mapping[str, str]
    seen: str | None


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            PathsCase(
                ("PATHS=$(shell touch {tmp}/pwned)a.py",), {}, "$(shell touch {tmp}/pwned)a.py"
            ),
            id="command-line-function",
        ),
        pytest.param(PathsCase((), {"PATHS": "check.log"}, None), id="environment"),
        pytest.param(PathsCase(("PATHS=a.py b.py",), {}, "a.py b.py"), id="command-line"),
    ],
)
def test_hands_paths_to_recipes_as_text_when_given_on_command_line_only(
    case: PathsCase, tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    probe = tmp_path / "probe.mk"
    probe.write_text(PROBE.format(python=shlex.quote(sys.executable)), encoding="utf-8")
    inherited = {
        name: value for name, value in os.environ.items() if name not in PARENT_MAKE_VARIABLES
    }
    arguments = [argument.format(tmp=tmp_path) for argument in case.arguments]

    result = run(
        ["make", "--no-print-directory", "-s", "-f", "Makefile", "-f", str(probe), "probe"]
        + arguments,
        env={**inherited, **case.environment},
    )

    seen = None if case.seen is None else case.seen.format(tmp=tmp_path)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == seen
    assert not (tmp_path / "pwned").exists()


def test_keeps_command_line_variables_from_child_makes_when_check_changed_runs(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    """A make the script starts would read PATHS from MAKEFLAGS, and expand it (amendment A11)."""
    probe = tmp_path / "recipe_probe.py"
    probe.write_text(RECIPE_PROBE, encoding="utf-8")
    inherited = {
        name: value for name, value in os.environ.items() if name not in PARENT_MAKE_VARIABLES
    }
    paths = f"$(shell touch {tmp_path}/pwned)a.py b.py"

    result = run(
        [
            "make",
            "--no-print-directory",
            "-s",
            "check-changed",
            f"PATHS={paths}",
            f"RUN={shlex.quote(sys.executable)} {shlex.quote(str(probe))}",
        ],
        env=inherited,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout)
    assert "scripts.check_changed" in seen["argv"]
    assert seen["PATHS"] == paths
    assert "PATHS" not in seen["MAKEFLAGS"]
    assert not (tmp_path / "pwned").exists()
