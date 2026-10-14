"""``hub workflow list|validate`` over a hub's ``workflows/`` packs (AC-213.1, AC-213.3).

Each case builds a hub under ``tmp_path`` and points the built-ins at a folder of its own, so the
packs the platform ships never change what a case sees.
"""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import workflow_command
from agent_hub.cli.main import app

CHECK_YAML = """\
version: 1
name: check
revision: 1
description: Lint, then test.
nodes:
  - id: lint
    type: shell
    command: [make, lint]
  - id: test
    type: shell
    command: [make, test]
    depends_on: [lint]
"""


@pytest.fixture
def builtins(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> Path:
    folder = tmp_path_factory.mktemp("builtin")
    monkeypatch.setattr(workflow_command, "BUILTIN_WORKFLOWS", folder)
    return folder


@pytest.fixture
def hub(tmp_path: Path, builtins: Path) -> Path:
    (tmp_path / "hub.json").write_text("{}\n")
    (tmp_path / "workflows" / "demo").mkdir(parents=True)
    return tmp_path


def write(root: Path, relative: str, text: str) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


def run(hub: Path, *args: str) -> Result:
    return CliRunner().invoke(app, ["workflow", *args], env={"AGENT_HUB_ROOT": str(hub)})


def test_lists_each_workflow_when_every_file_loads(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    deliver = {
        "version": 1,
        "name": "deliver",
        "revision": 2,
        "nodes": [{"id": "a", "type": "halt", "reason": "x"}],
    }
    write(hub, "workflows/ship/deliver.json", json.dumps(deliver))

    result = run(hub, "list")

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test.", "deliver  1 nodes"]


def test_lists_nothing_when_hub_has_no_workflows_folder(tmp_path: Path, builtins: Path) -> None:
    (tmp_path / "hub.json").write_text("{}\n")

    result = run(tmp_path, "list")

    assert (result.exit_code, result.stdout) == (0, "")


def test_lists_the_loading_ones_and_exits_one_when_a_file_is_broken(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    write(hub, "workflows/demo/broken.yaml", "version: 1\nname: broken\nname: again\n")

    result = run(hub, "list")

    assert result.exit_code == 1
    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test."]
    assert result.stderr.startswith("workflows/demo/broken.yaml:3: $: ")


def test_validates_each_workflow_when_every_file_loads(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)

    result = run(hub, "validate")

    assert result.exit_code == 0, result.output
    assert result.stdout == "check: valid (2 nodes in 2 layers)\n"


def test_names_file_line_and_key_when_validate_finds_load_errors(hub: Path) -> None:
    write(
        hub,
        "workflows/demo/check.yaml",
        CHECK_YAML.replace(
            "    command: [make, lint]\n", "    command: [make, lint]\n    promt: x\n"
        ),
    )
    write(
        hub,
        "workflows/demo/cycle.yaml",
        "version: 1\nname: cycle\nrevision: 1\nnodes:\n"
        "  - id: a\n    type: halt\n    reason: x\n    depends_on: [b]\n"
        "  - id: b\n    type: halt\n    reason: x\n    depends_on: [a]\n",
    )

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        "workflows/demo/check.yaml:9: nodes[0].promt: unknown key",
        "workflows/demo/cycle.yaml:8: nodes[0].depends_on: a cycle runs through the nodes a, b",
    ]


def test_checks_only_the_named_workflow_when_validate_gets_a_name(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)
    write(hub, "workflows/demo/broken.yaml", "version: 1\nname: broken\nname: again\n")

    result = run(hub, "validate", "check")

    assert (result.exit_code, result.stdout) == (0, "check: valid (2 nodes in 2 layers)\n")


def test_exits_one_when_validate_names_no_workflow(hub: Path) -> None:
    result = run(hub, "validate", "ghost")

    assert result.exit_code == 1
    assert result.stderr == "no workflow named ghost in workflows/ or the built-ins\n"


def test_refuses_the_file_when_it_is_over_the_size_cap(hub: Path) -> None:
    write(hub, "workflows/demo/check.yaml", CHECK_YAML + "#" * (256 * 1024) + "\n")

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stderr.startswith("workflows/demo/check.yaml: $: the file is over 262144 bytes")


def test_refuses_the_file_when_it_links_out_of_its_pack(
    hub: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    target = write(tmp_path_factory.mktemp("elsewhere"), "check.yaml", CHECK_YAML)
    (hub / "workflows" / "demo" / "check.yaml").symlink_to(target)

    result = run(hub, "validate")

    assert result.exit_code == 1
    assert result.stderr.startswith("workflows/demo/check.yaml: $: a link that leaves its pack")


def test_overrides_the_builtin_when_hub_has_a_workflow_of_its_name(
    hub: Path, builtins: Path
) -> None:
    write(builtins, "base/check.yaml", CHECK_YAML.replace("Lint, then test.", "Built in."))
    write(builtins, "base/broken.yaml", "version: 1\nname: broken\nname: again\n")
    write(hub, "workflows/demo/check.yaml", CHECK_YAML)

    result = run(hub, "list")

    assert result.stdout.splitlines() == ["check  2 nodes  Lint, then test."]
    assert result.stderr.startswith("<builtin>/base/broken.yaml:3: $: ")


def test_exits_two_when_folder_is_not_a_hub(tmp_path: Path, builtins: Path) -> None:
    result = run(tmp_path, "list")

    assert result.exit_code == 2
    assert "not a hub" in result.stderr
