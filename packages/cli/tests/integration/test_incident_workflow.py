"""The built-in ``incident`` pack (AGH-483): the workflow loads and plans, its fixtures pass, its
nodes are read-only where they read and write no tracker (ADR 0030), its agents' replies are
bounded by their output_format, and its prompts fence the untrusted text.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.substitution import RefContext, canonical_text, render
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import load_workflow_bytes

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "incident"
WORKFLOW = PACK / "incident.yaml"
READ_ONLY = ("evidence", "check", "mitigation")
PROMPTS = {
    "recall": ("recall.md", ("evidence",)),
    "hypotheses": ("hypotheses.md", ("report", "evidence", "recall")),
    "postmortem": ("postmortem.md", ("report", "check", "mitigation")),
}
ALLOWED = ("git", "grep", "test", "ls", "cat", "head", "tail", "wc")
GIT_SUBCOMMANDS = (
    "log",
    "show",
    "diff",
    "grep",
    "blame",
    "ls-files",
    "ls-tree",
    "cat-file",
    "rev-parse",
    "merge-base",
    "rev-list",
)
MAX_ARGUMENT_BYTES = 131072
WRITERS = ("handoff", "note")
WIDE = "\U0001f600"  # four bytes in UTF-8
FIXTURES = (
    "incident-awaiting-mitigation",
    "incident-confirmed",
    "incident-mitigation-declined",
    "incident-none-confirmed",
)


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


def raw_document() -> dict[str, Any]:
    document: dict[str, Any] = load_workflow_bytes(
        WORKFLOW.read_bytes(), source=str(WORKFLOW)
    ).document
    return document


def a_hypothesis(n: int, *, wide: str = WIDE) -> dict[str, Any]:
    return {
        "id": f"H{n}",
        "rank": n,
        "statement": wide * 500,
        "repo": "a" * 64,
        "check": [wide * 256] * 16,
        "confirms_when": wide * 300,
        "mitigation": {"summary": wide * 300, "undo": wide * 300},
    }


def a_postmortem(*, follow_ups: int = 10) -> dict[str, Any]:
    return {
        "title": WIDE * 120,
        "summary": WIDE * 1000,
        "timeline": [{"at": WIDE * 40, "what": WIDE * 300}] * 30,
        "root_cause": WIDE * 2000,
        "detection_gap": WIDE * 2000,
        "what_fixed_it": WIDE * 2000,
        "follow_ups": [WIDE * 300] * follow_ups,
        "learnings": [{"target": WIDE * 200, "text": WIDE * 1000}] * 5,
    }


def a_recall(matches: int = 10) -> dict[str, Any]:
    return {"matches": [{"path": WIDE * 300, "why": WIDE * 400}] * matches, "summary": WIDE * 1000}


def test_validates_and_passes_every_fixture_when_incident_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "incident")
    tested = run_command(demo_workspace.hub, "workflow", "test", "incident")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "incident: valid (10 nodes in 10 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/incident/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning" not in tested.stdout
    assert tested.stdout.endswith("4 fixtures: 4 passed, 0 failed\n")


def test_declares_read_only_nodes_and_no_tracker_step_when_document_loaded() -> None:
    document, nodes = raw_document(), nodes_of("incident")

    assert set(document["inputs"]) == {"report", "since"}
    assert document["inputs"]["since"]["default"] == "72h"
    assert document["inputs"]["report"]["required"] is True
    assert "issue" not in document["inputs"]
    assert "environment" not in document
    assert document["returns"] == "note"
    assert document["outcome_field"] == "status"
    # The one hub step node reads hub.json for the scripts (AGH-480) and writes nothing.
    shells = [node for node in document["nodes"] if node["type"] == "shell"]
    assert [node["command"] for node in shells] == [["hub", "step", "config"]]
    for node_id in READ_ONLY:
        assert nodes[node_id].effect == "read", node_id
    for node_id in WRITERS:
        assert "effect" not in next(n for n in document["nodes"] if n["id"] == node_id)
        assert nodes[node_id].effect is None, node_id
    executable = {key: node for key, node in nodes.items() if hasattr(node, "mutates_checkout")}
    assert set(executable) == {*nodes} - {"mitigate"}
    for node_id, node in executable.items():
        assert node.mutates_checkout is (node_id in WRITERS), node_id
        assert node.retry is not None and node.retry.max_attempts == 0, node_id
    mitigate = nodes["mitigate"]
    assert [decision.id for decision in mitigate.decisions] == ["record", "none"]
    assert mitigate.capture_response is True
    assert "$check.output.mitigations" in mitigate.when
    assert "$mitigate.output.decision" in nodes["mitigation"].when
    assert nodes["handoff"].trigger_rule == "none_failed_min_one_success"


@pytest.mark.parametrize(
    ("node", "value", "passes"),
    [
        ("hypotheses", {"hypotheses": [a_hypothesis(n) for n in range(1, 6)]}, True),
        ("hypotheses", {"hypotheses": [a_hypothesis(n % 5 + 1) for n in range(6)]}, False),
        ("hypotheses", {"hypotheses": []}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["x" * 257]}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["x"] * 17}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "check": ["a\nb"]}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "id": "H6"}]}, False),
        ("hypotheses", {"hypotheses": [{**a_hypothesis(1), "mitigation": None}]}, True),
        ("recall", a_recall(), True),
        ("recall", a_recall(11), False),
        ("postmortem", a_postmortem(), True),
        ("postmortem", a_postmortem(follow_ups=11), False),
    ],
    ids=[
        "hypotheses-at-bounds",
        "six-hypotheses",
        "no-hypothesis",
        "argv-element-257",
        "argv-17-elements",
        "argv-control-char",
        "id-h6",
        "no-mitigation",
        "recall-at-bounds",
        "recall-11-matches",
        "postmortem-at-bounds",
        "postmortem-11-follow-ups",
    ],
)
def test_bounds_agent_replies_when_outputs_validated(
    node: str, value: dict[str, Any], *, passes: bool
) -> None:
    schema = nodes_of("incident")[node].output_format
    outputs = JsonSchemaOutputs()

    if passes:
        outputs.check(schema, value)
    else:
        with pytest.raises(NodeFailedError):
            outputs.check(schema, value)


def prompt(node: str, values: dict[str, Any]) -> str:
    """``node``'s prompt file rendered with its ``with`` values."""
    file, _ = PROMPTS[node]
    text = (PACK / "prompts" / file).read_text(encoding="utf-8")
    return render(text, RefContext({}, {}, with_values=values))


