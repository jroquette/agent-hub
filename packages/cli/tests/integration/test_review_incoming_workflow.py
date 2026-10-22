"""The built-in ``review-incoming`` pack (AGH-493): someone else's PR through the spec, quality and
security lenses, drafted as one review the owner edits and approves; ``/review`` reads the PR
and posts it after the run. The document loads and plans, the run can make no GitHub call and
holds no push, the lenses are read-only and fresh, and every agent reply is bounded.
"""

import json
import re
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "review-incoming"
INPUTS = {"repo", "pr", "ref", "pr_file", "ci_file", "spec_file"}
LENSES = ("spec", "quality", "security")
READ_ONLY = ("fetch", "check", "surface", *LENSES, "draft")
# What the run must never do: call GitHub, run a hub step, push, or move a ref.
FORBIDDEN = re.compile(r"\bgh |hub step|\bpush|update-ref")
# The engine's cap on one argument (an argv element) and on a prompt.
ARGUMENT_CAP = 131072
WIDE = "\U0001d11e"


def nodes_of() -> dict[str, Any]:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "review-incoming"]
    document = parse_workflow(workflow.document)
    return {node.id: node for node in document.nodes}


def document_of() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "review-incoming"]
    return parse_workflow(workflow.document)


def passes(schema: Any, value: Any) -> bool:
    try:
        JsonSchemaOutputs().check(schema, value)
    except NodeFailedError:
        return False
    return True


def a_finding(number: int, *, width: int = 400, char: str = WIDE) -> dict[str, Any]:
    return {
        "id": f"F{number}".ljust(32, "x"),
        "kind": "security",
        "severity": "blocking",
        "path": char * 300,
        "line": 10000000,
        "acs": ["A" * 64 for _ in range(10)],
        "what": char * width,
        "expected": char * 400,
    }


def a_lens(reviewer: str, *, findings: int = 15, coverage: int = 0) -> dict[str, Any]:
    return {
        "reviewer": reviewer,
        "commit": "0" * 40,
        "verdict": "FAIL",
        "findings": [a_finding(n) for n in range(1, findings + 1)],
        "coverage": [
            {"ac": "A" * 64, "status": "not testable", "test": WIDE * 160} for _ in range(coverage)
        ],
    }


def a_comment(*, sources: tuple[str, ...] = ("security:F1",)) -> dict[str, Any]:
    return {
        "path": WIDE * 300,
        "line": None,
        "severity": "blocking",
        "body": WIDE * 1500,
        "sources": list(sources),
    }


def a_draft(*, comments: int = 30, sources: tuple[str, ...] = ("security:F1",)) -> dict[str, Any]:
    return {"summary": WIDE * 3000, "comments": [a_comment(sources=sources)] * comments}


def test_validates_and_passes_every_fixture_when_review_incoming_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "review-incoming")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "review-incoming: valid (11 nodes in 8 layers)\n"


def test_runs_no_github_call_when_document_loaded() -> None:
    document, nodes = document_of(), nodes_of()

    assert [node.type for node in nodes.values() if node.type == "shell"] == []
    for node in nodes.values():
        for arg in getattr(node, "args", ()):
            assert not FORBIDDEN.search(arg), (node.id, arg)
        prompt_file = getattr(node, "prompt_file", None)
        if prompt_file is not None:
            text = (PACK / "prompts" / prompt_file).read_text(encoding="utf-8")
            assert not FORBIDDEN.search(text), node.id
    for path in sorted((PACK / "scripts").glob("*.py")):
        assert not FORBIDDEN.search(path.read_text(encoding="utf-8")), path.name
    assert set(document.inputs) == INPUTS
    assert [decision.id for decision in nodes["gate"].decisions] == [
        "comment",
        "request-changes",
        "approve",
        "reject",
    ]
    assert nodes["gate"].capture_response is False
    assert nodes["final"].when == "$gate.output.decision != 'reject'"
    assert document.returns == "final"
    assert document.outcome_field == "event"


def test_declares_read_only_lenses_when_document_loaded() -> None:
    nodes = nodes_of()

    for node_id in READ_ONLY:
        assert nodes[node_id].mutates_checkout is False, node_id
    for lens in LENSES:
        assert nodes[lens].cwd == "$fetch.output.path", lens
        assert nodes[lens].context == "fresh", lens
    assert nodes["draft"].context == "fresh"
    assert nodes["security"].when == "$surface.output.risky == true"
    assert nodes["security"].model == "large"
    assert nodes["findings"].trigger_rule == "none_failed_min_one_success"
    for node in nodes.values():
        if hasattr(node, "retry"):
            assert node.retry is not None, node.id
            assert node.retry.max_attempts == 0, node.id


def test_bounds_agent_replies_when_outputs_validated() -> None:
    nodes = nodes_of()
    spec, draft = nodes["spec"].output_format, nodes["draft"].output_format
    widest = a_lens("spec", coverage=50)

    assert passes(spec, widest)
    for lens in ("quality", "security"):
        assert passes(nodes[lens].output_format, a_lens(lens))
        assert not passes(nodes[lens].output_format, a_lens(lens, coverage=1)), lens
    assert passes(draft, a_draft())
    # A lens at its bounds still fits one argument of the findings script.
    assert len(json.dumps(widest, ensure_ascii=False).encode()) < ARGUMENT_CAP
    assert not passes(spec, a_lens("spec", findings=16))
    too_long = a_lens("spec", findings=1)
    too_long["findings"] = [a_finding(1, width=401, char="x")]
    assert not passes(spec, too_long)
    assert not passes(spec, a_lens("quality"))
    assert not passes(draft, a_draft(comments=31))
    assert not passes(draft, a_draft(sources=("tracker:F1",)))
    assert not passes(draft, a_draft(sources=("security:F1 now",)))
