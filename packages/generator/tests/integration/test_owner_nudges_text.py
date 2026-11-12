"""The rendered hub's text that spares the owner a nudge (fewer-owner-nudges).

When the owner drops the direction a session was following (AC-39, AC-40), ``/handoff`` holds the
procedure in one ``**Dropped direction**`` paragraph after its three numbered items: stop, ask
"Why?" once, file the answer with ``/learn`` (``provenance: human``) and run the three steps; with
no answer, still hand off and record "no reason given". The ticket keeps its status (or moves to
the state the owner names, after one confirmation) and gets one comment on what was done and
dropped; an open PR is left to the owner. The hub's ``AGENTS.md`` points to it in one "Brain
rules" line, since the owner drops a direction outside any skill. Phrases are checked on the demo
render; the two-team and conventions renders check that no project value reaches the new text,
which adds no ``@@{…}`` placeholder.

The scope tests (AGH-813, AC-33 to AC-35): ``/change``, ``/refactor`` and ``/upgrade`` show an
in-scope and an out-of-scope list with their first plan, post both on the tracker issue (not in the
PR body), and before the PR remove or ask about each changed file outside the in-scope list. The
upgrade workflow's branch belongs to the run, so at its ``publish`` gate the session only asks the
owner. The same phrases hold in the three skills; each step is sliced by its number or its bold
name.
"""

import re
from collections.abc import Callable
from importlib.resources import files
from typing import Any, NamedTuple

import pytest

from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

AGENTS = "AGENTS.md"
HANDOFF = "plugin/hub-workflow/skills/handoff/SKILL.md"
DROPPED_LEAD = "**Dropped direction**"
AGENTS_TRIGGER = "drops the direction"
MAX_WIDTH = 120
STOP_CLAUSE = "stop: no further edit, commit or push"
PR_LEFT = "An open PR on the dropped direction is left to the owner"
PLACEHOLDER_MARK = "@@"
ROUTING_LABELS = ("  - team fact:", "  - personal preference", "  - repo command")
LEAK_DOCUMENTS = [
    pytest.param(a_two_team_document, id="two_teams"),
    pytest.param(a_conventions_document, id="conventions"),
]


def rendered(config: HubConfig, path: str) -> str:
    """The rendered file at ``path``, as text."""
    content = {file.path: file.content for file in render_hub(config).files}[path]
    assert content is not None
    return content.decode("utf-8")


def template(path: str) -> str:
    """The generator's template at ``templates/path``, as text."""
    return files("agent_hub.generator").joinpath(f"templates/{path}").read_text("utf-8")


def flat(text: str) -> str:
    """``text`` with every run of whitespace turned into one space."""
    return " ".join(text.split())


def section(text: str, heading: str) -> str:
    """The raw text of the ``## heading`` section, up to the next one."""
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def dropped_paragraphs(handoff: str) -> list[str]:
    """Every paragraph of ``handoff`` that starts with the Dropped direction lead, raw."""
    return [paragraph for paragraph in handoff.split("\n\n") if paragraph.startswith(DROPPED_LEAD)]


def dropped_paragraph(handoff: str) -> str:
    """The one Dropped direction paragraph, whitespace-joined ("" when there is none)."""
    paragraphs = dropped_paragraphs(handoff)
    return flat(paragraphs[0]) if len(paragraphs) == 1 else ""


def trigger_lines(agents: str) -> list[str]:
    """The "Brain rules" lines that name the owner dropping the direction."""
    return [line for line in section(agents, "Brain rules").splitlines() if AGENTS_TRIGGER in line]


@pytest.fixture
def handoff(demo_config: HubConfig) -> str:
    return rendered(demo_config, HANDOFF)


@pytest.fixture
def demo_agents(demo_config: HubConfig) -> str:
    return rendered(demo_config, AGENTS)


@pytest.fixture(params=LEAK_DOCUMENTS)
def leak_config(request: pytest.FixtureRequest) -> HubConfig:
    document: Callable[[], dict[str, Any]] = request.param
    return HubConfig.model_validate(document())


