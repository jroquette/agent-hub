from typing import Any

import pytest

from agent_hub.core.hub_config.conventions import EffectiveConventions
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.run_texts import (
    MAX_COMMIT_SUMMARY_CHARS,
    MAX_DIAGNOSIS_CHARS,
    MAX_PR_SUMMARY_CHARS,
    MAX_PR_TITLE_CHARS,
    MAX_SUCCESS_SUMMARY_CHARS,
    WORKSPACE_WORDS,
    PrTitle,
    commit_summary,
    conventional_pr_title,
    failure_comment,
    inbox_line,
    pr_body,
    pr_title,
    sanitized_summary,
    success_comment,
)
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document

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

    assert commit_summary(text, workspace=WORKSPACE) == "c" * MAX_COMMIT_SUMMARY_CHARS
    assert commit_summary(" feat: x\n\nbody\n", workspace=WORKSPACE) == "feat: x\n\nbody"


def test_builds_pr_body_when_gate_green() -> None:
    body = pr_body(
        issue_id="DEM-1", summary="Adds the parser.", gate="make check", workspace=WORKSPACE
    )

    assert body == "DEM-1\n\nAdds the parser.\n\n## Verification\nGates green: `make check`."


def test_cuts_pr_summary_when_over_cap() -> None:
    body = pr_body(
        issue_id="DEM-1",
        summary="s" * (MAX_PR_SUMMARY_CHARS + 1),
        gate="make check",
        workspace=WORKSPACE,
    )

    assert body == (
        f"DEM-1\n\n{'s' * MAX_PR_SUMMARY_CHARS}\n\n## Verification\nGates green: `make check`."
    )


def test_writes_neutral_comment_when_run_succeeds() -> None:
    comment = success_comment(
        run_id="ab12cd34",
        pr_url=URL,
        summary="x" * (MAX_SUCCESS_SUMMARY_CHARS + 1),
        workspace=WORKSPACE,
    )

    assert comment == f"Run ab12cd34 opened {URL}. {'x' * MAX_SUCCESS_SUMMARY_CHARS}"
    assert "Agent" not in success_comment(
        run_id="ab12cd34", pr_url=URL, summary="Done.", workspace=WORKSPACE
    )


def test_writes_neutral_comment_when_run_fails() -> None:
    comment = failure_comment(
        run_id="ab12cd34",
        stage="VERIFYING",
        reason="r" * (MAX_DIAGNOSIS_CHARS + 1),
        workspace=WORKSPACE,
    )

    assert comment == f"Run ab12cd34 failed at VERIFYING. Diagnosis: {'r' * MAX_DIAGNOSIS_CHARS}"
    assert "Agent" not in failure_comment(
        run_id="ab12cd34", stage="PR_OPEN", reason="x", workspace=WORKSPACE
    )


def test_formats_inbox_line_when_outcome_given() -> None:
    common = {"issue_id": "DEM-1", "repo": "demo-api", "run_id": "ab12cd34"}

    assert inbox_line(**common, outcome=f"PR {URL}", cost_usd=1.234) == (
        f"- DEM-1 (demo-api) run ab12cd34: PR {URL}; $1.23"
    )
    assert inbox_line(**common, outcome="FAILED at IMPLEMENTING", cost_usd=0) == (
        "- DEM-1 (demo-api) run ab12cd34: FAILED at IMPLEMENTING; $0.00"
    )


ROBOT = "\N{ROBOT FACE}"
# One row per class of character the summary must lose.
UNSAFE_CHARACTERS = {
    "nul": "\x00",
    "c0-escape": "\x1b[2J",
    "bell": "\x07",
    "delete": "\x7f",
    "c1-csi": "\x9b",
    "bidi-embedding": "\u202a",
    "bidi-override": "\u202e",
    "bidi-isolate": "\u2066",
    "pop-isolate": "\u2069",
    "left-to-right-mark": "\u200e",
    "right-to-left-mark": "\u200f",
    "arabic-letter-mark": "\u061c",
    "zero-width-space": "\u200b",
    "zero-width-non-joiner": "\u200c",
    "zero-width-joiner": "\u200d",
    "word-joiner": "\u2060",
    "byte-order-mark": "\ufeff",
}


