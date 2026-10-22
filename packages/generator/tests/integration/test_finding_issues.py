"""The at-most-once marker of a scenario finding's issue, shared by the CLI and hub web."""

import fcntl
import json
import os
from pathlib import Path

import pytest

from agent_hub.generator.finding_issues import (
    HeldIssue,
    IssueMarked,
    claim_issue,
    issue_marker,
    marked_issue,
    retake_issue,
)

URL = "https://linear.example.com/demo/issue/DEM-7"


def held(claimed: HeldIssue | IssueMarked) -> HeldIssue:
    assert isinstance(claimed, HeldIssue), claimed
    return claimed


def refused(claimed: HeldIssue | IssueMarked) -> IssueMarked:
    assert isinstance(claimed, IssueMarked), claimed
    return claimed


def test_refuses_second_claim_when_finding_issue_claimed(tmp_path: Path) -> None:
    first = held(claim_issue(tmp_path, "f1"))
    running = refused(claim_issue(tmp_path, "f1"))
    first.record(issue_id="DEM-7", url=URL)
    created = marked_issue(tmp_path, "f1")

    assert running.running
    assert running.reason == (
        "a create of finding f1's issue is running: wait for it, then check the tracker"
    )
    assert created is not None
    assert created.reason == f"finding f1 already has the issue DEM-7: {URL}"
    assert refused(claim_issue(tmp_path, "f1")).issue_id == "DEM-7"
    assert marked_issue(tmp_path, "f2") is None
    assert issue_marker(tmp_path, "f1").stat().st_mode & 0o777 == 0o600
    assert json.loads(issue_marker(tmp_path, "f1").read_text()) == {"id": "DEM-7", "url": URL}


def test_never_retries_from_claim_when_finding_issue_create_failed(tmp_path: Path) -> None:
    held(claim_issue(tmp_path, "f1")).fail()

    again = refused(claim_issue(tmp_path, "f1"))

    assert json.loads(issue_marker(tmp_path, "f1").read_text()) == {"failed": True}
    assert (again.issue_id, again.failed, again.running) == (None, True, False)
    assert again.reason == (
        "an earlier create of finding f1's issue failed: the issue may already exist in the"
        " tracker; check it, then create it with hub scenario findings --issue on a terminal"
    )


def test_never_follows_link_when_finding_issue_marker_linked(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    issue_marker(tmp_path, "f1").symlink_to(target)

    earlier = refused(claim_issue(tmp_path, "f1"))

    assert earlier.issue_id is None
    assert not target.exists()
    with pytest.raises(FileNotFoundError):
        claim_issue(tmp_path / "missing", "f1")


def test_lets_one_retry_win_when_failed_finding_issue_retaken(tmp_path: Path) -> None:
    held(claim_issue(tmp_path, "f1")).fail()
    failed = marked_issue(tmp_path, "f1")
    assert failed is not None
    assert failed.state == "an earlier create of finding f1's issue failed"

    first = held(retake_issue(tmp_path, failed))
    second = refused(retake_issue(tmp_path, failed))
    # The marker never vanished, so hub web's exclusive claim still refuses.
    web = refused(claim_issue(tmp_path, "f1"))
    first.fail()
    stale = refused(retake_issue(tmp_path, failed))

    assert second.running
    assert web.running
    # A retry warned about an older state is refused: the person sees the new one first.
    assert (stale.failed, stale.generation) == (True, 1)
    newer = marked_issue(tmp_path, "f1")
    assert newer is not None
    held(retake_issue(tmp_path, newer)).record(issue_id="DEM-7", url=URL)
    done = marked_issue(tmp_path, "f1")
    assert done is not None
    assert refused(retake_issue(tmp_path, done)) == done
    assert issue_marker(tmp_path, "f1").stat().st_mode & 0o777 == 0o600


def test_refuses_retake_when_finding_issue_create_running(tmp_path: Path) -> None:
    # A claim not yet recorded whose holder still runs: its lock is held on another fd.
    issue_marker(tmp_path, "f1").write_text("", encoding="utf-8")
    lock = os.open(tmp_path / "finding-f1.issue.lock", os.O_RDWR | os.O_CREAT, 0o600)
    fcntl.flock(lock, fcntl.LOCK_EX)
    unfinished = marked_issue(tmp_path, "f1")
    assert unfinished is not None

    while_running = refused(retake_issue(tmp_path, unfinished))
    untouched = issue_marker(tmp_path, "f1").read_text(encoding="utf-8")
    os.close(lock)  # the holder exits without recording: a crash
    after_exit = retake_issue(tmp_path, unfinished)

    assert while_running.running
    assert untouched == ""
    held(after_exit).record(issue_id="DEM-7", url=URL)
    assert json.loads(issue_marker(tmp_path, "f1").read_text())["id"] == "DEM-7"


def test_retakes_when_finding_issue_generation_lock_left(tmp_path: Path) -> None:
    # A retry stopped after its generation file and before the replace (an older layout).
    issue_marker(tmp_path, "f1").write_text('{"failed": true}', encoding="utf-8")
    leftover = tmp_path / "finding-f1.issue.1"
    leftover.write_text("", encoding="utf-8")
    failed = marked_issue(tmp_path, "f1")
    assert failed is not None

    retaken = held(retake_issue(tmp_path, failed))
    retaken.record(issue_id="DEM-7", url=URL)

    assert not leftover.exists()
    assert json.loads(issue_marker(tmp_path, "f1").read_text())["id"] == "DEM-7"


def test_keeps_marker_when_finding_issue_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue_marker(tmp_path, "f1").write_text('{"failed": true}', encoding="utf-8")
    failed = marked_issue(tmp_path, "f1")
    assert failed is not None

    def refuse(_source: object, _target: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", refuse)
    with pytest.raises(OSError, match="disk full"):
        retake_issue(tmp_path, failed)
    monkeypatch.undo()

    assert sorted(path.name for path in tmp_path.iterdir() if path.name.startswith(".")) == []
    assert json.loads(issue_marker(tmp_path, "f1").read_text()) == {"failed": True}
    # The lock is not left held: a later retake proceeds.
    assert isinstance(retake_issue(tmp_path, failed), HeldIssue)
