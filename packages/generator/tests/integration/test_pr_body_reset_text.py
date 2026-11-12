"""Every rendered skill step that opens a pull request says to set the PR's body again.

A cloud session's environment appends an attribution footer to a PR's body when the PR is created,
and the hub CI's authorship step then fails the PR. An edit with the same text through the
session's GitHub tools removes the footer; an edit through ``gh`` gets a footer again there.
So the line that opens a PR also says to set the body again right after the create, through those
tools when the session has them, to read the PR back, and to tell the user once when the body read
back still carries AI attribution. ``CLAUDE.md``, loaded even where the skills are not, says the
same in its note on session instructions.

A workflow run's ``pr`` step sets the body again through ``gh`` and warns when the footer stays, so
a skill that starts such a run says what the session does with that warning.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.rendered_file import RenderedFile
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

SKILLS = "plugin/hub-workflow/skills/"
WORKFLOWS = "workflows/"
FRONT_MATTER_END = "\n---\n"
# What the line says: the body set again (one PR, or each of a step's several), with which
# tools, the read back, and the one message to the user.
RESET_PHRASES = (
    re.compile(r"set (?:the|each) PR's body again with the same text"),
    re.compile(r"through the session's GitHub tools"),
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
    " through the session's GitHub tools right after the create and read it back",
    "tell the owner if it stays",
)
# What a skill says where it starts a workflow run that opens a PR for the session.
RUN_PR_SENTENCE = (
    "A PR the run opened: when its `pr` step warns that the body still carries AI attribution,"
    " set the body again without the footer through the session's GitHub tools and read it back."
)
# Each part of a skill that starts such a run and reports it: its skill, the words the part
# starts with and the words that follow it.
RUN_PARTS = [
    ("learn", "## promote", "If `./hub workflow list` has no `inbox` workflow"),
    ("release", "## Run", "1. `script` **Changes**"),
    ("upgrade", "3. **Run**", "5. **Merge**"),
]
STARTS_RUN = re.compile(r"\./hub workflow run ([a-z0-9-]+)")
# A workflow node that opens a PR runs ``hub step pr``.
PR_STEP = "hub, step, pr,"


def skill_texts(files: tuple[RenderedFile, ...]) -> list[tuple[str, str]]:
    """Each rendered skill file's text after its front matter (a description may say the skill
    opens a PR), with its skill."""
    found: list[tuple[str, str]] = []
    for file in files:
        if not (file.path.startswith(SKILLS) and file.path.endswith(".md")):
            continue
        skill = file.path.removeprefix(SKILLS).split("/", 1)[0]
        text = file.content.decode("utf-8")
        body = text.partition(FRONT_MATTER_END)[2] if text.startswith("---\n") else text
        found.append((skill, body))
    return found


def skill_lines(config: HubConfig) -> list[tuple[str, str]]:
    """Each rendered skill line after its file's front matter, with its skill."""
    texts = skill_texts(render_hub(config).files)
    return [(skill, line) for skill, text in texts for line in text.splitlines()]


def missing_phrases(line: str) -> list[str]:
    return [phrase.pattern for phrase in RESET_PHRASES if phrase.search(line) is None]


def flat(text: str) -> str:
    """``text`` with every run of whitespace as one space: a skill may wrap a sentence."""
    return " ".join(text.split())


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
    claude = flat(rendered["CLAUDE.md"].decode("utf-8"))

    assert [phrase for phrase in CLAUDE_PHRASES if phrase not in claude] == []
    assert "you cannot remove" not in claude


@pytest.mark.parametrize(("skill", "start", "end"), RUN_PARTS, ids=[part[0] for part in RUN_PARTS])
def test_says_what_to_do_with_the_run_warning_when_skill_starts_run_that_opens_pr(
    demo_config: HubConfig, *, skill: str, start: str, end: str
) -> None:
    (text,) = [text for name, text in skill_texts(render_hub(demo_config).files) if name == skill]
    part = text[text.index(start) : text.index(end)]

    assert RUN_PR_SENTENCE in flat(part)
    assert flat(text).count(RUN_PR_SENTENCE) == 1


@pytest.mark.parametrize(
    "document",
    [a_hub_document, a_two_team_document, a_conventions_document],
    ids=["demo", "two_teams", "conventions"],
)
def test_says_what_to_do_with_the_run_warning_when_started_workflow_has_pr_step(
    document: Callable[[], dict[str, Any]],
) -> None:
    files = render_hub(HubConfig.model_validate(document())).files
    opening = {
        file.path.rsplit("/", 1)[1].removesuffix(".yaml")
        for file in files
        if file.path.startswith(WORKFLOWS)
        and file.path.endswith(".yaml")
        and PR_STEP in file.content.decode("utf-8")
    }
    starting = {
        skill: text for skill, text in skill_texts(files) if opening & set(STARTS_RUN.findall(text))
    }

    assert set(starting) == {skill for skill, _, _ in RUN_PARTS}
    assert [skill for skill, text in starting.items() if RUN_PR_SENTENCE not in flat(text)] == []
