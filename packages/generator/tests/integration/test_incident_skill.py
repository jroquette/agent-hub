"""The ``/incident`` workflow skill as the demo hub renders it (AGH-104).

What a text can prove of the skill's acceptance criteria: each step is there with its type, the
incident log keeps every hypothesis's status, investigation stays read-only, mitigation waits on
the user, a reproduction hands off to ``/fix`` and the postmortem is blameless with its sections.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/incident/SKILL.md"
# A numbered step: "<n>. `<type>` **<title>**".
STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*([^*]+)\*\*", re.MULTILINE)
EXPECTED_TYPES = ["human", "agent", "agent", "gate", "agent", "agent"]
# The nested instruction file limit of the doctor's ``instructions.size`` rule.
MAX_LINES = 80


@pytest.fixture
def skill(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[SKILL_PATH]
    assert content is not None
    return content.decode()


def _body(text: str) -> str:
    return text.split("\n---\n", 1)[1]


def _flat(text: str) -> str:
    return " ".join(_body(text).split())


def test_marks_each_step_with_its_type_when_rendered(skill: str) -> None:
    steps = STEP.findall(skill)

    assert [int(number) for number, _, _ in steps] == list(range(1, len(EXPECTED_TYPES) + 1))
    assert [kind for _, kind, _ in steps] == EXPECTED_TYPES


def test_keeps_timestamped_log_with_hypothesis_status_when_symptom_given(skill: str) -> None:
    text = _flat(skill)

    assert "incident log" in text
    assert "timestamp" in text
    assert "`open`, `confirmed` or `killed`" in text
    assert "confirm or kill" in text


def test_stays_read_only_when_investigating(skill: str) -> None:
    text = _flat(skill)

    assert "read-only" in text
    assert "scratchpad" in text
    assert "throwaway worktree" in text
    assert "never on a shared branch" in text


def test_waits_for_user_gate_when_mitigating(skill: str) -> None:
    text = _flat(skill)

    assert "**Gate: the user approves the mitigation**" in text
    assert "never deploys" in text
    assert "no push to the default branch" in text
    assert "no data change" in text


def test_hands_off_with_reproduction_when_one_exists(skill: str) -> None:
    text = _flat(skill)

    assert "`/fix`" in text
    assert "`/feature`" in text
    assert "linked from the tracker issue" in text


def test_writes_blameless_postmortem_when_closing(skill: str) -> None:
    text = _flat(skill)

    assert "blameless" in text
    for section in ("Timeline", "Root cause", "Detection gap", "What fixed it", "Follow-ups"):
        assert f"*{section}*" in text, section
    assert "every follow-up becomes a tracker issue" in text
    assert "`/learn`" in text


def test_names_no_project_value_when_rendered(skill: str) -> None:
    for value in ("demo", "DEM", "acme", "jdoe", "Jane Doe", "@@{"):
        assert value not in skill, value
    assert "disable-model-invocation: true" in skill
    assert "authored by the user" in _flat(skill)
    assert len(skill.splitlines()) <= MAX_LINES
