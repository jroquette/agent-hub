"""The scenario builder's reads and its save (hub web's visual editor of a scenario).

- ``validate`` renders a scenario document (the JSON the builder holds) as the canonical YAML
  Save would write (``generator.scenario_yaml``), loads it with the strict loader and core's
  ``check_workflows`` (an include resolving among the pack's scenarios on disk, as the catalog
  does), checks each action reference against the hub's actions (a tree's through its
  translated blocks), and places every problem on its node. It writes nothing.
- ``library`` lists the hub's actions (the builder's palette), each with its output fields and
  the scenarios that call it.
- ``save`` writes the scenario file (``scenarios/<pack>/<name>.yaml``) through the shared item
  write step (``ItemVersionWrites.write_file``: one lock, the disk recorded first, never through
  a link, a ``publish`` version recorded), only when the document loads, with the revision the
  server sets (the file's plus one) and only over the content the builder last read
  (``base_content_hash``), else ``stale_document``. When the document with the file's own
  revision renders to the file's bytes, it writes nothing and keeps the revision
  (``changed`` false). No git command runs.
- ``migrate`` writes a graph scenario (``version: 1``) again as blocks (``version: 2``), as
  ``hub scenario migrate NAME`` does (core's ``migrate_graph``, the canonical writer, the text
  loaded back and translated again): one stage named after the scenario, its revision kept. It
  migrates the bytes it read, only over the content the builder last read when it sends
  ``base_content_hash`` (``stale_document`` else), through the same write step as Save; with
  ``check`` it writes nothing. A node a tree cannot hold, a JSON file or a path the item writer
  does not write is a problem, and nothing is written; a ``version: 2`` scenario is 409
  ``scenario_already_tree``.
"""

import contextlib
import hashlib
import posixpath
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from agent_hub.api.scenario_catalog import (
    DOCUMENT_TEXT_BYTES,
    ScenarioActionView,
    ScenarioCatalog,
    action_view,
    read_bytes_bounded,
    read_text_bounded,
)
from agent_hub.core.features.output_shape import output_path
from agent_hub.core.item_versions.hub_item_writer import checked_unit_parts
from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.item_version_ports import ItemVersionWrites, ItemWriteResult
from agent_hub.core.json_form import JsonValue
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.readmodels.view_types import ViewModel
from agent_hub.core.scenarios.action_catalog import ActionRefError, resolve_action
from agent_hub.core.scenarios.action_document import parse_action
from agent_hub.core.scenarios.tree_migrate import MigrationError, migrate_graph
from agent_hub.core.scenarios.tree_translate import Block, translate_tree
from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile, check_workflows
from agent_hub.core.workflows.document import Loc, WorkflowLoadError, is_tree
from agent_hub.core.workflows.launch import RunConflictError
from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions
from agent_hub.generator.scenario_discovery import HUB_SCENARIOS, discover_scenarios
from agent_hub.generator.scenario_yaml import render_document
from agent_hub.generator.workflow_discovery import pack_resolver
from agent_hub.generator.workflow_outputs import JsonSchemaOutputs
from agent_hub.generator.workflow_yaml import JSON_SUFFIX, WorkflowFileError, load_workflow_bytes

KEBAB: Final = r"^[a-z][a-z0-9-]{0,63}$"
_KEBAB: Final = re.compile(KEBAB)
_NODE_KEY: Final = re.compile(r"^nodes\[(\d+)\]")
MAX_DOCUMENT_BYTES: Final = 256 << 10
_ACTION_NODES: Final = frozenset({"action", "expect"})
# The tree's blocks that call an action, by their kind key.
_ACTION_BLOCKS: Final = frozenset({"do", "wait_until"})


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


class MigrateRequest(BaseModel):
    """A migrate: ``check`` writes nothing; ``base_content_hash``, when sent, is the content
    hash of the file the builder last read, which the file must still hold."""

    model_config = ConfigDict(extra="forbid")

    check: StrictBool = False
    base_content_hash: str | None = None


class MigrationProblemView(ViewModel):
    """A node a tree cannot hold, and why (``node`` None for the document or its file)."""

    node: str | None
    message: str


