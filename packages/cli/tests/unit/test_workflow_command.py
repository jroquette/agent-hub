"""What ``hub workflow list`` loads (AGH-636, AC-25): the catalog, never the run machinery."""

import json
import os
import subprocess
import sys
from pathlib import Path

# What only a run, a step or a stored record of `hub workflow` uses: the action and run start
# chains, the run store and its outputs, and the third-party libraries behind them.
RUN_CHAIN = (
    "agent_hub.cli.action_runs",
    "agent_hub.cli.action_process",
    "agent_hub.cli.workflow_delivery",
    "agent_hub.cli.step_command",
    "agent_hub.cli.workflow_policy",
    "agent_hub.cli.workflow_executors",
    "agent_hub.cli.run_log",
    "agent_hub.cli.run_children",
    "agent_hub.core.workflows.engine",
    "agent_hub.core.workflows.launch",
    "agent_hub.core.agent_sessions.agent_session",
    "agent_hub.generator.workflow_outputs",
    "jsonschema",
    "sqlalchemy",
)


def fixed_env() -> dict[str, str]:
    return {
        "PATH": os.environ["PATH"],
        "HOME": os.environ["HOME"],
        "_TYPER_FORCE_DISABLE_TERMINAL": "1",
        "TERMINAL_WIDTH": "100",
        "COLUMNS": "100",
    }


def test_loads_no_run_machinery_when_workflow_list_runs(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text("{}\n")
    code = (
        "import importlib, json, sys\n"
        f"CHAIN = {RUN_CHAIN!r}\n"
        "def loaded():\n"
        "    return sorted(m for m in CHAIN if m in sys.modules)\n"
        "from typer.testing import CliRunner\n"
        "import agent_hub.cli.main\n"
        "env = {'AGENT_HUB_ROOT': sys.argv[1]}\n"
        "result = CliRunner().invoke(agent_hub.cli.main.app, ['workflow', 'list'], env=env)\n"
        "assert result.exit_code == 0, result.output\n"
        "seen = {'output': result.stdout, 'list': loaded()}\n"
        "for name in CHAIN:\n"
        "    importlib.import_module(name)\n"
        "seen['self-check import'] = loaded()\n"
        "print(json.dumps(seen))\n"
    )

    result = subprocess.run(  # noqa: S603 - this interpreter, a fixed script
        [sys.executable, "-c", code, str(hub)],
        env=fixed_env(),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.splitlines()[-1])
    # Self-check: the command really listed the built-ins, and the probe sees every name of the
    # chain once it is imported.
    assert any(line.startswith("issue-to-pr  ") for line in seen.pop("output").splitlines())
    assert seen.pop("self-check import") == sorted(RUN_CHAIN)
    assert seen == {"list": []}
