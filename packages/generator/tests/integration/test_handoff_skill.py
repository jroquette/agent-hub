"""The rendered ``/handoff`` skill: the tracker step, then ``brain/now.md`` and the journal.

``/deliver`` moves an issue to Done only once its merge commit is green, which usually happens
after its session ended, so issues stayed In Progress or In Review (AGH-699 E-14). The handoff
closes them first: each issue in a started or review state whose linked PR merged and whose merge
commit is green gets the PR link and moves to Done, after one confirmation from the user.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_two_team_document
from agent_hub.generator.render_hub import render_hub

HANDOFF = "plugin/hub-workflow/skills/handoff/SKILL.md"
ITEM = re.compile(r"^(\d+)\. \*\*([^*]+)\*\*", re.MULTILINE)
ITEMS = ["Tracker", "`brain/now.md`", "`brain/journal/YYYY/MM/DD.md`"]
TRACKER_PHRASES = (
    "`hub.json` → `tracker.states`",
    "`started` or `review` state",
    "linked PR merged",
    "merge commit is green",
    "post the PR link",
    "unless a comment already holds it",
    "move it to Done",
    "after one confirmation",
    "red or still running",
    "stays where it is",
)


def rendered_handoff(config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(config).files}
    content = rendered[HANDOFF]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def handoff_text(demo_config: HubConfig) -> str:
    return rendered_handoff(demo_config)


def items(text: str) -> dict[str, str]:
    """Each numbered item's bold name and its text, up to the next item or a blank line."""
    starts = list(ITEM.finditer(text))
    found: dict[str, str] = {}
    for index, match in enumerate(starts):
        next_item = starts[index + 1].start() if index + 1 < len(starts) else len(text)
        blank = text.find("\n\n", match.start())
        end = next_item if blank == -1 else min(next_item, blank)
        found[match.group(2)] = text[match.start() : end]
    return found


def test_settles_tracker_before_brain_files_when_handoff_rendered(handoff_text: str) -> None:
    assert list(items(handoff_text)) == ITEMS


def test_moves_merged_green_issues_to_done_when_handoff_rendered(handoff_text: str) -> None:
    tracker = " ".join(items(handoff_text)["Tracker"].split())

    missing = [phrase for phrase in TRACKER_PHRASES if phrase not in tracker]

    assert missing == []


def test_names_no_team_key_when_two_team_handoff_rendered() -> None:
    config = HubConfig.model_validate(a_two_team_document())
    tracker = " ".join(items(rendered_handoff(config))["Tracker"].split())

    assert [key for key in config.tracker.team_keys if key in tracker] == []
    assert "`hub.json` → `tracker.states`" in tracker
