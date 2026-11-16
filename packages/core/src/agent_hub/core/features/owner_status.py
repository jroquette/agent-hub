"""The owner decides a feature's status from hub web (playground): pure, no I/O but the ports.

The phase a feature shows is derived from its records, and some records are never closed: an agent
that stops at "In Review", a plan whose tickets were never listed, owner checks nobody will run.
The owner's decision ends that: ``shipped`` (the work is delivered), ``closed`` (it ends without
shipping) or ``paused`` (set aside, out of the work in progress). It is written as
``brain/features/<slug>/status.md``, left uncommitted for the owner's hub PR, as the owner sign-off
is (ADR 0040), and the list reads it over the derived phase. ``active`` reopens the feature: the
note stays, with ``status: active``, so the derived phase speaks again.
"""

from collections.abc import Callable
from datetime import datetime
from typing import Final, Literal, Protocol

from agent_hub.core.features.feature_status import STATUS
from agent_hub.core.features.owner_signoff import ProjectHubs
from agent_hub.core.readmodels.read_ports import EntityNotFoundError

MAX_STATUS_NOTE_CHARS: Final = 2_000

type OwnerStatusDecision = Literal["shipped", "closed", "paused", "active"]

_TITLES: Final[dict[OwnerStatusDecision, str]] = {
    "shipped": "Marked shipped by the owner",
    "closed": "Closed by the owner without shipping",
    "paused": "Paused by the owner",
    "active": "Reopened by the owner",
}


class StatusWriter(Protocol):
    """Writes a feature folder's ``status.md``."""

    def write_status(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        """Replace ``brain/features/<slug>/<name>`` with ``text``; ``FileNotFoundError`` when
        the feature folder does not exist."""
        ...


def status_note(
    *, slug: str, status: OwnerStatusDecision, at: datetime, note: str | None = None
) -> str:
    """The text of ``status.md`` for the owner's decision."""
    body = f"\n{note.strip()}\n" if note and note.strip() else ""
    return (
        "---\n"
        "type: feature-status\n"
        f"feature: {slug}\n"
        f"status: {status}\n"
        f"decided_at: {at.isoformat(timespec='seconds')}\n"
        "provenance: owner\n"
        "---\n"
        f"# {_TITLES[status]}\n"
        f"{body}"
    )


class SetOwnerStatus:
    """Writes the owner's decision on a feature into its hub folder."""

    def __init__(
        self, hubs: ProjectHubs, writer: StatusWriter, *, clock: Callable[[], datetime]
    ) -> None:
        self._hubs = hubs
        self._writer = writer
        self._clock = clock

    def __call__(
        self, project: str, slug: str, *, status: OwnerStatusDecision, note: str | None = None
    ) -> None:
        """Record ``status`` for the feature; ``EntityNotFoundError`` when it has no folder."""
        hub = self._hubs.hub_path_of(project)
        text = status_note(slug=slug, status=status, at=self._clock(), note=note)
        try:
            self._writer.write_status(hub, slug=slug, name=STATUS, text=text)
        except FileNotFoundError as missing:
            raise EntityNotFoundError(entity="feature", entity_id=slug) from missing
