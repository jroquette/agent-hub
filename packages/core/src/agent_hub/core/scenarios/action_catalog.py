"""The actions a hub has: each one's pack, files, content hash and draft state, and how an
``action`` reference finds one (docs/design/scenarios.md § Actions and the script contract).

The loader (``generator.action_discovery``) reads the files and asks git which are drafts; this
module only names what it found. A reference is ``<name>``, an action of the same pack, or
``<pack>/<name>``; without a pack (a command given a bare name) the name must be in one pack.
"""

import hashlib
from collections.abc import Iterable
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.scenarios.action_document import ActionDocument

# The hub's folder of action packs, ``actions/<pack>/``.
HUB_ACTIONS_FOLDER: Final = "actions"


class ActionRefError(AgentHubError):
    """An ``action`` reference that names no action, or more than one."""


class ActionEntry(BaseModel):
    """One loaded action: ``draft`` when its files are not committed as they are on disk."""

    model_config = ConfigDict(frozen=True)

    pack: str
    document: ActionDocument
    # Paths relative to the hub, with ``/``.
    document_path: str
    script_path: str
    content_hash: str
    draft: bool

    @property
    def ref(self) -> str:
        """The reference that names this action from any pack: ``<pack>/<name>``."""
        return f"{self.pack}/{self.document.name}"


def action_content_hash(
    *, document_path: str, document: bytes, script_path: str, script: bytes
) -> str:
    """``sha256:`` over the document then the script, each as ``<path>\\0<len>\\0<bytes>``
    (the framing of a run's snapshot hash), so a run can pin exactly what it ran."""
    digest = hashlib.sha256()
    for path, data in ((document_path, document), (script_path, script)):
        digest.update(f"{path}\0{len(data)}\0".encode() + data)
    return f"sha256:{digest.hexdigest()}"


def resolve_action(
    entries: Iterable[ActionEntry], ref: str, *, pack: str | None = None
) -> ActionEntry:
    """The action ``ref`` names, read from ``pack`` when it is a bare name; raises
    ``ActionRefError`` when it names none or, without a pack, more than one."""
    entries = tuple(entries)
    if "/" in ref:
        found = [entry for entry in entries if entry.ref == ref]
        where = ""
    else:
        found = [
            entry for entry in entries if entry.document.name == ref and pack in (None, entry.pack)
        ]
        where = f" in pack {pack}" if pack is not None else ""
    if not found:
        raise ActionRefError(f"unknown action {ref!r}{where}")
    if len(found) > 1:
        packs = ", ".join(sorted(entry.pack for entry in found))
        raise ActionRefError(
            f"action {ref!r} is in more than one pack ({packs}): name it as <pack>/{ref}"
        )
    return found[0]
