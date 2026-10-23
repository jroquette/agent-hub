"""The scenario builder's reads and its save (hub web's visual editor of a scenario).

- ``validate`` renders a scenario document (the JSON the builder holds) as the canonical YAML
  Save would write, loads it with the strict loader and core's ``check_workflows`` (an include
  resolving among the pack's scenarios on disk, as the catalog does), checks each action
  reference against the hub's actions, and places every problem on its node. It writes nothing.
- ``library`` lists the hub's actions (the builder's palette), each with its output fields and
  the scenarios that call it.
- ``save`` writes the scenario file (``scenarios/<pack>/<name>.yaml``) through the shared item
  write step (``ItemVersionWrites.write_file``: one lock, the disk recorded first, never through
  a link, a ``publish`` version recorded), only when the document loads, with the revision the
  server sets (the file's plus one) and only over the content the builder last read
  (``base_content_hash``), else ``stale_document``. No git command runs.
"""

import contextlib
import hashlib
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agent_hub.api.scenario_catalog import (
    DOCUMENT_TEXT_BYTES,
    ScenarioActionView,
    ScenarioCatalog,
    action_view,
    read_text_bounded,
)
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.item_version_ports import ItemVersionWrites, ItemWriteResult
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.scenarios.action_catalog import ActionRefError, resolve_action
from agent_hub.core.scenarios.action_document import parse_action
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile, check_workflows
from agent_hub.core.workflows.document import WorkflowLoadError
from agent_hub.core.workflows.launch import RunConflictError
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, discover_scenarios
from agent_hub.generator.workflow_discovery import pack_resolver
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import WorkflowFileError, load_workflow_bytes

KEBAB: Final = r"^[a-z][a-z0-9-]{0,63}$"
_KEBAB: Final = re.compile(KEBAB)
_NODE_KEY: Final = re.compile(r"^nodes\[(\d+)\]")
# The keys of a document in the order the YAML lists them; a node's ``id`` and ``type`` first.
_DOCUMENT_ORDER: Final = ("version", "kind", "name", "revision", "description", "environment")
_NODE_ORDER: Final = ("id", "type", "description", "depends_on", "when", "trigger_rule")
MAX_DOCUMENT_BYTES: Final = 256 << 10
_ACTION_NODES: Final = frozenset({"action", "expect"})


class BuilderProblem(ViewModel):
    """A reason the document does not load (``error``) or will not plan (``warning``), on the
    node it names (``node`` None for the document)."""

    node: str | None
    key: str | None
    line: int | None
    message: str
    severity: str = "error"


class NodeLines(ViewModel):
    id: str
    first_line: int
    last_line: int


class ValidateRequest(BaseModel):
    """A scenario document to check: its pack and the document as the builder holds it."""

    model_config = ConfigDict(extra="forbid")

    pack: str = Field(pattern=KEBAB)
    document: dict[str, JsonValue]


class ValidateResult(ViewModel):
    loads: bool
    yaml: str
    problems: tuple[BuilderProblem, ...]
    nodes: tuple[NodeLines, ...]


class SaveRequest(BaseModel):
    """A save: the pack, the document and the content hash of the file the builder last read
    (None for a new scenario)."""

    model_config = ConfigDict(extra="forbid")

    pack: str = Field(pattern=KEBAB)
    document: dict[str, JsonValue]
    base_content_hash: str | None = None


class SaveResult(ViewModel):
    path: str
    revision: int
    content_hash: str
    yaml: str
    changed: bool
    versioned: bool


class OutputField(ViewModel):
    path: str
    type: str | None


class LibraryAction(ViewModel):
    """An action of the hub as the palette lists it."""

    action: ScenarioActionView
    output_fields: tuple[OutputField, ...]
    used_by: tuple[str, ...]


class ActionLibrary(ViewModel):
    items: tuple[LibraryAction, ...]
    problems: tuple[str, ...]


