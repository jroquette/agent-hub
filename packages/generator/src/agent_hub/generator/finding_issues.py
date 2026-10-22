"""The at-most-once marker of a scenario finding's tracker issue (AGH-350, AGH-363, E-14).

``hub scenario findings --issue`` and hub web's ``POST
/scenario-runs/{run}/findings/{finding}/issue`` both create a finding's issue only while they
hold its claim: ``finding-<id>.issue.lock`` in the scenario run's folder, locked ``LOCK_EX``
(``flock``) from the claim until the result is recorded, and ``finding-<id>.issue``, the marker,
made exclusively, owner-only, never through a link, before the tracker is called. After the
call the marker holds the issue (``{"id", "url"}``) or ``{"failed": true}``; a crash between the
claim and the record leaves it empty, and the crash releases the lock.

A marker naming an issue refuses every later create, from either side. While the lock is held a
create is running, and nothing claims or retakes it. A marker without an issue and without a
running create (a failed or unfinished create: the issue may exist) refuses hub web too; only a
person on a terminal, warned, may take it again (``retake_issue``): under the lock, and only
while the marker still reads as the person was shown, a fresh marker replaces it atomically, so
hub web never sees the finding unclaimed. A leftover ``finding-<id>.issue.<n>`` (an older
retry's generation file) is ignored, and removed once a result is recorded.
"""

import contextlib
import fcntl
import json
import os
import re
import secrets
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

_NEW_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC
_LOCK_FILE: Final = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_CLOEXEC
_READ_FILE: Final = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC
_WRITE_FILE: Final = os.O_WRONLY | os.O_TRUNC | os.O_NOFOLLOW | os.O_CLOEXEC
_MARKER_BYTES: Final = 4096


@dataclass(frozen=True, kw_only=True, slots=True)
class IssueMarked:
    """A claim of the finding's issue that stands: the issue when it is known, whether the
    earlier create failed, and whether a create is running now."""

    finding_id: str
    issue_id: str | None
    url: str | None
    failed: bool = False
    generation: int = 0
    running: bool = False

    @property
    def state(self) -> str:
        """What happened to the earlier create, in plain words."""
        if self.issue_id is not None:
            return f"finding {self.finding_id} already has the issue {self.issue_id}"
        if self.running:
            return f"a create of finding {self.finding_id}'s issue is running"
        happened = "failed" if self.failed else "did not finish"
        return f"an earlier create of finding {self.finding_id}'s issue {happened}"

    @property
    def reason(self) -> str:
        """Why no issue is created now, in plain words."""
        if self.running:
            return f"{self.state}: wait for it, then check the tracker"
        if self.issue_id is None:
            return (
                f"{self.state}: the issue may already exist in the tracker; check it, then"
                " create it with hub scenario findings --issue on a terminal"
            )
        return f"{self.state}: {self.url}" if self.url else self.state


@dataclass(kw_only=True)
class HeldIssue:
    """A claim this process holds (its lock): record the result, which releases it."""

    folder: Path
    finding_id: str
    generation: int
    lock: int
    done: bool = field(default=False)

    def record(self, *, issue_id: str, url: str) -> None:
        """Write the created issue into the marker, then release the claim."""
        self._finish({"id": issue_id, "url": url})

    def fail(self) -> None:
        """Mark the create as failed (hub web never tries it again), then release."""
        self._finish({"failed": True})

    def release(self) -> None:
        """Release the claim without a result (the marker stays as it is)."""
        if not self.done:
            self.done = True
            os.close(self.lock)

    def _finish(self, value: dict[str, object]) -> None:
        kept = value | {"generation": self.generation} if self.generation else value
        try:
            with contextlib.suppress(OSError):
                descriptor = os.open(issue_marker(self.folder, self.finding_id), _WRITE_FILE)
                with os.fdopen(descriptor, "wb") as file:
                    file.write(json.dumps(kept).encode())
            _remove_generation_files(self.folder, self.finding_id)
        finally:
            self.release()


