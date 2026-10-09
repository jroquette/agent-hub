"""The ``/incident`` workflow skill as the demo hub renders it (AGH-104).

What a text can prove of the skill's acceptance criteria: each step is there with its type, the
incident log keeps every hypothesis's status, investigation stays read-only, mitigation waits on
the user, a reproduction hands off to ``/fix`` and the postmortem is blameless with its sections.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document
from agent_hub.generator.placeholders import substitution_mapping
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/incident/SKILL.md"
# A numbered step: "<n>. `<type>` **<title>**".
STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*([^*]+)\*\*", re.MULTILINE)
EXPECTED_TYPES = ["human", "agent", "agent", "gate", "agent", "agent"]
NO_AI_ATTRIBUTION = 'no AI co-author trailer, no "Generated with", no 🤖'
# The nested instruction file limit of the doctor's ``instructions.size`` rule.
MAX_LINES = 80


def _rendered(config: HubConfig) -> str:
    content = {file.path: file.content for file in render_hub(config).files}[SKILL_PATH]
    assert content is not None
    return content.decode()


@pytest.fixture
def skill(demo_config: HubConfig) -> str:
    return _rendered(demo_config)


def _body(text: str) -> str:
    return text.split("\n---\n", 1)[1]


def _flat(text: str) -> str:
    return " ".join(_body(text).split())


def _step(text: str, number: int) -> str:
    """Step ``number``'s paragraph, flattened: from its heading to the next step or blank line."""
    starts = {int(match.group(1)): match.start() for match in STEP.finditer(text)}
    assert number in starts, number
    end = starts.get(number + 1, text.find("\n\n", starts[number]))
    return " ".join(text[starts[number] : end].split())


def test_marks_each_step_with_its_type_when_rendered(skill: str) -> None:
    steps = STEP.findall(skill)

    assert [int(number) for number, _, _ in steps] == list(range(1, len(EXPECTED_TYPES) + 1))
    assert [kind for _, kind, _ in steps] == EXPECTED_TYPES


def test_keeps_timestamped_log_with_hypothesis_status_when_symptom_given(skill: str) -> None:
    log, hypotheses = _step(skill, 2), _step(skill, 3)

    assert "incident log" in log
    assert "UTC timestamp" in log
    assert "`open`, `confirmed` or `killed`" in hypotheses
    assert "confirm or kill" in hypotheses


def test_stays_read_only_when_investigating(skill: str) -> None:
    text = _step(skill, 2)

    assert "read-only on the repos" in text
    assert "scratchpad" in text
    assert "throwaway worktree" in text
    assert "never on a shared branch" in text


def test_keeps_external_text_out_of_brain_when_investigating(skill: str) -> None:
    text = _step(skill, 2)

    assert "never becomes a brain note" in text
    assert "`brain/_inbox/` with `provenance: agent-from-external`" in text


def test_waits_for_user_gate_when_mitigating(skill: str) -> None:
    text = _step(skill, 4)

    assert "**Gate: the user approves the mitigation**" in text
    assert "never deploys" in text
    assert "no push to the default branch" in text
    assert "no data change" in text
    assert "`check_fast`, then its `check` (both from `hub.json`)" in text
    assert "`$?` checked" in text


def test_hands_off_with_reproduction_when_one_exists(skill: str) -> None:
    text = _step(skill, 5)

    assert "`/fix`" in text
    assert "`/feature`" in text
    assert "linked from the tracker issue" in text


def test_writes_blameless_postmortem_when_closing(skill: str) -> None:
    text = _step(skill, 6)

    assert "blameless" in text
    for section in ("Timeline", "Root cause", "Detection gap", "What fixed it", "Follow-ups"):
        assert f"*{section}*" in text, section
    assert "every follow-up becomes a tracker issue" in text
    assert "`/learn`" in text


def test_names_no_project_value_when_rendered(demo_config: HubConfig, skill: str) -> None:
    branch = substitution_mapping(demo_config)["kickoff_branch"]
    assert f"on branch {branch}:" in _flat(skill)
    # The branch shape, from hub.json, is the one project value the skill renders.
    without_branch = skill.replace(branch, "")
    for value in ("demo", "DEM", "acme", "jdoe", "Jane Doe", "@@{", "<branch_prefix>"):
        assert value not in without_branch, value
    assert "disable-model-invocation: true" in skill
    assert "authored by the user" in _flat(skill)
    assert NO_AI_ATTRIBUTION in _flat(skill)
    assert len(skill.splitlines()) <= MAX_LINES


def test_names_configured_branch_when_hub_sets_conventions() -> None:
    config = HubConfig.model_validate(a_conventions_document())
    rendered = _rendered(config)

    text = _flat(rendered)

    assert f"on branch {substitution_mapping(config)['kickoff_branch']}:" in text
    assert "`jdoe/{ISSUE}-{slug}`" in text
    assert "<branch_prefix>" not in text
    assert len(rendered.splitlines()) <= MAX_LINES
