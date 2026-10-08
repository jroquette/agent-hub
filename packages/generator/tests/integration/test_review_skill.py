"""The ``/review`` workflow skill as a hub renders it: its steps, their types and its stop rules.

The skill is text an agent follows, so what a text can prove is pinned here: every step is
present in order with its type from SPEC "Defined directions" §1, the reviewers run in fresh
contexts, nothing is posted before the user's gate, and the never-do lines hold. The demo hub's
own values (project, team, repo, author) never appear: they come from ``hub.json`` at run time.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

SKILL_PATH = "plugin/hub-workflow/skills/review/SKILL.md"

# The ticket's steps, in order, each with its type.
STEPS = (
    (1, "script", "Read the PR"),
    (2, "agent", "Decisions"),
    (3, "agent", "spec-reviewer"),
    (4, "agent", "quality-reviewer"),
    (5, "agent", "Consolidate"),
    (6, "gate", "user picks"),
    (7, "script", "Post"),
)


def _skill_text() -> str:
    rendered = {
        file.path: file.content
        for file in render_hub(HubConfig.model_validate(a_hub_document())).files
    }
    content = rendered[SKILL_PATH]
    assert content is not None
    return content.decode("utf-8")


def _body() -> str:
    text = _skill_text()
    return text.split("\n---\n", 1)[1]


def _step(number: int) -> str:
    """The text of one numbered step: its line and the indented lines that follow it."""
    lines = _body().splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{number}. "))
    end = next(
        (i for i in range(start + 1, len(lines)) if not lines[i].startswith(" ")), len(lines)
    )
    return "\n".join(lines[start:end])


@pytest.mark.parametrize(("number", "kind", "name"), STEPS)
def test_marks_each_step_with_its_type_when_skill_rendered(
    number: int, kind: str, name: str
) -> None:
    step = _step(number)

    assert re.match(rf"{number}\. `{kind}` \*\*[^*]+\*\*", step), step.splitlines()[0]
    assert name in step


def test_lists_steps_in_ticket_order_when_skill_rendered() -> None:
    numbers = [
        int(line.split(".", 1)[0]) for line in _body().splitlines() if re.match(r"\d+\. ", line)
    ]

    assert numbers == [number for number, _, _ in STEPS]


def test_reads_the_pr_read_only_when_given_a_pr() -> None:
    step = _step(1)

    assert "read-only" in step
    assert "number or URL" in step
    assert "brain/features/<slug>/spec.md" in step


def test_runs_both_reviewers_in_fresh_contexts_when_skill_rendered() -> None:
    for number in (3, 4):
        assert "fresh context" in _step(number), number


def test_cites_evidence_or_marks_a_question_when_finding_consolidated() -> None:
    step = _step(5)

    assert "path:line" in step
    for severity in ("blocking", "should-fix", "nit"):
        assert severity in step
    assert "by path" in step
    assert "question" in step
    assert "dropped" in step


def test_marks_every_ac_when_ticket_has_acs() -> None:
    step = _step(3)

    for status in ("covered", "not covered", "not testable"):
        assert f"`{status}`" in step
    assert "the test that covers it" in step


def test_posts_nothing_before_the_gate_when_skill_rendered() -> None:
    gate = _step(6)
    post = _step(7)

    for verdict in ("approve", "request changes", "comment"):
        assert verdict in gate
    assert "Nothing is posted before" in post
    assert "one pending review" in post
    assert "no AI attribution" in post


def test_never_approves_own_pr_nor_merges_when_skill_rendered() -> None:
    body = _body()

    assert "Never approve a PR this session opened" in body
    assert "never merge" in body
    assert "can only get comment" in _step(6)


def test_stops_on_an_unreviewable_pr_when_skill_rendered() -> None:
    step = _step(1)

    assert "**Stop** when the PR cannot be read" in step
    assert "closed or merged" in step
    assert "not in `hub.json`" in step


def test_never_checks_out_nor_pushes_when_pr_read() -> None:
    step = _step(1)

    assert "no checkout over a working tree, no commit, no push" in step


def test_resumes_the_pending_review_when_submit_failed() -> None:
    step = _step(7)

    assert "do not create another" in step
    assert "`PENDING`" in step
    assert "/reviews/<id>/events" in step
    assert "stop and report it: never rerun the step" in step


def test_files_recurring_findings_as_external_when_proposed_to_learn() -> None:
    body = _body()

    assert "`/learn`" in body
    assert "provenance: agent-from-external" in body


def test_keeps_project_values_out_when_demo_hub_rendered() -> None:
    body = _body()

    for value in ("demo", "DEM", "jdoe", "Jane Doe", "acme", "AGH"):
        assert value not in body, value
    assert "hub.json" in body


def test_keeps_the_workflow_off_model_invocation_when_skill_rendered() -> None:
    head = _skill_text().split("\n---\n", 1)[0]

    assert "disable-model-invocation: true" in head
    assert 'argument-hint: "<PR>"' in head
