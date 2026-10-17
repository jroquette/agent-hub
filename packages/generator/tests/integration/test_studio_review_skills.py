"""``/overengineering-review``, ``/ux-review`` and the ``ux-designer`` agent as a hub renders them.

The three came from a hub's Studio and ship in the base plugin (AGH-274). They are text an agent
follows, so what a text can prove is pinned here: each skill's steps in order with their type from
SPEC "Defined directions" §1, its catalogue file next to it, that it stays read-only and posts
nothing before the user's gate, and that no project value nor agent-hub's own design paths are
written into it: the design system is the one the repo's ``AGENTS.md`` names.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILLS = "plugin/hub-workflow/skills"
OVERENGINEERING = f"{SKILLS}/overengineering-review/SKILL.md"
PATTERNS = f"{SKILLS}/overengineering-review/references/patterns.md"
UX_REVIEW = f"{SKILLS}/ux-review/SKILL.md"
CHECKLIST = f"{SKILLS}/ux-review/references/checklist.md"
UX_DESIGNER = "plugin/hub-workflow/agents/ux-designer.md"
STEP_LINE = re.compile(r"^(\d+)\. `([a-z]+)` \*\*([^*]+)\*\*", re.MULTILINE)
# Each skill's steps, in order: number, type, bold title.
OVERENGINEERING_STEPS = [
    (1, "script", "Scope"),
    (2, "agent", "Today's problem"),
    (3, "agent", "Hunt"),
    (4, "agent", "Report"),
    (5, "gate", "The user picks"),
]
UX_REVIEW_STEPS = [
    (1, "script", "Scope"),
    (2, "agent", "Load the yardstick"),
    (3, "agent", "The screen's job"),
    (4, "agent", "Hunt"),
    (5, "agent", "Report"),
    (6, "gate", "The user picks"),
]
# What only agent-hub's own repo has: a generic platform text never names it.
AGENT_HUB_PATHS = (
    "docs/design/control-plane",
    "apps/web",
    "tokens.json",
    "32-decisions.md",
    "01-navigation.md",
    "plugin/agent-hub",
    "agent-hub",
)


@pytest.fixture(scope="module")
def texts() -> dict[str, str]:
    rendered = render_hub(HubConfig.model_validate(a_hub_document())).files
    return {
        file.path: file.content.decode("utf-8") for file in rendered if file.content is not None
    }


def _steps(text: str) -> list[tuple[int, str, str]]:
    return [(int(number), kind, title) for number, kind, title in STEP_LINE.findall(text)]


@pytest.mark.parametrize(
    ("path", "steps"),
    [(OVERENGINEERING, OVERENGINEERING_STEPS), (UX_REVIEW, UX_REVIEW_STEPS)],
)
def test_marks_each_step_with_its_type_when_skill_rendered(
    texts: dict[str, str], path: str, steps: list[tuple[int, str, str]]
) -> None:
    assert _steps(texts[path]) == steps


@pytest.mark.parametrize(
    ("path", "catalogue"),
    [
        (OVERENGINEERING, "[references/patterns.md](references/patterns.md)"),
        (UX_REVIEW, "[references/checklist.md](references/checklist.md)"),
    ],
)
def test_links_its_catalogue_when_skill_rendered(
    texts: dict[str, str], path: str, catalogue: str
) -> None:
    assert catalogue in texts[path]


def test_ships_each_catalogue_next_to_its_skill_when_hub_rendered(texts: dict[str, str]) -> None:
    patterns = texts[PATTERNS]
    checklist = texts[CHECKLIST]

    for pattern in range(1, 12):
        assert f"| P{pattern} |" in patterns, pattern
    for check in ("P1", "C1", "S1", "L1", "T1", "K1", "A1", "R1", "U1"):
        assert f"| {check} |" in checklist, check
    assert "## Not over-engineering" in patterns
    assert "## Not a finding" in checklist


@pytest.mark.parametrize("path", [OVERENGINEERING, UX_REVIEW])
def test_stays_read_only_and_posts_nothing_when_skill_rendered(
    texts: dict[str, str], path: str
) -> None:
    text = texts[path]
    head = text.split("\n---\n", 1)[0]

    assert "disable-model-invocation: true" in head
    assert "never edits, commits, pushes or posts" in text
    assert "never by checking it out" in text
    assert "Nothing is applied here" in text
    assert "created only after the user says so" in text
    assert "posts nothing on a PR" in text


def test_proves_each_finding_with_a_search_when_overengineering_reviewed(
    texts: dict[str, str],
) -> None:
    text = texts[OVERENGINEERING]

    assert "**minimum-sufficient rule** at the top of the `/feature` skill" in text
    assert "**prove it with a search**" in text
    assert "A finding without a search behind it is dropped" in text
    for verdict in ("`LEAN`", "`SOME FAT`", "`OVER-ENGINEERED`"):
        assert verdict in text
    assert "the fix for over-engineering is less code" in text


def test_names_the_rule_and_the_improvement_when_ux_reviewed(texts: dict[str, str]) -> None:
    text = texts[UX_REVIEW]

    assert "the files its `AGENTS.md` names for it" in text
    assert "With none named, say so and review against the heuristics alone" in text
    for severity in ("`blocker`", "`friction`", "`polish`"):
        assert severity in text
    for verdict in ("`ON SYSTEM`", "`DRIFTING`", "`OFF SYSTEM`"):
        assert verdict in text
    assert "`needs a spec change`" in text


def test_writes_one_design_per_screen_when_ux_designer_rendered(texts: dict[str, str]) -> None:
    text = texts[UX_DESIGNER]
    head = text.split("\n---\n", 1)[0]

    assert "name: ux-designer" in head
    assert "tools: Read, Grep, Glob, Bash, Write" in head
    assert "model: opus" in head
    assert "mutates_checkout" not in head
    assert "`brain/features/<slug>/ux-<new|change>-<screen>.md`" in text
    assert "`plugin/hub-workflow/skills/ux-review/references/checklist.md`" in text
    assert "never rewritten" in text
    assert "**Compound step:**" in text


@pytest.mark.parametrize("path", [OVERENGINEERING, PATTERNS, UX_REVIEW, CHECKLIST, UX_DESIGNER])
def test_keeps_project_and_agent_hub_values_out_when_demo_hub_rendered(
    texts: dict[str, str], path: str
) -> None:
    text = texts[path]

    for value in ("demo", "DEM", "jdoe", "Jane Doe", "acme", "AGH", *AGENT_HUB_PATHS):
        assert value not in text, value
