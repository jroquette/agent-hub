"""The rendered ``/feature`` skill's spike route (AGH-492).

A spike-sized item runs the built-in ``spike`` workflow, with the inputs that workflow declares;
the question reaches the run through a file, never pasted into the command, and the user answers
the pick with the decisions the workflow's gate declares. The hand-run *Spike* line stays the
fallback. Checked on the demo hub's render.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

FEATURE = "plugin/hub-workflow/skills/feature/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "spike" / "spike.yaml"
TEXT_FILE = '--input question="$(cat "<file>")"'


@pytest.fixture
def raw(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[FEATURE]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def text(raw: str) -> str:
    return " ".join(raw.split())


def run_line(raw: str) -> str:
    """The skill's one line that holds the spike's run command."""
    [line] = [line for line in raw.splitlines() if "`./hub workflow run spike" in line]
    return line


def spike() -> dict[str, object]:
    return dict(load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document)


def test_starts_the_spike_workflow_with_its_inputs_when_feature_rendered(raw: str) -> None:
    line = run_line(raw)
    command = line[line.index("`./hub workflow run spike") :]
    command = command[: command.index("`", 1) + 1]
    inputs = spike()["inputs"]

    assert line.startswith("*Spike run*: ")
    assert command.endswith(" --live`"), command
    assert isinstance(inputs, dict)
    for name in inputs:
        assert f"--input {name}=" in command, name
    assert "brain/features/<slug>/research.md" in line
    assert "`/adr`" in line


def test_passes_the_question_through_a_file_when_feature_rendered(raw: str, text: str) -> None:
    line = run_line(raw)

    assert TEXT_FILE in line
    assert 'question="<' not in text.replace(TEXT_FILE, "")
    assert '`echo "${TMPDIR:-/tmp}"`' in line
    assert "with the Write tool" in line
    assert "replacing a file left by an earlier run" in line
    assert "`test -s <file>`" in line
    assert line.index("`test -s <file>`") < line.index("`./hub workflow run spike")


def test_names_the_pick_decisions_when_feature_rendered(raw: str) -> None:
    line = run_line(raw)
    nodes = spike()["nodes"]
    assert isinstance(nodes, list)
    (choose,) = [node for node in nodes if node["id"] == "choose"]
    (pick,) = [node for node in choose["nodes"] if node["id"] == "pick"]
    ids = "|".join(decision["id"] for decision in pick["decisions"])

    assert f'`./hub workflow respond <run> --choice {ids} --text "<note>"`' in line
    assert "never pick for them" in line
    # The user sees what the gate asks (the options' brief) before answering it.
    shown = (
        'the `message` of the last `"event": "gate"` line of'
        " `.agent-runs/workflows/<run>/records.jsonl`"
    )
    assert shown in line
    assert line.index(shown) < line.index("`./hub workflow respond")
    assert "do not edit the hub or a repo while it runs" in line
    assert "ends done with what it has, marked incomplete" in line


def test_keeps_the_manual_spike_steps_when_feature_rendered(raw: str) -> None:
    lines = raw.splitlines()
    spikes = [line for line in lines if line.startswith("*Spike*")]
    line = run_line(raw)

    assert len(spikes) == 1
    assert lines.index(line) == lines.index(spikes[0]) + 2
    assert "If `./hub workflow run` is not available, follow the *Spike* line by hand." in line