def test_asks_why_then_learns_and_hands_off_when_dropped_direction_handoff_rendered(
    handoff: str,
) -> None:
    paragraphs = dropped_paragraphs(handoff)
    assert len(paragraphs) == 1, f"one paragraph starting {DROPPED_LEAD}"
    start = handoff.index(paragraphs[0])
    paragraph = flat(paragraphs[0])

    assert handoff.index("3. **`brain/journal/YYYY/MM/DD.md`**") < start
    assert start < handoff.index("Facts only")
    missing = [
        phrase
        for phrase in (
            STOP_CLAUSE,
            "one line",
            '"Why?"',
            "`/learn`",
            "provenance: human",
            "the three steps above",
        )
        if phrase not in paragraph
    ]
    assert missing == []


def test_hands_off_without_an_answer_when_dropped_direction_handoff_rendered(
    handoff: str,
) -> None:
    paragraph = dropped_paragraph(handoff)

    missing = [
        phrase
        for phrase in (
            "no answer",
            "still",
            "status",
            "one comment",
            "what was done",
            "what was dropped",
            "no reason given",
            "after one confirmation",
            "out of In Progress",
            "nobody on it",
        )
        if phrase not in paragraph
    ]
    assert missing == []


def test_never_merges_or_closes_when_dropped_direction_handoff_rendered(handoff: str) -> None:
    paragraph = dropped_paragraph(handoff)

    assert PR_LEFT in paragraph
    for phrase in ("merge it", "approve", "close the PR", "force-push", "delete the branch"):
        assert phrase not in paragraph, phrase


def test_points_to_handoff_when_dropped_direction_agents_rendered(demo_agents: str) -> None:
    rules = section(demo_agents, "Brain rules")
    lines = rules.splitlines()
    triggers = trigger_lines(demo_agents)

    assert len(triggers) == 1, f"one Brain rules line containing {AGENTS_TRIGGER!r}"
    [line] = triggers
    assert line.startswith("- ")
    assert '"why?"' in line
    assert "`/handoff`" in line
    assert len(line) <= MAX_WIDTH, len(line)
    subs = [index for index, text in enumerate(lines) if text.startswith("  - ")]
    assert len(subs) == 3
    assert subs == list(range(subs[0], subs[0] + 3))
    assert [
        lines[index][: len(label)] for index, label in zip(subs, ROUTING_LABELS, strict=True)
    ] == [*ROUTING_LABELS]


def test_names_no_project_value_when_dropped_direction_rendered(leak_config: HubConfig) -> None:
    paragraph = dropped_paragraph(rendered(leak_config, HANDOFF))
    triggers = trigger_lines(rendered(leak_config, AGENTS))
    values = {leak_config.project.name, *leak_config.tracker.team_keys}

    assert paragraph != "", f"one paragraph starting {DROPPED_LEAD}"
    assert len(triggers) == 1, f"one Brain rules line containing {AGENTS_TRIGGER!r}"
    for text in (paragraph, *triggers):
        for value in values:
            token = rf"(?<![\w-]){re.escape(value)}(?![\w-])"
            assert re.search(token, text) is None, (value, text)
    agents_lines = [
        line for line in template("AGENTS.md.tmpl").splitlines() if AGENTS_TRIGGER in line
    ]
    handoff_template = template("plugin/hub-workflow/skills/handoff/SKILL.md.tmpl")
    template_paragraphs = dropped_paragraphs(handoff_template)
    assert len(agents_lines) == 1, f"one AGENTS.md.tmpl line containing {AGENTS_TRIGGER!r}"
    assert len(template_paragraphs) == 1, f"one template paragraph starting {DROPPED_LEAD}"
    for text in (*agents_lines, *template_paragraphs):
        assert PLACEHOLDER_MARK not in text, text


# The scope lists of /change, /refactor and /upgrade (AGH-813).

