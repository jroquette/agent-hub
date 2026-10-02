import pytest

from agent_hub.core.runner.run_texts import (
    MAX_COMMIT_SUMMARY_CHARS,
    MAX_DIAGNOSIS_CHARS,
    MAX_PR_SUMMARY_CHARS,
    MAX_SUCCESS_SUMMARY_CHARS,
    commit_summary,
    failure_comment,
    inbox_line,
    pr_body,
    sanitized_summary,
    success_comment,
)

WORKSPACE = "/work/ws"
# Assembled, so the repo holds no attribution line (as test_text_rules.py does).
CO_AUTHOR = "Co-" + "Authored-By:"
ATTRIBUTION_LINES = {
    "co-author": CO_AUTHOR + " " + "Claude" + " <noreply@example.com>",
    "co-author-vendor": CO_AUTHOR + " Someone <bot@" + "anthropic" + ".com>",
    "generated": "\N{ROBOT FACE} Generated " + "with [Claude" + " Code](https://example.com)",
    "branch": "pushed to " + "claude" + "/fix-login",
}
URL = "https://github.com/acme/demo-api/pull/99"


def test_pins_caps_when_module_loaded() -> None:
    assert MAX_COMMIT_SUMMARY_CHARS == 1_200
    assert MAX_PR_SUMMARY_CHARS == 20_000
    assert MAX_SUCCESS_SUMMARY_CHARS == 600
    assert MAX_DIAGNOSIS_CHARS == 900


def test_strips_workspace_prefix_when_summary_has_paths() -> None:
    summary = (
        f"Changed {WORKSPACE}/demo-api/src/x.py and {WORKSPACE}/hub/brain/now.md.\n"
        f"Ran make in {WORKSPACE}."
    )

    assert sanitized_summary(summary, workspace=WORKSPACE) == (
        "Changed demo-api/src/x.py and hub/brain/now.md.\nRan make in the workspace."
    )


def test_keeps_longer_folder_when_it_only_starts_like_workspace() -> None:
    summary = f"See {WORKSPACE}2/notes, {WORKSPACE}-old/x and /other{WORKSPACE}/y."

    assert sanitized_summary(summary, workspace=WORKSPACE) == summary


@pytest.mark.parametrize("line", list(ATTRIBUTION_LINES.values()), ids=list(ATTRIBUTION_LINES))
def test_drops_attribution_line_when_summary_has_one(line: str) -> None:
    summary = f"Adds the parser.\n\n{line}\nTests: make check."

    assert sanitized_summary(summary, workspace=WORKSPACE) == (
        "Adds the parser.\n\nTests: make check."
    )


def test_cuts_commit_summary_when_over_cap() -> None:
    text = "\n" + "c" * (MAX_COMMIT_SUMMARY_CHARS + 10) + "\n"

    assert commit_summary(text) == "c" * MAX_COMMIT_SUMMARY_CHARS
    assert commit_summary(" feat: x\n\nbody\n") == "feat: x\n\nbody"


def test_builds_pr_body_when_gate_green() -> None:
    body = pr_body(issue_id="DEM-1", summary="Adds the parser.", gate="make check")

    assert body == "DEM-1\n\nAdds the parser.\n\n## Verification\nGates green: `make check`."


def test_cuts_pr_summary_when_over_cap() -> None:
    body = pr_body(issue_id="DEM-1", summary="s" * (MAX_PR_SUMMARY_CHARS + 1), gate="make check")

    assert body == (
        f"DEM-1\n\n{'s' * MAX_PR_SUMMARY_CHARS}\n\n## Verification\nGates green: `make check`."
    )


def test_writes_neutral_comment_when_run_succeeds() -> None:
    comment = success_comment(
        run_id="ab12cd34", pr_url=URL, summary="x" * (MAX_SUCCESS_SUMMARY_CHARS + 1)
    )

    assert comment == f"Run ab12cd34 opened {URL}. {'x' * MAX_SUCCESS_SUMMARY_CHARS}"
    assert "Agent" not in success_comment(run_id="ab12cd34", pr_url=URL, summary="Done.")


def test_writes_neutral_comment_when_run_fails() -> None:
    comment = failure_comment(
        run_id="ab12cd34", stage="VERIFYING", reason="r" * (MAX_DIAGNOSIS_CHARS + 1)
    )

    assert comment == f"Run ab12cd34 failed at VERIFYING. Diagnosis: {'r' * MAX_DIAGNOSIS_CHARS}"
    assert "Agent" not in failure_comment(run_id="ab12cd34", stage="PR_OPEN", reason="x")


def test_formats_inbox_line_when_outcome_given() -> None:
    common = {"issue_id": "DEM-1", "repo": "demo-api", "run_id": "ab12cd34"}

    assert inbox_line(**common, outcome=f"PR {URL}", cost_usd=1.234) == (
        f"- DEM-1 (demo-api) run ab12cd34: PR {URL}; $1.23"
    )
    assert inbox_line(**common, outcome="FAILED at IMPLEMENTING", cost_usd=0) == (
        "- DEM-1 (demo-api) run ab12cd34: FAILED at IMPLEMENTING; $0.00"
    )
