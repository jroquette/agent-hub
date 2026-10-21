"""The owner's decision on a plan change request, written into the hub's feature folder
(two-level-flows AC-2.14, D-11): ``brain/features/<slug>/change-requests/<n>.decision.md``.

The slug comes from a feature folder the reader found, ``n`` from a request it read. The file is
created exclusively, never overwriting a decision, and no link is followed into the feature
folder, its ``change-requests/`` folder or the file itself.
"""

import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.features.change_request_decision import MAX_NOTE_CHARS
from agent_hub.core.features.ticket_records import CHANGE_REQUESTS_FOLDER

_FEATURES = ("brain", "features")


class ChangeRequestDecisionBody(BaseModel):
    """``POST .../change-requests/{n}/decision``: approved or declined, and the owner's note
    (required to decline)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: Literal["approved", "declined"]
    note: str | None = Field(default=None, max_length=MAX_NOTE_CHARS)


class HubDecisionWriter:
    """``DecisionWriter`` on the local file system."""

    def create_decision(self, hub_path: str, *, slug: str, n: int, text: str) -> None:
        """Create the decision of request ``n``; ``FileExistsError`` when one exists (or any
        file or link of that name), ``FileNotFoundError`` when a folder is missing or a link."""
        if "/" in slug or slug.startswith(".") or n < 1:
            raise ValueError("invalid feature or change request")
        feature = Path(hub_path, *_FEATURES, slug)
        folder = feature / CHANGE_REQUESTS_FOLDER
        for part in (feature, folder):
            if part.is_symlink() or not part.is_dir():
                raise FileNotFoundError(part.name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(folder / f"{n}.decision.md", flags, 0o644)
        with os.fdopen(descriptor, "w", encoding="utf-8") as note:
            note.write(text)