def content_hash(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def render_document(document: Mapping[str, JsonValue]) -> str:
    """The canonical YAML of a scenario document: its keys in a fixed order, then the rest."""
    ordered: dict[str, JsonValue] = {
        key: document[key] for key in _DOCUMENT_ORDER if key in document
    }
    for key, value in document.items():
        if key not in ordered and key != "nodes":
            ordered[key] = value
    nodes = document.get("nodes")
    if isinstance(nodes, list):
        ordered["nodes"] = [_ordered_node(node) for node in nodes]
    elif nodes is not None:
        ordered["nodes"] = nodes
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True, width=100)


def _ordered_node(node: JsonValue) -> JsonValue:
    if not isinstance(node, dict):
        return node
    ordered: dict[str, JsonValue] = {key: node[key] for key in _NODE_ORDER if key in node}
    ordered.update({key: value for key, value in node.items() if key not in ordered})
    body = ordered.get("nodes")
    if isinstance(body, list):
        ordered["nodes"] = [_ordered_node(item) for item in body]
    return ordered


class _OneFile:
    """A ``WorkflowSource`` of one in-memory file."""

    def __init__(self, item: WorkflowFile) -> None:
        self.item = item

    def workflow_files(self) -> tuple[WorkflowFile]:
        return (self.item,)


class ScenarioBuilder:
    """The builder's reads over the registered hubs (``catalog`` names them)."""

    def __init__(self, catalog: ScenarioCatalog) -> None:
        self.catalog = catalog

    def validate(self, project: str, request: ValidateRequest) -> ValidateResult:
        """Render, load and check ``request.document``; never writes."""
        hub = Path(self.catalog.hub_of(project))
        return _validate(hub, request.pack, request.document, found=discover_actions(hub))

    def library(self, project: str) -> ActionLibrary:
        """The hub's actions, by pack then name, with their output fields and users."""
        hub = Path(self.catalog.hub_of(project))
        found = discover_actions(hub)
        users = _users(hub)
        items = tuple(
            LibraryAction(
                action=action_view(entry.ref, entry.pack, found),
                output_fields=tuple(_output_fields(entry.document.output_format)),
                used_by=tuple(sorted(users.get(entry.ref, ()))),
            )
            for entry in sorted(found.actions, key=lambda item: (item.pack, item.document.name))
        )
        problems = tuple(str(problem.reason) for problem in found.problems)
        return ActionLibrary(items=items, problems=problems)

    def save(
        self, project: str, name: str, *, request: SaveRequest, writes: ItemVersionWrites
    ) -> SaveResult:
        """Write the scenario file when its document loads (see the module docstring)."""
        if not _KEBAB.fullmatch(name):
            raise RunConflictError(
                code="document_invalid", reason=f"{name!r} is not a scenario name"
            )
        hub = Path(self.catalog.hub_of(project))
        unit_path = f"{HUB_SCENARIOS}/{request.pack}/{name}.yaml"
        taken = next(
            (
                found
                for found in discover_scenarios(hub).workflows
                if found.name == name and found.pack != request.pack
            ),
            None,
        )
        if taken is not None:
            raise RunConflictError(
                code="name_taken", reason=f"pack {taken.pack} already has a scenario named {name}"
            )
        target = hub / unit_path
        on_disk = target.read_bytes() if target.is_file() and not target.is_symlink() else None
        disk_hash = None if on_disk is None else content_hash(on_disk)
        if disk_hash != request.base_content_hash:
            reason = (
                "the scenario file changed since the builder read it"
                if on_disk is not None
                else "the scenario file is gone"
            )
            raise RunConflictError(code="stale_document", reason=reason)
        document = dict(request.document)
        document["name"] = name
        document["kind"] = "scenario"
        document["revision"] = _revision(on_disk) + 1
        checked = _validate(hub, request.pack, document, found=discover_actions(hub))
        if not checked.loads:
            first = next(problem for problem in checked.problems if problem.severity == "error")
            raise RunConflictError(code="document_invalid", reason=first.message)
        data = checked.yaml.encode()
        unit = ItemUnit(project=project, unit_path=unit_path, kind=UnitKind.SCENARIO)
        written: ItemWriteResult = writes.write_file(str(hub), unit, data)
        revision = document["revision"]
        return SaveResult(
            path=unit_path,
            revision=revision if isinstance(revision, int) else 1,
            content_hash=content_hash(data),
            yaml=checked.yaml,
            changed=written.changed,
            versioned=written.versioned,
        )


