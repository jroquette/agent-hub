"""The rendered ``/adr`` workflow skill: its typed steps, stop rules and never-do lines.

The text is the contract a session follows; these tests pin what a text can prove: every step
carries its type, in order, and each rule sits in the step that applies it (the gate waits for
the pick; the write step uses the next free number, supersedes instead of editing, goes through
the guard's ask and updates the spec in the same PR; the ship step keeps the user's authorship).
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/adr/SKILL.md"
KICKOFF_PATH = "plugin/hub-workflow/skills/kickoff/SKILL.md"
KICKOFF_BRANCH = re.compile(r"branch: work on (`[^`]+`)\.")
EXPECTED_STEP_TYPES = ("human", "agent", "agent", "gate", "agent", "script")
_STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*", re.MULTILINE)
_PROJECT_VALUES = (
    "@@",
    "AGH",
    "agent-hub",
    "roquettejh",
    "jroquette",
    "José",
    "Defined directions",
    "§",
)


@pytest.fixture(scope="module")
def rendered() -> dict[str, str]:
    config = HubConfig.model_validate(a_hub_document())
    return {file.path: file.content.decode("utf-8") for file in render_hub(config).files}


@pytest.fixture(scope="module")
def skill_body(rendered: dict[str, str]) -> str:
    """The demo hub's rendered ``/adr`` skill, below its frontmatter."""
    _, _, body = rendered[SKILL_PATH].partition("\n---\n")
    return body


@pytest.fixture(scope="module")
def steps(skill_body: str) -> dict[int, str]:
    """Each numbered step's text, from its marker to the next step's (the last runs to the end)."""
    starts = list(_STEP.finditer(skill_body))
    ends = [match.start() for match in starts[1:]] + [len(skill_body)]
    return {
        int(match.group(1)): skill_body[match.start() : end]
        for match, end in zip(starts, ends, strict=True)
    }


def test_marks_each_step_with_its_type_when_rendered(skill_body: str) -> None:
    found = _STEP.findall(skill_body)

    assert [int(number) for number, _ in found] == list(range(1, len(EXPECTED_STEP_TYPES) + 1))
    assert tuple(kind for _, kind in found) == EXPECTED_STEP_TYPES


def test_files_external_sources_in_the_inbox_when_researching(steps: dict[int, str]) -> None:
    assert "`brain/_inbox/`" in steps[2]
    assert "`provenance: agent-from-external`" in steps[2]


def test_records_every_option_and_why_the_pick_wins_when_written(steps: dict[int, str]) -> None:
    assert "2–4 options" in steps[3]
    assert "every option considered with its trade-offs" in steps[5]
    assert "why the chosen one wins" in steps[5]


def test_stops_without_a_pick_when_the_gate_is_open(steps: dict[int, str]) -> None:
    assert "nothing is written until the user picks" in steps[4]


def test_stops_on_a_taken_number_when_numbering(steps: dict[int, str]) -> None:
    assert "next free number read from the folder" in steps[5]
    assert "Stop if that number is already taken" in steps[5]


def test_supersedes_without_editing_the_accepted_body_when_replacing(
    steps: dict[int, str],
) -> None:
    assert "never edit an accepted ADR's body" in steps[5]
    assert "a new ADR that supersedes it" in steps[5]
    assert "diff check" in steps[5]


def test_goes_through_the_guard_ask_when_editing_adrs(steps: dict[int, str]) -> None:
    assert "`guard.ask_before_edit`" in steps[5]
    assert "never bypass the ask" in steps[5]


def test_updates_the_spec_in_the_same_pr_when_scope_changes(steps: dict[int, str]) -> None:
    assert "updates the repo's spec" in steps[5]
    assert "in the same PR" in steps[5]


def test_checks_each_gate_exit_code_when_shipping(steps: dict[int, str]) -> None:
    assert "`check_fast`, then its `check`" in steps[6]
    assert "output redirected to a file and `$?` checked" in steps[6]


def test_keeps_the_authorship_rules_when_shipping(steps: dict[int, str]) -> None:
    assert "authored by the user" in steps[6]
    assert 'no AI co-author trailer, no "Generated with", no 🤖' in steps[6]
    assert "No push to the default branch, no force-push." in steps[6]


def test_takes_project_values_from_the_config_when_rendered(
    rendered: dict[str, str], steps: dict[int, str]
) -> None:
    kickoff_branch = KICKOFF_BRANCH.search(rendered[KICKOFF_PATH])
    assert kickoff_branch is not None

    assert f"on branch {kickoff_branch.group(1)}" in steps[5]
    assert "jdoe/" in steps[5]
    assert "`tracker.team` in `hub.json`" in steps[1]


@pytest.mark.parametrize("value", _PROJECT_VALUES)
def test_names_no_project_value_when_rendered(skill_body: str, value: str) -> None:
    assert value not in skill_body
    assert "This workflow is not written yet" not in skill_body
