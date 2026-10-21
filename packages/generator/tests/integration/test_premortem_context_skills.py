"""``/premortem`` and ``/context-audit`` as a hub renders them (AGH-414).

Both are text an agent follows, so what a text can prove is pinned here: each skill's steps in
order with their type from SPEC "Defined directions" §1, and that both only report: neither
edits a file, and the context audit labels its numbers as estimates.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILLS = "plugin/hub-workflow/skills"
PREMORTEM = f"{SKILLS}/premortem/SKILL.md"
CONTEXT_AUDIT = f"{SKILLS}/context-audit/SKILL.md"
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*([^*]+)\*\*", re.MULTILINE)
PREMORTEM_STEPS = [
    (1, "agent", "The decision"),
    (2, "agent", "It failed"),
    (3, "agent", "Rank"),
    (4, "agent", "Experiments"),
    (5, "agent", "Report"),
    (6, "gate", "The user decides"),
]
CONTEXT_AUDIT_STEPS = [
    (1, "script", "Inventory"),
    (2, "script", "Estimate"),
    (3, "agent", "Flag"),
    (4, "agent", "Report"),
    (5, "gate", "The user picks"),
]


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    rendered = render_hub(HubConfig.model_validate(a_hub_document())).files
    return {
        file.path: file.content.decode("utf-8") for file in rendered if file.content is not None
    }


@pytest.mark.parametrize(
    ("path", "steps"),
    [(PREMORTEM, PREMORTEM_STEPS), (CONTEXT_AUDIT, CONTEXT_AUDIT_STEPS)],
)
def test_marks_each_step_with_its_type_when_rendered(
    texts: dict[str, str], path: str, steps: list[tuple[int, str, str]]
) -> None:
    found = [(int(number), kind, title) for number, kind, title in STEP_LINE.findall(texts[path])]

    assert found == steps


def test_asks_an_experiment_that_can_fail_when_premortem_rendered(texts: dict[str, str]) -> None:
    text = texts[PREMORTEM]

    assert "**cheapest experiment**" in text
    assert "no percentages" in text


def test_labels_numbers_as_estimates_when_context_audit_rendered(texts: dict[str, str]) -> None:
    text = texts[CONTEXT_AUDIT]

    assert "an **estimate**" in text
    assert "`/context`" in text


@pytest.mark.parametrize("path", [PREMORTEM, CONTEXT_AUDIT])
def test_edits_nothing_when_rendered(texts: dict[str, str], path: str) -> None:
    text = texts[path]

    assert "edits nothing" in text
    assert "@@{" not in text
