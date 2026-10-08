"""The rendered ``/adr`` workflow skill: its typed steps, stop rules and never-do lines.

The text is the contract a session follows; these tests pin what a text can prove: every step
carries its type (SPEC "Defined directions" §1), in order, and the rules that keep a decision
honest (every option with its trade-offs, the next free number, supersede never edit, the
guard's ask, the spec in the same PR, the user's authorship).
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/adr/SKILL.md"
EXPECTED_STEP_TYPES = ("human", "agent", "agent", "gate", "agent", "script")
_STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*", re.MULTILINE)


@pytest.fixture
def skill_body() -> str:
    """The demo hub's rendered ``/adr`` skill, below its frontmatter."""
    rendered = {
        file.path: file.content
        for file in render_hub(HubConfig.model_validate(a_hub_document())).files
    }
    content = rendered[SKILL_PATH]
    assert content is not None
    text = content.decode("utf-8")
    _, _, body = text.partition("\n---\n")
    return body


def test_marks_each_step_with_its_type_when_rendered(skill_body: str) -> None:
    steps = _STEP.findall(skill_body)

    assert [int(number) for number, _ in steps] == list(range(1, len(EXPECTED_STEP_TYPES) + 1))
    assert tuple(kind for _, kind in steps) == EXPECTED_STEP_TYPES


def test_records_every_option_and_why_the_pick_wins_when_written(skill_body: str) -> None:
    assert "2–4 options" in skill_body
    assert "every option considered with its trade-offs" in skill_body
    assert "why the chosen one wins" in skill_body


def test_stops_on_a_taken_number_when_numbering(skill_body: str) -> None:
    assert "next free number read from the folder" in skill_body
    assert "Stop if that number is already taken" in skill_body


def test_supersedes_without_editing_the_accepted_body_when_replacing(skill_body: str) -> None:
    assert "never edit an accepted ADR's body" in skill_body
    assert "a new ADR that supersedes it" in skill_body
    assert "diff check" in skill_body


def test_goes_through_the_guard_ask_when_editing_adrs(skill_body: str) -> None:
    assert "`guard.ask_before_edit`" in skill_body
    assert "never bypass the ask" in skill_body


def test_updates_the_spec_in_the_same_pr_when_scope_changes(skill_body: str) -> None:
    assert "Defined directions" in skill_body
    assert "in the same PR" in skill_body


def test_keeps_the_authorship_rules_when_shipping(skill_body: str) -> None:
    assert "authored by the user" in skill_body
    assert 'no AI co-author trailer, no "Generated with", no 🤖' in skill_body
    assert "No push to the default branch, no force-push." in skill_body


def test_stops_without_a_pick_when_the_gate_is_open(skill_body: str) -> None:
    assert "nothing is written until the user picks" in skill_body


def test_names_no_project_value_when_rendered(skill_body: str) -> None:
    assert "@@" not in skill_body
    assert "AGH" not in skill_body
    assert "agent-hub" not in skill_body
    assert "This workflow is not written yet" not in skill_body
