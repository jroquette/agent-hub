"""The review-incoming pack's ``review.py`` (AGH-493): ``merge`` folds the lenses' findings,
blocking first, within budget; ``compose`` writes the review file the owner edits, every blocking
finding kept and each comment checked against the diff; ``final`` parses the edited file again
into the payload ``/review`` posts."""

import hashlib
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
        "moved": 0,
        "note": "",
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


PAYLOAD_FILE = f".agent-runs/review-incoming/{RUN_ID}.payload.json"


@pytest.fixture
def final(review: ModuleType, *, clone: Clone, capsys: pytest.CaptureFixture[str]) -> Any:
    def finishing(decision: str = "comment", file: str = REVIEW_FILE) -> tuple[int, Any, str]:
        argv = ["final", "--file", file, "--decision", decision, "--path", str(clone.repo)]
        code = review.main([*argv, "--base", clone.base, "--head", clone.head])
        captured = capsys.readouterr()
        return code, json.loads(captured.out) if code == 0 else None, captured.err

    return finishing


def composed(compose: Any, *comments: dict[str, Any], summary: str = "One problem.") -> None:
    code, _, err = compose({"summary": summary, "comments": list(comments)}, merged_of())
    assert code == 0, err


def edit(clone: Clone, old: str, new: str) -> None:
    path = clone.hub / REVIEW_FILE
    text = path.read_text(encoding="utf-8")
    assert old in text
    path.write_text(text.replace(old, new), encoding="utf-8")


def payload(clone: Clone) -> Any:
    return json.loads((clone.hub / PAYLOAD_FILE).read_text(encoding="utf-8"))


def test_builds_payload_from_owner_edits_when_file_changed(
    clone: Clone, compose: Any, final: Any
) -> None:
    dropped = a_comment(line=4, body="Drop me.", sources=["quality:F2"])
    composed(compose, a_comment(), dropped)
    edit(clone, "One problem.", "One problem, said my way.")
    edit(clone, "## app/run.py:4\nDrop me.\n", "")

    code, result, _ = final("request-changes")

    assert code == 0
    sent = payload(clone)
    assert sent["commit_id"] == clone.head
    assert sent["body"].startswith("One problem, said my way.")
    assert [comment["line"] for comment in sent["comments"]] == [5]
    assert "Drop me." not in json.dumps(sent)
    assert result["inline"] == 1


def test_separates_blocking_and_optional_in_body_and_comments_when_payload_built(
    clone: Clone, compose: Any, final: Any
) -> None:
    minor = a_comment(line=4, severity="minor", body="Name it.", sources=["quality:F2"])
    composed(compose, minor, a_comment(severity="minor", body="Also here.", sources=["q:F3"]))

    code, result, _ = final("comment")

    assert code == 0
    assert (result["blocking"], result["optional"], result["inline"]) == (0, 2, 2)
    sent = payload(clone)
    assert [c["body"] for c in sent["comments"]] == [
        "**Optional.** Name it.",
        "**Optional.** Also here.",
    ]
    assert {c["side"] for c in sent["comments"]} == {"RIGHT"}
    assert "Blocking (0)" in sent["body"]
    assert "Optional (2)\n- `app/run.py:4` Name it.\n- `app/run.py:5` Also here." in sent["body"]


def test_skips_held_minor_section_when_owner_left_its_heading(
    clone: Clone, compose: Any, final: Any
) -> None:
    minor = a_comment(line=4, severity="minor", body="Name it.", sources=["quality:F2"])
    composed(compose, a_comment(body="Use a list."), minor)

    code, result, _ = final("request-changes")
    held = payload(clone)
    (clone.hub / PAYLOAD_FILE).unlink()
    edit(clone, HELD, "# Optional (minor)")
    renamed_code, renamed, _ = final("request-changes")

    assert (code, renamed_code) == (0, 0)
    assert [c["body"] for c in held["comments"]] == ["**Blocking.** Use a list."]
    assert (result["blocking"], result["optional"]) == (1, 0)
    assert (renamed["blocking"], renamed["optional"]) == (1, 1)
    assert "**Optional.** Name it." in [c["body"] for c in payload(clone)["comments"]]


@pytest.mark.parametrize(
    "case",
    [("comment", "COMMENT"), ("request-changes", "REQUEST_CHANGES"), ("approve", "APPROVE")],
)
def test_maps_decision_to_event_when_final_runs(
    clone: Clone, *, compose: Any, final: Any, case: tuple[str, str]
) -> None:
    decision, event = case
    composed(compose)

    code, result, _ = final(decision)

    assert code == 0
    assert result["event"] == event
    assert "event" not in payload(clone)


def test_exits_two_when_decision_is_reject(clone: Clone, compose: Any, final: Any) -> None:
    composed(compose)

    code, _, err = final("reject")

    assert code == 2
    assert "decision" in err
    assert not (clone.hub / PAYLOAD_FILE).exists()


def test_prints_sha256_of_written_payload_when_final_runs(
    clone: Clone, compose: Any, final: Any
) -> None:
    composed(compose, a_comment())

    code, result, _ = final("comment")

    assert code == 0
    assert result["path"] == PAYLOAD_FILE
    data = (clone.hub / PAYLOAD_FILE).read_bytes()
    assert result["sha256"] == hashlib.sha256(data).hexdigest()


def test_refuses_review_file_when_it_is_a_link(clone: Clone, compose: Any, final: Any) -> None:
    composed(compose)
    path = clone.hub / REVIEW_FILE
    other = path.with_name("other.md")
    path.rename(other)
    path.symlink_to(other)

    code, _, err = final("comment")

    assert code == 1
    assert "cannot read the review" in err
    assert not (clone.hub / PAYLOAD_FILE).exists()


