"""The flow catalog: one Markdown row per built-in workflow, derived, never kept by hand (AGH-495).

Each column comes from what the platform already ships:

- **Use when**: the first sentence of the workflow's ``description``, the line hub web's
  Workflows cards show first. A workflow without one (no description, a blank one, or fewer than
  ``MIN_USE_WHEN_WORDS`` words) is what ``missing_use_when`` names.
- **Start**, by the first rule that holds: a workflow ``hub run`` takes
  (``TRACKER_WORKFLOWS``) starts with ``./hub run``; one a hub skill template runs
  (``./hub workflow run <name>``) starts with that skill; one another workflow of its pack
  includes runs inside it; any other starts with ``./hub workflow run <name>``.
- **Your gates**: the ``approval`` nodes and the ``wait`` nodes with ``attention`` of the planned
  workflow (includes expanded), in order, each by its description or its own id, once.
- **Skills and agents inside**: the ``.claude/skills/<name>/SKILL.md`` and
  ``.claude/agents/<name>.md`` paths its agent and loop prompts name (inline, or the pack's
  prompt file).

Only package data is read: the built-ins (discovery's file budget) and the skill templates. A
built-in that does not plan is left out; the built-ins' own tests own loading. ``builtin_flows``
is cached per pair of roots, as the README placeholder is built on every render.
"""

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import Final

from agent_hub.core.workflows.document import WorkflowDocument, WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.launch import TRACKER_WORKFLOWS
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    IncludeNode,
    LoopGroupNode,
    LoopNode,
    WaitNode,
)
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.rewrite import SEPARATOR
from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    DiscoveredWorkflow,
    PackPathError,
    discover_builtins,
    pack_resolver,
    resolve_pack_file,
)

SKILL_TEMPLATES: Final = Path(
    str(files("agent_hub.generator").joinpath("templates", "plugin", "hub-workflow", "skills"))
)
MIN_USE_WHEN_WORDS: Final = 4
FLOW_HEADER: Final = "| Flow | Use when | Start | Your gates | Skills and agents inside |"
FLOW_FOOTER: Final = (
    "Any flow can also start from `hub web` (Workflow runs › Start run; `issue-to-pr` only"
    " through `./hub run`), or by itself from `hub.json` → `schedules` (a time) and `events`"
    " (a merge, a new PR, a red CI run). Each pack's file suggests its own entries."
)

_RUNS_WORKFLOW: Final = re.compile(r"\./hub workflow run ([a-z][a-z0-9-]*)")
_SKILL_PATH: Final = re.compile(r"\.claude/skills/([a-z0-9][a-z0-9-]*)/SKILL\.md")
_AGENT_PATH: Final = re.compile(r"\.claude/agents/([a-z0-9][a-z0-9-]*)\.md")
_SENTENCE: Final = re.compile(r"^(.+?[.!?])(?:\s|$)", re.DOTALL)


@dataclass(frozen=True, kw_only=True, slots=True)
class Flow:
    """One built-in workflow as the catalog shows it."""

    name: str
    pack: str
    use_when: str | None
    starts: tuple[str, ...]
    gates: tuple[str, ...]
    inside: tuple[str, ...]


@cache
def builtin_flows(
    builtin_root: Path = BUILTIN_WORKFLOWS, skills_root: Path = SKILL_TEMPLATES
) -> tuple[Flow, ...]:
    """Every built-in that plans, sorted by pack, then name."""
    discovery = discover_builtins(builtin_root)
    starters = _skill_starters(skills_root)
    documents = {w.name: _parsed(w) for w in discovery.workflows}
    includers = _includers(discovery.workflows, documents)
    flows: list[Flow] = []
    for workflow in discovery.workflows:
        document = documents[workflow.name]
        if document is None:
            continue
        try:
            plan = plan_workflow(document, includes=pack_resolver(discovery, workflow.pack_root))
        except WorkflowLoadError:
            continue
        flows.append(
            Flow(
                name=workflow.name,
                pack=workflow.pack,
                use_when=_use_when(document.description),
                starts=_starts(workflow.name, starters, includers),
                gates=_gates(plan),
                inside=_inside(plan, workflow.pack_root),
            )
        )
    return tuple(sorted(flows, key=lambda flow: (flow.pack, flow.name)))


