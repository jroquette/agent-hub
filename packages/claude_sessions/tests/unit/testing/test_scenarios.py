"""Scenario files, the ``claude`` shim and the stub's records (P17)."""

import os
import sys
from pathlib import Path

from agent_hub.claude_sessions.testing.scenarios import (
    RECORD_ENV,
    SCENARIO_ENV,
    STUB_MODULE,
    DeltaStep,
    ResultStep,
    Scenario,
    TextStep,
    held_turn,
    local_settings_rule,
    read_records,
    simple_turn,
    stub_environment,
    write_scenario,
    write_shim,
)
from agent_hub.claude_sessions.testing.stub_claude import load_scenario


def test_builds_two_deltas_text_and_result_when_protocol_turn_built() -> None:
    turn = simple_turn("abcd")

    assert turn == [DeltaStep(text="ab"), DeltaStep(text="cd"), TextStep(text="abcd"), ResultStep()]


def test_round_trips_scenario_when_written_and_loaded(tmp_path: Path) -> None:
    scenario = Scenario(turns=[simple_turn(), held_turn()], grandchild=True, cloud=False)

    path = write_scenario(tmp_path, scenario)

    assert load_scenario({SCENARIO_ENV: str(path)}) == scenario


def test_loads_default_scenario_when_variable_unset() -> None:
    assert load_scenario({}) == Scenario()


def test_writes_executable_shim_when_shim_requested(tmp_path: Path) -> None:
    shim = write_shim(tmp_path / "bin", python="/opt/python3")

    text = shim.read_text()
    assert shim.name == "claude"
    assert os.access(shim, os.X_OK)
    assert 'STUB_CLAUDE_ARGV0="$0"' in text
    assert f'exec "/opt/python3" -m {STUB_MODULE} "$@"' in text


def test_points_stub_at_files_when_environment_built(tmp_path: Path) -> None:
    environ = stub_environment(tmp_path / "s.json", tmp_path / "r.jsonl")

    assert environ[SCENARIO_ENV] == str(tmp_path / "s.json")
    assert environ[RECORD_ENV] == str(tmp_path / "r.jsonl")
    assert environ["PATH"] == os.environ["PATH"]


def test_reads_no_records_when_stub_never_ran(tmp_path: Path) -> None:
    assert read_records(tmp_path / "missing.jsonl") == []


def test_targets_local_settings_when_rule_suggested() -> None:
    rule = local_settings_rule("Bash", "npm run *")

    assert rule["destination"] == "localSettings"
    assert rule["rules"] == [{"toolName": "Bash", "ruleContent": "npm run *"}]


def test_uses_running_python_when_shim_default() -> None:
    assert write_shim.__defaults__ == (sys.executable,)
