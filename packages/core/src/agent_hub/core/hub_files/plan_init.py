"""The init planner (ADR 0011): what ``hub init`` writes into a target, decided in memory.

``plan_init`` takes the render, the ``hub.json`` bytes this run would write and a snapshot of the
target. It returns an ``InitPlan``: the leftovers to remove, the folders to make, then the writes
in the order of spec Q-16 (files, links, ``hub.json``, and ``hub.lock`` last), with what was kept.
Or it returns an ``InitRefusal`` naming every path the target may not hold (spec Q-4), each with its
cause or its way out. It does no I/O; the generator's file adapter applies the plan.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final, NamedTuple

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    HubLock,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.rendered_file import Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
    TreeSnapshot,
    is_leftover_name,
)


@dataclass(frozen=True, kw_only=True, slots=True)
class FileWrite:
    """Write ``content`` at ``path``, with the executable bit or without it."""

    path: str
    content: bytes
    executable: bool


@dataclass(frozen=True, kw_only=True, slots=True)
class LinkWrite:
    """Make ``path`` a symlink to ``target``, relative to the link's folder."""

    path: str
    target: str


class PathProblem(NamedTuple):
    """Why ``path`` stops the init, with the way out."""

    path: str
    message: str


@dataclass(frozen=True, kw_only=True, slots=True)
class InitRefusal:
    """Every refused path, sorted by path: nothing is written."""

    problems: tuple[PathProblem, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class InitPlan:
    """What an init does, in order, and what it counts. Every path tuple is sorted.

    ``kept_seeded`` holds seeded files already there (``hub.json`` included), ``kept_equal`` managed
    files equal to their render, and ``kept_links`` links equal to their render, whatever their
    ownership: links are counted apart from files (spec Q-1).
    """

    leftovers: tuple[str, ...]
    folders: tuple[str, ...]
    writes: tuple[FileWrite | LinkWrite, ...]
    created_managed: tuple[str, ...]
    created_seeded: tuple[str, ...]
    created_links: tuple[str, ...]
    kept_seeded: tuple[str, ...]
    kept_equal: tuple[str, ...]
    kept_links: tuple[str, ...]
    lock: HubLock


class _Outcome(Enum):
    WRITE = "write"
    KEPT_SEEDED = "kept seeded"
    KEPT_EQUAL = "kept equal"


class _Group(Enum):
    MANAGED = "managed file"
    SEEDED = "seeded file"
    LINK = "link"


# A verdict is what happens at a path: an outcome, or the message of the problem that refuses it.
type _Verdict = _Outcome | str

_LOCK_PRESENT: Final = "this folder is already a hub; run hub sync"
_DIFFERS: Final = "differs from its render; run hub sync --adopt"
_HUB_JSON_DIFFERS: Final = "differs from the one this run would write; run hub sync --adopt"
_UNKNOWN: Final = "not part of the hub; run hub sync --adopt"
_OUTSIDE: Final = "resolves outside the hub"
_NOT_REGULAR: Final = "not a regular file"


@dataclass(frozen=True, kw_only=True, slots=True)
class _Decision:
    path: str
    group: _Group
    verdict: _Verdict
    write: FileWrite | LinkWrite


def _content(entry: FileEntry, path: str) -> bytes:
    if entry.content is None:
        # A caller bug: the tree reader was not asked to read a path the planner compares.
        msg = f"{path}: content was not read; wanted must include it"
        raise ValueError(msg)
    return entry.content


def _type_problem(entry: TreeEntry, *, belongs: str) -> str:
    if isinstance(entry, OtherEntry):
        return _NOT_REGULAR
    found = {FileEntry: "file", LinkEntry: "link", FolderEntry: "folder"}[type(entry)]
    return f"a {found} where a {belongs} belongs"


def _file_verdict(file: RenderedFile, entry: TreeEntry | None) -> _Verdict:
    if entry is None:
        return _Outcome.WRITE
    if not isinstance(entry, FileEntry):
        return _type_problem(entry, belongs="file")
    # A seeded file is the project's once written: kept whatever its bytes or mode.
    if file.ownership is Ownership.SEEDED:
        return _Outcome.KEPT_SEEDED
    if _content(entry, file.path) == file.content and entry.executable == file.executable:
        return _Outcome.KEPT_EQUAL
    return _DIFFERS


def _link_verdict(link: RenderedLink, entry: TreeEntry | None) -> _Verdict:
    if entry is None:
        return _Outcome.WRITE
    if not isinstance(entry, LinkEntry):
        return _type_problem(entry, belongs="link")
    if entry.outside:
        return _OUTSIDE
    return _Outcome.KEPT_EQUAL if entry.target == link.target else _DIFFERS


def _hub_json_verdict(hub_json: bytes, entry: TreeEntry | None) -> _Verdict:
    if entry is None:
        return _Outcome.WRITE
    if not isinstance(entry, FileEntry):
        return _type_problem(entry, belongs="file")
    return _Outcome.KEPT_SEEDED if _content(entry, HUB_JSON_PATH) == hub_json else _HUB_JSON_DIFFERS


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts))]


def _ancestor_problem(path: str, entries: Mapping[str, TreeEntry]) -> str | None:
    # The reader never descends into a link, so the first ancestor that is not a folder is the one.
    for ancestor in _ancestors(path):
        entry = entries.get(ancestor)
        if isinstance(entry, LinkEntry):
            return f"symlinked ancestor {ancestor}"
        if entry is not None and not isinstance(entry, FolderEntry):
            return f"a file where a folder belongs: {ancestor}"
    return None


