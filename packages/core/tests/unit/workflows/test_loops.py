"""The ``loop`` node: its channels, its cap and its session, run through the engine."""

from collections.abc import Mapping

import pytest

from agent_hub.core.testing.workflow_fakes import (
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.loops import last_line
from agent_hub.core.workflows.ports import NodeReply
from agent_hub.core.workflows.run_state import RunReport

DONE_SCHEMA = {"type": "object", "properties": {"done": {"type": "boolean"}}, "required": ["done"]}


def a_loop(**keys: object) -> dict[str, object]:
    return {"id": "fix", "type": "loop", "prompt": "Fix it.", "max_iterations": 3} | keys


def run(loop: Mapping[str, object], runner: ScriptedRunner) -> tuple[RunReport, ListRecorder]:
    recorder = ListRecorder()
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5)
    report = run_workflow(
        a_plan(loop, {"id": "after", "type": "shell", "command": ["true"], "depends_on": ["fix"]}),
        {},
        ports,
    )
    return report, recorder


def fix_ends(recorder: ListRecorder) -> list[tuple[int, str, str | None]]:
    return [(e.attempt, e.status, e.failure_kind) for e in recorder.ends if e.node == "fix"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [("work\nDONE\n", "DONE"), ("  DONE  \n\n", "DONE"), ("", ""), ("one line", "one line")],
)
def test_reads_the_last_non_blank_line_when_text_ends(text: str, expected: str) -> None:
    assert last_line(text) == expected


def test_stops_when_the_final_line_equals_until() -> None:
    runner = ScriptedRunner({"fix": ["still going", "work\nDONE"]})

    report, recorder = run(a_loop(until="DONE"), runner)

    assert fix_ends(recorder) == [(1, "ok", None), (2, "ok", None)]
    assert [call.iteration for call in runner.calls if call.node.id == "fix"] == [1, 2]
    assert recorder.end_of("fix").output == "work\nDONE"
    assert report.status == "done"


def test_keeps_going_when_until_appears_before_the_final_line() -> None:
    runner = ScriptedRunner({"fix": ["DONE\nnot yet", "DONE"]})

    _, recorder = run(a_loop(until="DONE"), runner)

    assert len(fix_ends(recorder)) == 2


def test_stops_when_until_field_is_true() -> None:
    loop = a_loop(until_field="done", output_format=DONE_SCHEMA)
    runner = ScriptedRunner({"fix": ['{"done": false}', '{"done": true}']})

    _, recorder = run(loop, runner)

    assert recorder.end_of("fix").output == {"done": True}
    assert len(fix_ends(recorder)) == 2


def test_stops_when_until_bash_exits_zero() -> None:
    runner = ScriptedRunner(exits={"fix": [1, 0]})

    _, recorder = run(a_loop(until_bash=["make", "check"]), runner)

    assert runner.until_calls == [("fix", ("make", "check")), ("fix", ("make", "check"))]
    assert len(fix_ends(recorder)) == 2


def test_skips_until_bash_when_until_already_matched() -> None:
    runner = ScriptedRunner({"fix": ["DONE"]})

    run(a_loop(until="DONE", until_bash=["make", "check"]), runner)

    assert runner.until_calls == []


def test_fails_max_iterations_when_no_channel_is_met_by_the_cap() -> None:
    runner = ScriptedRunner({"fix": ["a", "b", "c", "d"]})

    report, recorder = run(a_loop(until="DONE"), runner)

    assert fix_ends(recorder) == [(1, "ok", None), (2, "ok", None), (3, "failed", "max_iterations")]
    assert recorder.end_of("after").skip_cause == "upstream_failed"
    assert report.status == "failed"


def test_threads_the_session_when_context_is_not_fresh() -> None:
    replies = [NodeReply("a", session="s1"), NodeReply("b", session="s2"), "DONE"]
    runner = ScriptedRunner({"fix": replies})

    run(a_loop(until="DONE"), runner)

    assert [call.resume_session for call in runner.calls] == [None, "s1", "s2", None]


def test_starts_each_iteration_afresh_when_fresh_context_is_set() -> None:
    runner = ScriptedRunner({"fix": [NodeReply("a", session="s1"), "DONE"]})

    run(a_loop(until="DONE", fresh_context=True), runner)

    assert [call.resume_session for call in runner.calls] == [None, None, None]


def test_retries_an_iteration_with_a_new_attempt_when_it_fails_transiently() -> None:
    runner = ScriptedRunner({"fix": [NodeFailedError("transient"), "DONE"]})

    _, recorder = run(a_loop(until="DONE"), runner)

    assert fix_ends(recorder) == [(1, "failed", "transient"), (2, "ok", None)]
    assert [call.iteration for call in runner.calls if call.node.id == "fix"] == [1, 1]
