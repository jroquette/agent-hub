"""``links.dead``: relative Markdown links resolve to a file or folder (spec AC-11.27, Q-18, E19).

The rule reads every listed regular ``.md`` file that is UTF-8 text (any other is skipped,
Q-19), of the hub and of each checked-out repo, line by line (``config_lint.text_lines``, E29):

- Links: the destinations ``knowledge.document_links`` reads (its docstring holds the
  grammar: inline links and images and reference definitions, outside fenced blocks, HTML
  comments and code spans). A destination with a URI scheme, a fragment only, an absolute
  one or an empty one is not checked; else its path is resolved from the file's folder.
- Exists: a listed path or a folder with a listed path under it; for the hub, also the fixed
  paths present (``config_lint.known_paths``, E31), and every fixed path when not all were read.
  A link is never followed (D3). A hub link into ``../<dir>/`` for a ``repos[].dir`` is checked
  against that checkout's listing, and skipped when the checkout is missing (the runner reports
  it, Q-9) or could not be listed (E36), whose own files are not read either; any other link
  that leaves the hub, or a repo, is not checked (E37).

A repo's findings are at ``../<dir>/<path>``. Every scan is linear in its line (each search
resumes where the last one stopped, and the destinations never overlap) and every path is
resolved through a segments tree, so a hostile line, a deep path or many files never cost more
than their size.
"""

from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from agent_hub.core.doctor.config_lint import (
    MARKDOWN,
    PathTrie,
    file_text,
    known_paths,
    path_tree,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles, hub_paths
from agent_hub.core.hub_config.doctor_rules import LINKS_DEAD_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.knowledge.document_links import link_destinations, link_path

DEAD_FIX: Final = "point the link at an existing file or folder, or remove it"
_HERE: Final = frozenset({"", "."})
_UP: Final = ".."


@dataclass(frozen=True, kw_only=True, slots=True)
class _Tree:
    """A tree whose Markdown is read: its files and paths, how its paths are shown, and the
    checkouts its links into ``../<dir>/`` are checked against (``None`` for a repo's).
    """

    files: HubFiles
    paths: PathTrie
    shown_as: str
    checkouts: Mapping[str, PathTrie | None] | None


def _links_dead(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    # A checkout that could not be listed is treated as a missing one (E36).
    checkouts = {
        repo.dir: None
        if repo.files is None or repo.files.problem is not None
        else path_tree(repo.files.listed)
        for repo in snapshot.repos
    }
    hub = _Tree(
        files=snapshot.hub,
        paths=path_tree(_hub_paths(snapshot)),
        shown_as="",
        checkouts=checkouts,
    )
    yield from _tree_findings(hub)
    for repo in snapshot.repos:
        checkout = checkouts[repo.dir]
        if repo.files is not None and checkout is not None:
            tree = _Tree(
                files=repo.files, paths=checkout, shown_as=f"../{repo.dir}/", checkouts=None
            )
            yield from _tree_findings(tree)


def _hub_paths(snapshot: DoctorSnapshot) -> Iterator[str]:
    """The hub's known paths (E31); a fixed path not reached may exist, so it counts too."""
    config = snapshot.hub_config
    yield from known_paths(snapshot.hub, config=config)
    if not snapshot.hub.paths_read:
        yield from hub_paths(config)


def _tree_findings(tree: _Tree) -> Iterator[Finding]:
    for path in tree.files.listed:
        if not path.endswith(MARKDOWN):
            continue
        text = file_text(tree.files.entries.get(path))
        if not isinstance(text, str):
            continue
        folder = _folder_nodes(path, paths=tree.paths)
        for number, destination in link_destinations(text):
            target = link_path(destination)
            if target is not None and _is_dead(target, folder=folder, tree=tree):
                yield LINKS_DEAD.finding(
                    path=f"{tree.shown_as}{path}",
                    line=number,
                    message=f"dead link `{cut_echo(destination)}` (no such file or folder)",
                    fix=DEAD_FIX,
                )


def _folder_nodes(path: str, *, paths: PathTrie) -> list[PathTrie | None]:
    """The tree's nodes from the root to the file's folder, once per file."""
    node: PathTrie | None = paths
    nodes = [node]
    for segment in path.split("/")[:-1]:
        node = None if node is None else node.children.get(segment)
        nodes.append(node)
    return nodes


def _is_dead(target: str, *, folder: Sequence[PathTrie | None], tree: _Tree) -> bool:
    """Whether the target, from the file's folder, is no path or folder of the tree or of the
    checkout it climbs into; a target that leaves the workspace, or a repo, is never dead.
    """
    up, rest = _climbs_and_segments(target)
    depth = len(folder) - 1
    if up <= depth:
        node = folder[depth - up]
        return node is None or not node.holds(rest)
    if up > depth + 1 or not rest or tree.checkouts is None:
        return False
    checkout = tree.checkouts.get(rest[0])
    return checkout is not None and not checkout.holds(rest[1:])


def _climbs_and_segments(target: str) -> tuple[int, list[str]]:
    """How many folders the target climbs above its start, then its segments from there."""
    up = 0
    rest: list[str] = []
    for segment in target.split("/"):
        if segment == _UP:
            if rest:
                rest.pop()
            else:
                up += 1
        elif segment not in _HERE:
            rest.append(segment)
    return up, rest


LINKS_DEAD: Final = Rule(
    id=LINKS_DEAD_RULE,
    severity=Severity.ERROR,
    summary="relative Markdown links in the hub and its repos resolve to a file or folder",
    module=RULE_MODULES.get(LINKS_DEAD_RULE),
    reads=frozenset({Read.HUB_LISTING, Read.REPOS}),
    check=_links_dead,
)
