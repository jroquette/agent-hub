"""The feature agents and ``/feature`` as a hub renders them: ticket plan, evals, reviews (AGH-136).

The planner records the ticket plan in ``features.json`` (S3: draft keys, ``blocked_by``,
``order``, each AC's ``ticket``) and never calls the tracker; ``/feature`` step 4 creates the
issues, fills each ``id`` and creates the "blocked by" relations (Q1). The evaluator writes one new
``evals/<delivery>.md`` per evaluation with the S6 frontmatter and never overwrites one. An
approved spec changes only through ``## Amendments`` (S9). Step 7 writes the review record that
counts a ticket as reviewed (D4). One-team and two-team hubs render the same rules.

AGH-139: both reviewers and every skill that reads them speak one vocabulary (``PASS``/``FAIL``,
``blocking``/``minor``); a reviewer given the ticket, task, round and commit ends its reply with
one JSON block, a review output, and stays read-only.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_two_team_document
from agent_hub.generator.render_hub import render_hub

AGENTS = "plugin/hub-workflow/agents"
PLANNER = f"{AGENTS}/planner.md"
EVALUATOR = f"{AGENTS}/evaluator.md"
ANALYST = f"{AGENTS}/requirements-analyst.md"
SPEC_REVIEWER = f"{AGENTS}/spec-reviewer.md"
QUALITY_REVIEWER = f"{AGENTS}/quality-reviewer.md"
REVIEWERS = {"spec": SPEC_REVIEWER, "quality": QUALITY_REVIEWER}
FEATURE = "plugin/hub-workflow/skills/feature/SKILL.md"
FIX = "plugin/hub-workflow/skills/fix/SKILL.md"
REFACTOR = "plugin/hub-workflow/skills/refactor/SKILL.md"
REVIEW = "plugin/hub-workflow/skills/review/SKILL.md"

EVAL_FILE = "brain/features/<slug>/evals/<delivery>.md"
EVAL_FIELDS = (
    "type: eval",
    "delivery:",
    "verdict:",
    "tickets:",
    "acs:",
    "prs:",
    "commit:",
    "evaluated_at:",
)
VERDICTS = ("`SHIP`", "`SHIP-WITH-OWNER-STEPS`", "`NO-SHIP`")
REVIEW_FILE = "brain/features/<slug>/reviews/<ticket>.md"
REVIEW_FIELDS = (
    "type: review",
    "ticket:",
    "outcome: approved | changes-requested",
    "pr:",
    "reviewed_at:",
)
# AGH-139 E4: the reviewer words the unified vocabulary replaced, matched as whole words.
OLD_WORDS = (
    re.compile(r"\b(?:APPROVE|CHANGES)\b"),
    re.compile(r"\b(?:blockers?|should-fix|nits?)\b", re.IGNORECASE),
)
REVIEW_SCHEMA_FILE = "`plugin/hub-workflow/schemas/review.v1.json`"
REVIEW_INPUTS = "when the caller gives `ticket`, `task`, `round` and `commit`"
AMENDMENT_RULES = (
    "`status: approved`",
    "never rewritten",
    "`## Amendments`",
    "never renumbered",
    "withdrawn",
)


def texts_of(document: dict[str, object]) -> dict[str, str]:
    rendered = {
        file.path: file.content for file in render_hub(HubConfig.model_validate(document)).files
    }
    texts = {}
    for path in (
        PLANNER,
        EVALUATOR,
        ANALYST,
        FEATURE,
        SPEC_REVIEWER,
        QUALITY_REVIEWER,
        FIX,
        REFACTOR,
        REVIEW,
    ):
        content = rendered[path]
        assert content is not None, path
        texts[path] = content.decode("utf-8")
    return texts


@pytest.fixture(params=[a_hub_document, a_two_team_document], ids=["one_team", "two_teams"])
def texts(request: pytest.FixtureRequest) -> dict[str, str]:
    return texts_of(request.param())


def flat(text: str) -> str:
    """``text`` with its line breaks and runs of spaces read as one space."""
    return " ".join(text.split())


def step(text: str, number: int) -> str:
    """One numbered step of ``/feature``: its line and the indented lines that follow it."""
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{number}. "))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines)
    )
    return flat("\n".join(lines[start:end]))


def old_words(text: str) -> list[str]:
    """The old reviewer words ``text`` holds (E4), in pattern order."""
    return [word for pattern in OLD_WORDS for word in pattern.findall(text)]


def test_writes_new_eval_file_when_evaluator_rendered(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert f"You may write only a new `{EVAL_FILE}`" in text
    for field in EVAL_FIELDS:
        assert field in texts[EVALUATOR], field
    for verdict in VERDICTS:
        assert verdict in text, verdict
    assert "never overwrite" in text
    assert "`-r2`" in text
    # The single eval.md is no longer the output: only a past one, read as `legacy`.
    assert re.findall(r"[\w/<>-]*eval\.md", text) == ["eval.md"]
    assert "`legacy`" in text


def test_keeps_approved_spec_amendments_when_analyst_and_feature_rendered(
    texts: dict[str, str],
) -> None:
    for path in (ANALYST, FEATURE):
        text = flat(texts[path])
        for rule in AMENDMENT_RULES:
            assert rule in text, (path, rule)
    assert "`withdrawn: true`" in flat(texts[ANALYST])


def test_records_ticket_plan_when_planner_rendered(texts: dict[str, str]) -> None:
    planner = flat(texts[PLANNER])
    tickets = step(texts[FEATURE], 4)

    for phrase in (
        '"tickets": [',
        '"key": "T1"',
        '"blocked_by": [',
        '"order": 0',
        '"ticket": "T1"',
    ):
        assert phrase in planner, phrase
    assert "you do not call the tracker" in planner
    for phrase in ("create the issues", "fill each ticket's `id`", '"blocked by" relations'):
        assert phrase in tickets, phrase
    assert tickets.index("create the issues") < tickets.index('"blocked by" relations')


def test_writes_review_record_when_feature_skill_rendered(texts: dict[str, str]) -> None:
    review = step(texts[FEATURE], 7)
    verify = step(texts[FEATURE], 8)

    assert REVIEW_FILE in review
    for field in REVIEW_FIELDS:
        assert f"`{field}" in review, field
    assert "both reviewers pass" in review
    assert "brain/features/<slug>/evals/" in verify
    assert "eval.md" not in verify


def test_finds_old_words_when_base_phrases_scanned() -> None:
    found = old_words("Should-fix findings; On `CHANGES` with blockers; skip nits")

    assert found == ["CHANGES", "Should-fix", "blockers", "nits"]
    assert old_words("a unit test, initial `blocking` findings, `changes-requested`, approve") == []


def test_keeps_reviewers_read_only_when_review_json_added(texts: dict[str, str]) -> None:
    for path in REVIEWERS.values():
        text = texts[path]

        frontmatter = text.split("\n---\n", 1)[0].splitlines()
        assert "tools: Read, Grep, Glob, Bash" in frontmatter, path
        assert "You review; you never edit." in text, path


def test_reports_unified_verdict_when_review_json_reviewers_rendered(
    texts: dict[str, str],
) -> None:
    for path in REVIEWERS.values():
        text = flat(texts[path])

        assert "**Report:** `PASS` or `FAIL`" in text, path
        assert "`blocking` or `minor`" in text, path
        assert "`PASS` only when no finding is `blocking`" in text, path
        assert old_words(texts[path]) == [], path
    quality = flat(texts[QUALITY_REVIEWER])
    assert "List `minor` findings too, within the 100-finding bound" in quality
    assert "or it is `minor`" in quality


def test_ends_with_one_json_block_when_review_json_inputs_given(texts: dict[str, str]) -> None:
    for reviewer, path in REVIEWERS.items():
        text = flat(texts[path])
        other = next(name for name in REVIEWERS if name != reviewer)

        assert REVIEW_INPUTS in text, path
        assert "end the reply with exactly one fenced `json` block, nothing after it" in text, path
        assert REVIEW_SCHEMA_FILE in text, path
        assert '`"schema": "agent-hub/review/1"`' in text, path
        assert f'`"reviewer": "{reviewer}"`' in text, path
        assert f'"reviewer": "{other}"' not in text, path
        assert "the same `verdict` as the prose" in text, path
        assert "the same `severity`" in text, path
        assert "Without those four values, no block." in text, path
        assert "`./hub validate-output review <file>`" in text, path
        assert text.index(REVIEW_INPUTS) > text.index("**Report:**"), path
    spec = flat(texts[SPEC_REVIEWER])
    assert "`/feature` also gives the `ticket`, `task`, `round` and `commit`" in spec


def test_reads_unified_vocabulary_when_fix_refactor_review_rendered(
    texts: dict[str, str],
) -> None:
    fix = step(texts[FIX], 6)
    refactor = step(texts[REFACTOR], 5)
    review = step(texts[REVIEW], 5)

    assert "On `FAIL` with `blocking` findings: fix them" in fix
    assert "Minor findings without `blocking` ones: fix them or list them" in fix
    assert "as follow-ups" in fix
    assert "`blocking` findings: fix them and re-run both gates; no second pass." in refactor
    assert "severity (blocking / minor)" in review
    assert "minor findings go only when no blocking one is left" in review
    for path in (FIX, REFACTOR, REVIEW):
        assert old_words(texts[path]) == [], path