SKILLS = ("change", "refactor", "upgrade")
# The nested instruction-file line limit of the doctor's `instructions.size` rule.
NESTED_MAX_LINES = DEFAULT_MAX_LINES["*/*"]

IN_SCOPE_LIST = "an in-scope list"
OUT_OF_SCOPE_LIST = "an out-of-scope list"
OUTSIDE_SCOPE = "outside the in-scope list"
REMOVE_OR_ASK = "either remove its change or ask the owner, with one reason per file"
CHANGED_FILES = "`git diff --name-only"
ON_TRACKER = "in a tracker comment on the issue, not in the PR body"
OWNER_KEEPS = "a file the owner keeps joins the in-scope list in the tracker comment"
RERUN_BEFORE_PUSH = "again before the push"

# A numbered step line, at the start of a line (indented bullets inside a step do not match).
STEP_LINE = re.compile(r"^\d+\. ", re.MULTILINE)


def _skill_path(skill: str) -> str:
    return f"plugin/hub-workflow/skills/{skill}/SKILL.md"


def _rendered_skills(document: dict[str, Any]) -> dict[str, str]:
    by_path = {
        file.path: file.content for file in render_hub(HubConfig.model_validate(document)).files
    }
    skills = {}
    for skill in SKILLS:
        content = by_path[_skill_path(skill)]
        assert content is not None, skill
        skills[skill] = content.decode("utf-8")
    return skills


@pytest.fixture(scope="module")
def demo_skills() -> dict[str, str]:
    """The three skills of the demo render, by skill name."""
    return _rendered_skills(a_hub_document())


class Slice(NamedTuple):
    """Where a part of a skill sits in its text: its start offset and its text."""

    start: int
    text: str


def _step(text: str, number: int) -> Slice:
    """A numbered step: from its line to the next numbered line or the next blank line."""
    match = re.search(rf"^{number}\. ", text, re.MULTILINE)
    assert match is not None, f"no step {number}"
    start = match.start()
    next_step = STEP_LINE.search(text, match.end())
    ends = [text.find("\n\n", start), next_step.start() if next_step else -1]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


def _by_hand(text: str, name: str) -> Slice:
    """A **By hand** item: from its ``- **<name>**`` line to the next item or blank line."""
    start = text.index(f"\n- **{name}**") + 1
    ends = [text.find("\n- **", start), text.find("\n\n", start)]
    end = min((e for e in ends if e != -1), default=len(text))
    return Slice(start, text[start:end])


type Locator = Callable[[str], Slice]


def at_step(number: int) -> Locator:
    return lambda text: _step(text, number)


def at_by_hand(name: str) -> Locator:
    return lambda text: _by_hand(text, name)


# The step that shows each skill's first plan.
FIRST_PLAN = {"change": at_step(1), "refactor": at_step(1), "upgrade": at_step(2)}


class PlanCase(NamedTuple):
    """A skill's first plan: the phrase the lists come after, and phrases other steps hold."""

    skill: str
    after: str | None = None
    elsewhere: tuple[tuple[Locator, str], ...] = ()


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            PlanCase("change", after="size it against `/change`'s limits"), id="change-size"
        ),
        pytest.param(
            PlanCase("refactor", elsewhere=((at_step(3), "the step 1 scope lists"),)),
            id="refactor-scope",
        ),
        pytest.param(PlanCase("upgrade"), id="upgrade-pick"),
    ],
)
def test_shows_scope_lists_when_first_plan_shown(
    demo_skills: dict[str, str], case: PlanCase
) -> None:
    text = demo_skills[case.skill]
    step = FIRST_PLAN[case.skill](text).text

    assert IN_SCOPE_LIST in step
    assert OUT_OF_SCOPE_LIST in step
    if case.after is not None:
        assert step.index(case.after) < step.index(IN_SCOPE_LIST)
    for locate, phrase in case.elsewhere:
        assert phrase in locate(text).text


