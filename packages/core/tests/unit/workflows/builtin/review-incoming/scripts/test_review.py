"""The review-incoming pack's ``review.py`` (AGH-493): ``merge`` folds the lenses' findings,
blocking first, within budget; ``compose`` writes the review file the owner edits, every blocking
finding kept and each comment checked against the diff; ``final`` parses the edited file again
into the payload ``/review`` posts."""

import io
import json
import re
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

# The conftest's ``Clone``: a hub, its repo's clone, ``base`` and ``head``.
type Clone = Any

RUN_ID = "run-1"
REVIEW_FILE = f".agent-runs/review-incoming/{RUN_ID}.md"
RISKY_RUN = "import subprocess\n\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n"
WIDE = "\U0001d11e"
BUDGET = 40960
OLD_WORDS = re.compile(r"\b(?:APPROVE|CHANGES)\b|(?i:\b(?:blockers?|should-fix|nits?)\b)")
HELD = "# Optional (minor), not posted while a blocking finding is left"


def a_finding(number: int, severity: str = "blocking", **changes: Any) -> dict[str, Any]:
    finding = {
        "id": f"F{number}",
        "kind": "security",
        "severity": severity,
        "path": "app/run.py",
        "line": 5,
        "acs": [],
        "what": "The command reaches a shell.",
        "expected": "Pass an argument list.",
    }
    return finding | changes


def a_lens(reviewer: str, *findings: dict[str, Any], coverage: Any = ()) -> str:
    verdict = "FAIL" if any(f["severity"] == "blocking" for f in findings) else "PASS"
    review = {
        "reviewer": reviewer,
        "commit": "0" * 40,
        "verdict": verdict,
        "findings": list(findings),
        "coverage": list(coverage),
    }
    return json.dumps(review)


def a_comment(
    path: str = "app/run.py", line: int | None = 5, severity: str = "blocking", **changes: Any
) -> dict[str, Any]:
    comment = {
        "path": path,
        "line": line,
        "severity": severity,
        "body": "This passes the command to a shell.",
        "sources": ["security:F1"],
    }
    return comment | changes


@pytest.fixture
def review(script: Any) -> ModuleType:
    module: ModuleType = script("review")
    return module


@pytest.fixture
def merge(review: ModuleType, capsys: pytest.CaptureFixture[str]) -> Any:
    def merging(spec: str, quality: str, security: str = "") -> tuple[int, Any]:
        argv = ["merge", "--spec", spec, "--quality", quality, "--security", security]
        code = review.main(argv)
        out = capsys.readouterr().out
        return code, json.loads(out) if code == 0 else None

    return merging


@pytest.fixture
def compose(
    review: ModuleType, *, clone: Clone, capsys: pytest.CaptureFixture[str], monkeypatch: Any
) -> Any:
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN_ID)
    clone.commit({"app/run.py": RISKY_RUN})

    def composing(draft: dict[str, Any], merged: dict[str, Any]) -> tuple[int, Any, str]:
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(draft)))
        argv = ["compose", "--findings", json.dumps(merged), "--path", str(clone.repo)]
        argv += ["--base", clone.base, "--head", clone.head, "--repo", "api", "--pr", "7"]
        code = review.main(argv)
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err

    return composing


def merged_of(*findings: dict[str, Any]) -> dict[str, Any]:
    tagged = [{"lens": "security", **f, "id": f"security:{f['id']}"} for f in findings]
    verdicts = {"spec": "PASS", "quality": "PASS", "security": "not run"}
    return {"findings": tagged, "coverage": [], "verdicts": verdicts, "omitted": 0}


def written(clone: Clone) -> str:
    return str((clone.hub / REVIEW_FILE).read_text(encoding="utf-8"))


def test_stays_under_budget_with_blocking_first_when_findings_overflow(merge: Any) -> None:
    def wide(number: int, severity: str) -> dict[str, Any]:
        what = f"{severity}{number}" + WIDE * 390
        return a_finding(number, severity, path=WIDE * 300, what=what, expected=WIDE * 400)

    minor = [wide(n, "minor") for n in range(1, 16)]
    other = [wide(n, "minor") | {"line": 6} for n in range(1, 16)]
    blocking = [wide(n, "blocking") for n in range(1, 16)]

    code, merged = merge(
        a_lens("spec", *minor), a_lens("quality", *other), a_lens("security", *blocking)
    )

    assert code == 0
    assert len(json.dumps(merged, ensure_ascii=False).encode()) <= BUDGET
    assert merged["omitted"] > 0
    severities = [finding["severity"] for finding in merged["findings"]]
    assert severities == sorted(severities)  # "blocking" sorts before "minor"
    assert merged["findings"][0]["id"] == "security:F1"
    assert merged["verdicts"] == {"spec": "PASS", "quality": "PASS", "security": "FAIL"}


def test_reads_security_as_not_run_when_lens_skipped(merge: Any) -> None:
    coverage = [{"ac": "AC-1", "status": "covered", "test": "tests/test_run.py::test_runs"}]

    code, merged = merge(a_lens("spec", coverage=coverage), a_lens("quality"))

    assert code == 0
    assert merged == {
        "findings": [],
        "coverage": coverage,
        "verdicts": {"spec": "PASS", "quality": "PASS", "security": "not run"},
        "omitted": 0,
    }