@pytest.mark.parametrize("unsafe", list(UNSAFE_CHARACTERS.values()), ids=list(UNSAFE_CHARACTERS))
def test_strips_control_and_bidi_characters_when_summary_holds_them(unsafe: str) -> None:
    summary = f"Adds{unsafe} the parser.\n\tTests:\tmake check."

    assert sanitized_summary(summary, workspace=WORKSPACE) == (
        "Adds the parser.\n\tTests:\tmake check."
    )


def test_replaces_lone_surrogate_when_summary_holds_one() -> None:
    cleaned = sanitized_summary("Adds \ud800 the parser.", workspace=WORKSPACE)

    assert cleaned == "Adds \ufffd the parser."
    cleaned.encode()


@pytest.mark.parametrize(
    "line", [ROBOT, f"  {ROBOT}  ", f"{ROBOT} Made by a bot"], ids=["bare", "padded", "with-text"]
)
def test_drops_robot_line_when_summary_has_one(line: str) -> None:
    summary = f"Adds the parser.\n{line}\nTests: make check."

    assert sanitized_summary(summary, workspace=WORKSPACE) == (
        "Adds the parser.\nTests: make check."
    )


def test_strips_file_url_prefix_when_summary_links_workspace() -> None:
    summary = f"See file://{WORKSPACE}/demo-api/src/x.py and file://{WORKSPACE}."

    assert sanitized_summary(summary, workspace=WORKSPACE) == (
        f"See demo-api/src/x.py and {WORKSPACE_WORDS}."
    )


def test_cleans_summary_when_commit_summary_built() -> None:
    text = f"feat: x\n\nTouches {WORKSPACE}/demo-api/x.py\x1b[2J\n" + CO_AUTHOR + " Claude <a@b>\n"

    assert commit_summary(text, workspace=WORKSPACE) == "feat: x\n\nTouches demo-api/x.py"


def test_cleans_texts_when_pr_body_and_comments_built() -> None:
    dirty = f"Edits {WORKSPACE}/demo-api/x.py\u202e.\n" + ATTRIBUTION_LINES["generated"]

    body = pr_body(issue_id="DEM-1", summary=dirty, gate="make check", workspace=WORKSPACE)
    opened = success_comment(run_id="ab12cd34", pr_url=URL, summary=dirty, workspace=WORKSPACE)
    failed = failure_comment(
        run_id="ab12cd34", stage="VERIFYING", reason=dirty, workspace=WORKSPACE
    )

    assert body == "DEM-1\n\nEdits demo-api/x.py.\n\n## Verification\nGates green: `make check`."
    assert opened == f"Run ab12cd34 opened {URL}. Edits demo-api/x.py."
    assert failed == "Run ab12cd34 failed at VERIFYING. Diagnosis: Edits demo-api/x.py."


def test_pins_title_cap_when_module_loaded() -> None:
    assert MAX_PR_TITLE_CHARS == 256


def test_cleans_title_when_subject_holds_controls_and_paths() -> None:
    subject = f"feat(api): touch {WORKSPACE}/demo-api/x.py\x1b[2J\u202e"

    assert pr_title(subject, workspace=WORKSPACE, fallback="DEM-1") == (
        "feat(api): touch demo-api/x.py"
    )


def test_cuts_title_when_subject_over_cap() -> None:
    title = pr_title("t" * (MAX_PR_TITLE_CHARS + 1), workspace=WORKSPACE, fallback="DEM-1")

    assert title == "t" * MAX_PR_TITLE_CHARS


@pytest.mark.parametrize(
    "subject",
    ["", "   \n\n", "\x1b[2J", ATTRIBUTION_LINES["co-author"], "\N{ROBOT FACE}"],
    ids=["empty", "blank", "control-only", "attribution", "robot"],
)
def test_falls_back_when_subject_has_no_text(subject: str) -> None:
    assert pr_title(subject, workspace=WORKSPACE, fallback="DEM-1") == "DEM-1"


