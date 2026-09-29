"""Links derived from the plugin files: one ``.claude`` link per agent file and per skill folder.

Claude Code reads a hub's own agents and skills from ``.claude/agents/`` and ``.claude/skills/``;
each entry there links to its plugin (spec D3). ``plugin/<p>/agents/<name>`` gives
``.claude/agents/<name>``, and every file under ``plugin/<p>/skills/<name>/`` gives the one link
``.claude/skills/<name>``. A dotfile (``.gitkeep``) never causes a link, nor does anything under a
dotfile ``<name>``. Links are data: nothing here touches the filesystem.
"""

from collections.abc import Iterator, Sequence

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
    return tuple(
        RenderedLink(
            path=link_path,
            target=_UP_TO_ROOT + targets[link_path],
            kind=Kind.GENERIC,
            ownership=Ownership.MANAGED,
            module=None,
        )
        for link_path in sorted(targets)
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
