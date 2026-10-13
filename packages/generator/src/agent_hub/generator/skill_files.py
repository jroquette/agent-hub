"""Read a hub's skills, agents and hooks for the Skills tab (AGH-164, S1, P1).

``list_skill_sources`` lists every entry under core's skill roots, stat-only and bounded;
``read_skill_file`` reads one path core's ``skill_relative`` accepts, never through a link, a
regular file of at most ``max_bytes``. Both follow ``brain_files``' read policy: each folder is
opened relative to its parent (``os.open(name, O_NOFOLLOW, dir_fd=parent)``), an entry is looked
at with ``follow_symlinks=False``, a link's target is read as text only, and messages hold no path.

Wave 0 declares the shape; the walk and the read land with stream G.
"""

from pathlib import Path

from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.skills.skill_sources import SkillLimits, SkillSources


def list_skill_sources(hub_root: Path, limits: SkillLimits) -> SkillSources:
    """Every entry under the skill roots of ``hub_root`` in path order, within ``limits``."""
    del hub_root, limits
    raise NotImplementedError


def read_skill_file(hub_root: Path, path: str, *, max_bytes: int) -> bytes | UnreadHubFile:
    """The bytes of the hub-relative ``path``, or why not."""
    del hub_root, path, max_bytes
    raise NotImplementedError
