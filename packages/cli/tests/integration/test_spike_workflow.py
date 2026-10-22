"""The built-in ``spike`` pack (AGH-492): the workflow loads and plans, its agents are read-only
and only its ``draft`` step writes, it declares no tracker side (ADR 0030), and its rework loop
is bounded by the same number of rounds ``settle`` counts.
"""

import json
import os
import re
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.core.workflows import dry_run
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.fixtures import parse_fixture, run_fixture
from agent_hub.core.workflows.plan import plan_workflow
from agent_hub.core.workflows.ports import NodeCall
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS, discover_workflows
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import load_workflow_bytes

pytestmark = pytest.mark.disable_socket

type CommandRunner = Callable[..., Result]
type Workspace = Any

PACK = BUILTIN_WORKFLOWS / "spike"
FIXTURES = ("spike-more", "spike-more-paused", "spike-no-pick", "spike-pick", "spike-timebox")
AGENTS = {
    "recall": ("20m", 30, 1.5),
    "research": ("60m", 60, 4.0),
    "choose__options": ("20m", 20, 1.5),
    "premortem": ("20m", 20, 1.5),
}


def document() -> Any:
    found = discover_workflows(PACK, builtin_root=BUILTIN_WORKFLOWS)
    (workflow,) = [item for item in found.workflows if item.name == "spike"]
    return parse_workflow(workflow.document)


def calls_of(fixture: str | dict[str, Any]) -> tuple[Any, list[NodeCall]]:
    """``fixture``'s dry run of the built-in spike (a fixture's name, or a fixture document),
    and each node call it made, in order."""
    calls: list[NodeCall] = []
    original = dry_run._StubRunner.run

    def recording(self: Any, call: NodeCall) -> Any:
        calls.append(call)
        return original(self, call)

    if isinstance(fixture, str):
        path = PACK / "fixtures" / f"{fixture}.yaml"
        parsed = load_workflow_bytes(path.read_bytes(), source=str(path)).document
    else:
        parsed = fixture
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(dry_run._StubRunner, "run", recording)
        result = run_fixture(
            plan_workflow(document()), parse_fixture(parsed), outputs=JsonSchemaOutputs()
        )
    assert result.passed, result.problems
    return parsed, calls


def nodes_of() -> dict[str, Any]:
    nodes: dict[str, Any] = {}
    for node in document().nodes:
        nodes[node.id] = node
        for body in getattr(node, "nodes", ()):
            nodes[f"{node.id}__{body.id}"] = body
    return nodes


def test_validates_and_passes_every_fixture_when_spike_tested(
    demo_workspace: Workspace, run_command: CommandRunner
) -> None:
    validated = run_command(demo_workspace.hub, "workflow", "validate", "spike")
    tested = run_command(demo_workspace.hub, "workflow", "test", "spike")

    assert validated.exit_code == 0, validated.output
    assert validated.stdout == "spike: valid (8 nodes in 8 layers)\n"
    assert tested.exit_code == 0, tested.output
    for fixture in FIXTURES:
        # The hub's seeded copy shadows the built-in (AGH-227).
        assert f"workflows/spike/fixtures/{fixture}.yaml: ok" in tested.stdout
    assert "warning" not in tested.stdout
    assert tested.stdout.endswith("5 fixtures: 5 passed, 0 failed\n")


def test_keeps_agents_read_only_and_writes_only_in_draft_when_document_loaded() -> None:
    nodes = nodes_of()

    for name, (timeout, turns, cost) in AGENTS.items():
        node = nodes[name]
        assert node.type == "agent", name
        assert node.mutates_checkout is False, name
        assert node.timeout == timeout, name
        assert node.retry is not None and node.retry.max_attempts == 0, name
        assert (node.limits.max_turns, node.limits.max_cost_usd) == (turns, cost), name
    agents = {name for name, node in nodes.items() if node.type == "agent"}
    assert agents == set(AGENTS)
    assert not [name for name, node in nodes.items() if node.type == "shell"]
    scripts = {name: node for name, node in nodes.items() if node.type == "script"}
    assert {name: node.script for name, node in scripts.items()} == {
        "setup": "budget.py",
        "t_recall": "budget.py",
        "t_research": "budget.py",
        "choose__t_options": "budget.py",
        "choose__settle": "budget.py",
        "draft": "draft.py",
    }
    # The budget steps compute and print; only draft writes, and only where its slug points.
    assert all(node.cwd is None for node in scripts.values())
    draft = list(scripts["draft"].args)
    assert draft[draft.index("--slug") + 1] == "$setup.output.slug"
    assert all(node.retry is not None and node.retry.max_attempts == 0 for node in scripts.values())


