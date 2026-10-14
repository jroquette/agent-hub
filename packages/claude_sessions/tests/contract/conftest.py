"""The adapter's contract fixtures: the core ``ContractScenario`` scripted into the stub CLI."""

import os
from collections.abc import Mapping
from pathlib import Path

import pytest

from agent_hub.claude_sessions.testing.scenarios import (
    RECORD_ENV,
    SCENARIO_ENV,
    DeltaStep,
    HoldStep,
    ResultStep,
    Scenario,
    Step,
    TextStep,
    ToolStep,
    write_scenario,
    write_shim,
)
from agent_hub.core.agent_sessions.driver import (
    PermissionRequest,
    TextBlock,
    TextDelta,
    TurnResult,
)
from agent_hub.core.testing.session_driver_contract import ContractScenario, contract_scenario
from agent_hub.core.testing.session_driver_fakes import Hold, ScriptItem, Turn


def _step(item: ScriptItem) -> Step:
    match item:
        case TextDelta(text=text):
            return DeltaStep(text=text)
        case TextBlock(text=text):
            return TextStep(text=text)
        case Hold():
            return HoldStep()
        case PermissionRequest():
            return ToolStep(
                name=item.tool,
                input=item.input,
                tool_use_id=f"toolu_{item.request_id.replace('-', '_')}",
                suggestions=[dict(s.rule) for s in item.suggestions if isinstance(s.rule, dict)],
            )
        case TurnResult(cost_usd=cost, usage=usage):
            return ResultStep(
                cost_usd=0.0 if cost is None else float(cost),
                input_tokens=0 if usage is None else usage.input,
                output_tokens=0 if usage is None else usage.output,
            )
        case _:
            msg = f"the stub cannot play {item!r}"
            raise ValueError(msg)


def stub_scenario(replies: Mapping[str, Turn]) -> Scenario:
    """The stub scenario that plays ``replies`` by message text."""
    return Scenario(
        replies={text: [_step(item) for item in turn] for text, turn in replies.items()}
    )


def stub_environ(tmp_path: Path, scenario: Scenario) -> dict[str, str]:
    """This process's environment with the stub ``claude`` first on ``PATH``."""
    shim = write_shim(tmp_path / "bin")
    return {
        **os.environ,
        "PATH": f"{shim.parent}{os.pathsep}{os.environ.get('PATH', '')}",
        SCENARIO_ENV: str(write_scenario(tmp_path, scenario)),
        RECORD_ENV: str(tmp_path / "record.jsonl"),
    }


@pytest.fixture
def scenario(tmp_path: Path) -> ContractScenario:
    cwd = tmp_path / "work"
    cwd.mkdir()
    return contract_scenario(str(cwd))