def issue_marker(folder: Path, finding_id: str) -> Path:
    """The marker of ``finding_id``'s issue in the scenario run's ``folder``."""
    return folder / f"finding-{finding_id}.issue"


def marked_issue(folder: Path, finding_id: str) -> IssueMarked | None:
    """The claim of ``finding_id``'s issue that stands, None when there is none; ``running``
    while another holder has its lock (probed, never kept: a retake takes it again)."""
    marker = issue_marker(folder, finding_id)
    if not marker.exists() and not marker.is_symlink():
        return None
    lock = _take_lock(folder, finding_id)
    if lock is None:
        return _running(folder, finding_id)
    os.close(lock)
    return _marked(marker, finding_id)


def claim_issue(folder: Path, finding_id: str) -> HeldIssue | IssueMarked:
    """Claim ``finding_id``'s issue: the held claim (the caller creates the issue, then
    records it), else the claim that stands; ``OSError`` when it cannot be made."""
    lock = _take_lock(folder, finding_id)
    if lock is None:
        return _running(folder, finding_id)
    try:
        os.close(os.open(issue_marker(folder, finding_id), _NEW_FILE, 0o600))
    except FileExistsError:
        os.close(lock)
        return _marked(issue_marker(folder, finding_id), finding_id)
    except BaseException:
        os.close(lock)
        raise
    return HeldIssue(folder=folder, finding_id=finding_id, generation=0, lock=lock)


def retake_issue(folder: Path, earlier: IssueMarked) -> HeldIssue | IssueMarked:
    """Take a failed or unfinished create's marker again (a person on a terminal, warned):
    the held claim, else the claim that stands (an issue, a running create, or a marker that
    changed since ``earlier`` was shown)."""
    if earlier.issue_id is not None:
        return earlier
    finding_id = earlier.finding_id
    lock = _take_lock(folder, finding_id)
    if lock is None:
        return _running(folder, finding_id)
    try:
        current = _marked(issue_marker(folder, finding_id), finding_id)
        if _shown(current) != _shown(earlier):
            os.close(lock)
            return current
        generation = earlier.generation + 1
        fresh = folder / f".finding-{finding_id}.issue.{secrets.token_hex(4)}"
        try:
            descriptor = os.open(fresh, _NEW_FILE, 0o600)
            with os.fdopen(descriptor, "wb") as file:
                file.write(json.dumps({"generation": generation}).encode())
            os.replace(fresh, issue_marker(folder, finding_id))
        finally:
            fresh.unlink(missing_ok=True)
    except BaseException:
        os.close(lock)
        raise
    return HeldIssue(folder=folder, finding_id=finding_id, generation=generation, lock=lock)


def _shown(marked: IssueMarked) -> tuple[str | None, str | None, bool, int]:
    """What the marker said, apart from whether a create was running when it was read."""
    return marked.issue_id, marked.url, marked.failed, marked.generation


def _take_lock(folder: Path, finding_id: str) -> int | None:
    """The claim's lock, taken without waiting; None while another holder has it."""
    lock = os.open(folder / f"finding-{finding_id}.issue.lock", _LOCK_FILE, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        os.close(lock)
        return None
    except BaseException:
        os.close(lock)
        raise
    return lock


def _running(folder: Path, finding_id: str) -> IssueMarked:
    known = _marked(issue_marker(folder, finding_id), finding_id)
    return IssueMarked(
        finding_id=finding_id,
        issue_id=known.issue_id,
        url=known.url,
        failed=known.failed,
        generation=known.generation,
        running=known.issue_id is None,
    )


def _remove_generation_files(folder: Path, finding_id: str) -> None:
    """Remove an older retry's ``finding-<id>.issue.<n>`` files."""
    pattern = re.compile(rf"finding-{re.escape(finding_id)}\.issue\.[0-9]+")
    with contextlib.suppress(OSError):
        for path in folder.iterdir():
            if pattern.fullmatch(path.name):
                with contextlib.suppress(OSError):
                    path.unlink()


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
