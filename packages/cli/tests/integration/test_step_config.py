"""``hub step config``: the hub.json values a pack script needs, read through the CLI's loader.

Each runs in process in a copy of the ``DEMO`` workspace. The output is one JSON object: the
project's branch facts, the developer's branch prefix (``hub.local.json`` first, as ``hub run``
reads it), the tracker's ready label and team keys, and each repo's GitHub name, effective
default branch and gates, plus a target skeleton ``hub step commits|pr`` read back. No token or
tracker key is printed, and nothing is written.
"""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
KEY_VALUE = "lin" + "_api_" + "x" * 40
GH_TOKEN_VALUE = "gh" + "o_" + "y" * 36
UNTITLED = {
    "branch": "",
    "commit_title": "",
    "pr_title": "",
    "titles_configured": False,
    "pr_title_explicit": False,
}


@pytest.fixture(autouse=True)
def tokens(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, KEY_VALUE)
    monkeypatch.setenv("GH_TOKEN", GH_TOKEN_VALUE)


def config_of(run_command: CommandRunner, hub: Path, *args: str) -> dict[str, Any]:
    result = run_command(hub, "step", "config", *args)
    assert result.exit_code == 0, result.output
    value = json.loads(result.stdout)
    assert isinstance(value, dict)
    return value


def hub_document(hub: Path) -> dict[str, Any]:
    value = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def test_prints_project_tracker_and_repo_values_when_config_read(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    hub = demo_workspace.hub
    document = hub_document(hub)

    output = config_of(run_command, hub)

    project = document["project"]
    assert output["default_branch"] == project["default_branch"]
    assert output["hub"] == {
        "github": project["hub_repo"],
        "default_branch": project["default_branch"],
        "target": {
            "github": project["hub_repo"],
            "default_branch": project["default_branch"],
            "conventions": UNTITLED,
        },
    }
    assert output["ready_label"] == document["tracker"].get("ready_label", "agent-ready")
    assert output["branch_prefix"]
    assert [repo["dir"] for repo in output["repos"]] == [repo["dir"] for repo in document["repos"]]
    for printed, declared in zip(output["repos"], document["repos"], strict=True):
        branch = declared.get("default_branch") or project["default_branch"]
        assert printed == {
            "dir": declared["dir"],
            "github": declared["github"],
            "default_branch": branch,
            "check_fast": declared.get("check_fast"),
            "check": declared["check"],
            "target": {
                "github": declared["github"],
                "default_branch": branch,
                "conventions": UNTITLED,
            },
        }
    assert "branch" not in output


def test_names_the_team_keys_when_tracker_declares_them(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    hub = demo_workspace.hub
    tracker = hub_document(hub)["tracker"]

    output = config_of(run_command, hub)

    declared = [tracker["team"]] if "team" in tracker else list(tracker.get("teams", []))
    assert declared
    assert output["teams"] == declared


def test_prints_no_token_or_tracker_key_when_config_read(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    result = run_command(demo_workspace.hub, "step", "config")

    assert result.exit_code == 0, result.output
    assert KEY_VALUE not in result.output
    assert GH_TOKEN_VALUE not in result.output
    assert KEY_VARIABLE not in result.output
    assert len(result.stdout.encode()) < 64 * 1024


def test_prints_nothing_when_config_over_size_cap(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    from agent_hub.cli import step_command

    monkeypatch.setattr(step_command, "MAX_CONFIG_BYTES", 64)

    result = run_command(demo_workspace.hub, "step", "config")

    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert "the config is larger than 0 KiB" in result.output


def test_takes_local_branch_prefix_first_when_hub_local_json_sets_one(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    hub = demo_workspace.hub
    local = hub / "hub.local.json"
    value = json.loads(local.read_text(encoding="utf-8")) if local.is_file() else {}
    value.setdefault("project", {})["branch_prefix"] = "zed/"
    local.write_text(json.dumps(value), encoding="utf-8")

    output = config_of(run_command, hub)

    assert output["branch_prefix"] == "zed/"


def test_prints_the_branch_under_the_prefix_when_branch_and_slug_given(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    hub = demo_workspace.hub

    output = config_of(run_command, hub, "--branch", "DEM-12", "--slug", "bump-platform")

    assert output["branch_name"] == "dem-12-bump-platform"
    assert output["branch"] == f"{output['branch_prefix']}dem-12-bump-platform"


def test_takes_the_slug_from_the_run_id_when_run_slug_given(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "20261023-abc123")

    output = config_of(
        run_command, demo_workspace.hub, "--branch", "brain-care-inbox", "--run-slug"
    )

    assert output["branch_name"] == "brain-care-inbox-20261023-abc123"
    assert output["branch"] == f"{output['branch_prefix']}brain-care-inbox-20261023-abc123"


def test_refuses_run_slug_when_no_run_id_set(
    demo_workspace: Workspace, run_command: CommandRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("AGENT_HUB_RUN_ID", raising=False)

    result = run_command(
        demo_workspace.hub, "step", "config", "--branch", "doc-drift", "--run-slug"
    )

    assert result.exit_code == 2
    assert "AGENT_HUB_RUN_ID" in result.output


@pytest.mark.parametrize(
    "args",
    [
        ("--branch", "../up", "--slug", "x"),
        ("--branch", "doc-drift"),
        ("--slug", "x"),
        ("--branch", "doc-drift", "--slug", "x", "--run-slug"),
        ("--branch", "doc-drift", "--slug", "Not A Slug"),
    ],
)
def test_refuses_branch_options_when_name_or_slug_bad(
    demo_workspace: Workspace, run_command: CommandRunner, args: tuple[str, ...]
) -> None:
    result = run_command(demo_workspace.hub, "step", "config", *args)

    assert result.exit_code == 2, result.output
    assert result.stdout == ""


def test_writes_nothing_when_config_read(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    hub = demo_workspace.hub
    before = sorted(path.relative_to(hub) for path in hub.rglob("*"))

    config_of(run_command, hub)

    assert sorted(path.relative_to(hub) for path in hub.rglob("*")) == before


def test_prints_null_prefix_when_no_source_gives_one(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    demo_workspace.drop_identity()

    output = config_of(run_command, demo_workspace.hub)

    assert output["branch_prefix"] is None
    assert output["author_name"] is None
    assert output["author_email"] is None


def test_refuses_branch_when_no_source_gives_a_prefix(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    demo_workspace.drop_identity()

    result = run_command(
        demo_workspace.hub, "step", "config", "--branch", "doc-drift", "--slug", "x"
    )

    assert result.exit_code == 2, result.output
    assert result.stdout == ""


def test_prints_the_author_when_hub_json_sets_it(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    project = hub_document(demo_workspace.hub)["project"]

    output = config_of(run_command, demo_workspace.hub)

    assert output["author_name"] == project["author_name"]
    assert output["author_email"] == project["author_email"]