def test_takes_first_line_when_subject_has_several() -> None:
    assert pr_title("\nfeat: x\nmore", workspace=WORKSPACE, fallback="DEM-1") == "feat: x"


def test_drops_attribution_line_when_zero_width_splits_it() -> None:
    line = "Co-\u200b" + "Authored-By: " + "Claude <noreply@example.com>"

    assert sanitized_summary(f"Adds x.\n{line}", workspace=WORKSPACE) == "Adds x."


def conventions_of(document: dict[str, Any], repo: str = "demo-api") -> EffectiveConventions:
    return HubConfig.model_validate(document).conventions_for(repo)


def with_repo_conventions(**keys: str) -> dict[str, Any]:
    document = a_hub_document()
    document["repos"][0]["conventions"] = keys
    return document


def titled(subject: str, conventions: EffectiveConventions) -> PrTitle:
    return conventional_pr_title(
        subject, conventions=conventions, issue_id="DEM-1", workspace=WORKSPACE
    )


UNCONFIGURED_SUBJECTS = ("feat(core): add x (DEM-1)", "feat: add x (DEM-2)", "add x")
UNCONFIGURED_HUBS = {
    "unconfigured": a_hub_document,
    "branch-only": lambda: with_repo_conventions(branch="{prefix}{ISSUE}-{slug}"),
}


@pytest.mark.parametrize("subject", UNCONFIGURED_SUBJECTS)
@pytest.mark.parametrize("hub", list(UNCONFIGURED_HUBS))
def test_keeps_cleaned_subject_when_titles_not_configured(hub: str, subject: str) -> None:
    conventions = conventions_of(UNCONFIGURED_HUBS[hub]())

    assert titled(subject, conventions) == PrTitle(
        title=pr_title(subject, workspace=WORKSPACE, fallback="DEM-1"), unmatched=False
    )
    assert titled(subject, conventions).title == subject


def test_renders_pr_title_from_parts_when_subject_matches() -> None:
    conventions = conventions_of(a_conventions_document(), "demo-web")

    assert titled("DEM-9: feat(cli): add x", conventions) == PrTitle(
        title="DEM-1: feat(cli): add x", unmatched=False
    )


def test_falls_back_to_subject_when_subject_does_not_match() -> None:
    conventions = conventions_of(a_conventions_document(), "demo-web")

    assert titled("add x", conventions) == PrTitle(title="add x", unmatched=True)


def test_parses_with_default_commit_title_when_only_pr_title_set() -> None:
    conventions = conventions_of(with_repo_conventions(pr_title="{ISSUE}: {summary}"))

    assert titled("feat(core): add x (DEM-1)", conventions) == PrTitle(
        title="DEM-1: add x", unmatched=False
    )


def test_renders_commit_shape_when_only_commit_title_set() -> None:
    document = a_hub_document()
    document["project"]["conventions"] = {"commit_title": "{ISSUE}: {summary}"}
    conventions = conventions_of(document)

    assert titled("DEM-9: add x", conventions) == PrTitle(title="DEM-1: add x", unmatched=False)
    assert titled("add x", conventions) == PrTitle(title="add x", unmatched=True)


def test_cleans_and_cuts_final_title_when_rendered() -> None:
    conventions = conventions_of(a_conventions_document(), "demo-web")
    robot = "\N{ROBOT FACE} Generated"

    with_path = titled(f"DEM-9: feat(cli): touch {WORKSPACE}/demo-web/x.py", conventions)
    with_robot = titled(f"{robot}\nDEM-9: feat(cli): add x", conventions)
    long = titled("DEM-9: feat(cli): " + "s" * 300, conventions)

    assert with_path == PrTitle(title="DEM-1: feat(cli): touch demo-web/x.py", unmatched=False)
    assert with_robot == PrTitle(title="DEM-1: feat(cli): add x", unmatched=False)
    assert long.title == "DEM-1: feat(cli): " + "s" * (256 - len("DEM-1: feat(cli): "))
    assert len(long.title) == 256
    assert long.unmatched is False
