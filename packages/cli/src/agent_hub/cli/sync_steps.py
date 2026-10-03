"""The steps ``hub sync`` and ``hub sync --adopt`` share: lock, tree read, render and apply.

``hub.lock`` is read once, never through a link: absent is ``None``; not a regular file or
malformed exits 1 with one line per problem, then the command's way out. Then one read of only the
planned paths (plus a listing of the project's agent and skill folders and a look at the link path
of each name found there), the project's extension inputs from that read (a bad
``*.project.json`` sibling or an entry name the lock cannot hold exits 1), and the render with
them. The apply opens the root once (leftovers, deletes, folders, files, links, ``hub.lock`` last);
an I/O error exits 1 naming the path.
"""

from collections.abc import Mapping
from pathlib import Path
from typing import Final, NamedTuple

from agent_hub.cli.command_exits import extension_inputs_or_exit, fail, fail_generator
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import LINKED_TYPES, ExtensionInputs
from agent_hub.core.hub_files.hub_lock import (
    HUB_JSON_PATH,
    HUB_LOCK_PATH,
    LOCK_NOT_REGULAR,
    HubLock,
    LockEntry,
    ManagedFileEntry,
    read_hub_lock,
)
from agent_hub.core.hub_files.plan_adopt import AdoptPlan
from agent_hub.core.hub_files.plan_sync import SyncPlan
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeSnapshot
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.file_adapter import apply_sync
from agent_hub.generator.hub_tree import LinkFolder, read_planned_tree, read_root_entry
from agent_hub.generator.render_hub import project_json_siblings, render_hub

# A change the project made to a managed path, or (adopt) a path listed: exit 3 (ADR 0009).
CONFLICT: Final = 3
# Changes are pending: nothing was written.
PENDING: Final = 4
MISSING_HUB_JSON_HINT: Final = "run hub sync in the hub folder"


class Rendering(NamedTuple):
    """The one tree read, the extension inputs found in it, and the render with them."""

    tree: TreeSnapshot
    extensions: ExtensionInputs
    rendered: RenderedHub


def lock_or_exit(root: Path, *, way_out: str) -> tuple[HubLock, bytes] | None:
    """The lock and its exact bytes, read once and never through a link (spec Q-6, Q-12).

    ``None`` when there is no ``hub.lock``; a lock that cannot be used exits 1, ``way_out`` last.
    """
    try:
        entry = read_root_entry(root, HUB_LOCK_PATH)
    except GeneratorError as error:
        fail_generator(error)
    if entry is None:
        return None
    # A regular file is always returned with its content; anything else was never opened.
    if not isinstance(entry, FileEntry) or entry.content is None:
        fail(_lock_line(LOCK_NOT_REGULAR), _lock_line(way_out))
    read = read_hub_lock(entry.content)
    if not isinstance(read, HubLock):
        problems = (_lock_line(f"{problem.path}: {problem.message}") for problem in read)
        fail(*problems, _lock_line(way_out))
    return read, entry.content


def _lock_line(message: str) -> str:
    return f"{HUB_LOCK_PATH}: {message}"


def planned_paths(
    rendered: RenderedHub, lock_files: Mapping[str, LockEntry]
) -> tuple[list[str], set[str]]:
    """The paths to look at and those whose content is compared.

    ``hub.json`` is the project's and ``hub.lock`` was read already: neither is looked at again.
    """
    in_render = {file.path for file in rendered.files} | {link.path for link in rendered.links}
    paths = sorted((in_render | set(lock_files)) - {HUB_JSON_PATH})
    wanted = {file.path for file in rendered.files if file.ownership is Ownership.MANAGED}
    wanted |= {path for path, entry in lock_files.items() if isinstance(entry, ManagedFileEntry)}
    return paths, wanted - {HUB_JSON_PATH}


def links_in(project: str) -> dict[str, LinkFolder]:
    """The project's agent and skill folders, each with the folder that holds their links."""
    return {
        f"plugin/{project}/{folder}": LinkFolder(f".claude/{folder}", linked=linked)
        for folder, linked in LINKED_TYPES.items()
    }


def rendering_or_exit(
    root: Path, *, config: HubConfig, lock_files: Mapping[str, LockEntry]
) -> Rendering:
    """One tree read for both renders (spec Q-20).

    The paths come from the render without extension inputs: the inputs only change the bytes of
    a merged ``X.json`` and add a ``.claude`` link per project entry, whose path the read looks at
    for each name it lists (so a project's own file there is a conflict, never replaced).
    """
    project = config.project.name
    try:
        siblings = project_json_siblings(config)
        paths, wanted = planned_paths(render_hub(config), lock_files)
        folders = links_in(project)
        tree = read_planned_tree(
            root, paths=paths, wanted={*wanted, *siblings}, listed=folders, links_in=folders
        )
    except GeneratorError as error:
        fail_generator(error)
    extensions = extension_inputs_or_exit(tree, project=project, siblings=siblings)
    try:
        # A sibling that cannot be merged is a ``MergeError``: one line, exit 1.
        rendered = render_hub(config, extensions)
    except GeneratorError as error:
        fail_generator(error)
    return Rendering(tree=tree, extensions=extensions, rendered=rendered)


def apply_or_exit(root: Path, plan: SyncPlan | AdoptPlan) -> None:
    """Apply ``plan`` with one open of ``root``; an I/O error exits 1 naming the path."""
    try:
        apply_sync(
            root,
            leftovers=plan.leftovers,
            deletes=plan.deletes,
            folders=plan.folders,
            writes=plan.writes,
        )
    except GeneratorError as error:
        fail_generator(error)