class ScenarioMigration(ViewModel):
    """What a migrate did: the file, whether it was written, the tree's canonical text (None
    when it cannot be migrated), the file's content hash after the call, and the problems."""

    path: str
    written: bool
    yaml: str | None
    content_hash: str | None
    problems: tuple[MigrationProblemView, ...]


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
        current = _revision(on_disk)
        found = discover_actions(hub)
        checked = _validate(hub, request.pack, document, found=found)
        if not checked.loads:
            first = next(problem for problem in checked.problems if problem.severity == "error")
            raise RunConflictError(code="document_invalid", reason=first.message)
        if on_disk is not None:
            # An unchanged document that loads writes nothing and keeps the file's revision.
            kept = render_document({**document, "revision": current})
            if kept.encode() == on_disk:
                return SaveResult(
                    path=unit_path,
                    revision=current,
                    content_hash=content_hash(on_disk),
                    yaml=kept,
                    changed=False,
                    versioned=False,
                )
        document["revision"] = current + 1
        checked = _validate(hub, request.pack, document, found=found)
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

    def migrate(
        self, project: str, name: str, *, request: MigrateRequest, writes: ItemVersionWrites
    ) -> ScenarioMigration:
        """Write the graph scenario ``name`` again as blocks (see the module docstring)."""
        hub, _plan, found = self.catalog.scenario_source(project, name)
        if is_tree(found.document):
            reason = f"{name} is already written as blocks (version 2)"
            raise RunConflictError(code="scenario_already_tree", reason=reason)
        unit_path = found.path.relative_to(hub).as_posix()
        refused = _not_in_place(found.path, unit_path)
        # One read: the bytes hashed are the bytes migrated.
        data = None if refused is not None else _read_no_link(found.path)
        disk_hash = None if data is None else content_hash(data)
        if request.base_content_hash is not None and request.base_content_hash != disk_hash:
            reason = "the scenario file changed since the builder read it"
            raise RunConflictError(code="stale_document", reason=reason)
        text: str | None = None
        problems: list[tuple[str | None, str]] = []
        if data is None:
            problems.append((None, refused or "the scenario file cannot be read"))
        else:
            text, problems = _migrated(data, unit_path)
        if text is None or problems:
            return ScenarioMigration(
                path=unit_path,
                written=False,
                yaml=None,
                content_hash=disk_hash,
                problems=tuple(
                    MigrationProblemView(node=node, message=message) for node, message in problems
                ),
            )
        if request.check:
            return ScenarioMigration(
                path=unit_path, written=False, yaml=text, content_hash=disk_hash, problems=()
            )
        unit = ItemUnit(project=project, unit_path=unit_path, kind=UnitKind.SCENARIO)
        written = writes.write_file(str(hub), unit, text.encode())
        return ScenarioMigration(
            path=unit_path,
            written=written.changed,
            yaml=text,
            content_hash=content_hash(text.encode()),
            problems=(),
        )


def _not_in_place(path: Path, unit_path: str) -> str | None:
    """Why migrate does not rewrite the file at ``path`` in place, or ``None``."""
    if path.suffix == JSON_SUFFIX:
        return "it is a JSON file: migrate rewrites a .yaml file in place"
    if path.is_symlink():
        return "it is a link: migrate writes the file in place, never through a link"
    try:
        checked_unit_parts(unit_path, UnitKind.SCENARIO)
    except ValueError:
        return "its path holds a backslash or a control character: migrate writes no such path"
    return None


def _read_no_link(path: Path) -> bytes | None:
    """The file's bytes, read once, never through a link and within the loader's bound; None
    when it cannot be read or is larger."""
    data = read_bytes_bounded(path, DOCUMENT_TEXT_BYTES)
    return None if data is None or len(data) > DOCUMENT_TEXT_BYTES else data


def _migrated(data: bytes, source: str) -> tuple[str | None, list[tuple[str | None, str]]]:
    """The canonical text of the tree the graph in ``data`` migrates to, or the problems."""
    written: list[str] = []

    def read_back(tree: dict[str, JsonValue]) -> object:
        written.append(render_document(tree))
        return load_workflow_bytes(written[-1].encode(), source=source).document

    try:
        loaded = load_workflow_bytes(data, source=source).document
    except WorkflowFileError as error:
        return None, [(None, f"the scenario file does not load: {error.reason}")]
    try:
        migrate_graph(loaded, read_back=read_back)
    except MigrationError as error:
        return None, [(problem.node, problem.message) for problem in error.problems]
    except WorkflowLoadError as error:
        return None, [(None, str(error))]
    except WorkflowFileError as error:
        return None, [(None, f"as blocks it would not load: {error.reason}")]
    return written[-1], []


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
    for block, ref in _tree_calls(loaded.document):
        key = output_path((*block.key, block.kind))
        node = block.nodes[0] if block.nodes else None
        problems.extend(_ref_problems(ref, node=node, key=key, pack=pack, found=found))
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
    return _ref_problems(ref, node=where, key="action", pack=pack, found=found)


