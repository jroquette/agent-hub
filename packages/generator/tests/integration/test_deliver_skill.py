"""The rendered ``/deliver`` skill (AGH-101): its typed steps, stop rules and never-do lines.

Each step carries its type from SPEC "Defined directions" §1 (`agent`, `script`, `gate`, `human`),
so the text is checked step by step on the demo hub's render; the behaviour itself (what a run
does with a real PR) is not testable from the text.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

DELIVER = "plugin/hub-workflow/skills/deliver/SKILL.md"
STEP = re.compile(r"^(\d+)\. \*\*([^*]+)\*\* \(`(agent|script|gate|human)`\)", re.MULTILINE)
NO_AI_ATTRIBUTION = 'no AI co-author trailer, no "Generated with", no 🤖'

# Step number → its type and the phrases its paragraph holds (AC ids from AGH-101).
STEPS = {
    1: ("script", ("head SHA", "CI per check", "mergeability", "review threads", "tracker issue")),
    # AC-1, AC-2, AC-3: conflict, then red CI, then review threads.
    2: (
        "agent",
        (
            "merge the default branch into the head",
            "a merge commit",
            "never rebase",
            "lockfiles",
            "the failing check, its root cause and the fix",
            '"flake" is not a cause',
            "at most once",
            "died before the tests ran",
            "a pushed fix and a reply",
            "a reply with the proposal and why it is not pushed",
            "none is left silent",
        ),
    ),
    3: ("script", ("`check_fast`, then its `check`", "`hub.json`", "`$?`", "adversarial")),
    4: ("gate", ("mergeable", "waits on reviewers", "never approves or merges")),
    5: ("human", ("the user merges",)),
    # AC-5, AC-6: the merge commit's CI, the dependents re-checked after each merge.
    6: (
        "script",
        (
            "merge commit",
            "`/fix`",
            "contract order",
            "`hub ship`",
            "dependents",
        ),
    ),
    7: ("script", ("PR link", "Done", "only once the merge commit is green", "./hub worktree")),
}
# AC-4 and the authorship rules: what no step may do.
NEVER_DO = (
    "skip, disable or quarantine a test",
    "add a skip marker",
    "weaken an assertion",
    "push an empty commit",
    "close or reopen the PR",
    "No push to the default branch, no force-push",
    NO_AI_ATTRIBUTION,
)


@pytest.fixture
def deliver_text(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[DELIVER]
    assert content is not None
    return content.decode("utf-8")


def _steps(text: str) -> dict[int, tuple[str, str]]:
    """Each numbered step's type and paragraph (up to the next step or the end)."""
    matches = list(STEP.finditer(text))
    found: dict[int, tuple[str, str]] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        found[int(match.group(1))] = (match.group(3), text[match.start() : end])
    return found


def test_marks_each_step_with_its_type_when_deliver_rendered(deliver_text: str) -> None:
    steps = _steps(deliver_text)

    assert sorted(steps) == sorted(STEPS)
    for number, (kind, phrases) in STEPS.items():
        actual_kind, paragraph = steps[number]
        assert actual_kind == kind, number
        for phrase in phrases:
            assert phrase in paragraph, (number, phrase)


def test_stops_for_the_user_when_deliver_rendered(deliver_text: str) -> None:
    # Unreadable input, a larger review ask and a red merge commit each stop the skill.
    assert "if it cannot be read, say so and stop" in deliver_text
    assert "stop for the user" in deliver_text
    assert "linked to the PR and stop" in deliver_text


def test_lists_never_do_lines_when_deliver_rendered(deliver_text: str) -> None:
    for line in NEVER_DO:
        assert line in deliver_text, line
    assert "placeholder" not in deliver_text
    assert "not written yet" not in deliver_text
