"""``/test-strength`` as a hub renders it (AGH-412).

The skill is text an agent follows, so what a text can prove is pinned here: its steps in order
with their type from SPEC "Defined directions" §1, its tool reference next to it, and the rules
that keep it from growing the suite: no score target, no test deleted, no mutation by hand.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILL = "plugin/hub-workflow/skills/test-strength/SKILL.md"
TOOLS = "plugin/hub-workflow/skills/test-strength/references/tools.md"
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*([^*]+)\*\*", re.MULTILINE)
STEPS = [
    (1, "script", "Scope"),
    (2, "script", "Run"),
    (3, "agent", "Classify"),
    (4, "agent", "Redundancy"),
    (5, "agent", "Report"),
    (6, "gate", "The user picks"),
]


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    rendered = render_hub(HubConfig.model_validate(a_hub_document())).files
    return {
        file.path: file.content.decode("utf-8") for file in rendered if file.content is not None
    }


def test_marks_each_step_with_its_type_when_rendered(texts: dict[str, str]) -> None:
    steps = [(int(number), kind, title) for number, kind, title in STEP_LINE.findall(texts[SKILL])]

    assert steps == STEPS


def test_links_tool_reference_when_rendered(texts: dict[str, str]) -> None:
    assert "[references/tools.md](references/tools.md)" in texts[SKILL]
    assert TOOLS in texts


def test_keeps_suite_from_growing_when_rendered(texts: dict[str, str]) -> None:
    text = texts[SKILL]

    assert "No score target" in text
    assert "never deletes a test" in text
    assert "never apply a mutation by hand" in text
    assert "a timeout is **inconclusive**" in text
