"""The backlog-care pack's ``hygiene.py`` (AGH-489), in process: orphans, stale issues, likely
duplicates and dependency cycles among the issues ``read.py`` printed, each with its evidence.
"""

import importlib.util
import json
import subprocess
import sys
from datetime import UTC, datetime, tzinfo
from importlib.resources import files
from io import StringIO
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/backlog-care/scripts/hygiene.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.backlog-care.scripts.hygiene"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


TODAY = "2026-10-26"
RECENT = "2026-10-20T10:00:00Z"


def an_issue(issue_id: str, title: str, **fields: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "id": issue_id,
        "title": title,
        "url": "",
        "state": {"name": "Todo", "type": "unstarted"},
        "created_at": "2026-09-01T10:00:00Z",
        "updated_at": RECENT,
        "labels": [],
        "blocked_by": [],
        "blocks": [],
        "links": [],
        "branch_name": "",
        "description": "",
    }
    return issue | fields


# The findings of fixture backlog-mixed.yaml's `read` stub (labels and dates aside; the stub
# itself is checked by test_backlog_care_workflows.py), as read.py prints them: one orphan
# (DEM-1), one stale issue (DEM-2), one duplicate pair (DEM-3, DEM-4), one cycle (DEM-5, DEM-6),
# and an issue in review with its PR linked (DEM-7), which is none of them.
BACKLOG_MIXED = [
    an_issue("DEM-1", "Add the export button", state={"name": "In Progress", "type": "started"}),
    an_issue("DEM-2", "Fix the login timeout", updated_at="2026-09-01T10:00:00Z"),
    an_issue("DEM-3", "feat(api): Add CSV export"),
    an_issue("DEM-4", "Add  csv export!"),
    an_issue("DEM-5", "Split the importer", blocked_by=["DEM-6"]),
    an_issue("DEM-6", "Retry the importer", blocked_by=["DEM-5"]),
    an_issue(
        "DEM-7",
        "Show the export size",
        state={"name": "In Review", "type": "started"},
        links=["https://github.com/acme/api/pull/7"],
    ),
]


def a_read(issues: list[dict[str, Any]], repos: tuple[str, ...] = ("api",)) -> dict[str, Any]:
    return {
        "ready_label": "agent-ready",
        "repos": list(repos),
        "read": len(issues),
        "open": len(issues),
        "unread": 0,
        "unread_line": "No open issue was left unread",
        "descriptions_dropped": 0,
        "skipped": [],
        "issues": issues,
    }