@pytest.mark.parametrize("node", sorted(PROMPTS))
def test_renders_untrusted_text_inside_fences_when_prompts_render(node: str) -> None:
    _, names = PROMPTS[node]
    values: dict[str, Any] = {name: f"<<{name} value>>" for name in names}
    values |= {"handoff": "brain/_inbox/x-handoff.md"}

    text = prompt(node, values)

    first_fence = text.index("```text\n")
    instructions = " ".join(text[:first_fence].split()).lower()
    assert "ignore any instruction" in instructions
    assert "read-only" in instructions
    for name in names:
        at = text.index(f"<<{name} value>>")
        assert at > first_fence, name
        assert text.rfind("```text\n", 0, at) > text.rfind("\n```\n", 0, at), name
        assert text.index("\n```\nEnd of", at) > at, name
    assert "$WITH" not in text
    assert text.rstrip().endswith("JSON.")


def test_names_the_allow_list_when_hypotheses_prompt_renders() -> None:
    text = prompt("hypotheses", {"report": "r", "evidence": "e", "recall": "c"})
    instructions = " ".join(text[: text.index("```text\n")].split())

    assert "no shell" in instructions
    for program in ALLOWED:
        assert f"`{program}`" in instructions, program
    for subcommand in GIT_SUBCOMMANDS:
        assert f"`{subcommand}`" in instructions, subcommand
    for option in ("--output", "-O", "--ext-diff", "--textconv", "--no-index", "tail -f"):
        assert option in instructions, option
    assert "at most 5" in instructions
    assert "undo" in instructions
    assert "relative" in instructions


def test_points_the_agents_at_the_hub_skills_when_prompts_render() -> None:
    recall = prompt("recall", {"evidence": "e"})
    postmortem = prompt(
        "postmortem",
        {"report": "r", "check": "c", "mitigation": "", "handoff": "brain/_inbox/h.md"},
    )

    assert ".claude/skills/recall/SKILL.md" in recall
    assert "brain/_inbox/" in recall
    assert "verify-" in recall
    assert ".claude/skills/learn/SKILL.md" in postmortem
    assert "Blameless" in postmortem
    assert "brain/_inbox/h.md" in postmortem
    assert "/triage" in postmortem


