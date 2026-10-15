"""The sdlc pack's ``verdict.py`` (AGH-229), in process: PASS only when both lenses pass."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/verdict.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.verdict"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


@pytest.mark.parametrize(
    ("spec", "quality", "verdict"),
    [("PASS", "PASS", "PASS"), ("PASS", "FAIL", "FAIL"), ("FAIL", "FAIL", "FAIL")],
)
def test_passes_only_when_both_lenses_pass_when_verdicts_are_joined(
    capsys: pytest.CaptureFixture[str], *, spec: str, quality: str, verdict: str
) -> None:
    assert load().main(["--spec", spec, "--quality", quality]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output == {"verdict": verdict, "lenses": {"spec": spec, "quality": quality}}


@pytest.mark.parametrize("argv", [["--spec", "PASS", "--quality", ""], ["--spec", "PASS"]])
def test_exits_two_when_a_verdict_is_missing_or_unknown(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        load().main(argv)

    assert stopped.value.code == 2
