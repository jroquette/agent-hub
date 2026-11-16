"""Every rendered skill step that runs ``gh pr create``, ``edit``, ``view`` or ``list`` names its
fallback in the same step (AGH-699 E-19).

Those ``gh pr`` commands go through GitHub's GraphQL API, which cloud sessions refuse, so each step
says what to use when ``gh`` answers that GraphQL is not available: the session's GitHub tools or
``gh api`` (REST). A PR body still goes through its file: the fallback that writes one reads the
same body file (``-F body=@<file>``), or gives the GitHub tools that file's text unchanged.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document, a_two_team_document
from agent_hub.generator.render_hub import render_hub

SKILLS = "plugin/hub-workflow/skills/"
GH_PR = re.compile(r"`gh pr (create|edit|view|list)\b")
WRITES = {"create", "edit"}
FALLBACK = ("GraphQL is not available", "the session's GitHub tools", "`gh api ")
BODY_FILE = ("-F body=@", "unchanged")
# The skills whose steps run one of those commands today: a scan that finds none of them is broken.
EXPECTED_SKILLS = {
    "feature",
    "implement",
    "onboard",
    "overengineering-review",
    "retro",
    "upgrade",
    "ux-review",
}


def gh_pr_lines(config: HubConfig) -> list[tuple[str, str, set[str]]]:
    """Each rendered skill line that runs a ``gh pr`` command: its skill, text and subcommands."""
    found: list[tuple[str, str, set[str]]] = []
    for file in render_hub(config).files:
        if not (file.path.startswith(SKILLS) and file.path.endswith(".md")):
            continue
        skill = file.path.removeprefix(SKILLS).split("/", 1)[0]
        for line in file.content.decode("utf-8").splitlines():
            commands = set(GH_PR.findall(line))
            if commands:
                found.append((skill, line, commands))
    return found


@pytest.mark.parametrize(
    "document",
    [a_two_team_document, a_conventions_document],
    ids=["two_teams", "conventions"],
)
def test_names_fallback_in_same_step_when_skill_runs_gh_pr(
    document: Callable[[], dict[str, Any]],
) -> None:
    lines = gh_pr_lines(HubConfig.model_validate(document()))

    missing = [
        (skill, phrase) for skill, line, _ in lines for phrase in FALLBACK if phrase not in line
    ]

    assert {skill for skill, _, _ in lines} == EXPECTED_SKILLS
    assert missing == []


def test_keeps_pr_body_in_its_file_when_fallback_writes_one(demo_config: HubConfig) -> None:
    writes = [
        (skill, line) for skill, line, commands in gh_pr_lines(demo_config) if commands & WRITES
    ]

    missing = [
        (skill, phrase) for skill, line in writes for phrase in BODY_FILE if phrase not in line
    ]

    assert {skill for skill, _ in writes} == {"feature", "implement"}
    assert missing == []
