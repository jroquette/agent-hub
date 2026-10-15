"""The built-in ``issue-to-pr`` workflow (AGH-223): it loads and plans, its fixtures pass, its
prompt is ``hub run``'s, and what ``hub step`` prints matches the output_format each node declares.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.issue_block import issue_block
from agent_hub.core.runner.session_prompt import implementing_prompt, prompt_parts
from agent_hub.core.testing.builders import an_issue
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.substitution import NodeResult, RefContext, render
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "issue-to-pr"
OUTCOMES = (
    "done",
    "no-commit",
    "blocked",
    "dirty",
    "error",
    "gate-failure",
    "pr-failure",
    "from-verify",
)


def node_formats() -> dict[str, Any]:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "issue-to-pr"]
    document = parse_workflow(workflow.document)
    return {node.id: getattr(node, "output_format", None) for node in document.nodes}


def test_validates_and_passes_every_fixture_when_pack_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "issue-to-pr")
    tested = run_command(demo_workspace.hub, "workflow", "test", "issue-to-pr")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "issue-to-pr: valid (7 nodes in 7 layers)\n"
    assert tested.exit_code == 0, tested.output
    for outcome in OUTCOMES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/issue-to-pr/fixtures/{outcome}.yaml: ok" in tested.stdout
    assert tested.stdout.endswith("8 fixtures: 8 passed, 0 failed\n")


@pytest.mark.parametrize("sensitive", [(), ("hub.json", "docs/adr")])
def test_renders_hub_run_prompt_when_prompt_file_filled(sensitive: tuple[str, ...]) -> None:
    issue = an_issue()
    parts = prompt_parts(
        sensitive=sensitive,
        fast_gate="make check-fast",
        full_gate="make check",
        issue_id=issue.id,
        prefix="DEM-",
    )
    worktree: JsonValue = {"branch": "jdoe/dem-1", "hub": "/ws/hub", "hub_name": "hub"}
    context = RefContext(
        {"issue": issue.id, "repo": "demo-api", "issue_text": issue_block(issue)},
        {"worktree": NodeResult("completed", {**worktree, "prompt": dict(parts)})},
    )

    rendered = render((PACK / "prompts" / "implement.md").read_text(encoding="utf-8"), context)

    today = implementing_prompt(
        issue,
        repo="demo-api",
        branch="jdoe/dem-1",
        hub="/ws/hub",
        hub_name="hub",
        sensitive=sensitive,
        fast_gate="make check-fast",
        full_gate="make check",
        prefix="DEM-",
    )
    assert rendered == today


def test_prints_declared_output_when_steps_run(
    run_workspace: Workspace, run_command: CommandRunner
) -> None:
    workspace = run_workspace.workspace
    formats, outputs = node_formats(), JsonSchemaOutputs()
    issue = ("--issue", "DEM-1", "--repo", "demo-api")
    worktree = workspace.ws / "demo-api" / ".claude" / "worktrees" / "dem-1"
    identity = ("-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com")
    target: list[str] = []
    steps = {
        "worktree": ("worktree", *issue),
        "verdict": ("verdict",),
        "commits": ("commits", "--target"),
        "pr": ("pr", "--issue", "DEM-1", "--summary", "Adds it.", "--target"),
        "report": ("report", "--status", "done", "--commits", "1", "--pr", "https://x/1"),
    }

    for node_id, args in steps.items():
        given = (*args, *target) if args[-1] == "--target" else args
        result = run_command(workspace.hub, "step", *given)
        assert result.exit_code == 0, result.output
        output = json.loads(result.stdout)
        outputs.check(formats[node_id], output)
        if node_id == "worktree":
            target.append(json.dumps(output["target"]))
            (worktree / "change.txt").write_text("change\n")
            workspace.git(worktree, "add", "change.txt")
            workspace.git(worktree, *identity, "commit", "-q", "-m", "feat(api): it (DEM-1)")


def test_shows_stdin_when_dry_run_prints_verdict_node(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    # issue_text is the parent's to fill (from the tracker); a dry run reads no tracker.
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api")

    result = run_command(demo_workspace.hub, "workflow", "run", "issue-to-pr", *given)

    assert result.exit_code == 0, result.output
    assert "would run: verdict (shell): hub step verdict   stdin: $implement.output" in (
        result.stdout.splitlines()
    )
