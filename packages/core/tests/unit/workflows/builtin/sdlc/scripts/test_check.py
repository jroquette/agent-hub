"""The sdlc pack's ``check.py`` (AGH-229), in process: the check's result as JSON, exit 0."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import IO, Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/sdlc/scripts/check.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.sdlc.scripts.check"


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


def fake_run(output: bytes, code: int, seen: list[list[str]]) -> Any:
    def run(
        argv: list[str], *, stdout: IO[bytes], **_: object
    ) -> subprocess.CompletedProcess[bytes]:
        seen.append(argv)
        stdout.write(output)
        return subprocess.CompletedProcess(argv, code)

    return run


@pytest.mark.parametrize(
    ("argv", "code", "expected"),
    [
        (["make check"], 0, {"passed": True, "exit_code": 0, "round": 1, "tail": "ok\n"}),
        (["make check", ""], 2, {"passed": False, "exit_code": 2, "round": 1, "tail": "ok\n"}),
        (["make check", "2"], 1, {"passed": False, "exit_code": 1, "round": 3, "tail": "ok\n"}),
    ],
)
def test_prints_the_result_and_exits_zero_when_the_check_ends(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    argv: list[str],
    code: int,
    expected: dict[str, object],
) -> None:
    module, seen = load(), []
    monkeypatch.setattr(module.subprocess, "run", fake_run(b"ok\n", code, seen))

    assert module.main(argv) == 0

    assert json.loads(capsys.readouterr().out) == expected
    assert seen == [["bash", "-c", "make check"]]


def test_keeps_the_last_4000_characters_when_the_output_is_long(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    output = ("é" * 9000 + "END").encode()
    monkeypatch.setattr(module.subprocess, "run", fake_run(output, 0, []))

    module.main(["make check"])

    tail = json.loads(capsys.readouterr().out)["tail"]
    assert len(tail) == 4000
    assert tail.endswith("éEND")


@pytest.mark.parametrize("argv", [[], ["a", "1", "x"], ["make check", "x"], ["make check", "-1"]])
def test_exits_two_and_runs_nothing_when_the_arguments_are_bad(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], argv: list[str]
) -> None:
    module, seen = load(), []
    monkeypatch.setattr(module.subprocess, "run", fake_run(b"", 0, seen))

    assert module.main(argv) == 2

    assert (capsys.readouterr().out, seen) == ("", [])
