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
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

SKILL_PATH = "plugin/hub-workflow/skills/review/SKILL.md"
WORKFLOW = BUILTIN_WORKFLOWS / "review-incoming" / "review-incoming.yaml"
RUN = "`./hub workflow run review-incoming"
# AGH-139 E4: the reviewer words the unified vocabulary replaced, matched as whole words.
OLD_WORDS = re.compile(r"\b(?:APPROVE|CHANGES)\b|(?i:\b(?:blockers?|should-fix|nits?)\b)")

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
    for severity in ("blocking", "minor"):
        assert severity in step
    # AGH-139 E4: the unified vocabulary left no old reviewer word in the step.
    assert OLD_WORDS.findall(step) == []
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


def _flat(text: str) -> str:
    return " ".join(text.split())


def test_starts_the_review_incoming_workflow_with_its_inputs_when_rendered() -> None:
    [line] = [line for line in _body().splitlines() if RUN in line]
    command = line[line.index(RUN) :]
    command = command[: command.index("`", 1) + 1]
    inputs = load_workflow_bytes(WORKFLOW.read_bytes(), source=str(WORKFLOW)).document["inputs"]

    assert command.endswith(" --live`"), command
    for name in inputs:
        assert f"--input {name}=" in command, name
    assert "review-incoming" in _skill_text().split("\n---\n", 1)[0]


def test_passes_pr_text_through_files_when_rendered() -> None:
    text = _flat(_body())

    assert '`echo "${TMPDIR:-/tmp}"`' in text
    assert "replacing files left by an earlier run" in text
    assert "with the Write tool" in text
    assert "Never paste PR or issue text into a command" in text
    assert "--input spec=" not in text
    assert '"$(cat' not in text


def test_fetches_the_head_to_a_review_ref_and_deletes_it_when_rendered() -> None:
    read, post = _flat(_step(1)), _flat(_step(7))
    commands = re.findall(r"`([^`]+)`", _body())

    assert "+pull/<n>/head:refs/agent-hub/review/<n>" in read
    assert "never a branch" in read
    assert "`git update-ref -d refs/agent-hub/review/<n>`" in post
    assert "in every ended case" in post
    assert [command for command in commands if "push" in command] == []


def test_posts_only_the_approved_payload_when_run_done() -> None:
    post = _flat(_step(7))

    assert "`run <run>: done, outcome <event>`" in post
    assert "`COMMENT`, `REQUEST_CHANGES` or the approving event" in post
    assert '`"node": "final"`' in post
    assert "`.agent-runs/workflows/<run>/records.jsonl`" in post
    assert "`sha256sum <path>`" in post
    assert "--input <path>" in post
    assert post.index("`sha256sum <path>`") < post.index("one pending review")


def test_posts_nothing_when_gate_rejected() -> None:
    gate, post = _flat(_step(6)), _flat(_step(7))

    assert "`./hub workflow respond <run> --choice reject`" in gate
    assert "Never decide it yourself" in gate
    assert "`done` with no outcome" in post
    assert "post nothing" in post


def test_keeps_a_prose_fallback_when_workflow_unavailable() -> None:
    body = _body()
    [fallback] = [line for line in body.splitlines() if "If `./hub workflow run`" in line]

    assert not re.match(r"\d+\. ", fallback)
    assert "do steps 3-5 by hand" in fallback
    for reviewer in ("`spec-reviewer`", "`quality-reviewer`", "`security-reviewer`"):
        assert reviewer in fallback, reviewer


def test_stops_when_the_pr_json_cannot_be_written_by_redirect_when_rendered() -> None:
    read = _flat(_step(1))

    assert "write its exact output with the Write tool" not in _flat(_body())
    assert "If the sandbox refuses the redirect, stop and say why" in read
    assert "never passes through text you type" in read