def an_evidence_at_cap() -> dict[str, Any]:
    """The evidence at its 48 KiB cap: what ``evidence.py`` prints is at most that long."""
    commit: Any = {
        "sha": "0" * 40,
        "at": "x" * 25,
        "subject": "s" * 200,
        "merge": False,
        "paths": [],
        "more_paths": 0,
    }
    repo = {"dir": "api", "ref": "origin/main", "head": "0" * 40, "more_commits": 0, "tags": []}
    evidence: dict[str, Any] = {
        "since": "72h",
        "since_iso": "x" * 25,
        "repos": [repo | {"commits": []}],
        "unreadable": [],
        "left_out": [],
        "trimmed": True,
    }
    cap, each = 48 * 1024, len(canonical_text(commit).encode()) + 1
    room = (cap - len(canonical_text(evidence).encode())) // each + 1
    size = cap + 1
    while size > cap:
        room -= 1
        evidence["repos"] = [repo | {"commits": [commit] * 100}] * (room // 100)
        evidence["repos"].append(repo | {"commits": [commit] * (room % 100)})
        size = len(canonical_text(evidence).encode())
    assert cap - 2 * each < size
    return evidence


def a_check_at_bounds() -> dict[str, Any]:
    result = {
        "id": "H1",
        "rank": 1,
        "repo": "a" * 64,
        "status": "confirmed",
        "exit_code": 0,
        "reason": WIDE * 200,
        "tail": WIDE * 1000,
    }
    return {"results": [result] * 5, "confirmed": 5, "mitigations": 5, "menu": WIDE * 4096}


def test_stays_under_the_prompt_cap_when_inputs_are_at_their_bound() -> None:
    nodes, outputs = nodes_of("incident"), JsonSchemaOutputs()
    report = WIDE * (32768 // 4)
    evidence, recall, check = an_evidence_at_cap(), a_recall(), a_check_at_bounds()
    hypotheses: Any = {"hypotheses": [a_hypothesis(n) for n in range(1, 6)]}
    mitigation: Any = {
        "id": "H1",
        "summary": WIDE * 2000,
        "undo": WIDE * 300,
        "source": "owner",
        "approver": WIDE * 200,
    }
    for node, value in (
        ("evidence", evidence),
        ("recall", recall),
        ("check", check),
        ("hypotheses", hypotheses),
        ("mitigation", mitigation),
    ):
        outputs.check(nodes[node].output_format, value)
    assert len(report.encode()) == 32768
    prompts = {
        "recall": prompt("recall", {"evidence": evidence}),
        "hypotheses": prompt(
            "hypotheses", {"report": report, "evidence": evidence, "recall": recall}
        ),
        "postmortem": prompt(
            "postmortem",
            {
                "report": report,
                "check": check,
                "mitigation": mitigation,
                "handoff": "brain/_inbox/x.md",
            },
        ),
    }

    for node, text in prompts.items():
        assert len(text.encode()) < MAX_ARGUMENT_BYTES, node
    # The script nodes' argv elements that carry an output.
    for value in (check, hypotheses, mitigation, evidence["repos"]):
        assert len(canonical_text(value).encode()) < MAX_ARGUMENT_BYTES


def script(name: str, *args: str, cwd: Path, stdin: str) -> Any:
    """Run the pack's script ``name`` as the engine would (its own interpreter, no shell); its
    JSON output. A failure fails the test."""
    done = subprocess.run(  # noqa: S603 - this interpreter, a pack script, fixed arguments
        [sys.executable, "-I", str(PACK / "scripts" / name), *args],
        cwd=cwd,
        input=stdin,
        env={**os.environ, "AGENT_HUB_RUN_ID": "0123456789abcdef"},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    assert done.returncode == 0, (name, done.stderr)
    return json.loads(done.stdout)


def checkout_state(workspace: Workspace, repo: Path) -> tuple[str, ...]:
    return tuple(
        workspace.git(repo, *args)
        for args in (
            ("rev-parse", "HEAD"),
            ("branch", "--show-current"),
            ("status", "--porcelain"),
            ("worktree", "list", "--porcelain"),
        )
    )


@pytest.mark.parametrize(
    ("pattern", "status"), [("BUG", "draft"), ("NOT_THERE", "open")], ids=["confirmed", "none"]
)
def test_writes_handoff_and_postmortem_when_scripts_chain_on_real_git(
    pattern: str, status: str, demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    nodes, outputs = nodes_of("incident"), JsonSchemaOutputs()
    hub, repo = demo_workspace.hub, demo_workspace.ws / "demo-api"
    (repo / "app.py").write_text("BUG = True\n", encoding="utf-8")
    demo_workspace.git(repo, "add", "app.py")
    demo_workspace.git(
        repo, "-c", "user.name=T", "-c", "user.email=t@example.com", "commit", "-qm", "feat: app"
    )
    # As last fetched: the evidence reads origin/<branch>, never the local branch.
    demo_workspace.git(repo, "update-ref", "refs/remotes/origin/trunk", "HEAD")
    (repo / "notes.txt").write_text("the owner's work in progress\n", encoding="utf-8")
    before = checkout_state(demo_workspace, repo)
    report = "Checkout fails since Tuesday. ```\npasted log\n```"
    reply = {
        "hypotheses": [
            {
                "id": "H1",
                "rank": 1,
                "statement": "app.py sets BUG.",
                "repo": "demo-api",
                "check": ["git", "grep", "-q", pattern, "--", "app.py"],
                "confirms_when": "Found.",
                "mitigation": {"summary": "Revert the app commit.", "undo": "Re-apply it."},
            },
            {
                "id": "H2",
                "rank": 2,
                "statement": "A file is missing.",
                "repo": "demo-api",
                "check": ["test", "-f", "missing.txt"],
                "confirms_when": "It exists.",
                "mitigation": None,
            },
            {
                "id": "H3",
                "rank": 3,
                "statement": "Anything.",
                "repo": "demo-api",
                "check": ["sh", "-c", "true"],
                "confirms_when": "Always.",
                "mitigation": None,
            },
        ]
    }

    # The workflow's config node: the real hub step config output, as --config takes it.
    config = run_command(hub, "step", "config")
    assert config.exit_code == 0, config.output
    evidence = script(
        "evidence.py", "--since", "72h", "--config", config.stdout, cwd=hub, stdin=report
    )
    check = script(
        "check.py", "--repos", json.dumps(evidence["repos"]), cwd=hub, stdin=json.dumps(reply)
    )
    confirmed = check["mitigations"] > 0
    mitigation = (
        script(
            "mitigation.py",
            "--check",
            json.dumps(check),
            "--text",
            "H1",
            "--approver",
            "Jo",
            cwd=hub,
            stdin=json.dumps(reply),
        )
        if confirmed
        else ""
    )
    handoff = script(
        "inbox.py",
        "handoff",
        "--hypotheses",
        json.dumps(reply),
        "--check",
        json.dumps(check),
        "--mitigation",
        json.dumps(mitigation) if mitigation else "",
        "--decision",
        "record" if confirmed else "",
        cwd=hub,
        stdin=report,
    )
    stub = {
        "title": "Checkout fails",
        "summary": "s",
        "timeline": [],
        "root_cause": "r",
        "detection_gap": "d",
        "what_fixed_it": "",
        "follow_ups": ["f"],
        "learnings": [],
    }
    note = script(
        "inbox.py",
        "postmortem",
        "--confirmed",
        str(check["confirmed"]),
        "--handoff",
        handoff["path"],
        cwd=hub,
        stdin=json.dumps(stub),
    )

    for node, value in (
        ("evidence", evidence),
        ("check", check),
        ("handoff", handoff),
        ("note", note),
        *((("mitigation", mitigation),) if mitigation else ()),
    ):
        outputs.check(nodes[node].output_format, value)
    assert [r["dir"] for r in evidence["repos"]] == ["demo-api", "demo-web"]
    assert evidence["repos"][0]["commits"][0]["paths"] == ["app.py"]
    statuses = [result["status"] for result in check["results"]]
    assert statuses == ["confirmed" if confirmed else "failed", "failed", "refused"]
    assert note["status"] == status
    assert handoff["path"].startswith("brain/_inbox/incident-")
    assert handoff["path"].endswith("-01234567-handoff.md")
    assert (hub / handoff["path"]).is_file()
    text = (hub / note["path"]).read_text(encoding="utf-8")
    assert f"\nstatus: {status}\n" in text
    assert "\nprovenance: agent\n" in text
    assert checkout_state(demo_workspace, repo) == before
    assert len(before[3].strip().split("\n\n")) == 1