def _revision(data: bytes | None) -> int:
    if data is None:
        return 0
    try:
        value = yaml.safe_load(data)
    except yaml.YAMLError:
        return 0
    revision = value.get("revision") if isinstance(value, dict) else None
    return revision if isinstance(revision, int) else 0


def _validate(
    hub: Path, pack: str, document: Mapping[str, JsonValue], *, found: ActionDiscovery
) -> ValidateResult:
    text = render_document(document)
    name = document.get("name")
    stem = name if isinstance(name, str) and name else "scenario"
    shown = f"{HUB_SCENARIOS}/{pack}/{stem}.yaml"
    nodes_raw = document.get("nodes")
    node_ids = (
        [str(node.get("id")) if isinstance(node, dict) else "" for node in nodes_raw or []]
        if isinstance(nodes_raw, list)
        else []
    )
    problems: list[BuilderProblem] = []
    if len(text.encode()) > MAX_DOCUMENT_BYTES:
        problems.append(
            BuilderProblem(node=None, key=None, line=None, message="the scenario is over 256 KiB")
        )
        return ValidateResult(loads=False, yaml=text, problems=tuple(problems), nodes=())
    if document.get("kind") != "scenario":
        problems.append(
            BuilderProblem(node=None, key="kind", line=None, message="kind must be scenario")
        )
    try:
        loaded = load_workflow_bytes(text.encode(), source=shown)
    except WorkflowFileError as error:
        problems.append(BuilderProblem(node=None, key=None, line=None, message=str(error)))
        return ValidateResult(loads=False, yaml=text, problems=tuple(problems), nodes=())
    lines = _node_lines(loaded.lines, node_ids, text)
    discovery = discover_scenarios(hub)
    includes = pack_resolver(discovery, hub / HUB_SCENARIOS / pack)
    item = WorkflowFile(shown, stem, loaded.document, loaded.lines, "hub", includes)
    catalog = check_workflows(_OneFile(item))
    problems.extend(_problem(problem, node_ids) for problem in catalog.problems)
    for index, node in enumerate(nodes_raw if isinstance(nodes_raw, list) else []):
        problems.extend(_action_problems(node, index, node_ids=node_ids, pack=pack, found=found))
    loads = bool(catalog.plans) and not any(item.severity == "error" for item in problems)
    return ValidateResult(loads=loads, yaml=text, problems=tuple(problems), nodes=lines)


def _action_problems(
    node: JsonValue, index: int, *, node_ids: list[str], pack: str, found: ActionDiscovery
) -> list[BuilderProblem]:
    """An action reference that names no action (or one that is a draft: a warning)."""
    if not isinstance(node, dict) or node.get("type") not in _ACTION_NODES:
        if isinstance(node, dict) and isinstance(node.get("nodes"), list):
            out: list[BuilderProblem] = []
            for inner in node["nodes"]:  # type: ignore[union-attr]
                out.extend(
                    _action_problems(inner, index, node_ids=node_ids, pack=pack, found=found)
                )
            return out
        return []
    ref = node.get("action")
    where = node_ids[index] if index < len(node_ids) else None
    if not isinstance(ref, str) or ref == "":
        return [BuilderProblem(node=where, key="action", line=None, message="choose an action")]
    try:
        entry = resolve_action(found.actions, ref, pack=pack)
    except ActionRefError as error:
        return [BuilderProblem(node=where, key="action", line=None, message=str(error))]
    if entry.draft:
        return [
            BuilderProblem(
                node=where,
                key="action",
                line=None,
                message=f"action {ref} is a draft: commit it before the scenario can run",
                severity="warning",
            )
        ]
    return []


def _problem(problem: LoadProblem, node_ids: list[str]) -> BuilderProblem:
    match = _NODE_KEY.match(problem.key)
    node = None
    if match is not None:
        index = int(match.group(1))
        node = node_ids[index] if index < len(node_ids) else None
    return BuilderProblem(node=node, key=problem.key, line=problem.line, message=problem.message)