def _ref_problems(
    ref: object, *, node: str | None, key: str, pack: str, found: ActionDiscovery
) -> list[BuilderProblem]:
    """``ref`` when it names no action, or one that is a draft (a warning)."""
    if not isinstance(ref, str) or ref == "":
        return [BuilderProblem(node=node, key=key, line=None, message="choose an action")]
    try:
        entry = resolve_action(found.actions, ref, pack=pack)
    except ActionRefError as error:
        return [BuilderProblem(node=node, key=key, line=None, message=str(error))]
    if entry.draft:
        return [
            BuilderProblem(
                node=node,
                key=key,
                line=None,
                message=f"action {ref} is a draft: commit it before the scenario can run",
                severity="warning",
            )
        ]
    return []


def _tree_calls(content: object) -> list[tuple[Block, object]]:
    """Each Do and Wait until block of the tree ``content`` holds, with the action it names;
    none for a graph or a tree that does not translate (its load problems say why)."""
    if not is_tree(content):
        return []
    try:
        blocks = translate_tree(content).blocks.blocks
    except WorkflowLoadError:
        return []
    return [
        (block, _at(content, block.key).get(block.kind))
        for block in blocks
        if block.kind in _ACTION_BLOCKS
    ]


def _at(content: object, key: Loc) -> dict[str, object]:
    """The mapping at ``key`` in ``content``, else an empty one."""
    value = content
    for part in key:
        if isinstance(part, int) and isinstance(value, list) and 0 <= part < len(value):
            value = value[part]
        elif isinstance(part, str) and isinstance(value, dict):
            value = value.get(part)
        else:
            return {}
    return value if isinstance(value, dict) else {}


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
        refs = [node.get("action") for node in _walk(nodes)]
        refs.extend(ref for _, ref in _tree_calls(found.document))
        for ref in refs:
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
    text, cut = _read_text_no_link(hub / relative)
    if text is None:
        raise EntityNotFoundError(entity="proposal", entity_id=f"{project}/{name}")
    if cut:
        return ProposalView(
            path=relative.as_posix(),
            document=None,
            check=None,
            problem="the proposal is over 256 KiB",
        )
    # The strict loader: no anchors, aliases or tags (an alias bomb never expands), JSON
    # scalars only, a mapping at the top.
    try:
        loaded = load_workflow_bytes(text.encode(), source=relative.as_posix())
    except WorkflowFileError as error:
        return ProposalView(path=relative.as_posix(), document=None, check=None, problem=str(error))
    document = dict(loaded.document)
    document["name"] = name
    document["kind"] = "scenario"
    check = _validate(hub, plan_pack, document, found=discover_actions(hub))
    return ProposalView(path=relative.as_posix(), document=document, check=check)


def drop_proposal(builder: ScenarioBuilder, project: str, name: str) -> None:
    """Removes Claude's proposal (accepted into the draft, or rejected); none is fine."""
    hub = Path(builder.catalog.hub_of(project))
    pack = builder.catalog.scenario(project, name)[2]
    relative = proposal_path(pack, name)
    # Every folder below the hub, and the file: unlink would follow a linked folder.
    below = (relative, *(parent for parent in relative.parents if parent != Path()))
    if any((hub / part).is_symlink() for part in below):
        raise RunConflictError(code="link_in_path", reason="the proposal path holds a link")
    with contextlib.suppress(FileNotFoundError):
        (hub / relative).unlink()


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
    # A script another action of the pack runs is never rewritten from one action's form.
    shared = sorted(
        entry.document.name
        for entry in found.actions
        if entry.pack == action.pack
        and entry.document.name != action.name
        and posixpath.normpath(entry.document.script) == posixpath.normpath(script)
    )
    if shared:
        raise RunConflictError(
            code="script_shared",
            reason=f"actions/{action.pack}/{script} is also run by: {', '.join(shared)}",
        )
    moved = existing is None or script != existing.document.script
    if moved and (hub / "actions" / action.pack / script).exists():
        raise RunConflictError(
            code="name_taken", reason=f"actions/{action.pack}/{script} already exists"
        )
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
