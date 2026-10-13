"""The feature agents and ``/feature`` as a hub renders them: ticket plan, evals, reviews (AGH-136).

The planner records the ticket plan in ``features.json`` (S3: draft keys, ``blocked_by``,
``order``, each AC's ``ticket``) and never calls the tracker; ``/feature`` step 4 creates the
issues, fills each ``id`` and creates the "blocked by" relations (Q1). The evaluator writes one new
``evals/<delivery>.md`` per evaluation with the S6 frontmatter and never overwrites one. An
approved spec changes only through ``## Amendments`` (S9). Step 7 writes the review record that
counts a ticket as reviewed (D4). One-team and two-team hubs render the same rules.
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
FEATURE = "plugin/hub-workflow/skills/feature/SKILL.md"

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
    for path in (PLANNER, EVALUATOR, ANALYST, FEATURE):
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


def test_keeps_approved_spec_amendments_when_analyst_and_feature_rendered(texts: dict[str, str]) -> None:
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
