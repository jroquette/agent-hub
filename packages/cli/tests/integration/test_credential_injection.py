"""Credentials reach only an action's process (AC-350.9, docs/design/scenarios.md § Credentials).

Each test builds a hub folder whose ``staging`` environment declares ``aws_profile:
demo-staging`` and ``env: [DEMO_DB_URL]``, puts ``DEMO_DB_URL`` (a synthetic value built from
parts) and ``AWS_PROFILE=demo-staging`` in the developer's environment, and runs the command in
process with ``AGENT_HUB_ROOT`` naming the hub. Each child writes its environment to a file the
test reads; no value may reach the run's folder or the events database.
"""

import json
import os
import shutil
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_environments_document

SECRET = "x-" + "secret" + "-y"
FAKE_CLAUDE = """#!/bin/sh
env > "$DUMP/claude.env"
printf '{"type": "result", "subtype": "success", "is_error": false, "result": "done"}'
"""
WORKFLOW = """\
version: 1
name: creds
revision: 1
nodes:
  - id: shell
    type: shell
    command: [sh, -c, "env > {dump}/shell.env"]
  - id: script
    type: script
    runtime: sh
    script: dump.sh
    args: [{dump}/script.env]
  - id: agent
    type: agent
    prompt: "Say done."
  - id: loop
    type: loop
    prompt: "Say done."
    max_iterations: 1
    until_bash: [sh, -c, "env > {dump}/until.env"]
"""


def a_credentials_hub(root: Path) -> Path:
    """A hub whose ``staging`` declares a profile and a variable name, and the ``creds``
    workflow; ``root`` holds the hub folder and the fakes' ``bin``."""
    hub = root / "hub"
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env": ["DEMO_DB_URL"],
    }
    (hub / "workflows" / "demo" / "scripts").mkdir(parents=True)
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    dump = root / "dump"
    dump.mkdir()
    workflow = WORKFLOW.replace("{dump}", str(dump))
    (hub / "workflows" / "demo" / "creds.yaml").write_text(workflow)
    (hub / "workflows" / "demo" / "scripts" / "dump.sh").write_text('env > "$1"\n')
    fakes = root / "bin"
    fakes.mkdir()
    (fakes / "claude").write_text(FAKE_CLAUDE)
    (fakes / "claude").chmod(0o755)
    for tool in ("sh", "env"):
        found = shutil.which(tool)
        assert found is not None
        (fakes / tool).symlink_to(os.path.realpath(found))
    return hub


def run_hub(hub: Path, *args: str, env: dict[str, str]) -> Result:
    return CliRunner().invoke(app, list(args), env={"AGENT_HUB_ROOT": str(hub), **env})


def variables(path: Path) -> dict[str, str]:
    lines = path.read_text().splitlines()
    return dict(line.split("=", 1) for line in lines if "=" in line)


def stored_anywhere(secret: str, *roots: Path) -> list[str]:
    """The files under ``roots`` (or the files themselves) whose bytes hold ``secret``."""
    found = []
    for root in roots:
        files = [root] if root.is_file() else [path for path in root.rglob("*") if path.is_file()]
        found.extend(str(path) for path in files if secret.encode() in path.read_bytes())
    return found


@pytest.fixture
def credentials_env(tmp_path: Path) -> dict[str, Any]:
    return {
        "PATH": str(tmp_path / "bin"),
        "DUMP": str(tmp_path / "dump"),
        "DEMO_DB_URL": SECRET,
        "AWS_PROFILE": "demo-staging",
        "AGENT_HUB_DB": str(tmp_path / "events.db"),
    }


def test_hides_credentials_from_workflow_nodes_when_credential_injection_workflow_runs(
    tmp_path: Path, credentials_env: dict[str, str]
) -> None:
    hub = a_credentials_hub(tmp_path)

    result = run_hub(hub, "workflow", "run", "creds", "--live", env=credentials_env)

    assert result.exit_code == 0, result.output
    dumps = sorted(path.name for path in (tmp_path / "dump").iterdir())
    assert dumps == ["claude.env", "script.env", "shell.env", "until.env"]
    for dump in dumps:
        seen = variables(tmp_path / "dump" / dump)
        assert "DEMO_DB_URL" not in seen, dump
        assert "AWS_PROFILE" not in seen, dump
        assert seen["PATH"] == str(tmp_path / "bin")
    assert SECRET not in result.output
    assert stored_anywhere(SECRET, hub / ".agent-runs", tmp_path / "events.db") == []
