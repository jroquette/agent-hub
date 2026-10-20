"""``hub action list|plan|run`` (AC-350.11, .12, .28, .46; docs/design/scenarios.md).

Each test builds a workspace under ``tmp_path``: a hub (``hub.json`` with the environments of
``an_environments_document``) holding the ``demo`` action pack, a git checkout with its own
identity, and runs the command in process with ``AGENT_HUB_ROOT`` naming the hub. Every script
appends its stdin to the file ``MARKER`` names, so a test sees which mode ran, if any.
"""

import json
import shutil
import subprocess
from importlib.metadata import version
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.storage.event_store import open_event_store

SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
case "$stdin" in
  *'"mode": "plan"'*) printf '{"summary": "would act"}' ;;
  *) printf '{"order": "o-1"}' ;;
esac
"""
ACTION = """\
version: 1
name: {name}
description: A demo {effect}
effect: {effect}
runtime: sh
script: scripts/{name}.sh
inputs:
  target: {{type: service, required: true}}
  count: {{type: integer, default: 1}}
output_format:
  type: object
  required: [order]
  properties: {{order: {{type: string}}}}
"""


def git(hub: Path, *args: str) -> None:
    found = shutil.which("git")
    assert found is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    command = [found, *identity, *args]
    subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def write_action(hub: Path, name: str, effect: str) -> None:
    pack = hub / "actions" / "demo"
    (pack / "scripts").mkdir(parents=True, exist_ok=True)
    (pack / f"{name}.yaml").write_text(ACTION.format(name=name, effect=effect))
    (pack / "scripts" / f"{name}.sh").write_text(SCRIPT)


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """A committed hub with the read action ``get-order`` and the write ``send-order``."""
    root = tmp_path / "workspace" / "hub"
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (root / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    write_action(root, "get-order", "read")
    write_action(root, "send-order", "write")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "demo hub")
    return root


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


def run_action_command(hub: Path, marker: Path, *args: str, **env: str) -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **env,
    }
    return CliRunner().invoke(app, ["action", *args], env=environ, input="")


def modes(marker: Path) -> list[str]:
    if not marker.exists():
        return []
    return [json.loads(line)["mode"] for line in marker.read_text().splitlines()]


def stored(hub: Path) -> list[tuple[str, dict[str, object]]]:
    database = hub.parent.parent / "events.db"
    if not database.exists():
        return []
    return [(event.type, event.payload) for event in open_event_store(database).read_all()]


def test_lists_actions_with_draft_when_list_runs(hub: Path, marker: Path) -> None:
    write_action(hub, "fix-order", "destroy")
    (hub / "actions" / "demo" / "scripts" / "get-order.sh").write_text(SCRIPT + "\n")

    result = run_action_command(hub, marker, "list")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "demo/fix-order  destroy  target (service), count (integer)  draft",
        "demo/get-order  read  target (service), count (integer)  draft",
        "demo/send-order  write  target (service), count (integer)",
    ]
    listed = json.loads(run_action_command(hub, marker, "list", "--json").stdout)
    assert [(item["action"], item["draft"]) for item in listed["actions"]] == [
        ("demo/fix-order", True),
        ("demo/get-order", True),
        ("demo/send-order", False),
    ]
    assert listed["actions"][2]["inputs"] == {"target": "service", "count": "integer"}
    assert modes(marker) == []


def test_prints_no_actions_yet_when_empty_hub(tmp_path: Path, marker: Path) -> None:
    root = tmp_path / "workspace" / "hub"
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (root / "hub.json").write_text(json.dumps(document) + "\n")

    result = run_action_command(root, marker, "list")

    assert (result.exit_code, result.stdout) == (0, "no actions yet\n")


@pytest.mark.parametrize(
    "args",
    [
        ("plan", "demo/get-order"),
        ("plan", "demo/get-order", "--env", "staging", "--input", "no-equals"),
        ("run", "demo/get-order", "--env"),
        ("unknown",),
        ("list", "--yes"),
        ("run", "demo/send-order", "--env", "staging", "--yes"),
    ],
)
def test_exits_two_when_action_usage_wrong(hub: Path, marker: Path, args: tuple[str, ...]) -> None:
    result = run_action_command(hub, marker, *args)

    assert result.exit_code == 2, result.output
    assert modes(marker) == []


def test_starts_no_run_process_when_standalone_plan(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "plan", "demo/send-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "action: demo/send-order (write)",
        "environment: staging (access ask)",
        "inputs: target=api, count=1",
        "endpoints: target → demo-api/api https://api.staging.example.com",
        f"content hash: {content_hash(hub, 'send-order')}",
        "draft: no",
        "plan: would act",
        "decision: ask",
    ]
    assert modes(marker) == ["plan"]
    assert stored(hub) == []


def test_exits_one_naming_reason_when_standalone_plan_denies(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "plan", "send-order", "--env", "live", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stdout.splitlines()[-1] == (
        "decision: deny (live is a production environment: writes and destroys are denied)"
    )


@pytest.mark.parametrize(
    "case",
    [
        (("--env", "qa", "--input", "target=api"), "environment qa is not declared"),
        (("--env", "live", "--input", "target=orders"), "has no endpoint in environment live"),
        (
            ("--env", "staging", "--input", "target=api", "--input", "count=two"),
            "input count must be of type integer",
        ),
        (
            (
                "--env",
                "staging",
            ),
            "input target is required",
        ),
    ],
)
def test_exits_one_naming_problem_when_standalone_plan_cannot_resolve(
    hub: Path, marker: Path, case: tuple[tuple[str, ...], str]
) -> None:
    given, line = case

    result = run_action_command(hub, marker, "plan", "demo/get-order", *given)

    assert result.exit_code == 1, result.output
    assert line in result.stderr
    assert modes(marker) == []


def content_hash(hub: Path, name: str) -> str:
    listed = json.loads(
        CliRunner()
        .invoke(app, ["action", "list", "--json"], env={"AGENT_HUB_ROOT": str(hub)})
        .stdout
    )
    return next(item["content_hash"] for item in listed["actions"] if item["name"] == name)