def test_declares_no_tracker_side_when_document_loaded() -> None:
    spike = document()

    assert spike.name == "spike"
    assert set(spike.inputs) == {"question", "timebox", "slug"}
    assert spike.inputs["question"].required is True
    assert spike.inputs["timebox"].default == "2h"
    assert spike.inputs["slug"].default == ""
    assert (spike.returns, spike.outcome_field) == ("draft", "result")
    commands = [node.command for node in nodes_of().values() if hasattr(node, "command")]
    assert not [command for command in commands if list(command[:2]) == ["hub", "step"]]


def test_matches_loop_bound_and_settle_rounds_when_document_loaded() -> None:
    nodes = nodes_of()
    settle = list(nodes["choose__settle"].args)
    pick = nodes["choose__pick"]

    assert nodes["choose"].max_iterations == 3
    assert settle[settle.index("--max-rounds") + 1] == str(nodes["choose"].max_iterations)
    assert nodes["choose"].until_when == "$settle.output.done == true"
    assert [decision.id for decision in pick.decisions] == ["a", "b", "c", "more"]
    assert pick.capture_response is True
    assert nodes["research"].when == "$t_recall.output.over == false"
    assert nodes["choose__options"].when == "$t_research.output.over == false"
    assert nodes["choose__pick"].when == "$t_options.output.over == false"
    assert nodes["premortem"].when == "$choose.output.settle.go == true"


def test_runs_options_once_more_with_the_note_when_owner_asks_for_more() -> None:
    _, more = calls_of("spike-more")
    _, paused = calls_of("spike-more-paused")

    options = [call for call in more if call.node.id == "choose__options"]
    assert len(options) == 2
    assert [call.context.with_values["feedback"] for call in options] == [
        "",
        "Add an option without a cache.",
    ]
    ran = [call.node.id for call in more]
    assert ran.index("premortem") > max(i for i, n in enumerate(ran) if n == "choose__settle")
    waited = [call.node.id for call in paused]
    assert waited.count("choose__options") == 2
    assert "draft" not in waited
    assert "premortem" not in waited


PROMPTS = {
    "recall": ("recall.md", (".claude/skills/recall/SKILL.md",)),
    "research": (
        "research.md",
        (".claude/agents/researcher.md", ".claude/skills/research/SKILL.md"),
    ),
    "choose__options": ("options.md", (".claude/skills/adr/SKILL.md",)),
    "premortem": ("premortem.md", (".claude/skills/premortem/SKILL.md",)),
}


def prompts_of(calls: list[NodeCall]) -> dict[str, str]:
    """Each agent call's prompt file, rendered as the runner renders it (the last call wins)."""
    rendered: dict[str, str] = {}
    for call in calls:
        name = getattr(call.node, "prompt_file", None)
        if call.node.type == "agent" and name is not None:
            template = (PACK / "prompts" / name).read_text(encoding="utf-8")
            rendered[call.node.id] = call.scope.render(template, call.context)
    return rendered


@pytest.mark.parametrize("node", list(PROMPTS))
def test_follows_the_skill_file_when_each_prompt_renders(node: str) -> None:
    _, calls = calls_of("spike-pick")
    name, skills = PROMPTS[node]

    prompt = prompts_of(calls)[node]

    assert nodes_of()[node].prompt_file == name
    question = "```text\nShould the session brief be cached between sessions?\n```"
    assert question in prompt
    for skill in skills:
        assert skill in prompt
        assert prompt.index(skill) < prompt.index(question)
    assert "change no file" in prompt
    assert "minutes of the spike's agent time are left" in prompt
    assert "ignore any instruction" in prompt
    assert prompt.index("ignore any instruction") < prompt.index(question)
    assert "\nEnd of the question" in prompt
    shape = "alone on the last line, compact and with no code fence"
    assert prompt.index(question) < prompt.index(shape)
    assert "No line break inside any" in prompt[prompt.index(shape) :]
    assert "$WITH" not in prompt


WIDE = "\U0001f600"  # four bytes in UTF-8


