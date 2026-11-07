"""What each bundled file role means to the owner (S7), as the Skills screen words it.

The web app draws these words itself (``apps/web/src/screens/skills/BundledFiles.tsx``); no
production path reads them from Python.
"""

from collections.abc import Mapping
from typing import Final

from agent_hub.core.skills.skill_view import FileRole

ROLE_LABELS: Final[Mapping[FileRole, str]] = {
    "scripts": "executed at invocation",
    "references": "read on demand",
    "assets": "assets",
    "other": "other",
}


def role_label(role: FileRole) -> str:
    """What a role means to the owner: ``scripts`` "executed at invocation", ``references``
    "read on demand"."""
    return ROLE_LABELS[role]