def missing_use_when(flows: Iterable[Flow]) -> tuple[str, ...]:
    """The flows whose "use when" line is missing or under ``MIN_USE_WHEN_WORDS`` words."""
    return tuple(
        flow.name
        for flow in flows
        if flow.use_when is None or len(flow.use_when.split()) < MIN_USE_WHEN_WORDS
    )


def flow_table(flows: Iterable[Flow]) -> str:
    """The Markdown table of ``flows``, a blank line and ``FLOW_FOOTER``; ends with a newline."""
    rows = [FLOW_HEADER, "|---|---|---|---|---|", *(_row(flow) for flow in flows)]
    return "\n".join([*rows, "", FLOW_FOOTER]) + "\n"


def _row(flow: Flow) -> str:
    cells = (
        f"`{flow.name}` (`{flow.pack}` pack)",
        flow.use_when or "",
        ", ".join(flow.starts),
        "; ".join(flow.gates) or "none",
        ", ".join(flow.inside) or "own prompts",
    )
    return "| " + " | ".join(_cell(cell) for cell in cells) + " |"


def _cell(text: str) -> str:
    return " ".join(text.split("\n")).replace("|", "\\|")


def _parsed(workflow: DiscoveredWorkflow) -> WorkflowDocument | None:
    try:
        return parse_workflow(workflow.document)
    except WorkflowLoadError:
        return None


def _use_when(description: str | None) -> str | None:
    text = (description or "").strip()
    if not text:
        return None
    match = _SENTENCE.match(text)
    return match.group(1) if match else text


def _skill_starters(skills_root: Path) -> dict[str, tuple[str, ...]]:
    """Each workflow a skill template runs, by name: the skills that run it, sorted."""
    starters: dict[str, set[str]] = {}
    for template in sorted(skills_root.glob("*/SKILL.md.tmpl")):
        for name in _RUNS_WORKFLOW.findall(template.read_text(encoding="utf-8")):
            starters.setdefault(name, set()).add(template.parent.name)
    return {name: tuple(sorted(skills)) for name, skills in starters.items()}


def _includers(
    workflows: Iterable[DiscoveredWorkflow], documents: dict[str, WorkflowDocument | None]
) -> dict[str, tuple[str, ...]]:
    """Each workflow another of its pack includes, by name: the includers, sorted."""
    packs = {workflow.name: workflow.pack for workflow in workflows}
    found: dict[str, set[str]] = {}
    for name, document in documents.items():
        for node in _top_and_body(document.nodes if document else ()):
            if isinstance(node, IncludeNode) and packs.get(node.include) == packs[name]:
                found.setdefault(node.include, set()).add(name)
    return {name: tuple(sorted(parents)) for name, parents in found.items()}


def _top_and_body(nodes: Iterable[object]) -> Iterator[object]:
    for node in nodes:
        yield node
        if isinstance(node, LoopGroupNode):
            yield from node.nodes


def _starts(
    name: str, starters: dict[str, tuple[str, ...]], includers: dict[str, tuple[str, ...]]
) -> tuple[str, ...]:
    if name in TRACKER_WORKFLOWS:
        return ("`./hub run <issue>`",)
    if name in starters:
        return tuple(f"`/{skill}`" for skill in starters[name])
    if name in includers:
        return tuple(f"inside `{parent}`" for parent in includers[name])
    return (f"`./hub workflow run {name}`",)


def _gates(plan: WorkflowPlan) -> tuple[str, ...]:
    gates: dict[str, None] = {}
    for node in plan.all_nodes():
        if isinstance(node, ApprovalNode) or (
            isinstance(node, WaitNode) and node.attention is not None
        ):
            gates[node.description or node.id.rsplit(SEPARATOR, 1)[-1]] = None
    return tuple(gates)


def _inside(plan: WorkflowPlan, pack_root: Path) -> tuple[str, ...]:
    text = "\n".join(_prompt(node, pack_root) for node in plan.all_nodes())
    skills = dict.fromkeys(f"`/{name}`" for name in _SKILL_PATH.findall(text))
    agents = dict.fromkeys(f"`{name}` agent" for name in _AGENT_PATH.findall(text))
    return (*skills, *agents)


def _prompt(node: object, pack_root: Path) -> str:
    if not isinstance(node, AgentNode | LoopNode):
        return ""
    if node.prompt_file is None:
        return node.prompt or ""
    try:
        return resolve_pack_file(pack_root, "prompts", node.prompt_file).read_text(encoding="utf-8")
    except PackPathError, OSError, UnicodeDecodeError:
        return ""
