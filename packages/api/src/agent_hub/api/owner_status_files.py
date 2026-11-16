"""The owner's status decision, written as ``status.md`` into the hub's feature folder (ADR 0065).

Like the owner sign-off (ADR 0040) it is left uncommitted for the owner's hub PR. Unlike the
sign-off's eval note, which is created once, the decision replaces the last one: it is written to
a fresh temporary file in the folder and renamed over ``status.md``, never through a link.
"""

import os
import tempfile
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.api.owner_signoff_files import feature_folder
from agent_hub.core.features.owner_status import MAX_STATUS_NOTE_CHARS


class OwnerStatusBody(BaseModel):
    """``POST .../status``: the owner's decision and an optional note on why."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["shipped", "closed", "paused", "active"]
    note: str | None = Field(default=None, max_length=MAX_STATUS_NOTE_CHARS)


class HubStatusWriter:
    """``StatusWriter`` on the local file system."""

    def write_status(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        """Replace ``brain/features/<slug>/<name>``; ``FileNotFoundError`` without the folder, or
        when the slug or name is not one plain name or ``name`` is a link."""
        if "/" in slug or "/" in name or slug.startswith(".") or name.startswith("."):
            raise FileNotFoundError(slug)
        feature = feature_folder(hub_path, slug)
        target = feature / name
        if target.is_symlink():
            raise FileNotFoundError(name)
        descriptor, temporary = tempfile.mkstemp(dir=feature, prefix=f".{name}.", suffix=".tmp")
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as note:
                note.write(text)
            Path(temporary).chmod(0o644)
            Path(temporary).replace(target)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise
