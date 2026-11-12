"""The owner-nudges text of the workflow skills, as configured hubs render them.

The scope tests (AGH-813, AC-33 to AC-35): ``/fix``, ``/refactor`` and ``/upgrade`` show an in-scope
and an out-of-scope list with their first plan, post both on the tracker issue (not in the PR body),
and before the PR remove or ask about each changed file outside the in-scope list. The upgrade
workflow's branch belongs to the run, so at its ``publish`` gate the session only asks the owner.
The same phrases hold in the three skills; each step is sliced by its number or its bold name.
"""

import re
from collections.abc import Callable
from typing import Any, NamedTuple

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

SKILLS = ("fix", "refactor", "upgrade")
# The nested instruction-file line limit of the doctor's `instructions.size` rule.
NESTED_MAX_LINES = DEFAULT_MAX_LINES["*/*"]

IN_SCOPE_LIST = "an in-scope list"
OUT_OF_SCOPE_LIST = "an out-of-scope list"
OUTSIDE_SCOPE = "outside the in-scope list"
REMOVE_OR_ASK = "either remove its change or ask the owner, with one reason per file"
CHANGED_FILES = "`git diff --name-only"
ON_TRACKER = "in a tracker comment on the issue, not in the PR body"
OWNER_KEEPS = "a file the owner keeps joins the in-scope list in the tracker comment"
RERUN_BEFORE_PUSH = "again before the push"

# A numbered step line, at the start of a line (indented bullets inside a step do not match).
STEP_LINE = re.compile(r"^\d+\. ", re.MULTILINE)


def _skill_path(skill: str) -> str:
    return f"plugin/hub-workflow/skills/{skill}/SKILL.md"


def _rendered_skills(document: dict[str, Any]) -> dict[str, str]:
    rendered = {
        file.path: file.content for file in render_hub(HubConfig.model_validate(document)).files
    }
    skills = {}
    for skill in SKILLS:
        content = rendered[_skill_path(skill)]
        assert content is not None, skill
        skills[skill] = content.decode("utf-8")
    return skills


@pytest.fixture(scope="module")
def demo_skills() -> dict[str, str]:
    """The three skills of the demo render, by skill name."""
    return _rendered_skills(a_hub_document())


class Slice(NamedTuple):
    """Where a part of a skill sits in its text: its start offset and its text."""

    start: int
    text: str


def _step(text: str, number: int) -> Slice:
    """A numbered step: from its line to the next numbered line or the next blank line."""
    match = re.search(rf"^{number}\. ", text, re.MULTILINE)
    assert match is not None, f"no step {number}"
    start = match.start()
    next_step = STEP_LINE.search(text, match.end())
    ends = [text.find("\n\n", start), next_step.start() if next_step else -1]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


def _by_hand(text: str, name: str) -> Slice:
    """A **By hand** item: from its ``- **<name>**`` line to the next item or blank line."""
    start = text.index(f"\n- **{name}**") + 1
    ends = [text.find("\n- **", start), text.find("\n\n", start)]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


type Locator = Callable[[str], Slice]


def at_step(number: int) -> Locator:
    return lambda text: _step(text, number)


def at_by_hand(name: str) -> Locator:
    return lambda text: _by_hand(text, name)


# The step that shows each skill's first plan.
FIRST_PLAN = {"fix": at_step(1), "refactor": at_step(1), "upgrade": at_step(2)}


class PlanCase(NamedTuple):
    """A skill's first plan: the phrase the lists come after, and phrases other steps hold."""

    skill: str
    after: str | None = None
    elsewhere: tuple[tuple[Locator, str], ...] = ()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(PlanCase("fix", after="size it against `/fix`'s limits"), id="fix-size"),
        pytest.param(
            PlanCase("refactor", elsewhere=((at_step(3), "the step 1 scope lists"),)),
            id="refactor-scope",
        ),
        pytest.param(PlanCase("upgrade"), id="upgrade-pick"),
    ],
)
def test_shows_scope_lists_when_first_plan_shown(
    demo_skills: dict[str, str], case: PlanCase
) -> None:
    text = demo_skills[case.skill]
    step = FIRST_PLAN[case.skill](text).text

    assert IN_SCOPE_LIST in step
    assert OUT_OF_SCOPE_LIST in step
    if case.after is not None:
        assert step.index(case.after) < step.index(IN_SCOPE_LIST)
    for locate, phrase in case.elsewhere:
        assert phrase in locate(text).text


