"""Find the workflows a hub can run: its own packs, then the built-ins (ADR 0032).

A pack is a folder ``<root>/<pack>/`` holding ``<workflow>.yaml`` (or ``.json``) files beside its
``prompts/``, ``scripts/`` and ``fixtures/``. The roots are the hub's ``workflows/`` and the
built-ins shipped as core package data (``BUILTIN_WORKFLOWS``, empty or absent until packs land
there). A workflow's name is its file stem, claimed by the first file of that stem in a root (in
pack, then file, name order), whether or not it loads: a later file of the same stem is a problem,
and a hub file that fails still takes its name from the built-ins, so a broken override never
falls back silently. Hidden names are skipped. At most ``MAX_ROOT_WORKFLOWS`` workflow files are
read per root; past that the root gets one problem and the rest is left out.

Each file is read through ``workflow_yaml`` into a raw mapping and its key lines; what it means is
core's document model. A problem belongs to one file (or one folder) and never stops the scan: a
hub ``workflows/`` that is a link (not scanned), a linked pack folder, a workflow file directly
under a root, a file whose real path leaves its pack, one that is not a regular file, one that
does not load, a ``name`` that is not the stem, a name already taken (naming the claiming file
relative to its root, so no absolute path reaches a message).

``pack_resolver`` resolves the workflows a workflow includes, by name, among those of its own pack
(the hub's choice, or a pack-mate the hub overrides): a node's ``prompt_file`` and ``script`` are
paths inside its pack, so an included node must come from the same one.

``resolve_pack_file`` turns a node's ``prompt_file`` or ``script`` into a file inside its pack:
relative to the pack's ``prompts/`` or ``scripts/``, no ``..``, not absolute, and its real path
(links followed) still inside the pack.

Limit: the containment checks resolve a path, then open it. A link swapped in between could be
followed; the packs are the hub owner's own files, so the reader does not walk descriptors
(``O_NOFOLLOW`` per segment) as ``brain_files`` does.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from agent_hub.core.workflows.document import WorkflowDocument, parse_workflow
from agent_hub.core.workflows.includes import IncludeResolver
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.regular_files import read_regular
from agent_hub.generator.workflow_yaml import (
    JSON_SUFFIX,
    MAX_WORKFLOW_BYTES,
    KeyPath,
    LoadedWorkflow,
    WorkflowFileError,
    WorkflowMapping,
    load_workflow_bytes,
)

HUB_WORKFLOWS: Final = "workflows"
BUILTIN_WORKFLOWS: Final = Path(str(files("agent_hub.core").joinpath("workflows", "builtin")))
WORKFLOW_SUFFIXES: Final = (".yaml", JSON_SUFFIX)
MAX_ROOT_WORKFLOWS: Final = 200

type WorkflowOrigin = Literal["hub", "builtin"]
type PackFolder = Literal["prompts", "scripts"]


@dataclass(frozen=True, kw_only=True, slots=True)
class DiscoveredWorkflow:
    """One workflow file that loaded: its name (the stem), pack, origin, file, raw mapping and
    the 1-based line of each key path (``workflow_yaml.LoadedWorkflow.lines``)."""

    name: str
    pack: str
    origin: WorkflowOrigin
    path: Path
    pack_root: Path
    document: WorkflowMapping
    lines: Mapping[KeyPath, int]


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkflowProblem:
    """Why a file or pack folder was left out; ``line`` is 1-based when known."""

    origin: WorkflowOrigin
    path: Path
    line: int | None
    reason: str

    @property
    def message(self) -> str:
        where = str(self.path) if self.line is None else f"{self.path}:{self.line}"
        return f"{where}: {self.reason}"


@dataclass(frozen=True, kw_only=True, slots=True)
class WorkflowDiscovery:
    """The workflows by name, the built-ins a hub workflow overrides, and the problems found."""

    workflows: tuple[DiscoveredWorkflow, ...]
    overridden: tuple[DiscoveredWorkflow, ...]
    problems: tuple[WorkflowProblem, ...]


class PackPathError(GeneratorError):
    """A ``prompt_file`` or ``script`` path that does not name a file inside its pack."""


def discover_workflows(
    hub_root: Path, *, builtin_root: Path = BUILTIN_WORKFLOWS
) -> WorkflowDiscovery:
    """The hub's workflows over the built-ins; a missing root reads as empty."""
    problems: list[WorkflowProblem] = []
    hub = _Root(origin="hub", problems=problems)
    folder = hub_root / HUB_WORKFLOWS
    if folder.is_symlink():
        problems.append(_problem("hub", folder, "the workflows folder is a link; it is not read"))
    else:
        hub.scan(folder)
    builtin = _Root(origin="builtin", problems=problems)
    builtin.scan(builtin_root)
    shadowed = builtin.found.keys() & hub.claimed.keys()
    chosen = {name: w for name, w in builtin.found.items() if name not in shadowed} | hub.found
    return WorkflowDiscovery(
        workflows=tuple(chosen[name] for name in sorted(chosen)),
        overridden=tuple(builtin.found[name] for name in sorted(shadowed)),
        problems=tuple(problems),
    )


