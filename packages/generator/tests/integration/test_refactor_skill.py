"""The ``/refactor`` workflow skill as the demo hub renders it.

A behaviour-preserving change too big for ``/fix`` and too small for a spec: the text proves each
step carries its type (SPEC "Defined directions" §1), the stop rules that send work to
``/feature``, the characterization-first and batch rules, and the authorship lines.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/refactor/SKILL.md"
STEP_TYPES = ("agent", "script", "gate", "human")
# The nested instruction-file line limit of the doctor's `instructions.size` rule.
NESTED_MAX_LINES = 80

# Each step: its type, then phrases its text holds.
STEPS = {
    1: (
        "agent",
        (
            "public surface",
            "CLI output",
            "schemas",
            "import contracts",
            "`brain/_inbox/` with `provenance: agent-from-external`",
        ),
    ),
    2: ("agent", ("characterization", "own commit", "unchanged code", "never weakened")),
    3: (
        "gate",
        (
            "batch plan",
            "verification command",
            "15 non-test files",
            "passes the repo's `check` on its own",
        ),
    ),
    4: ("agent", ("worktree", "`check_fast`", "`check`", "Coverage floors", "import-linter")),
    5: ("agent", ("`quality-reviewer`", "behaviour drift", "error messages", "ordering")),
    6: ("script", ("previous batch's PR", "batch k of N", "In Review")),
}
STOP_RULES = (
    "**Stop and switch to `/feature`**",
    "adds or changes a contract",
    "`guard.ask_before_edit`",
)
SHIP_RULES = (
    'no AI co-author trailer, no "Generated with", no 🤖',
    "No push to the default branch, no force-push",
)
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*", re.MULTILINE)


@pytest.fixture
def skill_text() -> str:
    rendered = {
        file.path: file.content
        for file in render_hub(HubConfig.model_validate(a_hub_document())).files
    }
    content = rendered[SKILL_PATH]
    assert content is not None
    return content.decode("utf-8")


def _step(text: str, number: int) -> str:
    """The step's text: from its numbered line to the next numbered line or the end."""
    starts = [(int(match.group(1)), match.start()) for match in STEP_LINE.finditer(text)]
    ends = dict(zip([n for n, _ in starts], [s for _, s in starts[1:]] + [len(text)], strict=True))
    start = dict(starts)[number]
    return text[start : ends[number]]


def test_marks_each_step_with_its_type_when_skill_rendered(skill_text: str) -> None:
    typed = [(int(number), kind) for number, kind in STEP_LINE.findall(skill_text)]

    assert typed == [(number, kind) for number, (kind, _) in STEPS.items()]
    assert {kind for _, kind in typed} <= set(STEP_TYPES)


@pytest.mark.parametrize("number", sorted(STEPS))
def test_holds_step_rules_when_skill_rendered(skill_text: str, number: int) -> None:
    step = _step(skill_text, number)

    for phrase in STEPS[number][1]:
        assert phrase in step, (number, phrase)


def test_stops_for_feature_when_scope_changes_contract(skill_text: str) -> None:
    scope = _step(skill_text, 1)

    for phrase in STOP_RULES:
        assert phrase in scope, phrase


def test_sends_golden_diffs_to_pr_body_or_revert_when_batch_reviewed(skill_text: str) -> None:
    assert "the PR body explains each one, or the batch is reverted" in skill_text


def test_keeps_authorship_rules_in_pr_step_when_skill_rendered(skill_text: str) -> None:
    ship = _step(skill_text, 6)

    for phrase in SHIP_RULES:
        assert phrase in ship, phrase


def test_stays_generic_and_short_when_skill_rendered(skill_text: str) -> None:
    document = a_hub_document()

    assert "@@" not in skill_text
    assert "not written yet" not in skill_text
    assert document["project"]["name"] not in skill_text
    assert document["tracker"]["team"] not in skill_text
    for repo in document["repos"]:
        assert repo["dir"] not in skill_text
    assert len(skill_text.splitlines()) <= NESTED_MAX_LINES
