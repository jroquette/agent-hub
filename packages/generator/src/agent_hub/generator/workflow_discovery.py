"""Find the workflows a hub can run: its own packs, then the built-ins (ADR 0032).

A pack is a folder ``<root>/<pack>/`` holding ``<workflow>.yaml`` (or ``.json``) files beside its
``prompts/``, ``scripts/`` and ``fixtures/``. The roots are the hub's ``workflows/`` and the
built-ins shipped as core package data (``BUILTIN_WORKFLOWS``, empty or absent until packs land
there). A workflow's name is its file stem; a hub workflow overrides a built-in of the same name,
and inside one root the first pack in name order keeps a name. Hidden names are skipped.

Each file is read through ``workflow_yaml`` into a raw mapping; what it means is core's document
model. A problem belongs to one file (or one pack folder) and never stops the scan: a linked pack
folder, a workflow file directly under a root, a file whose real path leaves its pack, one that is
not a regular file, one that does not load, a ``name`` that is not the stem, a name already taken.

``resolve_pack_file`` turns a node's ``prompt_file`` or ``script`` into a file inside its pack:
relative to the pack's ``prompts/`` or ``scripts/``, no ``..``, not absolute, and its real path
(links followed) still inside the pack.
"""

import os
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Final, Literal

from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.regular_files import read_regular
from agent_hub.generator.workflow_yaml import (
    JSON_SUFFIX,
    MAX_WORKFLOW_BYTES,
    WorkflowFileError,
    WorkflowMapping,
    load_workflow_bytes,
)

HUB_WORKFLOWS: Final = "workflows"
BUILTIN_WORKFLOWS: Final = Path(str(files("agent_hub.core").joinpath("workflows", "builtin")))
WORKFLOW_SUFFIXES: Final = (".yaml", JSON_SUFFIX)

type WorkflowOrigin = Literal["hub", "builtin"]
type PackFolder = Literal["prompts", "scripts"]


@dataclass(frozen=True, kw_only=True, slots=True)
class DiscoveredWorkflow:
    """One workflow file that loaded: its name (the stem), pack, origin, file and raw mapping."""

    name: str
    pack: str
    origin: WorkflowOrigin
    path: Path
    pack_root: Path
    document: WorkflowMapping


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
    hub = _scan(hub_root / HUB_WORKFLOWS, "hub", problems)
    builtin = _scan(builtin_root, "builtin", problems)
    chosen = builtin | hub
    return WorkflowDiscovery(
        workflows=tuple(chosen[name] for name in sorted(chosen)),
        overridden=tuple(builtin[name] for name in sorted(builtin.keys() & hub.keys())),
        problems=tuple(problems),
    )


def resolve_pack_file(pack_root: Path, folder: PackFolder, relative: str) -> Path:
    """The real path of ``<pack_root>/<folder>/<relative>``; raises ``PackPathError`` unless it
    is a regular file whose real path stays inside the pack."""
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


def _scan(
    root: Path, origin: WorkflowOrigin, problems: list[WorkflowProblem]
) -> dict[str, DiscoveredWorkflow]:
    found: dict[str, DiscoveredWorkflow] = {}
    for entry in _entries(root, origin, problems):
        path = Path(entry.path)
        if entry.is_symlink():
            problems.append(_problem(origin, path, "a pack folder is a link; it is not read"))
        elif entry.is_dir(follow_symlinks=False):
            _scan_pack(path, origin, found=found, problems=problems)
        elif path.suffix in WORKFLOW_SUFFIXES:
            problems.append(_problem(origin, path, "a workflow file belongs in a pack folder"))
    return found


def _scan_pack(
    pack_root: Path,
    origin: WorkflowOrigin,
    *,
    found: dict[str, DiscoveredWorkflow],
    problems: list[WorkflowProblem],
) -> None:
    for entry in _entries(pack_root, origin, problems):
        path = Path(entry.path)
        if path.suffix not in WORKFLOW_SUFFIXES or entry.is_dir():
            continue
        loaded = _load(pack_root, path)
        if isinstance(loaded, WorkflowFileError):
            problems.append(_problem(origin, path, loaded.reason, line=loaded.line))
            continue
        name = path.stem
        declared = loaded.get("name")
        if isinstance(declared, str) and declared != name:
            reason = f"name {declared!r} is not the file name {name!r}"
            problems.append(_problem(origin, path, reason))
        elif name in found:
            reason = f"the workflow name {name!r} is already taken by {found[name].path}"
            problems.append(_problem(origin, path, reason))
        else:
            found[name] = DiscoveredWorkflow(
                name=name,
                pack=pack_root.name,
                origin=origin,
                path=path,
                pack_root=pack_root,
                document=loaded,
            )


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


def _load(pack_root: Path, path: Path) -> WorkflowMapping | WorkflowFileError:
    content = _read_inside(pack_root, path)
    if isinstance(content, str):
        return WorkflowFileError(source=str(path), line=None, reason=content)
    try:
        return load_workflow_bytes(content, source=str(path))
    except WorkflowFileError as error:
        return error


def _read_inside(pack_root: Path, path: Path) -> bytes | str:
    """The file's bytes (one past the cap at most, so the loader sees it too large), or why not:
    its real path must stay inside the pack and be a regular file, read without blocking."""
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
