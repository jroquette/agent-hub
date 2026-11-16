"""The ``/upgrade`` workflow skill as the demo hub renders it.

What the text can prove: each step and its type (SPEC "Defined directions" §1), that a uv or npm
package starts the built-in ``upgrade`` workflow with the inputs it declares (AGH-484), that the
old steps stay as the "By hand" fallback, the stop rules, the never-do lines, the PR body's
contents and that the text stays generic and unattributed.
"""

import re

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.doctor.text_rules import ATTRIBUTIONS
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

SKILL_PATH = "plugin/hub-workflow/skills/upgrade/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "upgrade" / "upgrade.yaml"
# The steps in order: (title, type).
STEPS = (
    ("Inventory", "script"),
    ("Pick", "gate"),
    ("Run", "script"),
    ("Report", "agent"),
    ("Merge", "human"),
)
# The old steps, kept as the by-hand fallback: (title, type, old step number).
BY_HAND = (
    ("Changelog review", "agent", 2),
    ("Bump", "agent", 4),
    ("Verify", "script", 5),
    ("Ship", "script", 6),
)
STEP_LINE = re.compile(r"^(\d+)\. \*\*([^*]+)\*\* \(`(agent|script|gate|human)`\):", re.MULTILINE)
ITEM_LINE = re.compile(
    r"^- \*\*([^*]+)\*\* \(`(agent|script|gate|human)`, step (\d+)\):", re.MULTILINE
)
FALLBACK = (
    "If `./hub workflow run` is not available, or the bump is a toolchain, plugin pin, Docker"
    " digest, GitHub Action or lock maintenance, follow **By hand** below."
)


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
    following += [skill.index("\n## ", start)] if "\n## " in skill[start:] else []
    end = min(following) if following else len(skill)
    return skill[start:end]


def _by_hand(skill: str) -> str:
    """The "By hand" section, up to the stop rules after it."""
    start = skill.index("\n## By hand\n")
    return skill[start : skill.index("\nStop and say so", start)]


def _item(skill: str, title: str) -> str:
    """The text of one by-hand item, up to the next item or the section's end."""
    section = _by_hand(skill)
    start = section.index(f"- **{title}**")
    following = [m.start() for m in ITEM_LINE.finditer(section) if m.start() > start]
    return section[start : following[0] if following else len(section)]


def test_marks_each_step_with_its_type_when_skill_rendered(skill: str) -> None:
    found = [(m.group(2), m.group(3)) for m in STEP_LINE.finditer(skill)]
    numbers = [int(m.group(1)) for m in STEP_LINE.finditer(skill)]
    items = [(m.group(1), m.group(2), int(m.group(3))) for m in ITEM_LINE.finditer(skill)]

    assert found == list(STEPS)
    assert numbers == list(range(1, len(STEPS) + 1))
    assert items == list(BY_HAND)


def test_keeps_frontmatter_when_skill_rendered(skill: str) -> None:
    head = skill.split("---\n")[1]

    assert head.startswith("name: upgrade\n")
    assert "disable-model-invocation: true\n" in head
    assert "not written yet" not in skill


def test_stops_at_gate_with_inventory_when_no_target_given(skill: str) -> None:
    inventory = _step(skill, "Inventory")

    for shown in ("current", "latest", "`.claude-plugin/marketplace.json`", "toolchain"):
        assert shown in inventory, shown
    # Pick is step 2 now that the workflow runs the old steps 2, 4, 5 and 6.
    assert "No target: print the inventory and stop at the step 2 gate" in inventory
    assert "the one target named" in inventory


def test_starts_the_upgrade_workflow_with_its_inputs_when_skill_rendered(skill: str) -> None:
    run = _step(skill, "Run")
    [line] = [line for line in run.splitlines() if "`./hub workflow run upgrade" in line]
    command = line[line.index("`./hub workflow run upgrade") :]
    command = command[: command.index("`", 1) + 1]
    inputs = load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document["inputs"]

    assert command.endswith(" --live`"), command
    for name in inputs:
        assert f"--input {name}=" in command, name
    assert "output redirected to a file and `$?` checked" in run
    assert "Without `--live` it only prints what would run" in run


def test_falls_back_to_the_steps_by_hand_when_workflow_run_unavailable(skill: str) -> None:
    run = _step(skill, "Run")

    assert FALLBACK in run
    assert skill.index(FALLBACK) < skill.index("\n## By hand\n")
    assert "steps 2, 4, 5 and 6" in _by_hand(skill)


def test_names_the_gates_and_outcomes_when_skill_rendered(skill: str) -> None:
    report = _step(skill, "Report")

    for named in (
        "`size`",
        "`publish`",
        "`./hub workflow approve <run>`",
        "`./hub workflow reject <run>`",
        "Never decide it yourself",
        "`blocked`",
        "`delivered`",
        "`.agent-runs/workflows/<run>/records.jsonl`",
        '`"node": "report"`',
        "the failing check",
        "writes nothing to the tracker",
    ):
        assert named in report, named


def test_resolves_a_renovate_pr_into_package_and_version_when_pick_given_one(skill: str) -> None:
    pick = _step(skill, "Pick")

    assert "`gh pr view <n> --json title,headRefName`" in pick
    assert "one run per package" in pick
    assert "lock-maintenance one goes by hand" in pick
    # Each value is checked against the shapes bump.py accepts before it enters the command.
    for shape in (
        "`^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$`",
        "`^(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]{0,213}$`",
        "`^[0-9]+(\\.[0-9]+){0,3}$`",
        "Anything else: stop and say so",
    ):
        assert shape in pick, shape


def test_lists_breaking_changes_in_pr_body_when_target_given(skill: str) -> None:
    review = _item(skill, "Changelog review")
    ship = _item(skill, "Ship")

    assert "`path:line`" in review
    assert "none found" in review
    for listed in ("from → to", "breaking change", "how each was handled", "changelog links"):
        assert listed in ship, listed
    assert "none were found and which changelog was read" in ship


def test_fails_own_check_when_lockfile_hand_edited(skill: str) -> None:
    bump = _item(skill, "Bump")
    verify = _item(skill, "Verify")

    assert "never hand-edit a lockfile" in bump
    # The diff runs against the bump's own commit,
    # so the tool's fresh output is not mistaken for a hand edit.
    assert "Commit the bump" in bump
    assert "before step 5" in bump
    assert "lockfile check first, on the committed branch with a clean tree" in verify
    assert "`git diff --exit-code` on the lockfiles against that commit" in verify
    assert "lockfile check" in verify
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
    review = _item(skill, "Changelog review")

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
    # A tool-specific command is only ever an example of the repo's own tooling.
    for line in lines:
        if "`uv " in line:
            assert "e.g." in line or "or the equivalent" in line, line
    assert "@@" not in skill


# AGH-480: the owner sees what a gate asks before answering it.
GATE_RECORDS = "`.agent-runs/workflows/<run>/records.jsonl`"
GATE_MESSAGE = f'the `message` of the last `"event": "gate"` line of {GATE_RECORDS}'


def test_shows_the_gate_message_before_the_owner_answers_when_skill_rendered(skill: str) -> None:
    report = " ".join(_step(skill, "Report").split())

    assert GATE_MESSAGE in report
    assert report.index(GATE_MESSAGE) < report.index("`./hub workflow approve <run>`")
