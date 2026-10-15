"""The built-in ``sdlc`` pack (AGH-229, AC-213.17): ``deliver`` and ``review`` load and plan, their
fixtures pass, every lens declares the review JSON of ``hub validate-output review`` as its
output_format, the review stubs are valid review outputs, and the pack's Python scripts print what
their nodes declare.
"""

import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.core.features.agent_outputs import review_problems
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import load_workflow_bytes

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "sdlc"
REVIEW_SCHEMA = Path(__file__).parents[3] / "core/src/agent_hub/core/features/review.v1.json"
FIXTURES = (
    "deliver-check-error",
    "deliver-green",
    "deliver-max-rounds",
    "deliver-rework",
    "review-fail",
    "review-lens-failed",
    "review-pass",
)
LENSES = {"review": ("spec", "quality"), "deliver": ("rounds__spec", "rounds__quality")}


def nodes_of(name: str) -> dict[str, Any]:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == name]
    document = parse_workflow(workflow.document)
    nodes: dict[str, Any] = {}
    for node in document.nodes:
        nodes[node.id] = node
        for body in getattr(node, "nodes", ()):
            nodes[f"{node.id}__{body.id}"] = body
    return nodes


def resolved(schema: Any, defs: dict[str, Any]) -> Any:
    """``schema`` with each local ``$ref`` inlined and its titles and descriptions dropped."""
    if isinstance(schema, list):
        return [resolved(item, defs) for item in schema]
    if not isinstance(schema, dict):
        return schema
    if "$ref" in schema:
        return resolved(defs[schema["$ref"].removeprefix("#/$defs/")], defs)
    skipped = {"$defs", "title", "description"}
    return {key: resolved(value, defs) for key, value in schema.items() if key not in skipped}


def script(name: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    path = PACK / "scripts" / name
    return subprocess.run(  # noqa: S603 - this interpreter, a pack script, fixed arguments
        [sys.executable, "-I", str(path), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )


def test_validates_and_passes_every_fixture_when_deliver_and_review_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "deliver")
    reviewed = run_command(demo_workspace.hub, "workflow", "validate", "review")
    tested = run_command(demo_workspace.hub, "workflow", "test", "deliver", "review")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "deliver: valid (5 nodes in 5 layers)\n"
    assert reviewed.exit_code == 0, reviewed.output
    assert reviewed.stdout == "review: valid (3 nodes in 2 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/sdlc/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert tested.stdout.endswith("7 fixtures: 7 passed, 0 failed\n")


def test_prints_each_node_without_running_when_deliver_dry_run(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    given = ("--input", "issue=DEM-1", "--input", "repo=demo-api", "--input", "issue_text=x")

    result = run_command(demo_workspace.hub, "workflow", "run", "deliver", *given)

    assert result.exit_code == 0, result.output
    lines = unstyle(result.stdout).splitlines()
    worktree = "hub step worktree --issue '$INPUTS.issue' --repo '$INPUTS.repo'"
    assert lines[0] == f"would run: worktree (shell): {worktree}"
    # The group's body, layer by layer, under the group.
    assert [line.split(" (")[0] for line in lines[1:]] == [
        "would run: rounds",
        "  would run: rounds__implement",
        "  would run: rounds__check",
        "  would run: rounds__spec",
        "  would run: rounds__quality",
        "  would run: rounds__verdict",
        "would run: commits",
        "would run: pr",
        "would run: report",
    ]
    assert lines[3] == (
        "  would run: rounds__check (script): python scripts/check.py"
        " '$worktree.output.check' '$LOOP_PREV.rounds__check.output.round'"
    )


@pytest.mark.parametrize("workflow", ["review", "deliver"])
def test_declares_the_review_schema_when_a_lens_runs(workflow: str) -> None:
    review = json.loads(REVIEW_SCHEMA.read_text(encoding="utf-8"))
    nodes = nodes_of(workflow)

    for lens in LENSES[workflow]:
        node = nodes[lens]
        assert node.mutates_checkout is False, lens
        assert resolved(node.output_format, {}) == resolved(review, review["$defs"]), lens


def test_stubs_valid_review_outputs_when_fixtures_stub_a_lens() -> None:
    checked = 0
    for path in sorted((PACK / "fixtures").glob("*.yaml")):
        stubs = load_workflow_bytes(path.read_bytes(), source=str(path)).document["stubs"]
        for node_id, stub in stubs.items():
            if node_id.rsplit("__", 1)[-1] not in {"spec", "quality"}:
                continue
            for one in stub if isinstance(stub, list) else [stub]:
                if "output" not in one:
                    continue
                output = one["output"]
                name = f"{output['reviewer']}-r{output['round']}.json"
                content = json.dumps(output).encode()
                assert review_problems(content, file_name=name, folder_name=output["ticket"]) == ()
                checked += 1
    assert checked >= 8


@pytest.mark.parametrize(
    ("command", "previous", "expected"),
    [
        ("echo fine", "", {"passed": True, "exit_code": 0, "round": 1, "tail": "fine\n"}),
        (
            "echo bad >&2; exit 3",
            "2",
            {"passed": False, "exit_code": 3, "round": 3, "tail": "bad\n"},
        ),
    ],
)
def test_prints_the_check_result_and_exits_zero_when_check_script_runs(
    tmp_path: Path, *, command: str, previous: str, expected: dict[str, Any]
) -> None:
    result = script("check.py", command, previous, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output == expected
    JsonSchemaOutputs().check(nodes_of("deliver")["rounds__check"].output_format, output)


def test_keeps_only_the_last_bytes_when_check_output_is_long(tmp_path: Path) -> None:
    result = script("check.py", "printf 'a%.0s' $(seq 1 9000); printf END", "", cwd=tmp_path)

    tail = json.loads(result.stdout)["tail"]
    assert len(tail) == 4000
    assert tail.endswith("aEND")


@pytest.mark.parametrize("previous", ["x", "-1", "1.5"])
def test_exits_two_when_check_script_gets_a_bad_round(tmp_path: Path, previous: str) -> None:
    result = script("check.py", "true", previous, cwd=tmp_path)

    assert (result.returncode, result.stdout) == (2, "")


@pytest.mark.parametrize(
    ("spec", "quality", "verdict"),
    [("PASS", "PASS", "PASS"), ("PASS", "FAIL", "FAIL"), ("FAIL", "PASS", "FAIL")],
)
def test_passes_only_when_both_lenses_pass_when_verdict_script_runs(
    tmp_path: Path, *, spec: str, quality: str, verdict: str
) -> None:
    result = script("verdict.py", "--spec", spec, "--quality", quality, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output == {"verdict": verdict, "lenses": {"spec": spec, "quality": quality}}
    for workflow, node in (("review", "verdict"), ("deliver", "rounds__verdict")):
        JsonSchemaOutputs().check(nodes_of(workflow)[node].output_format, output)


def test_exits_two_when_verdict_script_gets_an_unknown_verdict(tmp_path: Path) -> None:
    result = script("verdict.py", "--spec", "PASS", "--quality", "", cwd=tmp_path)

    assert result.returncode == 2
    assert result.stdout == ""