class ShipCase(NamedTuple):
    """Where a skill checks the changed files, and where it opens the PR."""

    skill: str
    check_at: Locator
    pr_at: Locator
    opens_pr: str
    reruns: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            ShipCase(
                "fix", at_step(7), at_step(7), "open the PR", "run step 5 Gates again before the push"
            ),
            id="fix-ship",
        ),
        pytest.param(
            ShipCase(
                "refactor",
                at_step(5),
                at_step(6),
                "open its PR",
                "run the step 4 gates again before the push",
            ),
            id="refactor-pr",
        ),
        pytest.param(
            ShipCase(
                "upgrade",
                at_by_hand("Ship"),
                at_by_hand("Ship"),
                "open the PR",
                "run Verify again before the push",
            ),
            id="upgrade-by-hand-ship",
        ),
    ],
)
def test_checks_files_outside_scope_lists_when_pr_about_to_open(
    demo_skills: dict[str, str], case: ShipCase
) -> None:
    text = demo_skills[case.skill]
    check = case.check_at(text)
    pr = case.pr_at(text)
    opens_pr = case.opens_pr

    assert CHANGED_FILES in check.text
    assert OUTSIDE_SCOPE in check.text
    assert REMOVE_OR_ASK in check.text
    assert opens_pr in pr.text
    assert check.start + check.text.index(REMOVE_OR_ASK) < pr.start + pr.text.index(opens_pr)
    assert OWNER_KEEPS in check.text
    assert RERUN_BEFORE_PUSH in check.text
    assert case.reruns in check.text
    assert check.text.index(REMOVE_OR_ASK) < check.text.index(case.reruns)
    assert check.start + check.text.index(case.reruns) < pr.start + pr.text.index(opens_pr)


def test_asks_owner_about_files_outside_scope_lists_when_upgrade_paused_at_publish(
    demo_skills: dict[str, str],
) -> None:
    report = _step(demo_skills["upgrade"], 4).text

    assert "At `publish`, before you show that message" in report
    assert OUTSIDE_SCOPE in report
    assert "ask the owner about each one, with one reason per file" in report
    assert "Never edit the run's branch" in report
    assert OWNER_KEEPS in report


@pytest.mark.parametrize(
    ("skill", "pr_step_at", "pr_body"),
    [
        pytest.param("fix", at_step(7), "The PR body follows", id="fix"),
        pytest.param("refactor", at_step(6), "The body holds", id="refactor"),
        pytest.param("upgrade", at_by_hand("Ship"), "The PR body holds", id="upgrade"),
    ],
)
def test_posts_scope_lists_on_tracker_not_pr_body_when_lists_written(
    demo_skills: dict[str, str], skill: str, pr_step_at: Locator, pr_body: str
) -> None:
    text = demo_skills[skill]
    pr_step = pr_step_at(text).text
    # The PR-body text: from the PR body sentence to the end of its step or item.
    body_text = pr_step[pr_step.index(pr_body) :]
    body_sentences = [
        sentence for sentence in re.split(r"(?<=[.;:])\s", pr_step) if "body" in sentence
    ]

    assert ON_TRACKER in FIRST_PLAN[skill](text).text
    assert "scope list" not in body_text
    assert body_sentences
    for sentence in body_sentences:
        assert "scope list" not in sentence, sentence


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(a_hub_document, id="demo"),
        pytest.param(a_two_team_document, id="two_teams"),
        pytest.param(a_conventions_document, id="conventions"),
    ],
)
def test_scope_lists_add_no_placeholder_or_hub_value_when_hub_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    source = document()
    tracker = source["tracker"]
    teams = tracker.get("teams") or [tracker["team"]]
    values = [*teams, source["project"]["name"], *(repo["dir"] for repo in source["repos"])]

    for skill, text in _rendered_skills(source).items():
        assert "@@" not in text, skill
        for value in values:
            assert re.search(rf"\b{re.escape(value)}\b", text) is None, (skill, value)
        assert len(text.splitlines()) <= NESTED_MAX_LINES, skill
