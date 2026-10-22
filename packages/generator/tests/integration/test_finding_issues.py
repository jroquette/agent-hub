"""The at-most-once marker of a scenario finding's issue, shared by the CLI and hub web."""

import json
from pathlib import Path

import pytest

from agent_hub.generator.finding_issues import (
    claim_issue,
    issue_marker,
    marked_issue,
    record_failure,
    record_issue,
)

URL = "https://linear.example.com/demo/issue/DEM-7"


def test_refuses_second_claim_when_finding_issue_claimed(tmp_path: Path) -> None:
    first = claim_issue(tmp_path, "f1")
    pending = claim_issue(tmp_path, "f1")
    record_issue(tmp_path, "f1", issue_id="DEM-7", url=URL)
    created = marked_issue(tmp_path, "f1")

    assert first is None
    assert pending is not None
    assert pending.reason == (
        "an earlier create of finding f1's issue did not finish; check the tracker (it is not"
        " tried again)"
    )
    assert created is not None
    assert created.reason == f"finding f1 already has the issue DEM-7: {URL}"
    assert marked_issue(tmp_path, "f2") is None
    assert issue_marker(tmp_path, "f1").stat().st_mode & 0o777 == 0o600


def test_never_retries_when_finding_issue_create_failed(tmp_path: Path) -> None:
    assert claim_issue(tmp_path, "f1") is None
    record_failure(tmp_path, "f1")

    again = claim_issue(tmp_path, "f1")

    assert json.loads(issue_marker(tmp_path, "f1").read_text()) == {"failed": True}
    assert again is not None
    assert again.issue_id is None


def test_never_follows_link_when_finding_issue_marker_linked(tmp_path: Path) -> None:
    target = tmp_path / "elsewhere"
    issue_marker(tmp_path, "f1").symlink_to(target)

    earlier = claim_issue(tmp_path, "f1")
    record_issue(tmp_path, "f1", issue_id="DEM-7", url=URL)

    assert earlier is not None
    assert marked_issue(tmp_path, "f1") is not None
    assert not target.exists()
    with pytest.raises(FileNotFoundError):
        claim_issue(tmp_path / "missing", "f1")
