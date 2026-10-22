"""The at-most-once marker of a scenario finding's tracker issue (AGH-350, AGH-363 Q7).

``hub scenario findings --issue`` and hub web's ``POST
/scenario-runs/{run}/findings/{finding}/issue`` both create a finding's issue only after
claiming ``finding-<id>.issue`` in the scenario run's folder: made exclusively, owner-only,
never through a link, before the tracker is called. After the call the marker holds the issue
(``{"id", "url"}``) or ``{"failed": true}``; a later claim, from either side, is refused, so
together they create at most one issue per finding, and a create that failed is never tried
again (the issue may exist: the person checks the tracker).
"""

import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

_NEW_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FILE: Final = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
_MARKER_BYTES: Final = 4096


@dataclass(frozen=True, kw_only=True, slots=True)
class IssueMarked:
    """An earlier claim of the finding's issue: the issue when it is known."""

    finding_id: str
    issue_id: str | None
    url: str | None

    @property
    def reason(self) -> str:
        """Why no issue is created now, in plain words."""
        if self.issue_id is None:
            return (
                f"an earlier create of finding {self.finding_id}'s issue did not finish; check"
                " the tracker (it is not tried again)"
            )
        reason = f"finding {self.finding_id} already has the issue {self.issue_id}"
        return f"{reason}: {self.url}" if self.url else reason


def issue_marker(folder: Path, finding_id: str) -> Path:
    """The marker of ``finding_id``'s issue in the scenario run's ``folder``."""
    return folder / f"finding-{finding_id}.issue"


def marked_issue(folder: Path, finding_id: str) -> IssueMarked | None:
    """The earlier claim of ``finding_id``'s issue, None when there is none."""
    marker = issue_marker(folder, finding_id)
    if not marker.exists() and not marker.is_symlink():
        return None
    return _marked(marker, finding_id)


def claim_issue(folder: Path, finding_id: str) -> IssueMarked | None:
    """Claim ``finding_id``'s issue: None when this call made the marker (the caller then
    creates the issue and records it), else the earlier claim; ``OSError`` when the marker
    cannot be made."""
    marker = issue_marker(folder, finding_id)
    try:
        os.close(os.open(marker, _NEW_FILE, 0o600))
    except FileExistsError:
        return _marked(marker, finding_id)
    return None


def record_issue(folder: Path, finding_id: str, *, issue_id: str, url: str) -> None:
    """Write the created issue into the marker this side claimed."""
    _write(issue_marker(folder, finding_id), {"id": issue_id, "url": url})


def record_failure(folder: Path, finding_id: str) -> None:
    """Mark the claimed create as failed: it is never tried again."""
    _write(issue_marker(folder, finding_id), {"failed": True})


def _marked(marker: Path, finding_id: str) -> IssueMarked:
    value: object = {}
    with contextlib.suppress(OSError, ValueError):
        descriptor = os.open(marker, _READ_FILE)
        with os.fdopen(descriptor, "rb") as file:
            value = json.loads(file.read(_MARKER_BYTES) or b"{}")
    known = value if isinstance(value, dict) else {}
    issue_id, url = known.get("id"), known.get("url")
    return IssueMarked(
        finding_id=finding_id,
        issue_id=issue_id if isinstance(issue_id, str) else None,
        url=url if isinstance(url, str) else None,
    )


def _write(marker: Path, value: dict[str, object]) -> None:
    with contextlib.suppress(OSError):
        descriptor = os.open(marker, _WRITE_FILE)
        with os.fdopen(descriptor, "wb") as file:
            file.write(json.dumps(value).encode())
