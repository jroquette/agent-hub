"""The rendered ``/triage`` workflow skill: what its text promises (AGH-103, AGH-99).

``/triage`` brings a tracker issue to the Definition of Ready. Its steps carry their type from
SPEC "Defined directions" §1; nothing reaches the tracker before the user's gate; the ready label
is the one in ``hub.json``; an open question or a guarded path gets ``needs-human``; the issue's
text is kept; ``--hygiene`` only reports until the gate. The skill is generic: no project value
is written into it.
"""

import re
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.doctor.config_lint import Frontmatter, line_count, parse_frontmatter
from agent_hub.core.doctor.instruction_rules import DEFAULT_MAX_LINES
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing import builders
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/triage/SKILL.md"
TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src/agent_hub/generator/templates/plugin/hub-workflow/skills/triage/SKILL.md.tmpl"
)
DOCUMENTS = pytest.mark.parametrize(
    "document",
    [builders.a_hub_document, builders.a_two_team_document, builders.a_conventions_document],
    ids=["demo", "two_teams", "conventions"],
)

# Each step: its number, its bold title and its type (SPEC "Defined directions" §1).
STEPS = (
    (1, "Read", "script"),
    (2, "Size", "agent"),
    (3, "Draft", "agent"),
    (4, "Approve", "gate"),
    (5, "Update", "script"),
    (6, "Hygiene", "agent"),
)
STEP_TYPES = ("agent", "script", "gate", "human")
STEP_LINE = re.compile(r"^(\d+)\. \*\*([A-Za-z]+)\*\* \(`([a-z]+)`\)", re.MULTILINE)

# AC-1: what the draft states, and the gate before any tracker write.
DRAFT_FIELDS = ("AC ids", "Given/When/Then", "size", "repos", "blocked-by", "Verification command")
NO_WRITE_BEFORE_GATE = "Nothing is written to the tracker before step 4"
# AC-2: the label comes from hub.json, and `hub next` is what lists it.
READY_LABEL_KEY = "`tracker.ready_label`"
DEFAULT_READY_LABEL = "agent-ready"
HUB_NEXT = "`./hub next` (`make next`)"
# AC-3: the other label, and when it applies.
NEEDS_HUMAN = "`needs-human`"
GUARDED_PATHS = "`guard.ask_before_edit`"
NEVER_READY = "never the ready label"
# AC-4: the issue's text is kept.
KEEPS_TEXT = "adds or replaces sections, never the whole text"
OLD_TEXT_COMMENT = "the previous description goes first in a comment on the issue"
# AC-5: the hygiene report.
HYGIENE_FLAG = "`--hygiene`"
HYGIENE_FINDINGS = ("no linked branch or PR", "no update in", "duplicates", "dependency cycles")
HYGIENE_EVIDENCE = "with its evidence"
HYGIENE_NO_CHANGE = "changes nothing until the user approves"
# AC-6 (AGH-99's rules): the never-do lines.
NEVER_DO = (
    "Never edit code, create a branch or open a PR",
    'no AI co-author trailer, no "Generated with", no 🤖',
)
# A tracker issue id (`ABC-12`); the skill's own AC ids (`AC-1`) are examples, not issues.
PROJECT_ID = re.compile(r"\b(?!AC-)[A-Z]{2,}-\d+\b")


def triage_text(document: Callable[[], dict[str, Any]]) -> str:
    config = HubConfig.model_validate(document())
    files = {file.path: file.content for file in render_hub(config).files}
    return files[SKILL_PATH].decode("utf-8")


@pytest.fixture
def text() -> str:
    return triage_text(builders.a_hub_document)


def test_marks_each_step_with_its_type_when_triage_rendered(text: str) -> None:
    found = [(int(number), title, kind) for number, title, kind in STEP_LINE.findall(text)]

    assert found == list(STEPS)
    assert {kind for _, _, kind in found} <= set(STEP_TYPES)


def test_states_draft_fields_before_any_write_when_issue_drafted(text: str) -> None:
    draft = text[text.index("**Draft**") : text.index("**Approve**")]

    for field in DRAFT_FIELDS:
        assert field in draft, field
    assert text.count(NO_WRITE_BEFORE_GATE) == 1
    assert text.index(NO_WRITE_BEFORE_GATE) < text.index("**Update**")


def test_takes_ready_label_from_hub_json_when_draft_approved(text: str) -> None:
    update = text[text.index("**Update**") : text.index("**Hygiene**")]

    assert READY_LABEL_KEY in update
    assert HUB_NEXT in text
    assert DEFAULT_READY_LABEL not in text


def test_labels_needs_human_when_question_open_or_path_guarded(text: str) -> None:
    update = text[text.index("**Update**") : text.index("**Hygiene**")]

    assert NEEDS_HUMAN in update
    assert GUARDED_PATHS in update
    assert NEVER_READY in update


def test_keeps_previous_description_when_section_replaced(text: str) -> None:
    assert KEEPS_TEXT in text
    assert OLD_TEXT_COMMENT in text


def test_reports_without_changes_when_hygiene_run(text: str) -> None:
    hygiene = text[text.index("**Hygiene**") :]

    assert HYGIENE_FLAG in hygiene
    for finding in HYGIENE_FINDINGS:
        assert finding in hygiene, finding
    assert HYGIENE_EVIDENCE in hygiene
    assert HYGIENE_NO_CHANGE in hygiene


def test_states_never_do_lines_when_triage_rendered(text: str) -> None:
    for line in NEVER_DO:
        assert line in text, line


def test_disables_model_invocation_when_triage_rendered(text: str) -> None:
    frontmatter = parse_frontmatter(text)

    assert isinstance(frontmatter, Frontmatter)
    assert frontmatter.fields["name"] == "triage"
    assert frontmatter.fields["disable-model-invocation"] == "true"


@DOCUMENTS
def test_fits_size_limit_when_triage_rendered(document: Callable[[], dict[str, Any]]) -> None:
    # The limit is a literal so a change to the constant does not move the test with it.
    assert DEFAULT_MAX_LINES["*/*"] == 80

    assert line_count(triage_text(document)) <= DEFAULT_MAX_LINES["*/*"]


@DOCUMENTS
def test_names_no_project_value_when_triage_rendered(
    document: Callable[[], dict[str, Any]],
) -> None:
    config = HubConfig.model_validate(document())
    text = triage_text(document)
    body = text.split("---", 2)[2]

    assert config.project.name not in body
    for key in config.tracker.team_keys:
        assert key not in body, key
    for repo in config.repos:
        assert repo.dir not in body, repo.dir
    assert "@@{" not in text
    assert PROJECT_ID.search(TEMPLATE.read_text(encoding="utf-8")) is None
