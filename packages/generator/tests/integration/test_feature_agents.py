"""The feature agents and ``/feature`` as a hub renders them: ticket plan, evals, reviews (AGH-136).

The planner records the ticket plan in ``features.json`` (S3: draft keys, ``blocked_by``,
``order``, each AC's ``ticket``) and never calls the tracker; ``/feature`` step 4 creates the
issues, fills each ``id`` and creates the "blocked by" relations (Q1). The evaluator writes one new
``evals/<delivery>.md`` per evaluation with the S6 frontmatter and never overwrites one. An
approved spec changes only through ``## Amendments`` (S9). Step 7 writes the review record that
counts a ticket as reviewed (D4). One-team and two-team hubs render the same rules.

AGH-139: both reviewers and every skill that reads them speak one vocabulary (``PASS``/``FAIL``,
``blocking``/``minor``); a reviewer given the ticket, task, round and commit ends its reply with
one JSON block, a review output, and stays read-only. The evaluator writes and validates its own
``evals/<delivery>.json``; ``/feature`` saves and validates each reviewer's JSON, re-asks or
re-dispatches once on an invalid output, and gates review and ship only on validated files.
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
EVAL_JSON = "brain/features/<slug>/evals/<delivery>.json"
REVIEW_JSON = "brain/features/<slug>/reviews/<ticket>/<reviewer>-r<N>.json"
PRINTED_LINES = "every line the command printed (the `… and N more` line included)"
REVIEW_INPUTS = "when the caller gives `ticket`, `task`, `round` and `commit`"
SHIP_RULE = (
    "Act only on the validated JSON: ship on a validated `SHIP`, or on a validated"
    " `SHIP-WITH-OWNER-STEPS` once the user confirms its owner steps are done"
)
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


def test_writes_eval_json_when_evaluator_rendered(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert f"You may write only a new `{EVAL_FILE}` with its `.json` beside it" in text
    assert f"beside the `.md`, write `{EVAL_JSON}` (the same delivery and `-rN` name" in text
    assert "`plugin/hub-workflow/schemas/eval.v1.json`" in text
    assert '`"schema": "agent-hub/eval/1"`' in text
    assert (
        "`verdict`, `delivery`, `tickets`, `acs` and `commit` equal to the `.md` frontmatter"
        in text
    )
    for key in ("`results`", "`gates`", "`red_on_parent`", "`owner_steps`"):
        assert key in text, key
    assert "Then run `./hub validate-output eval <file>`" in text
    # The `.md` stays the record AGH-136 reads; the JSON only joins it.
    assert text.index(f"**Write** a new `{EVAL_FILE}`") < text.index(EVAL_JSON)
    assert texts[EVALUATOR].count("./hub doctor --only features.tracker") == 1


def test_rewrites_only_own_eval_json_when_evaluator_rendered(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert (
        "Until it exits 0, and before you hand back, you may rewrite only the `.json` you created"
        " in this run" in text
    )
    assert "never rewrite an eval file that existed before your run" in text
    assert "never overwrite or edit an existing eval file" in text


def test_writes_next_pair_when_eval_json_redispatched(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert (
        "**Re-dispatch:** when `/feature` sends you back with a failed delivery and its problem"
        " lines, run a new evaluation of the same scope and write the next free `<delivery>-rN`"
        " pair (`.md` and `.json`); the failed pair stays as it is, as evidence." in text
    )


def test_validates_review_outputs_when_feature_step_seven_rendered(texts: dict[str, str]) -> None:
    review = step(texts[FEATURE], 7)

    phrases = (
        "passing each the `ticket`, `task`, `round` (from 1) and `commit` it reviews",
        f"Save each reply's fenced `json` block verbatim to `{REVIEW_JSON}`",
        "run `./hub validate-output review <file>`",
        f"re-ask that reviewer once, passing {PRINTED_LINES}",
        "when the second reply is invalid too, stop and report to the user: no repair, no guessing",
        "send `blocking` findings back to the implementer",
        "weigh each `minor` one",
        "one-line reason",
        "the latest round of each is a validated `PASS`",
    )
    for phrase in phrases:
        assert phrase in review, phrase
    positions = [review.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)
    assert review.index("`approved` once both reviewers pass") > positions[-2]
    assert old_words(review) == []


def test_gates_ship_on_eval_outputs_when_feature_step_eight_rendered(
    texts: dict[str, str],
) -> None:
    verify = step(texts[FEATURE], 8)

    assert f"Run `./hub validate-output eval <file>` on the evaluator's `{EVAL_JSON}`" in verify
    assert SHIP_RULE in verify
    # An owner-steps verdict ships after the user's confirmation, so no "only on SHIP" rule.
    assert "ship only on `SHIP`" not in verify
    assert "`SHIP` required" not in verify
    assert "on `SHIP-WITH-OWNER-STEPS` list its `owner_steps` to the user" in verify
    assert "on `NO-SHIP` send its failing `results` and `gates` back to the implementer" in verify
    assert verify.index("Act only on the validated JSON") < verify.index("**Finish**")


def test_redispatches_once_when_eval_outputs_invalid(texts: dict[str, str]) -> None:
    verify = step(texts[FEATURE], 8)

    phrases = (
        "When it is missing or the command exits non-zero, re-dispatch the evaluator once with"
        f" the same scope, the failed delivery and {PRINTED_LINES}",
        "it writes a new `<delivery>-rN` pair and the failed pair stays as evidence",
        "validate that new `-rN` JSON",
        "A second missing or invalid output stops: report it to the user, no ship.",
    )
    for phrase in phrases:
        assert phrase in verify, phrase
    positions = [verify.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)


def test_hands_back_when_eval_problem_needs_md_or_rewrites_run_out(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    phrases = (
        "Then run `./hub validate-output eval <file>`",
        "you may rewrite only the `.json` you created in this run",
        "at most two rewrites of the `.json`, then hand back with every line the command printed",
        "When a printed problem names the `.md`, or a verdict the observed results do not support,"
        " never change a result or status to make it pass: hand back with every line the command"
        " printed (`/feature` then re-dispatches you).",
    )
    for phrase in phrases:
        assert phrase in text, phrase
    positions = [text.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)
    assert text.index(phrases[-1]) < text.index("**Re-dispatch:**")


def test_names_delivery_as_file_stem_when_evaluator_rendered(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert (
        "The frontmatter's `delivery` is the file stem, `-rN` included (`delivery: abc-12-r2` in"
        " `abc-12-r2.md`)." in text
    )
    assert "delivery: abc-12 # the file stem, -rN included (abc-12-r2)" in text
    assert "its `delivery` is that stem, `-rN` included (e.g. `abc-12-r2`)" in text


def test_leaves_out_empty_gate_when_evaluator_rendered(texts: dict[str, str]) -> None:
    text = flat(texts[EVALUATOR])

    assert (
        "a gate whose command is empty is skipped: say so in the body and leave it out of `gates`"
        in text
    )
    assert (
        "a gate skipped because its command is empty is left out of `gates`, never recorded as"
        " `not-run`" in text
    )


def test_counts_bad_block_and_rounds_when_feature_step_seven_rendered(
    texts: dict[str, str],
) -> None:
    review = step(texts[FEATURE], 7)

    block = (
        "A reply with no fenced `json` block, or more than one, counts as invalid: re-ask that"
        " reviewer once, as for an invalid file."
    )
    rounds = (
        "`N` the ticket's review round, counted across all its tasks and never restarted per task,"
        " so no file is overwritten"
    )
    assert block in review
    assert rounds in review
    assert review.index(rounds) < review.index(block)
    assert review.index(block) < review.index("when the second reply is invalid too")


def test_acts_on_each_verdict_when_feature_step_eight_rendered(texts: dict[str, str]) -> None:
    verify = step(texts[FEATURE], 8)

    phrases = (
        SHIP_RULE,
        "on `SHIP-WITH-OWNER-STEPS` list its `owner_steps` to the user and stop until they"
        " confirm, with no new evaluation",
        "on `NO-SHIP` send its failing `results` and `gates` back to the implementer and, after the"
        " fix, run a fresh evaluation (a new `<delivery>-rN` pair)",
        "The re-dispatch-once budget covers only a missing or invalid eval JSON,"
        " never a `NO-SHIP`.",
    )
    for phrase in phrases:
        assert phrase in verify, phrase
    positions = [verify.index(phrase) for phrase in phrases]
    assert positions == sorted(positions)
    assert positions[-1] < verify.index("**Finish**")
