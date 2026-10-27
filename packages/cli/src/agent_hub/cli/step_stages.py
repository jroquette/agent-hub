"""The ``implement`` workflow's agent stages, for a session that conducts a ticket itself.

``/implement`` runs each stage of a ticket as a subagent of the session (ADR 0050) instead of a
``claude -p`` child of ``hub workflow run``. The subagent's prompt and its output contract are
the workflow's own, read here from the workflows the hub would run (its own ``workflows/`` over
the built-ins, ``discover_workflows``), never copied into the skill. ``STAGES`` names each stage's
workflow and agent node; ``stage_prompt`` renders the node's ``prompt_file`` with the ``with``
values given (exactly the node's ``with`` names), as the engine renders it; ``stage_output``
reads a subagent's reply as the workflow's agent runner does (its last JSON line, else the whole
text) and checks it against the node's ``output_format`` with the engine's validator, so the
record steps get the value a workflow run would give them.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.runner.verdict import last_json_line
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import AgentNode, LoopGroupNode
from agent_hub.core.workflows.substitution import RefContext, SubstitutionError, render
from agent_hub.generator.workflow_discovery import (
    PackPathError,
    discover_workflows,
    resolve_pack_file,
)
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs


@dataclass(frozen=True, kw_only=True, slots=True)
class Stage:
    """A ticket stage's agent node: the workflow that holds it and its id there."""

    workflow: str
    node: str


class StageName(StrEnum):
    """The ticket stages a session runs as subagents with the workflow's prompts."""

    PREFLIGHT = "preflight"
    TICKET_PLAN = "ticket-plan"
    SPEC_LENS = "spec-lens"
    QUALITY_LENS = "quality-lens"
    TICKET_EVAL = "ticket-eval"


STAGES: Final[Mapping[StageName, Stage]] = {
    StageName.PREFLIGHT: Stage(workflow="preflight-check", node="preflight"),
    StageName.TICKET_PLAN: Stage(workflow="ticket-pass", node="plan"),
    StageName.SPEC_LENS: Stage(workflow="ticket-pass", node="spec"),
    StageName.QUALITY_LENS: Stage(workflow="ticket-pass", node="quality"),
    StageName.TICKET_EVAL: Stage(workflow="implement", node="eval"),
}


class StageError(AgentHubError):
    """The stage cannot be read, rendered or its output checked; the message says why."""


def stage_node(hub: Path, stage: StageName) -> tuple[AgentNode, Path]:
    """The stage's agent node and its pack's root, from the workflows the hub would run."""
    wanted = STAGES[stage]
    found = next((w for w in discover_workflows(hub).workflows if w.name == wanted.workflow), None)
    if found is None:
        raise StageError(f"the hub has no workflow {wanted.workflow}")
    try:
        document = parse_workflow(found.document)
    except WorkflowLoadError as error:
        raise StageError(f"workflow {wanted.workflow} does not load: {error}") from None
    nodes = [
        inner
        for node in document.nodes
        for inner in (node.nodes if isinstance(node, LoopGroupNode) else (node,))
    ]
    node = next((n for n in nodes if n.id == wanted.node), None)
    if not isinstance(node, AgentNode) or node.prompt_file is None:
        raise StageError(f"workflow {wanted.workflow} has no agent node {wanted.node}")
    return node, found.pack_root


def stage_prompt(hub: Path, stage: StageName, values: Mapping[str, str]) -> str:
    """The stage's prompt, its ``prompt_file`` rendered with ``values`` as its ``$WITH``."""
    node, pack_root = stage_node(hub, stage)
    names = set(node.with_)
    if missing := sorted(names - values.keys()):
        raise StageError(f"give --with for {', '.join(missing)}")
    if unknown := sorted(values.keys() - names):
        raise StageError(
            f"{stage} takes no {', '.join(unknown)}; it takes {', '.join(sorted(names))}"
        )
    try:
        template = resolve_pack_file(pack_root, "prompts", node.prompt_file or "").read_text(
            encoding="utf-8"
        )
    except (PackPathError, OSError, UnicodeDecodeError) as error:
        raise StageError(f"cannot read prompts/{node.prompt_file}: {error}") from None
    with_values: dict[str, JsonValue] = dict(values)
    try:
        return render(template, RefContext({}, {}, with_values=with_values))
    except SubstitutionError as error:
        raise StageError(str(error)) from None


def stage_output(hub: Path, stage: StageName, reply: str) -> dict[str, JsonValue]:
    """The subagent's ``reply`` as the stage's output: its last JSON line (else the whole text,
    which must be one JSON value), checked against the node's ``output_format``."""
    node, _pack_root = stage_node(hub, stage)
    found = last_json_line(reply)
    text = json.dumps(found) if found is not None else reply
    try:
        value: JsonValue = json.loads(text)
    except ValueError, RecursionError:
        raise StageError("the reply holds no JSON object on its last line") from None
    if node.output_format is not None:
        try:
            JsonSchemaOutputs().check(node.output_format, value)
        except NodeFailedError as error:
            raise StageError(error.detail or error.kind) from None
    if not isinstance(value, dict):
        raise StageError("the output is not a JSON object")
    return value
