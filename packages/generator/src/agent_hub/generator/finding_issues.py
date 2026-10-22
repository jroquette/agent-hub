"""The at-most-once marker of a scenario finding's tracker issue (AGH-350, AGH-363 Q7).

``hub scenario findings --issue`` and hub web's ``POST
/scenario-runs/{run}/findings/{finding}/issue`` both create a finding's issue only after
claiming ``finding-<id>.issue`` in the scenario run's folder: made exclusively, owner-only,
never through a link, before the tracker is called. After the call the marker holds the issue
(``{"id", "url"}``) or ``{"failed": true}``; a crash between the claim and the create leaves it
empty. A marker holding an issue refuses every later create, from either side. One without (a
failed or unfinished create: the issue may exist) refuses hub web too; only a person on a
terminal, warned, may take it again (``retake_issue``, E-14): the next generation's lock file
``finding-<id>.issue.<n>`` is made exclusively, so of two retries one wins, then a fresh marker
replaces the old one atomically, so hub web never sees the finding unclaimed.
"""

import contextlib
import json
import os
import secrets
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
    failed: bool = False
    generation: int = 0

    @property
    def state(self) -> str:
        """What happened to the earlier create, in plain words."""
        if self.issue_id is not None:
            return f"finding {self.finding_id} already has the issue {self.issue_id}"
        happened = "failed" if self.failed else "did not finish"
        return f"an earlier create of finding {self.finding_id}'s issue {happened}"

    @property
    def reason(self) -> str:
        """Why no issue is created now, in plain words."""
        if self.issue_id is None:
            return (
                f"{self.state}: the issue may already exist in the tracker; check it, then"
                " create it with hub scenario findings --issue on a terminal"
            )
        return f"{self.state}: {self.url}" if self.url else self.state


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


def retake_issue(folder: Path, earlier: IssueMarked) -> IssueMarked | None:
    """Take a failed or unfinished create's marker again (a person on a terminal, warned):
    None when this call took it, else the claim that stands (an issue, or another retry of
    the same generation)."""
    if earlier.issue_id is not None:
        return earlier
    generation = earlier.generation + 1
    lock = folder / f"finding-{earlier.finding_id}.issue.{generation}"
    try:
        os.close(os.open(lock, _NEW_FILE, 0o600))
    except FileExistsError:
        return _marked(issue_marker(folder, earlier.finding_id), earlier.finding_id)
    fresh = folder / f".finding-{earlier.finding_id}.issue.{secrets.token_hex(4)}"
    descriptor = os.open(fresh, _NEW_FILE, 0o600)
    with os.fdopen(descriptor, "wb") as file:
        file.write(json.dumps({"generation": generation}).encode())
    os.replace(fresh, issue_marker(folder, earlier.finding_id))
    return None


def record_issue(folder: Path, finding_id: str, *, issue_id: str, url: str) -> None:
    """Write the created issue into the marker this side claimed."""
    _write(issue_marker(folder, finding_id), {"id": issue_id, "url": url})


def record_failure(folder: Path, finding_id: str) -> None:
    """Mark the claimed create as failed: hub web never tries it again."""
    _write(issue_marker(folder, finding_id), {"failed": True})


def _marked(marker: Path, finding_id: str) -> IssueMarked:
    value: object = {}
    with contextlib.suppress(OSError, ValueError):
        descriptor = os.open(marker, _READ_FILE)
        with os.fdopen(descriptor, "rb") as file:
            value = json.loads(file.read(_MARKER_BYTES) or b"{}")
    known = value if isinstance(value, dict) else {}
    issue_id, url, generation = known.get("id"), known.get("url"), known.get("generation")
    return IssueMarked(
        finding_id=finding_id,
        issue_id=issue_id if isinstance(issue_id, str) else None,
        url=url if isinstance(url, str) else None,
        failed=known.get("failed") is True,
        generation=generation if isinstance(generation, int) and generation > 0 else 0,
    )


def _write(marker: Path, value: dict[str, object]) -> None:
    """Write ``value`` over the marker, keeping a retry's generation."""
    generation = _marked(marker, "").generation
    kept = value | {"generation": generation} if generation else value
    with contextlib.suppress(OSError):
        descriptor = os.open(marker, _WRITE_FILE)
        with os.fdopen(descriptor, "wb") as file:
            file.write(json.dumps(kept).encode())
