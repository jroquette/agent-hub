"""``hub workflow list|validate`` over a hub's ``workflows/`` packs (AC-213.1, AC-213.3)."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    (tmp_path / "hub.json").write_text("{}\n")
    (tmp_path / "workflows" / "demo").mkdir(parents=True)
    return tmp_path


def write_workflow(hub: Path, name: str, *, pack: str = "demo", **top: object) -> Path:
    document: dict[str, object] = {
        "version": 1,
        "name": name,
        "revision": 1,
        "nodes": [
            {"id": "lint", "type": "shell", "command": ["make", "lint"]},
            {"id": "test", "type": "shell", "command": ["make", "test"], "depends_on": ["lint"]},
        ],
    } | top
    path = hub / "workflows" / pack / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2))
    return path


def run(hub: Path, *args: str) -> Result:
    return CliRunner().invoke(app, ["workflow", *args], env={"AGENT_HUB_ROOT": str(hub)})


def test_lists_each_workflow_when_every_file_loads(hub: Path) -> None:
    write_workflow(hub, "check", description="Lint, then test.")
    write_workflow(hub, "deliver", pack="ship")

    result = run(hub, "list")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test.", "deliver  2 nodes"]


def test_lists_nothing_when_hub_has_no_workflows_folder(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_text("{}\n")

    result = run(tmp_path, "list")

    assert (result.exit_code, result.stdout) == (0, "")


def test_lists_the_loading_ones_and_exits_one_when_a_file_is_broken(hub: Path) -> None:
    write_workflow(hub, "check")
    (hub / "workflows" / "demo" / "broken.json").write_text('{"version": 1,\n  "name": }')

    result = run(hub, "list")

    assert result.exit_code == 1
    assert result.stdout.splitlines() == ["check  2 nodes"]
    assert result.stderr.startswith("workflows/demo/broken.json:2: $: not valid JSON")


def test_validates_each_workflow_when_every_file_loads(hub: Path) -> None:
    write_workflow(hub, "check")

    result = run(hub, "validate")

    assert result.exit_code == 0, result.output
    assert result.stdout == "check: valid (2 nodes in 2 layers)\n"


def test_names_file_and_key_when_validate_finds_a_load_error(hub: Path) -> None:
    write_workflow(hub, "check", effort="high")
    write_workflow(
        hub,
        "cycle",
        nodes=[
            {"id": "a", "type": "shell", "command": ["true"], "depends_on": ["b"]},
            {"id": "b", "type": "shell", "command": ["true"], "depends_on": ["a"]},
        ],
    )

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "workflows/demo/check.json: effort: unknown key",
        "workflows/demo/cycle.json: nodes[0].depends_on: a cycle runs through the nodes a, b",
    ]


def test_checks_only_the_named_workflow_when_validate_gets_a_name(hub: Path) -> None:
    write_workflow(hub, "check")
    write_workflow(hub, "broken", returns="ghost")

    result = run(hub, "validate", "check")

    assert (result.exit_code, result.stdout) == (0, "check: valid (2 nodes in 2 layers)\n")


def test_exits_one_when_validate_names_no_workflow(hub: Path) -> None:
    result = run(hub, "validate", "ghost")

    assert result.exit_code == 1
    assert result.stderr == "no workflow named ghost in workflows/\n"


def test_refuses_the_file_when_it_is_a_link(
    hub: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    target = write_workflow(tmp_path_factory.mktemp("elsewhere"), "check")
    (hub / "workflows" / "demo" / "check.json").symlink_to(target)

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert "check.json: $: not a regular file" in result.stderr


def test_exits_two_when_folder_is_not_a_hub(tmp_path: Path) -> None:
    result = run(tmp_path, "list")

    assert result.exit_code == 2
    assert "not a hub" in result.stderr
