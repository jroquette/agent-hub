"""The seeded extension inputs of a render (spec D2, Q-17): plain values built from a snapshot.

``ExtensionInputs`` holds the bytes of each seeded ``*.project.json`` sibling present and the
names of the project's agents and skills under ``plugin/<project>/``. The cli builds it with
``extension_inputs_from`` from the ``TreeSnapshot`` it already read and passes it to the render,
which stays pure. A sibling that is not a regular file, or an entry name that ``hub.lock`` cannot
record, is a problem (plan E9): the caller exits 1 and writes nothing.
"""

import unicodedata
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from agent_hub.core.hub_files.plan_init import PathProblem
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, TreeEntry, TreeSnapshot

PROJECT_JSON_SUFFIX: Final = ".project.json"
_NOT_REGULAR: Final = "not a regular file"
_UNLINKABLE: Final = "cannot be linked"
# The project folders whose entries are linked into ``.claude/<folder>``, by the linked type.
LINKED_TYPES: Final[Mapping[str, type[FileEntry] | type[FolderEntry]]] = MappingProxyType(
    {"agents": FileEntry, "skills": FolderEntry}
)
# Keys a sibling may not set, whatever their value: they weaken the harness (ADR 0009). One
# definition, for the generator's merge and hub doctor's ``settings.weakening`` rule.
REFUSED_KEYS: Final[Mapping[str, tuple[tuple[str, ...], ...]]] = MappingProxyType(
    {".claude/settings.project.json": (("disableAllHooks",), ("permissions", "defaultMode"))}
)


def unlinkable_reason(name: str) -> str | None:
    """Why ``name`` cannot be a link's name in the hub and ``hub.lock``, or ``None`` if it can."""
    try:
        name.encode("utf-8")
    except UnicodeEncodeError:
        return "not UTF-8"
    if "\\" in name:
        return "holds a backslash"
    if not name.isprintable():
        return "not printable"
    return None


def entry_name_key(name: str) -> str:
    """The key under which two entry names are one name (plan E37): NFC, then ``casefold()``.

    A case- or normalization-insensitive disk (macOS's default APFS) holds one entry for names
    with the same key, such as ``Evaluator.md`` and ``evaluator.md``, or an NFD and an NFC name.
    """
    return unicodedata.normalize("NFC", unicodedata.normalize("NFC", name).casefold())


def _is_plain(name: str) -> bool:
    return bool(name) and "/" not in name and not name.startswith(".")


def _checked_names(folder: str, names: Iterable[str]) -> tuple[str, ...]:
    ordered = tuple(sorted(names))
    for previous, current in zip(ordered, ordered[1:], strict=False):
        if previous == current:
            msg = f"{folder}: {current!r} appears more than once"
            raise ValueError(msg)
    for name in ordered:
        if not _is_plain(name):
            msg = f"{folder}: {name!r} is not a plain entry name"
            raise ValueError(msg)
        reason = unlinkable_reason(name)
        if reason is not None:
            msg = f"{folder}: {name!r} {_UNLINKABLE}: {reason}"
            raise ValueError(msg)
    return ordered


@dataclass(frozen=True, kw_only=True, slots=True)
class ExtensionInputs:
    """What the project adds to a render: sibling bytes by path, agent and skill names (sorted).

    The names are one plain segment each (no ``/``, no leading ``.``) that ``hub.lock`` can
    record; the mapping is copied into a read-only view. A value breaking this raises
    ``ValueError`` (a caller bug: ``extension_inputs_from`` reports such names as problems).
    """

    # Unhashable (a ``MappingProxyType`` field): never memoize ``render_hub`` on this value.

    project_json: Mapping[str, bytes]
    agents: tuple[str, ...]
    skills: tuple[str, ...]

    def __post_init__(self) -> None:
        for path in self.project_json:
            if not path.endswith(PROJECT_JSON_SUFFIX):
                msg = f"{path!r} is not a *{PROJECT_JSON_SUFFIX} path"
                raise ValueError(msg)
        frozen = MappingProxyType(dict(sorted(self.project_json.items())))
        object.__setattr__(self, "project_json", frozen)
        object.__setattr__(self, "agents", _checked_names("agents", self.agents))
        object.__setattr__(self, "skills", _checked_names("skills", self.skills))


NO_EXTENSIONS: Final = ExtensionInputs(project_json={}, agents=(), skills=())


def _sibling(path: str, *, entry: TreeEntry | None, problems: list[PathProblem]) -> bytes | None:
    if entry is None:
        return None
    if not isinstance(entry, FileEntry):
        problems.append(PathProblem(path, _NOT_REGULAR))
        return None
    if entry.content is None:
        # A caller bug: the tree reader was not asked to read the sibling.
        msg = f"{path}: content was not read; wanted must include it"
        raise ValueError(msg)
    return entry.content


def _entry_names(
    tree: TreeSnapshot,
    *,
    folder: str,
    linked: type[FileEntry | FolderEntry],
    problems: list[PathProblem],
) -> list[str]:
    """Q-17: the direct entries of ``folder`` of type ``linked``, dotfiles never."""
    prefix = f"{folder}/"
    names: list[str] = []
    for path, entry in tree.entries.items():
        if not path.startswith(prefix) or not isinstance(entry, linked):
            continue
        name = path.removeprefix(prefix)
        if "/" in name or name.startswith("."):
            continue
        reason = unlinkable_reason(name)
        if reason is None:
            names.append(name)
        else:
            problems.append(PathProblem(path, f"{_UNLINKABLE}: {reason}"))
    return names


def extension_inputs_from(
    tree: TreeSnapshot, *, project: str, siblings: Collection[str]
) -> ExtensionInputs | tuple[PathProblem, ...]:
    """Build the inputs from ``tree``, or return every problem sorted by path.

    ``siblings`` are the seeded ``*.project.json`` paths of the render: each present as a regular
    file gives its bytes (read by the caller), and any other type is ``not a regular file``.
    ``agents`` are the regular files right under ``plugin/<project>/agents``, ``skills`` the real
    folders right under ``plugin/<project>/skills``, whatever they hold; names starting with
    ``.``, links, other types and nested paths are left alone.
    """
    problems: list[PathProblem] = []
    project_json: dict[str, bytes] = {}
    for path in siblings:
        content = _sibling(path, entry=tree.entries.get(path), problems=problems)
        if content is not None:
            project_json[path] = content
    base = f"plugin/{project}"
    agents, skills = (
        _entry_names(
            tree, folder=f"{base}/{folder}", linked=LINKED_TYPES[folder], problems=problems
        )
        for folder in ("agents", "skills")
    )
    if problems:
        return tuple(sorted(problems))
    return ExtensionInputs(project_json=project_json, agents=tuple(agents), skills=tuple(skills))
