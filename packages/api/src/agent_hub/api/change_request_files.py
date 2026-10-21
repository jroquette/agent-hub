"""The owner's decision on a plan change request, written into the hub's feature folder
(two-level-flows AC-2.14, D-11): ``brain/features/<slug>/change-requests/<n>.decision.md``.

The slug comes from a feature folder the reader found, ``n`` from a request it read. Each folder
below the hub is opened with ``O_DIRECTORY | O_NOFOLLOW`` from its parent's descriptor, so no
link is followed on the way, even one swapped in after the read; the file is created there
exclusively (``O_EXCL``), never overwriting a decision or writing through a link of its name.
"""

import os
from contextlib import ExitStack
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.features.change_request_decision import MAX_NOTE_CHARS
from agent_hub.core.features.ticket_records import CHANGE_REQUESTS_FOLDER

_FEATURES = ("brain", "features")
_FOLDER = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)


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
        file or link of that name), another ``OSError`` when a folder is missing or a link."""
        if "/" in slug or slug.startswith(".") or n < 1:
            raise ValueError("invalid feature or change request")
        with ExitStack() as opened:
            folder = os.open(hub_path, os.O_RDONLY | os.O_DIRECTORY)
            opened.callback(os.close, folder)
            for name in (*_FEATURES, slug, CHANGE_REQUESTS_FOLDER):
                folder = os.open(name, _FOLDER, dir_fd=folder)
                opened.callback(os.close, folder)
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            descriptor = os.open(f"{n}.decision.md", flags, 0o644, dir_fd=folder)
            with os.fdopen(descriptor, "w", encoding="utf-8") as note:
                note.write(text)