def _decision(
    path: str,
    group: _Group,
    verdict: _Verdict,
    *,
    write: FileWrite | LinkWrite,
    entries: Mapping[str, TreeEntry],
) -> _Decision:
    problem = _ancestor_problem(path, entries)
    return _Decision(path=path, group=group, verdict=problem or verdict, write=write)


def _decisions(
    rendered: RenderedHub, hub_json: bytes, entries: Mapping[str, TreeEntry]
) -> list[_Decision]:
    # Built in write order (Q-16): files, links, then ``hub.json``.
    decisions = [
        _decision(
            file.path,
            _Group.SEEDED if file.ownership is Ownership.SEEDED else _Group.MANAGED,
            _file_verdict(file, entries.get(file.path)),
            write=FileWrite(path=file.path, content=file.content, executable=file.executable),
            entries=entries,
        )
        for file in rendered.files
    ]
    decisions.extend(
        _decision(
            link.path,
            _Group.LINK,
            _link_verdict(link, entries.get(link.path)),
            write=LinkWrite(path=link.path, target=link.target),
            entries=entries,
        )
        for link in rendered.links
    )
    decisions.append(
        _decision(
            HUB_JSON_PATH,
            _Group.SEEDED,
            _hub_json_verdict(hub_json, entries.get(HUB_JSON_PATH)),
            write=FileWrite(path=HUB_JSON_PATH, content=hub_json, executable=False),
            entries=entries,
        )
    )
    return decisions


def _is_leftover(path: str, entry: TreeEntry) -> bool:
    # Only a file or a link is a leftover: a folder with that name is unknown (spec Q-5).
    name = path.rsplit("/", 1)[-1]
    return isinstance(entry, FileEntry | LinkEntry) and is_leftover_name(name)


def _rest_of_tree(
    entries: Mapping[str, TreeEntry], decisions: Iterable[_Decision]
) -> tuple[list[str], list[PathProblem]]:
    """The leftovers and the unknown entries: every entry no rendered path decides."""
    decided = {each.path for each in decisions} | {HUB_LOCK_PATH}
    # Ancestors of decided paths: a folder there is allowed, anything else refuses the paths below.
    ancestors = {ancestor for path in decided for ancestor in _ancestors(path)}
    leftovers: list[str] = []
    unknown: list[PathProblem] = []
    for path, entry in entries.items():
        if path in decided or path in ancestors:
            continue
        if _is_leftover(path, entry):
            leftovers.append(path)
        else:
            unknown.append(PathProblem(path, _UNKNOWN))
    return sorted(leftovers), unknown


def _problems(
    decisions: Iterable[_Decision], unknown: Iterable[PathProblem], entries: Mapping[str, TreeEntry]
) -> tuple[PathProblem, ...]:
    found = [
        PathProblem(each.path, each.verdict) for each in decisions if isinstance(each.verdict, str)
    ]
    found.extend(unknown)
    if HUB_LOCK_PATH in entries:
        found.append(PathProblem(HUB_LOCK_PATH, _LOCK_PRESENT))
    return tuple(sorted(found))


def _missing_folders(paths: Iterable[str], present: Collection[str]) -> tuple[str, ...]:
    # Sorting puts a parent before its children: a path sorts before every longer one it prefixes.
    wanted = {ancestor for path in paths for ancestor in _ancestors(path)}
    return tuple(sorted(folder for folder in wanted if folder not in present))


def _check_render(rendered: RenderedHub) -> None:
    paths = {file.path for file in rendered.files} | {link.path for link in rendered.links}
    reserved = sorted(paths & {HUB_JSON_PATH, HUB_LOCK_PATH})
    if reserved:
        # A registry bug, never user input: init writes these two paths itself.
        msg = f"the render must not hold {reserved[0]}"
        raise ValueError(msg)


def _paths(decisions: Iterable[_Decision], outcome: _Outcome, *groups: _Group) -> tuple[str, ...]:
    return tuple(
        sorted(each.path for each in decisions if each.verdict is outcome and each.group in groups)
    )


def plan_init(
    *, rendered: RenderedHub, config: HubConfig, hub_json: bytes, tree: TreeSnapshot
) -> InitPlan | InitRefusal:
    """Plan an init of ``rendered`` for ``config`` into the target ``tree`` describes.

    ``tree`` must hold the content of every rendered managed file and of ``hub.json``: the tree
    reader's ``wanted`` includes those paths. Raises ``ValueError`` when the render holds
    ``hub.json`` or ``hub.lock``, or when a file it compares was read without its content.
    """
    _check_render(rendered)
    decisions = _decisions(rendered, hub_json, tree.entries)
    leftovers, unknown = _rest_of_tree(tree.entries, decisions)
    problems = _problems(decisions, unknown, tree.entries)
    if problems:
        return InitRefusal(problems=problems)
    lock = build_hub_lock(rendered=rendered, config=config)
    writes = [each.write for each in decisions if each.verdict is _Outcome.WRITE]
    writes.append(FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(lock), executable=False))
    write, kept_seeded, kept_equal = _Outcome.WRITE, _Outcome.KEPT_SEEDED, _Outcome.KEPT_EQUAL
    return InitPlan(
        leftovers=tuple(leftovers),
        folders=_missing_folders((each.path for each in decisions), tree.entries),
        writes=tuple(writes),
        created_managed=_paths(decisions, write, _Group.MANAGED),
        created_seeded=_paths(decisions, write, _Group.SEEDED),
        created_links=_paths(decisions, write, _Group.LINK),
        kept_seeded=_paths(decisions, kept_seeded, _Group.SEEDED),
        kept_equal=_paths(decisions, kept_equal, _Group.MANAGED),
        kept_links=_paths(decisions, kept_equal, _Group.LINK),
        lock=lock,
    )