def git(folder: Path, *args: str) -> None:
    identity = ("-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com")
    subprocess.run(  # noqa: S603 - git with fixed arguments in a temp repo
        ["git", *identity, *args],  # noqa: S607 - git from PATH, as the script runs it
        cwd=folder,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A hub folder beside one git repo, ``api``, with a branch for another issue."""
    repo = tmp_path / "api"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "commit", "-q", "--allow-empty", "-m", "start")
    git(repo, "branch", "jo/dem-70-other")
    hub = tmp_path / "hub"
    hub.mkdir()
    monkeypatch.chdir(hub)
    return hub


def run(
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    read: dict[str, Any],
) -> dict[str, Any]:
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(read)))
    assert load().main(["--stale-days", "14", "--today", TODAY]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_reports_orphan_stale_duplicate_and_cycle_when_backlog_mixed(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    found = run(capsys, monkeypatch, a_read(BACKLOG_MIXED))

    (orphan,) = found["orphans"]
    assert (orphan["id"], orphan["state"]) == ("DEM-1", "In Progress")
    assert "state In Progress (started)" in orphan["evidence"]
    assert "no PR link" in orphan["evidence"]
    assert "(^|/)dem-1(-|$)" in orphan["evidence"]
    (stale,) = found["stale"]
    assert (stale["id"], stale["days"]) == ("DEM-2", 55)
    assert stale["updated_at"] == "2026-09-01T10:00:00Z"
    assert "updated_at 2026-09-01T10:00:00Z" in stale["evidence"]
    assert "55 days" in stale["evidence"]
    (duplicate,) = found["duplicates"]
    assert duplicate["ids"] == ["DEM-3", "DEM-4"]
    assert duplicate["title"] == "add csv export"
    assert "'feat(api): Add CSV export'" in duplicate["evidence"]
    assert "'Add  csv export!'" in duplicate["evidence"]
    (cycle,) = found["cycles"]
    assert cycle["ids"] == ["DEM-5", "DEM-6"]
    assert "DEM-5 blocked by DEM-6" in cycle["evidence"]
    assert "DEM-6 blocked by DEM-5" in cycle["evidence"]
    assert found["unreadable"] == []
    assert found["summary"].startswith(
        "Hygiene of 7 issues read: 1 orphan, 1 stale, 1 duplicate group, 1 cycle."
    )
    for evidence in (orphan, stale, duplicate, cycle):
        assert evidence["evidence"] in found["summary"]


@pytest.mark.parametrize(
    "fields",
    [
        {"links": ["https://github.com/acme/api/pull/7"]},
        {"links": ["https://github.com/acme/api/tree/jo/dem-1-x"]},
        {"branch_name": "jo/export-button"},
        {"id": "DEM-70"},
    ],
    ids=["pr-link", "branch-link", "branch-name-ref", "id-ref"],
)
def test_skips_orphan_when_issue_has_pr_link_or_branch_ref(
    hub: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    fields: dict[str, Any],
) -> None:
    git(hub.parent / "api", "update-ref", "refs/remotes/origin/jo/export-button", "HEAD")
    started = {"name": "In Progress", "type": "started"}
    issue = an_issue("DEM-1", "Add the export button", state=started) | fields

    assert run(capsys, monkeypatch, a_read([issue]))["orphans"] == []


@pytest.mark.parametrize(
    "state",
    [{"name": "in review", "type": ""}, {"name": "IN PROGRESS", "type": ""}],
)
def test_reads_state_name_when_state_type_empty(
    hub: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    state: dict[str, str],
) -> None:
    issue = an_issue("DEM-1", "Add the export button", state=state)

    (orphan,) = run(capsys, monkeypatch, a_read([issue]))["orphans"]

    assert orphan["id"] == "DEM-1"


def test_says_links_not_read_when_links_null(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    started = {"name": "In Progress", "type": "started"}
    issue = an_issue("DEM-1", "Add the export button", state=started, links=None)

    (orphan,) = run(capsys, monkeypatch, a_read([issue]))["orphans"]

    assert "PR links not read" in orphan["evidence"]
    assert "no PR link" not in orphan["evidence"]


def test_matches_duplicate_when_titles_differ_by_prefix_and_case(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        an_issue("DEM-1", "fix(web)!: The Login, again"),
        an_issue("DEM-2", "the login again"),
        an_issue("DEM-3", "THE   LOGIN... AGAIN?"),
        an_issue("DEM-4", "The login page"),
        an_issue("DEM-5", "!!!"),
        an_issue("DEM-6", "..."),
    ]

    (duplicate,) = run(capsys, monkeypatch, a_read(issues))["duplicates"]

    assert duplicate["ids"] == ["DEM-1", "DEM-2", "DEM-3"]
    assert duplicate["title"] == "the login again"


def test_reports_one_cycle_when_three_issues_block_in_a_ring(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    issues = [
        an_issue("DEM-1", "One", blocked_by=["DEM-2"]),
        an_issue("DEM-2", "Two", blocks=["DEM-1"], blocked_by=["DEM-9"]),
        an_issue("DEM-3", "Three", blocks=["DEM-2"], blocked_by=["DEM-1"]),
        an_issue("DEM-4", "Four", blocked_by=["DEM-3", "DEM-4"]),
    ]

    (cycle,) = run(capsys, monkeypatch, a_read(issues))["cycles"]

    assert cycle["ids"] == ["DEM-1", "DEM-2", "DEM-3"]
    assert cycle["evidence"] == (
        "DEM-1 blocked by DEM-2; DEM-2 blocked by DEM-3; DEM-3 blocked by DEM-1"
    )


def test_finds_cycles_without_recursion_when_chain_is_long() -> None:
    graph = {f"DEM-{n}": [f"DEM-{n + 1}"] for n in range(1, 5001)}
    graph["DEM-5001"] = ["DEM-1"]
    graph["DEM-6000"] = []

    (ring,) = load().cycles_of(graph)

    assert len(ring) == 5001


def test_names_unreadable_repo_when_refs_cannot_be_read(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    (hub.parent / "plain").mkdir()
    started = {"name": "In Progress", "type": "started"}
    issue = an_issue("DEM-1", "Add the export button", state=started)

    found = run(capsys, monkeypatch, a_read([issue], repos=("api", "missing", "plain")))

    assert [entry["repo"] for entry in found["unreadable"]] == ["missing", "plain"]
    assert all(entry["reason"] for entry in found["unreadable"])
    (orphan,) = found["orphans"]
    assert "refs not read: missing, plain" in orphan["evidence"]
    assert "refs not read in missing: " in found["summary"]


def test_names_unreadable_repo_when_refs_over_limit(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    monkeypatch.setattr(module, "MAX_REFS", 1)
    git(hub.parent / "api", "branch", "jo/dem-71-more")
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(a_read([]))))

    assert module.main(["--today", TODAY]) == 0

    (unreadable,) = json.loads(capsys.readouterr().out)["unreadable"]
    assert unreadable == {"repo": "api", "reason": "more than 1 refs"}


def test_cuts_summary_when_findings_over_limit(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    old = "2020-01-01T00:00:00Z"
    issues = [an_issue(f"DEM-{n}", "x" * 400 + str(n), updated_at=old) for n in range(1, 101)]

    found = run(capsys, monkeypatch, a_read(issues))

    assert len(found["stale"]) == 100
    assert len(found["summary"]) <= 16000
    assert found["summary"].endswith("(cut)")


@pytest.mark.parametrize(
    ("stdin", "argv"),
    [
        ("not json", []),
        ("[1]", []),
        (json.dumps({"issues": "x", "repos": []}), []),
        (json.dumps(a_read([])), ["--today", "26/10/2026"]),
        (json.dumps(a_read([])), ["--stale-days", "0"]),
    ],
    ids=["text", "array", "issues-not-list", "bad-today", "bad-days"],
)
def test_exits_two_when_input_unreadable(
    hub: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
    *,
    stdin: str,
    argv: list[str],
) -> None:
    monkeypatch.setattr(sys, "stdin", StringIO(stdin))

    assert load().main(argv) == 2
    assert capsys.readouterr().err.startswith("hygiene.py: ")


def test_counts_days_from_utc_date_when_today_not_given(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    when = datetime(2026, 10, 26, 23, 30, tzinfo=UTC)
    monkeypatch.setattr(module, "datetime", FixedNow.at(when))
    issue = an_issue("DEM-2", "Old", updated_at="2026-10-12T00:00:00Z")
    monkeypatch.setattr(sys, "stdin", StringIO(json.dumps(a_read([issue]))))

    assert module.main([]) == 0

    (stale,) = json.loads(capsys.readouterr().out)["stale"]
    assert stale["days"] == 14


class FixedNow(datetime):
    """``datetime`` whose ``now`` is a fixed instant, converted to the zone asked for."""

    instant: datetime

    @classmethod
    def at(cls, instant: datetime) -> type[FixedNow]:
        return type("Fixed", (cls,), {"instant": instant})

    @classmethod
    def now(cls, tz: tzinfo | None = None) -> FixedNow:
        found = cls.instant.astimezone(tz)
        return cls(*found.timetuple()[:6], tzinfo=found.tzinfo)