def pack_documents(discovery: WorkflowDiscovery, pack_root: Path) -> dict[str, WorkflowMapping]:
    """The raw documents of the pack at ``pack_root``, by name: what an include may name."""
    return {
        workflow.name: workflow.document
        for workflow in (*discovery.overridden, *discovery.workflows)
        if workflow.pack_root == pack_root
    }


def pack_resolver(
    discovery: WorkflowDiscovery,
    pack_root: Path,
    *,
    used: dict[str, WorkflowMapping] | None = None,
) -> IncludeResolver:
    """Resolve an include by name among the workflows of the pack at ``pack_root``; a document
    that does not parse raises ``WorkflowLoadError``. ``used`` collects each document resolved
    (a run's snapshot keeps them)."""
    found = pack_documents(discovery, pack_root)

    def resolve(name: str) -> WorkflowDocument | None:
        document = found.get(name)
        if document is None:
            return None
        if used is not None:
            used[name] = document
        return parse_workflow(document)

    return resolve


def resolve_pack_file(pack_root: Path, folder: PackFolder, relative: str) -> Path:
    """The real path of ``<pack_root>/<folder>/<relative>``; raises ``PackPathError`` unless it
    is a regular file whose real path stays inside the pack.

    Checked when called: a link changed after the check is the module docstring's limit."""
    parts = PurePosixPath(relative)
    if not relative or "\0" in relative or "\\" in relative or parts.is_absolute():
        raise PackPathError(f"{relative!r} is not a relative path inside {folder}/")
    if ".." in parts.parts:
        raise PackPathError(f"{relative!r} may not use '..'")
    try:
        real = (pack_root / folder / relative).resolve(strict=True)
    except OSError, RuntimeError:
        raise PackPathError(f"no such file in {folder}/: {relative}") from None
    if not real.is_relative_to(pack_root.resolve()):
        raise PackPathError(f"{folder}/{relative} leaves its pack through a link")
    if not real.is_file():
        raise PackPathError(f"{folder}/{relative} is not a regular file")
    return real


