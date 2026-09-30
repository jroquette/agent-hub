"""Links derived from the plugin files: one ``.claude`` link per agent file and per skill folder.

Claude Code reads a hub's own agents and skills from ``.claude/agents/`` and ``.claude/skills/``;
each entry there links to its plugin (spec D3). ``plugin/<p>/agents/<name>`` gives
``.claude/agents/<name>``, and every file under ``plugin/<p>/skills/<name>/`` gives the one link
``.claude/skills/<name>``. A dotfile (``.gitkeep``) never causes a link, nor does anything under a
dotfile ``<name>``. The project's own entries, which the render never holds, are linked from their
names (``project_links``, spec Q-17). Links are data: nothing here touches the filesystem.
"""

from collections.abc import Collection, Iterator, Sequence

from agent_hub.core.hub_files.rendered_file import Kind, Ownership, RenderedFile
from agent_hub.core.hub_files.rendered_link import RenderedLink
from agent_hub.generator.errors import GeneratorError

# ``plugin/<p>/<folder>/<name>`` has this many segments; skills need at least one more.
_ENTRY_SEGMENTS = 4
# From ``.claude/<folder>/<name>`` back to the hub root.
_UP_TO_ROOT = "../../"


def plugin_links(files: Sequence[RenderedFile]) -> tuple[RenderedLink, ...]:
    """Return the links of ``files``' plugin entries, sorted by path, all generic and managed.

    Raises ``GeneratorError`` naming the link path when two plugins hold an entry of that name.
    """
    targets: dict[str, str] = {}
    for link_path, target in _entries(files):
        known = targets.setdefault(link_path, target)
        if known != target:
            msg = f"{link_path}: linked from two plugins ({known} and {target})"
            raise GeneratorError(msg)
    return tuple(_managed_link(link_path, targets[link_path]) for link_path in sorted(targets))


def project_links(
    *, project: str, agents: Sequence[str], skills: Sequence[str], taken: Collection[str]
) -> tuple[RenderedLink, ...]:
    """Return one link per project agent and skill name, sorted by path, all generic and managed.

    ``.claude/agents/<name>`` targets ``plugin/<project>/agents/<name>``, and the same for skills.
    A name whose link path is in ``taken`` (a base plugin link) gets none: the base plugin keeps
    its link, and the sync planner reports the name in both plugins (plan E8).
    """
    targets = {
        f".claude/{folder}/{name}": f"plugin/{project}/{folder}/{name}"
        for folder, names in (("agents", agents), ("skills", skills))
        for name in names
    }
    return tuple(
        _managed_link(link_path, targets[link_path])
        for link_path in sorted(targets)
        if link_path not in taken
    )


def _managed_link(link_path: str, entry_path: str) -> RenderedLink:
    return RenderedLink(
        path=link_path,
        target=_UP_TO_ROOT + entry_path,
        kind=Kind.GENERIC,
        ownership=Ownership.MANAGED,
        module=None,
    )


def _entries(files: Sequence[RenderedFile]) -> Iterator[tuple[str, str]]:
    """Yield ``(link path, entry path)`` per plugin entry file; a skill folder once per file."""
    for file in files:
        segments = file.path.split("/")
        if len(segments) < _ENTRY_SEGMENTS or segments[0] != "plugin":
            continue
        _, plugin, folder, name, *rest = segments
        # A dotfile never causes a link: a skill folder holding only ``.gitkeep`` gets none.
        if name.startswith(".") or segments[-1].startswith("."):
            continue
        if (folder == "agents" and not rest) or (folder == "skills" and rest):
            yield f".claude/{folder}/{name}", f"plugin/{plugin}/{folder}/{name}"