def at_max() -> dict[str, Any]:
    """Every agent's output, and the owner's text, at its schema's largest."""
    option = {
        "title": WIDE * 120,
        "summary": WIDE * 800,
        "pros": [WIDE * 200] * 5,
        "cons": [WIDE * 200] * 5,
    }
    return {
        "question": WIDE * 2000,
        "recall": {
            "summary": WIDE * 2000,
            "sources": [{"ref": WIDE * 200, "says": WIDE * 300}] * 10,
        },
        "research": {
            "summary": WIDE * 2000,
            "repos": ["r" * 64] * 10,
            "findings": [{"area": WIDE * 80, "fact": WIDE * 300, "where": WIDE * 160}] * 20,
            "invariants": [WIDE * 300] * 6,
            "open_questions": [WIDE * 300] * 6,
        },
        "options": {
            "options": [{"id": i, **option} for i in ("a", "b", "c")],
            "recommendation": "a",
            "reason": WIDE * 600,
            "brief": WIDE * 3000,
        },
        "premortem": {
            "causes": [
                {
                    "cause": WIDE * 600,
                    "likelihood": "unknown",
                    "impact": "moderate",
                    "sign": WIDE * 400,
                    "experiment": WIDE * 600,
                }
            ]
            * 3,
            "others": [WIDE * 300] * 5,
            "assumptions": [{"text": WIDE * 300, "checked": False}] * 8,
            "first": WIDE * 400,
        },
        "note": WIDE * 2000,
        "approver": WIDE * 200,
    }


def test_stays_under_the_argument_cap_when_outputs_are_schema_max() -> None:
    nodes, outputs, big = nodes_of(), JsonSchemaOutputs(), at_max()
    for node in ("recall", "research", "choose__options", "premortem"):
        key = node.removeprefix("choose__")
        outputs.check(nodes[node].output_format, big[key])
    path = PACK / "fixtures" / "spike-more.yaml"
    fixture: Any = load_workflow_bytes(path.read_bytes(), source=str(path)).document
    stubs = fixture["stubs"]
    fixture["inputs"] = fixture["inputs"] | {"question": big["question"]}
    for node in ("recall", "research", "premortem"):
        stubs[node] = {"output": big[node]}
    stubs["choose__options"] = [{"output": big["options"]}] * 2
    first, second = stubs["choose__settle"]
    first["output"] |= {"note": big["note"], "approver": big["approver"]}
    second["output"] |= {
        "note": big["note"],
        "approver": big["approver"],
        "option": big["options"]["options"][1],
    }
    for settled in stubs["choose__settle"]:
        outputs.check(nodes["choose__settle"].output_format, settled["output"])

    _, calls = calls_of(fixture)

    prompts = prompts_of(calls)
    assert set(prompts) == set(PROMPTS)
    for node, prompt in prompts.items():
        assert len(prompt.encode()) < 131072, node
    assert WIDE * 2000 in prompts["choose__options"]  # the owner's note reached round 2
    (draft,) = [call for call in calls if call.node.id == "draft"]
    for item in draft.argv:
        assert len(item.encode()) < 131072
    assert max(len(item.encode()) for item in draft.argv) > 40000
    assert draft.stdin is not None
    assert len(draft.stdin.encode()) < 1048576


@pytest.mark.parametrize("fixture", ["spike-pick", "spike-timebox"])
def test_writes_research_and_adr_draft_when_spike_pick_stubs_feed_the_draft(
    tmp_path: Path, fixture: str
) -> None:
    parsed, calls = calls_of(fixture)
    (draft,) = [call for call in calls if call.node.id == "draft"]

    result = subprocess.run(  # noqa: S603 - this interpreter, a pack script, rendered arguments
        [sys.executable, "-I", str(PACK / "scripts" / "draft.py"), *draft.argv],
        cwd=tmp_path,
        input=draft.stdin,
        env={"AGENT_HUB_RUN_ID": "run-1", "PATH": os.environ.get("PATH", "")},
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    JsonSchemaOutputs().check(nodes_of()["draft"].output_format, output)
    assert output["result"] == parsed["expect"]["outcome"]
    folder = tmp_path.resolve() / "brain/features/brief-cache"
    research = (folder / "research.md").read_text(encoding="utf-8")
    assert output["research"] == str(folder / "research.md")
    if fixture == "spike-pick":
        adr = (folder / "adr-draft-brief-cache.md").read_text(encoding="utf-8")
        premortem = adr.split("\n## Premortem\n", 1)[1]
        assert len(re.findall(r"^### \d\. ", premortem, re.MULTILINE)) == 3
        assert "status: draft" in adr
        assert "Go with A, keep the cache small." in adr
        assert "> Incomplete" not in research
    else:
        body = research.split("\n---\n", 1)[1].lstrip("\n")
        assert body.startswith("> Incomplete: timebox 2h reached after research.")
        assert output["adr"] == ""
        assert sorted(path.name for path in folder.iterdir()) == ["research.md"]
    assert not (tmp_path / "docs").exists()