@dataclass(kw_only=True, slots=True)
class _Root:
    """One root's scan: the names claimed (by the first file of a stem), the workflows that
    loaded, and the files read against the budget."""

    origin: WorkflowOrigin
    problems: list[WorkflowProblem]
    claimed: dict[str, Path] = field(default_factory=dict)
    found: dict[str, DiscoveredWorkflow] = field(default_factory=dict)
    read: int = 0

    def scan(self, root: Path) -> None:
        for entry in _entries(root, self.origin, self.problems):
            path = Path(entry.path)
            if entry.is_symlink():
                self._problem(path, "a pack folder is a link; it is not read")
            elif entry.is_dir(follow_symlinks=False):
                if not self._scan_pack(path):
                    reason = f"more than {MAX_ROOT_WORKFLOWS} workflow files; the rest is not read"
                    self._problem(root, reason)
                    return
            elif path.suffix in WORKFLOW_SUFFIXES:
                self._problem(path, "a workflow file belongs in a pack folder")

    def _scan_pack(self, pack_root: Path) -> bool:
        """Read the pack's workflow files; False once the root's budget is spent."""
        for entry in _entries(pack_root, self.origin, self.problems):
            path = Path(entry.path)
            if path.suffix not in WORKFLOW_SUFFIXES or entry.is_dir():
                continue
            if self.read >= MAX_ROOT_WORKFLOWS:
                return False
            self.read += 1
            self._take(pack_root, path)
        return True

    def _take(self, pack_root: Path, path: Path) -> None:
        name = path.stem
        if name in self.claimed:
            claimer = self.claimed[name].relative_to(pack_root.parent).as_posix()
            reason = f"the workflow name {name!r} is already taken by {claimer}"
            self._problem(path, reason)
            return
        self.claimed[name] = path
        loaded = _load(pack_root, path)
        if isinstance(loaded, WorkflowFileError):
            self._problem(path, loaded.reason, line=loaded.line)
            return
        declared = loaded.document.get("name")
        if isinstance(declared, str) and declared != name:
            reason = f"name {declared!r} is not the file name {name!r}"
            self._problem(path, reason, line=loaded.lines.get(("name",)))
            return
        self.found[name] = DiscoveredWorkflow(
            name=name,
            pack=pack_root.name,
            origin=self.origin,
            path=path,
            pack_root=pack_root,
            document=loaded.document,
            lines=loaded.lines,
        )

    def _problem(self, path: Path, reason: str, *, line: int | None = None) -> None:
        self.problems.append(_problem(self.origin, path, reason, line=line))


def _entries(
    folder: Path, origin: WorkflowOrigin, problems: list[WorkflowProblem]
) -> list[os.DirEntry[str]]:
    try:
        with os.scandir(folder) as listing:
            entries = [entry for entry in listing if not entry.name.startswith(".")]
    except FileNotFoundError:
        return []
    except OSError as error:
        problems.append(_problem(origin, folder, _cause(error)))
        return []
    return sorted(entries, key=lambda entry: entry.name)


def _load(pack_root: Path, path: Path) -> LoadedWorkflow | WorkflowFileError:
    content = _read_inside(pack_root, path)
    if isinstance(content, str):
        return WorkflowFileError(source=str(path), line=None, reason=content)
    try:
        return load_workflow_bytes(content, source=str(path))
    except WorkflowFileError as error:
        return error


def _read_inside(pack_root: Path, path: Path) -> bytes | str:
    """The file's bytes (one past the cap at most, so the loader sees it too large), or why not:
    its real path must stay inside the pack and be a regular file, read without blocking (checked,
    then opened: the module docstring's limit)."""
    try:
        real = path.resolve(strict=True)
        inside = real.is_relative_to(pack_root.resolve(strict=True))
    except (OSError, RuntimeError) as error:
        return _cause(error)
    if not inside:
        return "a link that leaves its pack; it is not read"
    try:
        folder = os.open(real.parent, os.O_RDONLY | os.O_DIRECTORY)
    except OSError as error:
        return _cause(error)
    try:
        read = read_regular(folder, real.name, limit=MAX_WORKFLOW_BYTES + 1)
    finally:
        os.close(folder)
    return "no such file" if read is None else read


def _problem(
    origin: WorkflowOrigin, path: Path, reason: str, *, line: int | None = None
) -> WorkflowProblem:
    return WorkflowProblem(origin=origin, path=path, line=line, reason=reason)


def _cause(error: BaseException) -> str:
    strerror = getattr(error, "strerror", None)
    return f"cannot read: {strerror or type(error).__name__}"
