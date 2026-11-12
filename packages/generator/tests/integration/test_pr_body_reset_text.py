"""Every rendered skill step that opens a pull request says to set the PR's body again.

A cloud session's environment appends an attribution footer to a PR's body when the PR is created,
and the hub CI's authorship step then fails the PR; an edit with the same text removes the footer.
So the line that opens a PR also says to set the body again right after the create, to read the PR
back, and to tell the user once when the body read back still carries AI attribution.
``CLAUDE.md``, loaded even where the skills are not, says the same in its note on session
instructions.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

SKILLS = "plugin/hub-workflow/skills/"
FRONT_MATTER_END = "\n---\n"
# What the line says: the body set again (one PR, or each of a step's several), the read back,
# and the one message to the user.
RESET_PHRASES = (
    re.compile(r"set (?:the|each) PR's body again with the same text"),
    re.compile(r"read the PR back"),
    re.compile(r"tell the user once, naming the PR"),
)
# The words a step opens a PR with. "opened" is left out: it tells of a PR another skill opened.
OPENS_PR = re.compile(r"`gh pr create\b|\bopens? (?:the|its) PR\b")
# The skills whose steps open a PR in those words today: a scan that finds none of them is broken.
EXPECTED_SKILLS = {"adr", "feature", "fix", "implement", "refactor", "release", "upgrade"}
# Each line that opens a PR: its skill, and words only that line of the skill holds.
OPENING_LINES = [
    ("adr", "**Ship**"),
    ("feature", "**Records PR**"),
    ("feature", "**Finish**"),
    ("fix", "**Ship**"),
    ("handoff", "create a branch + PR in the hub"),
    ("implement", "10. **PR**"),
    ("implement", "- Step 10:"),
    ("onboard", "through a hub PR the user merges"),
    ("onboard", "Commits and PRs in steps 6 and 7"),
    ("refactor", "**PR**"),
    ("release", "open the version PR yourself"),
    ("release", "open the PR on the hub repo"),
    ("retro", "the note goes on branch"),
    ("upgrade", "**Ship**"),
]
CLAUDE_PHRASES = (
    "when the environment appends a PR footer, set the PR's body again with the same text"
    " right after the create and read it back",
    "tell the owner if it stays",
)


def skill_lines(config: HubConfig) -> list[tuple[str, str]]:
    """Each rendered skill line after its file's front matter (a description may say the skill
    opens a PR), with its skill."""
    found: list[tuple[str, str]] = []
    for file in render_hub(config).files:
        if not (file.path.startswith(SKILLS) and file.path.endswith(".md")):
            continue
        skill = file.path.removeprefix(SKILLS).split("/", 1)[0]
        text = file.content.decode("utf-8")
        body = text.partition(FRONT_MATTER_END)[2] if text.startswith("---\n") else text
        found.extend((skill, line) for line in body.splitlines())
    return found


def missing_phrases(line: str) -> list[str]:
    return [phrase.pattern for phrase in RESET_PHRASES if phrase.search(line) is None]


@pytest.mark.parametrize(("skill", "words"), OPENING_LINES)
def test_says_to_set_body_again_when_skill_line_opens_pr(
    demo_config: HubConfig, skill: str, words: str
) -> None:
    lines = [line for name, line in skill_lines(demo_config) if name == skill and words in line]

    assert len(lines) == 1, lines
    assert missing_phrases(lines[0]) == []


@pytest.mark.parametrize(
    "document",
    [a_hub_document, a_two_team_document, a_conventions_document],
    ids=["demo", "two_teams", "conventions"],
)
def test_says_to_set_body_again_on_same_line_when_skill_names_pr_create(
    document: Callable[[], dict[str, Any]],
) -> None:
    lines = skill_lines(HubConfig.model_validate(document()))
    opening = [(skill, line) for skill, line in lines if OPENS_PR.search(line) is not None]

    missing = [(skill, phrase) for skill, line in opening for phrase in missing_phrases(line)]

    assert {skill for skill, _ in opening} == EXPECTED_SKILLS
    assert missing == []


def test_says_to_set_body_again_when_claude_notes_rendered(demo_config: HubConfig) -> None:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    claude = " ".join(rendered["CLAUDE.md"].decode("utf-8").split())

    assert [phrase for phrase in CLAUDE_PHRASES if phrase not in claude] == []
    assert "you cannot remove" not in claude
