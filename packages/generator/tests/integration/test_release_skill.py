"""The rendered ``/release`` skill: its typed steps, stop rules and never-do lines.

The text is what a hub's session follows, so each acceptance criterion a text can show is
checked on the demo render: the seven steps in order with their SPEC "Defined directions" §1
type, the gates it stops at, the tag it never touches and the authorship it keeps. The size
and reference rules run on the same text through ``hub doctor`` on a fresh ``hub init``.
"""

import re

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document
from agent_hub.generator.render_hub import render_hub

RELEASE_SKILL = "plugin/hub-workflow/skills/release/SKILL.md"
NESTED_LIMIT = DEFAULT_MAX_LINES["*/*"]
STEP = re.compile(r"^(\d+)\. `(agent|script|gate|human)` \*\*([^*]+)\*\*", re.MULTILINE)
STEP_TYPES = [
    (1, "script"),
    (2, "gate"),
    (3, "script"),
    (4, "agent"),
    (5, "human"),
    (6, "script"),
    (7, "agent"),
]
# Per step: the phrases its paragraph holds (the AC each one shows is named beside it).
STEP_PHRASES = {
    # AC-1: the PR list since the last tag and the proposed bump with its reason.
    1: (
        "last `v*` tag",
        "`type(scope): subject`",
        "feat → minor",
        "fix → patch",
        "major",
        "reason",
    ),
    # AC-1: the run stops at the version and SHA gate.
    2: ("full SHA", "Stop here", "confirms"),
    # AC-2: check on the confirmed SHA, never the working tree, stops with the log path.
    3: ("clean checkout of the confirmed SHA", "not the working tree", "`$?`", "log path"),
    # AC-3: the sync section computed by rendering both versions.
    4: (
        "Features",
        "Fixes",
        "What `hub sync` rewrites in every hub",
        "Doctor rules added or changed",
        "Migration steps",
        "rendering both versions",
        "never from memory",
        "notes file",
        "tag message",
    ),
    # AC-4: the user tags and pushes; the skill prints the commands only.
    5: (
        "git tag -a v<version> --cleanup=verbatim -F <notes file> <full sha>",
        "git push origin v<version>",
        "prints",
    ),
    # AC-5: the peeled SHA and the lightweight tag fail loudly.
    6: ('git ls-remote --tags origin "refs/tags/v<version>^{}"', "lightweight", "Fail loudly"),
    # AC-6: the hub PR with the pin, sync, doctor, and the shipped issues' comments.
    7: (
        "`bump-platform` as the description slug",
        "`platform.version`",
        "`./hub sync`",
        "`./hub doctor`",
        "What `hub sync` rewrites",
        "comment",
    ),
}
NEVER_DO = (
    "never creates, moves, deletes or pushes a tag",
    'no AI co-author trailer, no "Generated with", no 🤖',
    "No push to the default branch, no force-push",
    "never goes straight into `brain/`",
    "`brain/_inbox/` with `provenance: agent-from-external`",
)


def rendered_release(config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(config).files}
    content = rendered[RELEASE_SKILL]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def release_text(demo_config: HubConfig) -> str:
    return rendered_release(demo_config)


def step_paragraphs(text: str) -> dict[int, str]:
    """Each numbered step's text, up to the next step or the first blank line after it."""
    starts = list(STEP.finditer(text))
    paragraphs: dict[int, str] = {}
    for index, match in enumerate(starts):
        next_step = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        blank = text.find("\n\n", match.start())
        end = next_step if blank == -1 else min(next_step, blank)
        paragraphs[int(match.group(1))] = text[match.start() : end]
    return paragraphs


def test_types_each_step_when_release_skill_rendered(release_text: str) -> None:
    found = [(int(match.group(1)), match.group(2)) for match in STEP.finditer(release_text)]

    assert found == STEP_TYPES


@pytest.mark.parametrize("number", sorted(STEP_PHRASES))
def test_holds_step_rules_when_release_skill_rendered(release_text: str, number: int) -> None:
    paragraph = step_paragraphs(release_text)[number]

    missing = [phrase for phrase in STEP_PHRASES[number] if phrase not in paragraph]

    assert missing == [], f"step {number}"


def test_states_never_do_lines_when_release_skill_rendered(release_text: str) -> None:
    missing = [line for line in NEVER_DO if line not in release_text]

    assert missing == []


def test_stops_before_tag_when_check_or_gate_fails(release_text: str) -> None:
    paragraphs = step_paragraphs(release_text)

    assert "On failure stop and print the log path" in paragraphs[3]
    assert "Stop here" in paragraphs[2]
    assert "never pushes" in paragraphs[5]


def test_names_bump_branch_by_shape_when_hub_sets_conventions() -> None:
    config = HubConfig.model_validate(a_conventions_document())
    paragraph = step_paragraphs(rendered_release(config))[7]

    missing = [phrase for phrase in STEP_PHRASES[7] if phrase not in paragraph]

    assert missing == []
    assert "<desc>" not in paragraph
    assert "repo's own" not in paragraph


def test_fits_nested_size_limit_when_release_skill_rendered(release_text: str) -> None:
    assert len(release_text.splitlines()) <= NESTED_LIMIT


def test_names_no_project_value_when_release_skill_rendered(demo_config: HubConfig) -> None:
    document = a_conventions_document()
    config = HubConfig.model_validate(document)
    values = {
        config.project.name,
        *config.tracker.team_keys,
        *(repo.dir for repo in config.repos),
        *(repo.github for repo in config.repos),
        demo_config.project.name,
    }
    text = rendered_release(config)

    named = sorted(value for value in values if value and value in text)

    assert named == []