def test_refuses_review_file_when_path_is_not_this_runs(
    clone: Clone, compose: Any, final: Any
) -> None:
    composed(compose)

    code, _, err = final("comment", file=".agent-runs/review-incoming/run-2.md")

    assert code == 1
    assert "cannot read the review: not this run's file" in err


def test_refuses_review_file_when_over_cap(clone: Clone, compose: Any, final: Any) -> None:
    composed(compose)
    edit(clone, "One problem.", "x" * 65537)

    code, _, err = final("comment")

    assert code == 1
    assert "cannot read the review: over 65536 bytes" in err


def test_refuses_review_when_owner_added_attribution(
    clone: Clone, compose: Any, final: Any
) -> None:
    composed(compose)
    edit(clone, "One problem.", "One problem.\n\U0001f916 Generated with a tool")

    code, _, err = final("comment")

    assert code == 1
    assert "the review holds AI attribution: remove it and run /review again" in err
    assert not (clone.hub / PAYLOAD_FILE).exists()


@pytest.mark.parametrize("path", ["../secrets.txt", "/etc/passwd", "app/../../x"])
def test_refuses_payload_when_comment_path_escapes(
    review: ModuleType, clone: Clone, path: str
) -> None:
    parsed = review.parse_review(f"# Summary\nx\n# Blocking\n## {path}:5\nbody\n")
    anchors = {path: {5}}

    with pytest.raises(review.RefusedError, match="comments.path"):
        review.payload(parsed, anchors, head=clone.head)


def test_round_trips_compose_output_when_file_unedited(
    clone: Clone, compose: Any, final: Any
) -> None:
    off = a_comment(path="app/core.py", line=1, body="Also the adder.", sources=["quality:F3"])
    composed(compose, a_comment(body="Use a list.\n\nThen test it."), off)

    code, result, _ = final("request-changes")

    assert code == 0
    sent = payload(clone)
    assert sent["comments"] == [
        {
            "path": "app/run.py",
            "line": 5,
            "side": "RIGHT",
            "body": "**Blocking.** Use a list.\n\nThen test it.",
        }
    ]
    assert sent["body"] == (
        "One problem.\n\n"
        "Blocking (2)\n- `app/run.py:5` Use a list.\n- `app/core.py:1` Also the adder.\n\n"
        "Optional (0)\n\n"
        "**Blocking.** `app/core.py:1`: Also the adder."
    )
    assert (result["blocking"], result["optional"], result["inline"]) == (2, 0, 1)


def test_keeps_a_blocking_finding_when_only_a_minor_comment_cites_it(
    clone: Clone, compose: Any
) -> None:
    minor = a_comment(line=4, severity="minor", body="Maybe a list.", sources=["security:F1"])

    code, result, _ = compose(
        {"summary": "One problem.", "comments": [minor]}, merged_of(a_finding(1))
    )

    assert code == 0
    assert result["blocking"] >= 1
    assert result["suggested"] == "request-changes"
    text = written(clone)
    assert "# Blocking\n## app/run.py:5\nThe command reaches a shell." in text


def test_accepts_the_same_file_when_compose_runs_again(clone: Clone, compose: Any) -> None:
    draft = {"summary": "One problem.", "comments": [a_comment()]}

    first = compose(draft, merged_of(a_finding(1)))
    again = compose(draft, merged_of(a_finding(1)))

    assert (first[0], again[0]) == (0, 0)
    assert first[1] == again[1]


def test_exits_one_when_git_cannot_diff_for_compose(
    review: ModuleType, *, clone: Clone, monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN_ID)
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"summary": "x", "comments": []})))
    argv = ["compose", "--findings", json.dumps(merged_of()), "--path", str(clone.repo)]
    argv += ["--base", clone.base, "--head", "e" * 40, "--repo", "api", "--pr", "7"]

    code = review.main(argv)

    assert code == 1
    assert "git cannot diff" in capsys.readouterr().err
    assert not (clone.hub / REVIEW_FILE).exists()


def test_says_why_comments_moved_when_the_diff_was_cut(
    review: ModuleType, *, clone: Clone, compose: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(review, "DIFF_CAP", 40)

    code, result, _ = compose({"summary": "x", "comments": [a_comment()]}, merged_of())

    assert code == 0
    assert result["moved"] == 1
    assert "over 40 bytes" in result["note"]
    assert "over 40 bytes" in written(clone)


def test_says_why_comments_moved_when_final_cuts_the_diff(
    review: ModuleType,
    *,
    clone: Clone,
    compose: Any,
    final: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    composed(compose, a_comment())
    monkeypatch.setattr(review, "DIFF_CAP", 40)

    code, result, _ = final("request-changes")

    assert code == 0
    assert (result["inline"], result["moved"]) == (0, 1)
    assert "over 40 bytes" in result["note"]


def test_moves_comment_to_body_when_its_line_is_unchanged_in_a_renamed_file(
    clone: Clone, compose: Any, final: Any
) -> None:
    original = "".join(f"line {n}\n" for n in range(1, 21))
    clone.base = clone.commit({"app/long.py": original})
    clone.commit({"app/long.py": "", "app/longer.py": original.replace("line 20", "line 20!")})
    unchanged = a_comment(path="app/longer.py", line=2, body="Line two.", sources=["q:F1"])

    composed(compose, unchanged)
    code, result, _ = final("comment")

    text = written(clone)
    assert "## app/longer.py:2" not in text
    assert "**Blocking.** `app/longer.py:2`: Line two." in text
    assert code == 0
    assert (result["inline"], result["moved"]) == (0, 0)
    assert payload(clone)["comments"] == []
