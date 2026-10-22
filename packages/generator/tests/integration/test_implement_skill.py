"""The rendered ``/implement`` skill (two-level-flows AC-2.1).

``/implement <ticket>`` starts the built-in ``implement`` workflow for one ticket of a planned
feature, with the inputs that workflow declares, and runs no spec, research, plan or tickets
step; a ticket in no feature is sent to ``issue-to-pr`` or ``/fix``. The ticket's text reaches
the run through a file, never pasted into the command. Checked on the demo hub's render;
``/feature``'s Build step is checked in ``test_feature_agents.py``.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

IMPLEMENT = "plugin/hub-workflow/skills/implement/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "sdlc" / "implement.yaml"
TEXT_FILE = '--input issue_text="$(cat "<file>")"'


@pytest.fixture
def raw(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[IMPLEMENT]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def text(raw: str) -> str:
    return " ".join(raw.split())


def run_line(raw: str) -> str:
    """The skill's one line that holds the run command."""
    [line] = [line for line in raw.splitlines() if "`./hub workflow run implement" in line]
    return line


def test_starts_the_implement_workflow_with_its_inputs_when_implement_rendered(raw: str) -> None:
    line = run_line(raw)
    command = line[line.index("`./hub workflow run implement") :]
    command = command[: command.index("`", 1) + 1]
    inputs = load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document["inputs"]

    assert command.endswith(" --live`"), command
    for name in inputs:
        assert f"--input {name}=" in command, name
    assert "brain/features/*/features.json" in raw


def test_passes_the_ticket_text_through_a_file_when_implement_rendered(raw: str, text: str) -> None:
    line = run_line(raw)

    assert TEXT_FILE in line
    assert 'issue_text="<' not in text.replace(TEXT_FILE, "")
    assert '"$TMPDIR/' not in text
    # One absolute path, resolved once, for both the Write call and the command.
    assert '`echo "${TMPDIR:-/tmp}"`' in text
    assert "with the Write tool" in text
    assert "`test -s <file>`" in text
    assert text.index("`test -s <file>`") < text.index("`./hub workflow run implement")


def test_runs_no_spec_research_plan_or_tickets_step_when_implement_rendered(text: str) -> None:
    assert "no spec, research, plan or tickets step" in text
    assert "never commits in the hub" in text


def test_names_issue_to_pr_and_fix_for_a_ticket_in_no_feature_when_implement_rendered(
    text: str,
) -> None:
    stop = text[text.index("in no feature") :]

    assert "stop" in stop[:200]
    assert "`issue-to-pr`" in stop
    assert "`/fix`" in stop


def test_reports_paused_blocked_and_delivered_when_implement_rendered(text: str) -> None:
    for outcome in ("`paused`", "`blocked`", "`delivered`"):
        assert outcome in text, outcome
    assert "ticket panel" in text
    assert "`./hub workflow approve <run>`" in text
    assert "`./hub workflow respond <run> --choice decline" in text


def test_reads_the_delivery_from_the_run_records_when_implement_rendered(text: str) -> None:
    assert "`.agent-runs/workflows/<run>/records.jsonl`" in text
    assert '`"node": "delivery"`' in text
    for field in ("`question`", "`pr`", "`stage`", "`reason`", "`hub_files`", "`superseded`"):
        assert field in text, field
    # A23: an approval the plan moved past is told to the owner.
    assert "`superseded` whenever it is not empty" in text
