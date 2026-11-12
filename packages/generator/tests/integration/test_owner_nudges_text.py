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
"""

import re
from collections.abc import Callable
from importlib.resources import files
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document, a_two_team_document
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
