"""The ``/upgrade`` workflow skill as the demo hub renders it.

What the text can prove: each step and its type (SPEC "Defined directions" §1), the stop rules,
the never-do lines, the PR body's contents and that the text stays generic and unattributed.
"""

import re

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.doctor.text_rules import ATTRIBUTIONS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/upgrade/SKILL.md"
# The steps in order: (title, type).
STEPS = (
    ("Inventory", "script"),
    ("Changelog review", "agent"),
    ("Pick", "gate"),
    ("Bump", "agent"),
    ("Verify", "script"),
    ("Ship", "script"),
    ("Merge", "human"),
)
STEP_LINE = re.compile(r"^(\d+)\. \*\*([^*]+)\*\* \(`(agent|script|gate|human)`\):", re.MULTILINE)


@pytest.fixture
def skill(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[SKILL_PATH]
    assert content is not None
    return content.decode("utf-8")


def _step(skill: str, title: str) -> str:
    """The text of one numbered step, up to the next numbered step or section."""
    start = skill.index(f"**{title}**")
    following = [m.start() for m in STEP_LINE.finditer(skill) if m.start() > start]
    end = following[0] if following else len(skill)
    return skill[start:end]


def test_marks_each_step_with_its_type_when_skill_rendered(skill: str) -> None:
    found = [(m.group(2), m.group(3)) for m in STEP_LINE.finditer(skill)]
    numbers = [int(m.group(1)) for m in STEP_LINE.finditer(skill)]

    assert found == list(STEPS)
    assert numbers == list(range(1, len(STEPS) + 1))


def test_keeps_frontmatter_when_skill_rendered(skill: str) -> None:
    head = skill.split("---\n")[1]

    assert head.startswith("name: upgrade\n")
    assert "disable-model-invocation: true\n" in head
    assert "not written yet" not in skill


def test_stops_at_gate_with_inventory_when_no_target_given(skill: str) -> None:
    inventory = _step(skill, "Inventory")

    for shown in ("current", "latest", "`.claude-plugin/marketplace.json`", "toolchain"):
        assert shown in inventory, shown
    assert "No target: print the inventory and stop at the step 3 gate" in inventory
    assert "the one target named" in inventory


def test_lists_breaking_changes_in_pr_body_when_target_given(skill: str) -> None:
    review = _step(skill, "Changelog review")
    ship = _step(skill, "Ship")

    assert "`path:line`" in review
    assert "none found" in review
    for listed in ("from → to", "breaking change", "how each was handled", "changelog links"):
        assert listed in ship, listed
    assert "none were found and which changelog was read" in ship


def test_fails_own_check_when_lockfile_hand_edited(skill: str) -> None:
    bump = _step(skill, "Bump")
    verify = _step(skill, "Verify")

    assert "never hand-edit a lockfile" in bump
    assert "lockfile check" in verify
    assert "`git diff --exit-code`" in verify
    assert "a hand edit: stop" in verify
    assert "`claude plugin validate .`" in verify
    assert verify.index("lockfile check") < verify.index("`check_fast`") < verify.index("`check`")


def test_isolates_major_and_toolchain_bumps_when_grouping(skill: str) -> None:
    pick = _step(skill, "Pick")

    assert "major-version bump" in pick
    assert "toolchain change" in pick
    assert "its own PR" in pick
    assert "`docs/SPEC.md` or a new ADR in the same PR" in pick


def test_keeps_fetched_text_out_of_brain_when_changelog_read(skill: str) -> None:
    review = _step(skill, "Changelog review")

    assert "`brain/_inbox/`" in review
    assert "`provenance: agent-from-external`" in review
    assert "never straight into `brain/`" in review


def test_lists_stop_rules_and_never_do_lines_when_skill_rendered(skill: str) -> None:
    for rule in (
        "Stop and say so",
        "the ticket cannot be read",
        "no changelog",
        "the user picks nothing",
        "a gate stays red",
    ):
        assert rule in skill, rule
    for never in (
        "Never hand-edit a lockfile",
        "never copy fetched text into `brain/`",
        "never mix a major-version or toolchain bump with other upgrades",
        "never weaken an assertion or add a skip marker",
        "No push to the default branch, no force-push",
    ):
        assert never in skill, never


def test_follows_workflow_rules_when_skill_rendered(skill: str) -> None:
    lines = skill.splitlines()

    assert len(lines) <= DEFAULT_MAX_LINES["*/*"]
    for shape in ATTRIBUTIONS:
        assert not any(shape.matches(line) for line in lines), shape.kind
    for authorship in ("authored by the user", "no AI co-author trailer", 'no "Generated with"'):
        assert authorship in skill, authorship
    for project_value in ("demo", "DEM-", "acme", "Jane Doe"):
        assert project_value not in skill, project_value
    assert "@@" not in skill
