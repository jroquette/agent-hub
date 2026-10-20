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
import subprocess
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import workflow_command
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


ACTION = """\
version: 1
name: show-env
description: Show what the action sees
effect: read
runtime: sh
script: scripts/show-env.sh
output_format:
  type: object
  required: [seen, token]
"""
ACTION_SCRIPT = """\
cat > /dev/null
env > "$DUMP/action.env"
printf '{"seen": "%s", "token": "%s"}' "$DEMO_DB_URL" "$DEMO_TOKEN"
"""
ENV_FILE = "demo-api/environment/.env.staging"


def an_action_hub(root: Path) -> Path:
    """``a_credentials_hub`` whose ``staging`` also names an env file, with the committed read
    action ``ops/show-env``."""
    hub = a_credentials_hub(root)
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["staging"]["credentials"]["env_file"] = ENV_FILE
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    env_file = hub.parent / ENV_FILE
    env_file.parent.mkdir(parents=True)
    env_file.write_text(f"# staging\nexport DEMO_TOKEN='{SECRET}-file'\n")
    pack = hub / "actions" / "ops"
    (pack / "scripts").mkdir(parents=True)
    (pack / "show-env.yaml").write_text(ACTION)
    (pack / "scripts" / "show-env.sh").write_text(ACTION_SCRIPT)
    git = shutil.which("git")
    assert git is not None
    for tool in ("git", "cat"):
        found = shutil.which(tool)
        assert found is not None
        (root / "bin" / tool).symlink_to(os.path.realpath(found))
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    for args in (("init", "-q", "-b", "main"), ("add", "-A"), ("commit", "-q", "-m", "hub")):
        command = [git, *identity, *args]
        subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments
    return hub


def test_injects_credentials_only_into_action_when_credential_injection_runs(
    tmp_path: Path, credentials_env: dict[str, str]
) -> None:
    hub = an_action_hub(tmp_path)

    result = run_hub(hub, "action", "run", "ops/show-env", "--env", "staging", env=credentials_env)

    assert result.exit_code == 0, result.output
    seen = variables(tmp_path / "dump" / "action.env")
    assert seen["AWS_PROFILE"] == "demo-staging"
    assert seen["DEMO_DB_URL"] == SECRET
    assert seen["DEMO_TOKEN"] == SECRET + "-file"
    assert json.loads(result.stdout) == {
        "seen": "<credential DEMO_DB_URL>",
        "token": "<credential DEMO_TOKEN>",
    }
    assert SECRET not in result.output
    assert stored_anywhere(SECRET, hub / ".agent-runs", tmp_path / "events.db") == []
    assert (tmp_path / "events.db").exists()


QUOTED_SECRET = "x-" + 'sec"r' + "\\" + "ét-y"
QUOTED_ACTION = """\
version: 1
name: show-quoted
description: Print the quoted value JSON escaped
effect: read
runtime: sh
script: scripts/show-quoted.sh
output_format: {type: object}
"""


def test_hides_escaped_credential_when_credential_injection_output_parsed(
    tmp_path: Path, credentials_env: dict[str, str]
) -> None:
    hub = an_action_hub(tmp_path)
    env_file = hub.parent / ENV_FILE
    escaped = QUOTED_SECRET.replace("\\", "\\\\").replace('"', '\\"')
    env_file.write_text(env_file.read_text() + f'DEMO_QUOTED="{escaped}"\n')
    printed = json.dumps({"seen": QUOTED_SECRET})
    pack = hub / "actions" / "ops"
    (pack / "show-quoted.yaml").write_text(QUOTED_ACTION)
    (pack / "scripts" / "show-quoted.sh").write_text(f"cat > /dev/null\nprintf '%s' '{printed}'\n")
    git = shutil.which("git")
    assert git is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    for args in (("add", "-A"), ("commit", "-q", "-m", "quoted")):
        command = [git, *identity, *args]
        subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments

    result = run_hub(
        hub, "action", "run", "ops/show-quoted", "--env", "staging", env=credentials_env
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"seen": "<credential DEMO_QUOTED>"}
    assert QUOTED_SECRET not in result.output
    assert stored_anywhere(QUOTED_SECRET, hub / ".agent-runs", tmp_path / "events.db") == []


HUB_STEP_WORKFLOW = """\
version: 1
name: step-creds
revision: 1
nodes:
  - id: step
    type: shell
    command: [hub, step, verdict]
"""


def test_hides_credentials_from_hub_step_when_credential_injection_workflow_runs(
    tmp_path: Path, credentials_env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = a_credentials_hub(tmp_path)
    (hub / "workflows" / "demo" / "step-creds.yaml").write_text(HUB_STEP_WORKFLOW)
    shell = os.path.realpath(shutil.which("sh") or "/bin/sh")
    # The hub this node runs, played by a shell that writes its environment.
    program = (shell, "-c", 'env > "$DUMP/hubstep.env"', "hub")
    monkeypatch.setattr(workflow_command, "own_hub_program", lambda: program)

    result = run_hub(hub, "workflow", "run", "step-creds", "--live", env=credentials_env)

    assert result.exit_code == 0, result.output
    seen = variables(tmp_path / "dump" / "hubstep.env")
    assert "DEMO_DB_URL" not in seen
    assert "AWS_PROFILE" not in seen
    assert seen["DUMP"] == str(tmp_path / "dump")
