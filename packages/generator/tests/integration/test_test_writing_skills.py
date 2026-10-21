"""The ``test-writer`` agent and ``/property-based-testing`` as a hub renders them (AGH-411).

Both are text an agent follows, so what a text can prove is pinned here: the skill's steps in
order with their type from SPEC "Defined directions" §1, the agent's input boundary (the ACs and
the public interfaces, never the module under change), and that no project value is written into
either.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

PROPERTY_TESTS = "plugin/hub-workflow/skills/property-based-testing/SKILL.md"
TEST_WRITER = "plugin/hub-workflow/agents/test-writer.md"
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*([^*]+)\*\*", re.MULTILINE)
PROPERTY_TESTS_STEPS = [
    (1, "script", "Scope"),
    (2, "agent", "Claims"),
    (3, "agent", "Properties"),
    (4, "agent", "Write"),
    (5, "script", "Run"),
    (6, "agent", "Reflect"),
    (7, "agent", "Report"),
]


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    rendered = render_hub(HubConfig.model_validate(a_hub_document())).files
    return {
        file.path: file.content.decode("utf-8") for file in rendered if file.content is not None
    }


def test_marks_each_step_with_its_type_when_property_skill_rendered(
    texts: dict[str, str],
) -> None:
    steps = [
        (int(number), kind, title) for number, kind, title in STEP_LINE.findall(texts[PROPERTY_TESTS])
    ]

    assert steps == PROPERTY_TESTS_STEPS


def test_keeps_no_property_a_valid_outcome_when_property_skill_rendered(
    texts: dict[str, str],
) -> None:
    text = texts[PROPERTY_TESTS]

    assert "**No good property** is a valid outcome" in text
    assert "adding the library is the user's decision" in text


def test_reads_criteria_not_implementation_when_test_writer_rendered(
    texts: dict[str, str],
) -> None:
    text = texts[TEST_WRITER]
    head = text.split("\n---\n", 1)[0]

    assert "name: test-writer" in head
    assert "tools: Read, Grep, Glob, Bash, Write" in head
    assert "**Never read** the body of the module under change" in text
    assert "at most three tests per AC" in text


@pytest.mark.parametrize("path", [PROPERTY_TESTS, TEST_WRITER])
def test_names_no_project_value_when_rendered(texts: dict[str, str], path: str) -> None:
    text = texts[path]

    assert "@@{" not in text
    assert "agent-hub" not in text