def _node_lines(
    lines: Mapping[tuple[str | int, ...], int], node_ids: list[str], text: str
) -> tuple[NodeLines, ...]:
    """Each top-level node's first and last line in the rendered YAML."""
    starts = [(lines.get(("nodes", index)), node_id) for index, node_id in enumerate(node_ids)]
    known = [(line, node_id) for line, node_id in starts if line is not None]
    total = text.count("\n")
    out: list[NodeLines] = []
    for position, (line, node_id) in enumerate(known):
        end = known[position + 1][0] - 1 if position + 1 < len(known) else total
        out.append(NodeLines(id=node_id, first_line=line, last_line=max(line, end)))
    return tuple(out)


def _output_fields(schema: Mapping[str, JsonValue], prefix: str = "") -> list[OutputField]:
    """The paths a reference may read in an output format (objects only, two levels)."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return []
    out: list[OutputField] = []
    for key, value in properties.items():
        path = prefix + key
        kind = value.get("type") if isinstance(value, dict) else None
        out.append(OutputField(path=path, type=kind if isinstance(kind, str) else None))
        if isinstance(value, dict) and not prefix:
            out.extend(_output_fields(value, f"{path}."))
    return out


def _users(hub: Path) -> dict[str, set[str]]:
    """The scenarios that call each action, by the action's ``<pack>/<name>``."""
    users: dict[str, set[str]] = {}
    for found in discover_scenarios(hub).workflows:
        nodes = found.document.get("nodes") if isinstance(found.document, dict) else None
        for node in _walk(nodes):
            ref = node.get("action")
            if isinstance(ref, str):
                full = ref if "/" in ref else f"{found.pack}/{ref}"
                users.setdefault(full, set()).add(found.name)
    return users


def _walk(nodes: object) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    if isinstance(nodes, list):
        for node in nodes:
            if isinstance(node, dict):
                out.append(node)
                out.extend(_walk(node.get("nodes")))
    return out


# Claude's proposal for a scenario, and actions written from the builder.

PROPOSALS_FOLDER: Final = Path(".agent-runs", "proposals", "scenarios")
_ACTION_NAME: Final = re.compile(KEBAB)
_INPUT_NAME: Final = r"^[a-z][a-z0-9_]{0,63}$"


def proposal_path(pack: str, name: str) -> Path:
    """Where Claude writes its proposal for scenario ``name`` of ``pack`` (git ignores it)."""
    return PROPOSALS_FOLDER / pack / f"{name}.yaml"


class ProposalView(ViewModel):
    """Claude's proposal for the scenario: the document it wrote, checked as Save would check
    it (never written to the scenario file until the owner accepts it and saves)."""

    path: str
    document: dict[str, JsonValue] | None
    check: ValidateResult | None
    problem: str | None = None


class ActionInputDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_INPUT_NAME)
    type: Literal["string", "integer", "number", "boolean", "service"] = "string"
    required: bool = False
    description: str | None = Field(default=None, max_length=500)


class OutputFieldDraft(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=_INPUT_NAME)
    type: Literal["string", "integer", "number", "boolean", "object", "array"] = "string"


class NewAction(BaseModel):
    """A new action from the builder: its facts and its script's text."""

    model_config = ConfigDict(extra="forbid")

    pack: str = Field(pattern=KEBAB)
    name: str = Field(pattern=KEBAB)
    description: str = Field(min_length=1, max_length=500)
    effect: Literal["read", "write", "destroy"]
    runtime: Literal["python", "sh"] = "python"
    timeout: str = Field(default="5m", pattern=r"^[1-9][0-9]*(s|m|h)$")
    inputs: list[ActionInputDraft] = Field(default_factory=list, max_length=64)
    outputs: list[OutputFieldDraft] = Field(default_factory=list, max_length=64)
    script_text: str = Field(min_length=1, max_length=256 << 10)


def _action_yaml(action: NewAction, script: str) -> str:
    """The action document a new action is saved as."""
    document: dict[str, JsonValue] = {
        "version": 1,
        "name": action.name,
        "description": action.description,
        "effect": action.effect,
        "runtime": action.runtime,
        "script": script,
        "timeout": action.timeout,
    }
    if action.inputs:
        document["inputs"] = {
            item.name: {
                key: value
                for key, value in (
                    ("type", item.type),
                    ("required", item.required or None),
                    ("description", item.description),
                )
                if value is not None
            }
            for item in action.inputs
        }
    document["output_format"] = {
        "type": "object",
        "properties": {item.name: {"type": item.type} for item in action.outputs},
    }
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True, width=100)


