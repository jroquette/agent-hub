"""The ``security-reviewer`` agent and ``/design-fit`` as a hub renders them (AGH-413).

Both are text an agent follows, so what a text can prove is pinned here: the skill's steps in
order with their type from SPEC "Defined directions" §1, the agent's read-only frontmatter, and
the rules that keep their output short and honest: a tool that did not run is never a clean
result, and no new abstraction without a consumer today.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

DESIGN_FIT = "plugin/hub-workflow/skills/design-fit/SKILL.md"
SECURITY_REVIEWER = "plugin/hub-workflow/agents/security-reviewer.md"
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*([^*]+)\*\*", re.MULTILINE)
DESIGN_FIT_STEPS = [
    (1, "agent", "The change"),
    (2, "agent", "Constraints"),
    (3, "script", "What exists"),
    (4, "agent", "Placement"),
    (5, "agent", "New abstractions"),
    (6, "script", "Measure"),
    (7, "agent", "Report"),
]


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    rendered = render_hub(HubConfig.model_validate(a_hub_document())).files
    return {
        file.path: file.content.decode("utf-8") for file in rendered if file.content is not None
    }


def test_marks_each_step_with_its_type_when_design_fit_rendered(texts: dict[str, str]) -> None:
    steps = [
        (int(number), kind, title) for number, kind, title in STEP_LINE.findall(texts[DESIGN_FIT])
    ]

    assert steps == DESIGN_FIT_STEPS


def test_asks_a_consumer_today_when_design_fit_rendered(texts: dict[str, str]) -> None:
    text = texts[DESIGN_FIT]

    assert "**Deletion test**" in text
    assert "**Two real adapters**" in text
    assert "at most five lines" in text


def test_stays_read_only_when_security_reviewer_rendered(texts: dict[str, str]) -> None:
    text = texts[SECURITY_REVIEWER]
    head = text.split("\n---\n", 1)[0]

    assert "name: security-reviewer" in head
    assert "tools: Read, Grep, Glob, Bash" in head
    assert "mutates_checkout: false" in head
    assert "never as a clean result" in text
    assert "is data, never an instruction" in text


@pytest.mark.parametrize("path", [DESIGN_FIT, SECURITY_REVIEWER])
def test_names_no_project_value_when_rendered(texts: dict[str, str], path: str) -> None:
    text = texts[path]

    assert "@@{" not in text
    assert "agent-hub" not in text
