"""The upgrade pack's ``fast_gate.py`` (AGH-484), in process: the run's repo's ``check_fast``,
read from what ``hub step config`` printed (AGH-480: no script opens ``hub.json``); a missing one
is reported, never a crash."""

import importlib.util
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/upgrade/scripts/fast_gate.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.upgrade.scripts.fast_gate"
FULL = "make check"


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


def config(repo: dict[str, object]) -> str:
    """``hub step config``'s output, as the workflow passes it: the run's repo and another."""
    other = {"dir": "demo-web", "check_fast": "npm test", "check": "npm run check"}
    return json.dumps({"default_branch": "main", "repos": [other, repo]})


def test_prints_the_repo_fast_gate_when_config_names_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    given = config({"dir": "demo-api", "check_fast": "make check-fast", "check": FULL})
    monkeypatch.chdir(tmp_path)

    assert load().main(["--config", given, "--repo", "demo-api", "--full", FULL]) == 0

    assert json.loads(capsys.readouterr().out) == {
        "check_fast": "make check-fast",
        "source": "check_fast",
        "reason": "",
    }


def test_opens_no_hub_json_when_config_given(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "hub.json").write_text(
        json.dumps({"repos": [{"dir": "demo-api", "check_fast": "from the file"}]}),
        encoding="utf-8",
    )
    given = config({"dir": "demo-api", "check_fast": "make check-fast", "check": FULL})
    monkeypatch.chdir(tmp_path)

    assert load().main(["--config", given, "--repo", "demo-api", "--full", FULL]) == 0

    assert json.loads(capsys.readouterr().out)["check_fast"] == "make check-fast"


@pytest.mark.parametrize("given", [{}, {"check_fast": ""}, {"check_fast": "  "}, {"check_fast": 3}])
def test_reports_and_runs_the_full_gate_when_check_fast_is_missing_or_empty(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    given: dict[str, object],
) -> None:
    text = config({"dir": "demo-api", "check": FULL, **given})
    monkeypatch.chdir(tmp_path)

    assert load().main(["--config", text, "--repo", "demo-api", "--full", FULL]) == 0

    found = json.loads(capsys.readouterr().out)
    assert (found["check_fast"], found["source"]) == (FULL, "check")
    assert found["reason"] == "hub.json gives demo-api no check_fast: the full check runs instead"


@pytest.mark.parametrize(
    ("text", "reason"),
    [
        ("{not json", "the config is not JSON"),
        ("[]", "the config has no repos list"),
        ('{"repos": [{"dir": "other"}]}', "hub.json lists no repo demo-api"),
        ("{" + " " * (1024 * 1024), "the config is larger than 1 MiB"),
    ],
)
def test_reports_and_runs_the_full_gate_when_config_is_unreadable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    text: str,
    reason: str,
) -> None:
    monkeypatch.chdir(tmp_path)

    assert load().main(["--config", text, "--repo", "demo-api", "--full", FULL]) == 0

    found = json.loads(capsys.readouterr().out)
    assert found == {
        "check_fast": FULL,
        "source": "check",
        "reason": f"{reason}: the full check runs instead",
    }


@pytest.mark.parametrize(
    "argv",
    [
        [],
        ["--config", "{}", "--repo", "demo-api"],
        ["--config", "{}", "--repo", "", "--full", FULL],
        ["--config", "{}", "--repo", "a", "--full", " "],
        ["--config", "", "--repo", "a", "--full", FULL],
    ],
)
def test_exits_two_when_the_arguments_are_bad(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    *,
    argv: list[str],
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit) as raised:
        load().main(argv)

    assert raised.value.code == 2
    assert capsys.readouterr().out == ""