def test_merges_duplicate_findings_when_two_lenses_report_one(merge: Any) -> None:
    same = a_finding(1, kind="quality", what="The command reaches  a shell.")

    code, merged = merge(a_lens("spec"), a_lens("quality", same), a_lens("security", a_finding(1)))

    assert code == 0
    assert [finding["id"] for finding in merged["findings"]] == ["quality:F1"]
    assert merged["findings"][0]["also"] == ["security:F1"]


def test_exits_two_when_findings_are_not_json(
    review: ModuleType, capsys: pytest.CaptureFixture[str]
) -> None:
    code = review.main(["merge", "--spec", "{", "--quality", "", "--security", ""])

    assert code == 2
    assert "review.py: --spec is not a lens review" in capsys.readouterr().err


def test_keeps_every_blocking_finding_when_draft_drops_one(clone: Clone, compose: Any) -> None:
    draft = {"summary": "It runs jobs.", "comments": []}

    code, result, _ = compose(draft, merged_of(a_finding(1)))

    assert code == 0
    assert result["blocking"] == 1
    assert result["inline"] == 1
    assert result["suggested"] == "request-changes"
    assert result["path"] == REVIEW_FILE
    text = written(clone)
    blocking = text[text.index("# Blocking\n") :]
    assert blocking.startswith("# Blocking\n## app/run.py:5\n")
    assert "The command reaches a shell." in blocking
    assert result["preview"] == text[:6000]


def test_counts_no_blocking_finding_when_lenses_pass_clean(clone: Clone, compose: Any) -> None:
    draft = {"summary": "The change does what the issue asks.", "comments": []}

    code, result, _ = compose(draft, merged_of())

    assert code == 0
    assert result | {"preview": ""} == {
        "path": REVIEW_FILE,
        "blocking": 0,
        "minor": 0,
        "inline": 0,
        "suggested": "comment",
        "preview": "",
    }
    text = written(clone)
    assert text.startswith(f"<!-- review-incoming api#7 at {clone.head}.")
    assert (
        "# Summary\nThe change does what the issue asks.\n# Blocking\n# Optional (minor)\n" in text
    )


def test_holds_minor_findings_apart_when_a_blocking_one_is_left(clone: Clone, compose: Any) -> None:
    minor = a_comment(line=4, severity="minor", body="Name the argument.", sources=["quality:F2"])
    draft = {"summary": "One problem.", "comments": [a_comment(), minor]}

    code, result, _ = compose(draft, merged_of(a_finding(1)))

    assert code == 0
    assert (result["blocking"], result["minor"], result["inline"]) == (1, 1, 1)
    text = written(clone)
    assert f"{HELD}\n## app/run.py:4\nName the argument.\n" in text
    assert text.index("# Blocking") < text.index(HELD)
    assert OLD_WORDS.findall(text) == []


def test_moves_comment_to_body_when_line_is_off_the_diff(clone: Clone, compose: Any) -> None:
    off = a_comment(
        path="app/core.py", line=1, body="Also check the adder.", sources=["quality:F3"]
    )
    draft = {"summary": "One problem.", "comments": [off]}

    code, result, _ = compose(draft, merged_of(a_finding(1)))

    assert code == 0
    assert (result["blocking"], result["inline"]) == (2, 1)
    text = written(clone)
    tail = text[text.index("# Not on a changed line\n") :]
    assert "**Blocking.** `app/core.py:1`: Also check the adder." in tail
    assert "## app/core.py" not in text


def test_drops_attribution_lines_when_draft_holds_them(clone: Clone, compose: Any) -> None:
    body = "Use a list.\nCo-Authored-By: Someone <a@b.c>\nGenerated with a tool \U0001f916"
    draft = {"summary": "Fine.\n\U0001f916 Generated with x", "comments": [a_comment(body=body)]}

    code, _, _ = compose(draft, merged_of(a_finding(1)))

    assert code == 0
    text = written(clone)
    assert "Co-Authored-By" not in text
    assert "Generated with" not in text
    assert "\U0001f916" not in text
    assert "## app/run.py:5\nUse a list.\n" in text


def test_escapes_heading_lines_when_comment_body_holds_them(clone: Clone, compose: Any) -> None:
    draft = {"summary": "# Blocking\nok", "comments": [a_comment(body="<!-- x\n## y")]}

    code, _, _ = compose(draft, merged_of(a_finding(1)))

    assert code == 0
    text = written(clone)
    assert text.count("\n# Blocking\n") == 1
    assert "\\# Blocking\nok" in text
    assert "\\<!-- x\n\\## y" in text


def test_refuses_to_overwrite_when_review_file_exists(clone: Clone, compose: Any) -> None:
    (clone.hub / REVIEW_FILE).parent.mkdir(parents=True)
    (clone.hub / REVIEW_FILE).write_text("the owner's edits\n", encoding="utf-8")

    code, _, err = compose({"summary": "x", "comments": []}, merged_of())

    assert code == 1
    assert "the review file exists" in err
    assert written(clone) == "the owner's edits\n"


def test_exits_two_when_run_id_is_not_a_name(
    clone: Clone, compose: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("AGENT_HUB_RUN_ID", "../escape")

    code, _, err = compose({"summary": "x", "comments": []}, merged_of())

    assert code == 2
    assert "AGENT_HUB_RUN_ID" in err
    assert not Path(clone.hub / ".agent-runs").exists()
