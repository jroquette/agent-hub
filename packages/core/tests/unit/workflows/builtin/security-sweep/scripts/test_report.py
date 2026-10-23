"""The security-sweep pack's ``report.py`` (AGH-486), in process: the note for /triage holds only
the findings triage kept, a secret one as rule and path, and names what did not run."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/security-sweep/scripts/report.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.security-sweep.scripts.report"
TODAY = "2026-10-26"
HEAD = "0a1b2c3d4e5f60718293a4b5c6d7e8f901234567"
# Not a secret shape (no repo lint flags it); a test asserts it never reaches the note.
VALUE = "hunter2-fixture-value"
SCANNERS = ("semgrep", "bandit", "pip-audit", "npm", "guard")


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


def a_finding(n: int, path: str, **more: Any) -> Any:
    return {
        "id": f"F{n}",
        "fingerprint": f"app/semgrep/{n:016x}",
        "repo": "app",
        "scanner": "semgrep",
        "rule": f"rule-{n}",
        "path": path,
        "line": 10 + n,
        "severity": "high",
        "cwe": "",
        "secret": False,
        "package": "",
        "version": "",
        "advisory": "",
        "fixed": "",
        "title": "",
    } | more


def a_repo(status: str = "ran", note: str = "") -> Any:
    return {
        "repo": "app",
        "ref": "origin/main",
        "head": HEAD,
        "date": "2026-10-25T09:00:00+00:00",
        "status": "scanned",
        "note": "",
        "scanners": [
            {"name": name, "status": status, "note": note, "count": 0} for name in SCANNERS
        ],
    }


FINDINGS = [a_finding(1, "api/run.py"), a_finding(2, "api/db.py"), a_finding(3, "api/views.py")]
COUNTS = {"new": 3, "seen": 4, "more": 0}


class Inbox:
    """``report.py`` run in process in a hub folder at ``tmp_path``."""

    def __init__(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: Any):
        self.hub = tmp_path
        self.capsys = capsys
        self.monkeypatch = monkeypatch
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("AGENT_HUB_RUN_ID", "1f2e3d4c-5b6a-4789-8abc-def012345678")

    def report(self, triage: Any, *args: str, **given: Any) -> tuple[int, Any, str]:
        stdin = triage if isinstance(triage, str) else json.dumps(triage)
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        argv = [
            "--findings",
            json.dumps(given.get("findings", FINDINGS)),
            "--repos",
            json.dumps(given.get("repos", [a_repo()])),
            "--counts",
            json.dumps(given.get("counts", COUNTS)),
            "--today",
            TODAY,
            *args,
        ]
        code = load().main(argv)
        captured = self.capsys.readouterr()
        output = json.loads(captured.out) if code == 0 else None
        note = (self.hub / output["path"]).read_text(encoding="utf-8") if output else ""
        return code, output, captured.out + note


@pytest.fixture
def inbox(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: Any) -> Inbox:
    return Inbox(tmp_path, capsys, monkeypatch)


def a_triage(*kept: Any, unresolved: Any = (), dropped: Any = ()) -> Any:
    return {"kept": list(kept), "unresolved": list(unresolved), "dropped": list(dropped)}


def test_lists_only_kept_findings_when_triage_keeps_some(inbox: Inbox) -> None:
    kept = {"id": "F2", "attack": "A name reaches the SQL text.", "fix": "Bind it."}

    code, output, text = inbox.report(a_triage(kept, dropped=["F1", "F3"]))

    assert code == 0
    assert output == {
        "path": f"brain/_inbox/security-{TODAY}.md",
        "kept": 1,
        "secrets": 0,
        "missing": [],
        "triaged": ["F1", "F2", "F3"],
        "status": "findings",
    }
    assert "## Not triaged" not in text
    assert "[high] `rule-2` - `api/db.py:12` (semgrep, app)" in text
    assert "> Attack: A name reaches the SQL text." in text
    assert "> Fix: Bind it." in text
    assert "api/run.py" not in text
    assert "api/views.py" not in text
    assert "New: 3; kept: 1; dropped: 2; unresolved: 0; already seen: 4" in text


def test_names_missing_scanners_when_none_installed(inbox: Inbox) -> None:
    code, output, text = inbox.report(
        "", findings=[], repos=[a_repo("missing", "not installed")], counts=COUNTS | {"new": 0}
    )

    assert code == 0
    assert output["status"] == "clean"
    assert output["missing"] == [f"app: {name}" for name in SCANNERS]
    for name in SCANNERS:
        assert f"  - {name}: missing - not installed" in text
    assert "No finding kept." in text


def test_shows_rule_and_path_not_agent_text_when_secret_finding_kept(inbox: Inbox) -> None:
    secret = a_finding(1, "config/settings.py", line=None, secret=True, rule="hardcoded-password")
    kept = {"id": "F1", "attack": f"The key {VALUE} opens it.", "fix": f"Rotate {VALUE}."}
    unresolved = {"id": "F1", "why": VALUE}

    code, output, text = inbox.report(a_triage(kept, unresolved=[unresolved]), findings=[secret])

    assert code == 0
    assert (output["kept"], output["secrets"]) == (1, 1)
    assert "[secret] `hardcoded-password` - `config/settings.py` (semgrep, app)" in text
    assert "its value is not shown" in text
    assert VALUE not in text


def test_ignores_unknown_ids_when_triage_names_them(inbox: Inbox) -> None:
    triage = a_triage(
        {"id": "F9", "attack": "made up", "fix": "x"},
        {"id": "F3", "attack": "real", "fix": "y"},
        {"id": "F3", "attack": "twice", "fix": "z"},
        unresolved=[{"id": "F8", "why": "made up"}],
    )

    code, output, text = inbox.report(triage)

    assert (code, output["kept"]) == (0, 1)
    assert "made up" not in text
    assert "twice" not in text
    assert "Triage named 2 ids that are not in the listing; ignored." in text


def test_puts_agent_text_on_one_quoted_line_when_it_holds_newlines_and_backticks(
    inbox: Inbox,
) -> None:
    attack = "first\n# Heading\n```sh\nrm -rf /\n```\x1b[31m" + "a" * 500
    triage = a_triage({"id": "F1", "attack": attack, "fix": "ok"})

    code, _, text = inbox.report(triage)

    assert code == 0
    (line,) = [line for line in text.splitlines() if line.lstrip().startswith("> Attack:")]
    assert "`" not in line
    assert "\x1b" not in line
    assert "first # Heading '''sh rm -rf / '''[31m" in line
    assert len(line.split("> Attack: ", 1)[1]) == 400
    assert "\n# Heading" not in text


def test_writes_a_run_suffixed_name_when_todays_report_exists(inbox: Inbox) -> None:
    first = inbox.report(a_triage())[1]["path"]
    second = inbox.report(a_triage())[1]["path"]
    inbox.monkeypatch.delenv("AGENT_HUB_RUN_ID")
    third = inbox.report(a_triage())[1]["path"]
    fourth = inbox.report(a_triage())[1]["path"]

    assert first == f"brain/_inbox/security-{TODAY}.md"
    assert second == f"brain/_inbox/security-{TODAY}-1f2e3d4c.md"
    assert third == f"brain/_inbox/security-{TODAY}-local.md"
    assert fourth == f"brain/_inbox/security-{TODAY}-local-2.md"
    assert len(list((inbox.hub / "brain" / "_inbox").iterdir())) == 4


def test_hands_findings_to_triage_without_tracker_write_when_rendered(inbox: Inbox) -> None:
    inbox.report(a_triage({"id": "F1", "attack": "a", "fix": "f"}))

    note = (inbox.hub / f"brain/_inbox/security-{TODAY}.md").read_text(encoding="utf-8")
    assert note.startswith("---\ntype: security-sweep\nstatus: open\nprovenance: agent\n")
    assert f"last_verified: {TODAY}\nrepos: [app]\n---\n" in note
    assert "## Findings for /triage" in note
    assert note.rstrip().endswith(
        "No tracker write. File an issue for each finding you accept, then run /triage <issue>."
    )


def test_states_the_commit_scanned_when_rendered(inbox: Inbox) -> None:
    unreadable = {
        "repo": "web",
        "ref": "origin/trunk",
        "head": "",
        "date": "",
        "status": "unreadable",
        "note": "no origin/trunk: fetch it first",
        "scanners": [],
    }

    _, _, text = inbox.report(a_triage(), repos=[a_repo(), unreadable])

    assert f"- `app` as of `origin/main` `{HEAD[:7]}` (2026-10-25T09:00:00+00:00)" in text
    assert "- `web`: unreadable - no origin/trunk: fetch it first" in text
    assert "the sweep does not fetch" in text
    assert "npm audit reads package-lock.json only" in text


@pytest.mark.parametrize(
    ("status", "note", "line"),
    [
        ("ran", "", "  - semgrep: ran (0)"),
        ("skipped", "no tracked *.py", "  - semgrep: skipped (no tracked *.py)"),
        ("failed", "exit 2", "  - semgrep: failed (exit 2)"),
        ("timeout", "over 900 s", "  - semgrep: timeout (over 900 s)"),
    ],
)
def test_says_how_each_scanner_ended_when_rendered(
    inbox: Inbox, *, status: str, note: str, line: str
) -> None:
    _, _, text = inbox.report(a_triage(), repos=[a_repo(status, note)])

    assert line in text


def test_names_the_store_problem_when_new_reports_one(inbox: Inbox) -> None:
    problem = "the seen-findings store could not be read; read as empty"

    _, _, text = inbox.report(a_triage(), "--store-problem", problem)

    assert f"Store: {problem}." in text


def test_leaves_unresolved_findings_unseen_when_triage_names_them(inbox: Inbox) -> None:
    triage = a_triage(
        {"id": "F1", "attack": "a", "fix": "f"},
        unresolved=[{"id": "F3", "why": "checkout differs"}],
        dropped=["F2"],
    )

    code, output, text = inbox.report(triage)

    assert (code, output["status"]) == (0, "findings")
    # Not settled: only kept and dropped ids are marked seen, so F3 comes back next run.
    assert output["triaged"] == ["F1", "F2"]
    assert "## Unresolved" in text
    unresolved = text.split("## Unresolved", 1)[1].split("## ", 1)[0]
    assert "Not settled: these stay unseen and come back next run." in unresolved
    assert "[high] `rule-3` - `api/views.py:13` (semgrep, app)" in unresolved
    assert "> checkout differs" in unresolved
    assert "## Not triaged" not in text


@pytest.mark.parametrize(
    ("triage", "args"),
    [
        ("not json", ()),
        ("[]", ()),
        ("", ("--findings", "{")),
        ("", ("--repos", "[1]")),
        ("", ("--counts", "[]")),
        ("", ("--today", "today")),
    ],
)
def test_exits_two_when_triage_reply_is_not_json(
    inbox: Inbox, triage: str, args: tuple[str, ...]
) -> None:
    code, output, _ = inbox.report(triage, *args)

    assert (code, output) == (2, None)
    assert not (inbox.hub / "brain").exists()


def test_lists_untriaged_findings_and_flags_mismatch_when_reply_undercounts(inbox: Inbox) -> None:
    kept = {"id": "F2", "attack": "A name reaches the SQL text.", "fix": "Bind it."}

    code, output, text = inbox.report(a_triage(kept, dropped=["F9"]))

    assert code == 0
    assert output["triaged"] == ["F2"]
    assert "## Not triaged" in text
    not_triaged = text.split("## Not triaged", 1)[1].split("## ", 1)[0]
    assert "[high] `rule-1` - `api/run.py:11` (semgrep, app)" in not_triaged
    assert "[high] `rule-3` - `api/views.py:13` (semgrep, app)" in not_triaged
    assert "rule-2" not in not_triaged
    assert (
        "Triage accounted for 1 of 3 listed findings; the other 2 stay unseen and come back"
        " next run." in text
    )
    assert "Triage named 1 id that is not in the listing; ignored." in text
