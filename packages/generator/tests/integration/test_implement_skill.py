"""The rendered ``/implement`` skill and ``/feature``'s Build step (two-level-flows AC-2.1,
AC-2.11).

``/implement <ticket>`` starts the built-in ``implement`` workflow for one ticket of a planned
feature, with the inputs that workflow declares, and runs no spec, research, plan or tickets
step; a ticket in no feature is sent to ``issue-to-pr`` or ``/fix``. ``/feature`` dispatches
``/implement`` once per can-start ticket once its Tickets step is done, and ``/feature <id>`` of a
ticket of a planned feature points to ``/implement <id>``. Checked on the demo hub's render.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import RenderedFile, render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

IMPLEMENT = "plugin/hub-workflow/skills/implement/SKILL.md"
FEATURE = "plugin/hub-workflow/skills/feature/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "sdlc" / "implement.yaml"


@pytest.fixture
def demo_render(demo_config: HubConfig) -> dict[str, RenderedFile]:
    return {file.path: file for file in render_hub(demo_config).files}


def text_of(render: dict[str, RenderedFile], path: str) -> str:
    content = render[path].content
    assert content is not None, path
    return " ".join(content.decode("utf-8").split())


def step(render: dict[str, RenderedFile], number: int) -> str:
    """``/feature``'s numbered step ``number``, its line and the indented lines that follow."""
    content = render[FEATURE].content
    assert content is not None
    lines = content.decode("utf-8").splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{number}. "))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines)
    )
    return " ".join(" ".join(lines[start:end]).split())


def test_starts_the_implement_workflow_with_its_inputs_when_implement_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = text_of(demo_render, IMPLEMENT)
    inputs = load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document["inputs"]

    assert "`./hub workflow run implement" in text
    assert "--live" in text
    for name in inputs:
        assert f"--input {name}=" in text, name
    assert "brain/features/*/features.json" in text


def test_runs_no_spec_research_plan_or_tickets_step_when_implement_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = text_of(demo_render, IMPLEMENT)

    assert "no spec, research, plan or tickets step" in text
    assert "never commits in the hub" in text


def test_names_issue_to_pr_and_fix_for_a_ticket_in_no_feature_when_implement_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = text_of(demo_render, IMPLEMENT)

    stop = text[text.index("in no feature") :]
    assert "stop" in stop[:200]
    assert "`issue-to-pr`" in stop
    assert "`/fix`" in stop


def test_reports_paused_blocked_and_delivered_when_implement_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = text_of(demo_render, IMPLEMENT)

    for outcome in ("`paused`", "`blocked`", "`delivered`"):
        assert outcome in text, outcome
    assert "ticket panel" in text
    assert "`./hub workflow approve <run>`" in text
    assert "`./hub workflow respond <run> --choice decline" in text


def test_dispatches_implement_per_can_start_ticket_when_feature_build_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    build = step(demo_render, 5)

    assert build.startswith("5. **Build**")
    assert "once **Tickets** is done" in build
    assert "`/implement <ticket>` once per ticket the planning lists as can-start" in build


def test_points_a_planned_ticket_to_implement_when_feature_rendered(
    demo_render: dict[str, RenderedFile],
) -> None:
    text = text_of(demo_render, FEATURE)

    pointer = text[text.index("ticket of a planned feature") :][:400]
    assert "`/implement <id>`" in pointer
    assert "brief, sizing or spec" in pointer
    # The pointer comes before step 0, so nothing is restarted first.
    assert text.index("ticket of a planned feature") < text.index("0. **Brief**")


def test_keeps_the_feature_step_numbers_when_feature_rendered_with_implement(
    demo_render: dict[str, RenderedFile],
) -> None:
    content = demo_render[FEATURE].content
    assert content is not None
    numbered = [
        line.split(" ", 1)[0] for line in content.decode("utf-8").splitlines() if line[:1].isdigit()
    ]

    assert numbered == [f"{n}." for n in range(10)]