def read_proposal(builder: ScenarioBuilder, project: str, name: str) -> ProposalView:
    """Claude's proposal for scenario ``name``, checked; ``EntityNotFoundError`` when none."""
    hub_text, plan_pack = (
        builder.catalog.hub_of(project),
        builder.catalog.scenario(project, name)[2],
    )
    hub = Path(hub_text)
    relative = proposal_path(plan_pack, name)
    text, _ = _read_text_no_link(hub / relative)
    if text is None:
        raise EntityNotFoundError(entity="proposal", entity_id=f"{project}/{name}")
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as error:
        return ProposalView(path=relative.as_posix(), document=None, check=None, problem=str(error))
    if not isinstance(value, dict):
        return ProposalView(
            path=relative.as_posix(), document=None, check=None, problem="not a YAML mapping"
        )
    document = dict(value)
    document["name"] = name
    document["kind"] = "scenario"
    check = _validate(hub, plan_pack, document, found=discover_actions(hub))
    return ProposalView(path=relative.as_posix(), document=document, check=check)


def drop_proposal(builder: ScenarioBuilder, project: str, name: str) -> None:
    """Removes Claude's proposal (accepted into the draft, or rejected); none is fine."""
    hub = Path(builder.catalog.hub_of(project))
    pack = builder.catalog.scenario(project, name)[2]
    target = hub / proposal_path(pack, name)
    if target.is_symlink():
        raise RunConflictError(code="link_in_path", reason="the proposal is a link; not removed")
    with contextlib.suppress(FileNotFoundError):
        target.unlink()


def create_action(
    builder: ScenarioBuilder,
    project: str,
    action: NewAction,
    *,
    writes: ItemVersionWrites,
    replace: bool = False,
) -> ScenarioActionView:
    """Writes a new action (its document and its script) as a draft; ``name_taken`` when the
    pack already has one of that name, ``document_invalid`` when the loader refuses it. With
    ``replace`` it rewrites an action that exists (``unknown_action`` else), keeping its script's
    file when the runtime is unchanged; a changed action is a draft until it is committed."""
    hub = Path(builder.catalog.hub_of(project))
    found = discover_actions(hub)
    existing = next(
        (
            entry
            for entry in found.actions
            if entry.pack == action.pack and entry.document.name == action.name
        ),
        None,
    )
    if existing is not None and not replace:
        raise RunConflictError(
            code="name_taken", reason=f"pack {action.pack} already has an action {action.name}"
        )
    if existing is None and replace:
        raise RunConflictError(
            code="unknown_action", reason=f"pack {action.pack} has no action {action.name}"
        )
    suffix = ".py" if action.runtime == "python" else ".sh"
    script = f"scripts/{action.name.replace('-', '_')}{suffix}"
    if existing is not None and existing.document.script.endswith(suffix):
        script = existing.document.script
    text = _action_yaml(action, script)
    shown = f"actions/{action.pack}/{action.name}.yaml"
    try:
        document = parse_action(load_workflow_bytes(text.encode(), source=shown).document)
    except (WorkflowFileError, WorkflowLoadError) as error:
        raise RunConflictError(code="document_invalid", reason=str(error)) from None
    if problems := JsonSchemaOutputs().schema_problems(document.output_format):
        raise RunConflictError(code="document_invalid", reason="; ".join(problems))
    base = f"actions/{action.pack}"
    writes.write_file(
        str(hub),
        ItemUnit(project=project, unit_path=f"{base}/{script}", kind=UnitKind.ACTION),
        action.script_text.encode(),
    )
    writes.write_file(
        str(hub),
        ItemUnit(project=project, unit_path=shown, kind=UnitKind.ACTION),
        text.encode(),
    )
    return action_view(action.name, action.pack, discover_actions(hub))


def _read_text_no_link(path: Path) -> tuple[str | None, bool]:
    if path.is_symlink() or any(parent.is_symlink() for parent in path.parents):
        return None, False
    return read_text_bounded(path, DOCUMENT_TEXT_BYTES)
