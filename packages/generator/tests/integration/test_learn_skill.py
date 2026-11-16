"""The rendered ``/learn`` skill's ``promote`` mode (AGH-487).

``/learn promote`` starts the built-in brain-care ``inbox`` workflow from the hub (``--live``,
with every input it declares: none), reports where the run stopped, and leaves each group's
gate to the owner; an older platform without the workflow falls back to a review by hand. The
default and ``personal`` modes stay as they were. Checked on the demo hub's render.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

LEARN = "plugin/hub-workflow/skills/learn/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "brain-care" / "inbox.yaml"


@pytest.fixture
def raw(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[LEARN]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def text(raw: str) -> str:
    return " ".join(raw.split())


def run_line(raw: str) -> str:
    """The skill's one line that holds the run command."""
    [line] = [line for line in raw.splitlines() if "`./hub workflow run inbox" in line]
    return line


def test_starts_inbox_workflow_when_learn_promote_rendered(raw: str, text: str) -> None:
    line = run_line(raw)
    command = line[line.index("`./hub workflow run inbox") :]
    command = command[: command.index("`", 1) + 1]
    inputs = load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document.get(
        "inputs", {}
    )

    assert command.endswith(" --live`"), command
    for name in inputs:
        assert f"--input {name}=" in command, name
    assert "## promote" in raw
    assert "[personal|promote]" in raw
    # The run's output goes to a file and its exit code is checked.
    assert "$?" in line
    assert "paused at" in text


def test_leaves_gates_to_owner_when_learn_promote_rendered(text: str) -> None:
    respond = "`./hub workflow respond <run> --choice apply|drop|keep --text"

    assert respond in text
    assert "never yourself" in text
    assert "its own decision" in text
    assert "merges the hub PR" in text


def test_names_fallback_when_inbox_workflow_missing(text: str) -> None:
    assert "`./hub workflow list`" in text
    assert "review `brain/_inbox/` by hand" in text


def test_keeps_personal_mode_when_learn_promote_added(raw: str) -> None:
    assert "## personal" in raw
    assert "brain/auto/workspace/MEMORY.md" in raw
    assert raw.index("## personal") < raw.index("## promote")


# AGH-480: the owner sees what a gate asks before answering it.
GATE_RECORDS = "`.agent-runs/workflows/<run>/records.jsonl`"
GATE_MESSAGE = f'the `message` of the last `"event": "gate"` line of {GATE_RECORDS}'


def test_shows_the_gate_message_before_the_owner_answers_when_learn_promote_rendered(
    text: str,
) -> None:
    respond = "`./hub workflow respond <run> --choice apply|drop|keep --text"

    assert GATE_MESSAGE in text
    assert text.index(GATE_MESSAGE) < text.index(respond)
