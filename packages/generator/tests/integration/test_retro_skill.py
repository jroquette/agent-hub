"""The ``/retro`` workflow skill as a hub renders it: its typed steps, stop rules and limits.

The text is the contract an agent follows, so the checks read the rendered ``SKILL.md`` of the
demo hub: each step with its type (SPEC "Defined directions" §1), the evidence rule, the
privacy rule, the missing-source rule, what the skill never edits, and that it stays generic.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

RETRO_PATH = "plugin/hub-workflow/skills/retro/SKILL.md"
STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*([^*]+)\*\*", re.MULTILINE)
EXPECTED_STEPS = (
    ("1", "script", "Gather"),
    ("2", "agent", "Find where the flow gets stuck"),
    ("3", "agent", "Propose at most 5 changes"),
    ("4", "gate", "The user picks"),
    ("5", "script", "File the chosen ones"),
    ("6", "agent", "Record"),
)


@pytest.fixture(scope="module")
def retro_text() -> str:
    config = HubConfig.model_validate(a_hub_document())
    rendered = {file.path: file.content for file in render_hub(config).files}
    return rendered[RETRO_PATH].decode("utf-8")


def body_of(text: str) -> str:
    return text.split("\n---\n", 1)[1]


def test_lists_six_typed_steps_in_order_when_hub_rendered(retro_text: str) -> None:
    assert tuple(STEP.findall(retro_text)) == EXPECTED_STEPS


def test_names_every_data_source_when_hub_rendered(retro_text: str) -> None:
    for source in (
        "make mine",
        "make retro",
        "./hub stats",
        ".agent-runs/*.jsonl",
        "review rounds",
        "brain/_inbox/",
        "brain/journal/",
    ):
        assert source in retro_text, source


def test_drops_proposals_without_evidence_when_hub_rendered(retro_text: str) -> None:
    assert "A proposal without evidence is dropped" in retro_text
    assert "at most 5" in retro_text


def test_keeps_metrics_aggregated_when_hub_rendered(retro_text: str) -> None:
    assert "local and aggregated" in retro_text
    assert "No ranking or comparison of individual developers" in retro_text


def test_files_issues_instead_of_editing_when_hub_rendered(retro_text: str) -> None:
    never = next(line for line in retro_text.splitlines() if line.startswith("Never:"))
    for item in ("a skill", "an agent", "a guard rule", "the structure of `brain/`"):
        assert item in never, item
    assert "`/learn`" in retro_text
    assert "`/learn promote`" in retro_text


def test_names_missing_sources_and_goes_on_when_hub_rendered(retro_text: str) -> None:
    assert "is **missing**: list it with the reason" in retro_text
    assert "go on with the rest" in retro_text
    assert "Every source missing: say so and stop." in retro_text


def test_waits_for_the_user_before_filing_when_hub_rendered(retro_text: str) -> None:
    assert "Nothing is filed before the answer." in retro_text


def test_keeps_authorship_with_the_user_when_hub_rendered(retro_text: str) -> None:
    for rule in (
        "authored by the user",
        "no AI co-author trailer",
        'no "Generated with"',
        "no push to the default branch, no force-push",
    ):
        assert rule in retro_text, rule


def test_names_no_project_value_when_hub_rendered(retro_text: str) -> None:
    body = body_of(retro_text)
    for value in ("demo", "acme", "jdoe", "Jane Doe"):
        assert value not in body, value
    assert re.search(r"\b(?:DEM|AGH)\b", body) is None