class ShipCase(NamedTuple):
    """Where a skill checks the changed files, and where it opens the PR."""

    skill: str
    check_at: Locator
    pr_at: Locator
    opens_pr: str
    reruns: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            ShipCase(
                "change",
                at_step(7),
                at_step(7),
                "open the PR",
                "run step 5 Gates again before the push",
            ),
            id="change-ship",
        ),
        pytest.param(
            ShipCase(
                "refactor",
                at_step(5),
                at_step(6),
                "open its PR",
                "run the step 4 gates again before the push",
            ),
            id="refactor-pr",
        ),
        pytest.param(
            ShipCase(
                "upgrade",
                at_by_hand("Ship"),
                at_by_hand("Ship"),
                "open the PR",
                "run Verify again before the push",
            ),
            id="upgrade-by-hand-ship",
        ),
    ],
)
def test_checks_files_outside_scope_lists_when_pr_about_to_open(
    demo_skills: dict[str, str], case: ShipCase
) -> None:
    text = demo_skills[case.skill]
    check = case.check_at(text)
    pr = case.pr_at(text)
    opens_pr = case.opens_pr

    assert CHANGED_FILES in check.text
    assert OUTSIDE_SCOPE in check.text
    assert REMOVE_OR_ASK in check.text
    assert opens_pr in pr.text
    assert check.start + check.text.index(REMOVE_OR_ASK) < pr.start + pr.text.index(opens_pr)
    assert OWNER_KEEPS in check.text
    assert RERUN_BEFORE_PUSH in check.text
    assert case.reruns in check.text
    assert check.text.index(REMOVE_OR_ASK) < check.text.index(case.reruns)
    assert check.start + check.text.index(case.reruns) < pr.start + pr.text.index(opens_pr)


def test_asks_owner_about_files_outside_scope_lists_when_upgrade_paused_at_publish(
    demo_skills: dict[str, str],
) -> None:
    report = _step(demo_skills["upgrade"], 4).text

    assert "At `publish`, before you show that message" in report
    assert OUTSIDE_SCOPE in report
    assert "ask the owner about each one, with one reason per file" in report
    assert "Never edit the run's branch" in report
    assert OWNER_KEEPS in report


class BodyCase(NamedTuple):
    skill: str
    pr_step_at: Locator
    pr_body: str


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(BodyCase("change", at_step(7), "The PR body follows"), id="change"),
        pytest.param(BodyCase("refactor", at_step(6), "The body holds"), id="refactor"),
        pytest.param(BodyCase("upgrade", at_by_hand("Ship"), "The PR body holds"), id="upgrade"),
    ],
)
def test_posts_scope_lists_on_tracker_not_pr_body_when_lists_written(
    demo_skills: dict[str, str], case: BodyCase
) -> None:
    skill = case.skill
    text = demo_skills[skill]
    pr_step = case.pr_step_at(text).text
    # The PR-body text: from the PR body sentence to the end of its step or item.
    body_text = pr_step[pr_step.index(case.pr_body) :]
    body_sentences = [
        sentence for sentence in re.split(r"(?<=[.;:])\s", pr_step) if "body" in sentence
    ]

    assert ON_TRACKER in FIRST_PLAN[skill](text).text
    assert "scope list" not in body_text
    assert body_sentences
    for sentence in body_sentences:
        assert "scope list" not in sentence, sentence


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(a_hub_document, id="demo"),
        pytest.param(a_two_team_document, id="two_teams"),
        pytest.param(a_conventions_document, id="conventions"),
    ],
)
def test_scope_lists_add_no_placeholder_or_hub_value_when_hub_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    source = document()
    tracker = source["tracker"]
    teams = tracker.get("teams") or [tracker["team"]]
    values = [*teams, source["project"]["name"], *(repo["dir"] for repo in source["repos"])]

    for skill, text in _rendered_skills(source).items():
        assert PLACEHOLDER_MARK not in text, skill
        for value in values:
            assert re.search(rf"\b{re.escape(value)}\b", text) is None, (skill, value)
        assert len(text.splitlines()) <= NESTED_MAX_LINES, skill
