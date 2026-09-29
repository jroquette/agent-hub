"""The init planner (ADR 0011): what ``hub init`` writes into a target, decided in memory.

``plan_init`` takes the render, the ``hub.json`` bytes this run would write and a snapshot of the
target. It returns an ``InitPlan``: the folders to make, then the writes in the order of spec Q-16
(files, links, ``hub.json``, and ``hub.lock`` last), with what was kept. It does no I/O; the
generator's file adapter applies the plan.
"""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple, NoReturn

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
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry, TreeSnapshot


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


@dataclass(frozen=True, kw_only=True, slots=True)
class _Decision:
    path: str
    group: _Group
    outcome: _Outcome
    write: FileWrite | LinkWrite


def _not_planned(path: str) -> NoReturn:
    msg = f"{path}: no init rule covers what the target holds at this path"
    raise NotImplementedError(msg)


def _content(entry: FileEntry, path: str) -> bytes:
    if entry.content is None:
        # A caller bug: the tree reader was not asked to read a path the planner compares.
        msg = f"{path}: content was not read; wanted must include it"
        raise ValueError(msg)
    return entry.content


def _file_outcome(file: RenderedFile, entry: TreeEntry | None) -> _Outcome:
    if entry is None:
        return _Outcome.WRITE
    if isinstance(entry, FileEntry):
        # A seeded file is the project's once written: kept whatever its bytes or mode.
        if file.ownership is Ownership.SEEDED:
            return _Outcome.KEPT_SEEDED
        if _content(entry, file.path) == file.content and entry.executable == file.executable:
            return _Outcome.KEPT_EQUAL
    return _not_planned(file.path)


def _link_outcome(link: RenderedLink, entry: TreeEntry | None) -> _Outcome:
    if entry is None:
        return _Outcome.WRITE
    if isinstance(entry, LinkEntry) and not entry.outside and entry.target == link.target:
        return _Outcome.KEPT_EQUAL
    return _not_planned(link.path)


def _hub_json_outcome(hub_json: bytes, entry: TreeEntry | None) -> _Outcome:
    if entry is None:
        return _Outcome.WRITE
    if isinstance(entry, FileEntry) and _content(entry, HUB_JSON_PATH) == hub_json:
        return _Outcome.KEPT_SEEDED
    return _not_planned(HUB_JSON_PATH)


def _decisions(
    rendered: RenderedHub, hub_json: bytes, entries: Mapping[str, TreeEntry]
) -> list[_Decision]:
    # Built in write order (Q-16): files, links, then ``hub.json``.
    decisions = [
        _Decision(
            path=file.path,
            group=_Group.SEEDED if file.ownership is Ownership.SEEDED else _Group.MANAGED,
            outcome=_file_outcome(file, entries.get(file.path)),
            write=FileWrite(path=file.path, content=file.content, executable=file.executable),
        )
        for file in rendered.files
    ]
    decisions.extend(
        _Decision(
            path=link.path,
            group=_Group.LINK,
            outcome=_link_outcome(link, entries.get(link.path)),
            write=LinkWrite(path=link.path, target=link.target),
        )
        for link in rendered.links
    )
    decisions.append(
        _Decision(
            path=HUB_JSON_PATH,
            group=_Group.SEEDED,
            outcome=_hub_json_outcome(hub_json, entries.get(HUB_JSON_PATH)),
            write=FileWrite(path=HUB_JSON_PATH, content=hub_json, executable=False),
        )
    )
    return decisions


def _ancestors(path: str) -> list[str]:
    parts = path.split("/")
    return ["/".join(parts[:end]) for end in range(1, len(parts))]


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
        sorted(each.path for each in decisions if each.outcome is outcome and each.group in groups)
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
    lock = build_hub_lock(rendered=rendered, config=config)
    writes = [each.write for each in decisions if each.outcome is _Outcome.WRITE]
    writes.append(FileWrite(path=HUB_LOCK_PATH, content=lock_bytes(lock), executable=False))
    write, kept_seeded, kept_equal = _Outcome.WRITE, _Outcome.KEPT_SEEDED, _Outcome.KEPT_EQUAL
    return InitPlan(
        leftovers=(),
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
