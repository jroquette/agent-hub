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
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.engine import EnginePorts, WorkflowEngineError, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.loops import last_line
from agent_hub.core.workflows.plan import plan_workflow
from agent_hub.core.workflows.ports import NodeReply
from agent_hub.core.workflows.run_state import RunReport, RunState
from agent_hub.core.workflows.substitution import NodeResult

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
    assert recorder.end_of("fix").output == "c"
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


def test_keeps_going_when_until_field_is_truthy_but_not_true() -> None:
    loop = a_loop(until_field="done", output_format=DONE_SCHEMA)
    runner = ScriptedRunner({"fix": ['{"done": "true"}', '{"done": 1}', '{"done": true}']})

    report, recorder = run(loop, runner)

    assert len(fix_ends(recorder)) == 3
    assert report.status == "done"


def test_restarts_from_the_first_turn_when_a_loop_is_retried() -> None:
    loop = a_loop(until="DONE", max_iterations=2, retry={"max_attempts": 1, "on_error": "all"})
    replies = [NodeReply(text, session=f"s{n}") for n, text in enumerate("abcd")]
    runner = ScriptedRunner({"fix": replies})

    _, recorder = run(loop, runner)

    fix_calls = [call for call in runner.calls if call.node.id == "fix"]
    assert [call.iteration for call in fix_calls] == [1, 2, 1, 2]
    assert [call.resume_session for call in fix_calls] == [None, "s0", None, "s2"]
    assert [status for _, status, _ in fix_ends(recorder)] == ["ok", "failed", "ok", "failed"]
    assert [(retry.attempt, retry.kind) for _, retry in recorder.retries] == [(2, "max_iterations")]


# ``loop_group``: a body sub-graph repeated per iteration (AC-213.17).

NEVER = "$INPUTS.mode == 'on'"


def body_shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    return {
        "id": node_id,
        "type": "shell",
        "command": ["true"],
        "depends_on": list(depends_on),
    } | keys


def a_group(*body: dict[str, object], **keys: object) -> dict[str, object]:
    group = {"id": "g", "type": "loop_group", "max_iterations": 3, "nodes": list(body)}
    return group | (keys or {"until_when": "$b.output == 'done'"})


def run_group(
    group: Mapping[str, object], runner: ScriptedRunner, *after: dict[str, object]
) -> tuple[RunReport, ListRecorder]:
    recorder = ListRecorder()
    ports = EnginePorts(runner, recorder, FakeClock(), KeysOutputs(), lambda: 0.5)
    plan = a_plan(group, *after, inputs={"mode": {"default": "off"}})
    return run_workflow(plan, {}, ports), recorder


def steps(recorder: ListRecorder) -> list[tuple[str, int, str]]:
    return [(end.node, end.attempt, end.status) for end in recorder.ends]


def test_runs_the_body_per_iteration_under_recorded_ids_when_a_group_loops() -> None:
    runner = ScriptedRunner({"g__b": ["no", "done"]})

    report, recorder = run_group(a_group(body_shell("a"), body_shell("b", "a")), runner)

    assert runner.ran() == ["g__a", "g__b", "g__a", "g__b"]
    assert steps(recorder) == [
        ("g__a", 1, "ok"),
        ("g__b", 1, "ok"),
        ("g__a", 2, "ok"),
        ("g__b", 2, "ok"),
        ("g", 1, "ok"),
    ]
    assert [start.node for start in recorder.starts][0] == "g"
    assert report.status == "done"


def test_reads_the_previous_iteration_when_a_body_node_reads_loop_prev_in_a_group() -> None:
    group = a_group(body_shell("a"), body_shell("b", "a", command=["echo", "$LOOP_PREV.a.output"]))
    runner = ScriptedRunner({"g__a": ["first", "second"], "g__b": ["no", "done"]})

    run_group(group, runner)

    assert [call.argv for call in runner.calls if call.node.id == "g__b"] == [
        ("echo", ""),
        ("echo", "first"),
    ]


def test_ends_the_group_when_its_until_bash_exits_zero() -> None:
    group = a_group(body_shell("b"), until_bash=["test", "$b.output"])
    runner = ScriptedRunner({"g__b": ["x", "y"]}, exits={"g": [1, 0]})

    report, _ = run_group(group, runner)

    assert runner.until_calls == [("g", ("test", "x")), ("g", ("test", "y"))]
    assert report.status == "done"


def test_outputs_a_map_of_body_ids_when_the_group_completes() -> None:
    after = body_shell("after", "g", command=["echo", "$g.output.b"])
    runner = ScriptedRunner({"g__b": ["done"]})

    run_group(a_group(body_shell("a", when=NEVER), body_shell("b")), runner, after)

    assert runner.calls[-1].argv == ("echo", "done")


def test_fails_the_group_max_iterations_when_no_channel_is_met_by_the_cap() -> None:
    after = body_shell("after", "g")

    report, recorder = run_group(a_group(body_shell("b")), ScriptedRunner(), after)

    end = recorder.end_of("g")
    assert (end.status, end.failure_kind, end.output) == ("failed", "max_iterations", {"b": ""})
    assert recorder.end_of("after").skip_cause == "upstream_failed"
    assert [e.attempt for e in recorder.ends if e.node == "g__b"] == [1, 2, 3]
    assert report.status == "failed"


def test_fails_the_group_after_its_all_done_body_nodes_when_a_body_node_fails() -> None:
    body = (
        body_shell("a"),
        body_shell("b", "a"),
        body_shell("report", "a", trigger_rule="all_done"),
    )
    runner = ScriptedRunner({"g__a": [NodeFailedError("exec_failed")]})

    report, recorder = run_group(a_group(*body), runner)

    assert runner.ran() == ["g__a", "g__report"]
    assert recorder.end_of("g__b").skip_cause == "upstream_failed"
    assert (recorder.end_of("g").status, recorder.end_of("g").failure_kind) == (
        "failed",
        "exec_failed",
    )
    assert report.status == "failed"


def test_binds_if_skipped_when_a_body_producer_skips_in_the_iteration_of_a_group() -> None:
    agent = {
        "id": "b",
        "type": "agent",
        "prompt": "Got $WITH.x",
        "depends_on": ["s"],
        "trigger_rule": "all_done",
        "with": {"x": {"from": "$s.output", "if_skipped": "none"}},
    }
    runner = ScriptedRunner({"g__b": ["done"]})

    run_group(a_group(body_shell("s", when=NEVER), agent), runner)

    assert runner.calls[0].prompt == "Got none"


def test_fails_the_body_node_when_a_binding_reads_a_failed_producer_in_a_group() -> None:
    agent = {
        "id": "b",
        "type": "agent",
        "prompt": "Got $WITH.x",
        "depends_on": ["s"],
        "trigger_rule": "all_done",
        "with": {"x": {"from": "$s.output", "if_skipped": "none"}},
    }
    runner = ScriptedRunner({"g__s": [NodeFailedError("exec_failed")]})

    _, recorder = run_group(a_group(body_shell("s"), agent), runner)

    assert recorder.end_of("g__b").failure_kind == "config"


@pytest.mark.parametrize(("fresh", "resumed"), [(False, [None, "s1"]), (True, [None, None])])
def test_threads_body_sessions_by_fresh_context_when_a_group_iterates(
    fresh: bool,  # noqa: FBT001 - a parametrized case
    resumed: list[str | None],
) -> None:
    agent = {"id": "b", "type": "agent", "prompt": "Go."}
    runner = ScriptedRunner({"g__b": [NodeReply("no", session="s1"), NodeReply("done", "s2")]})

    run_group(a_group(agent, until_when="$b.output == 'done'", fresh_context=fresh), runner)

    assert [call.resume_session for call in runner.calls] == resumed


def test_keeps_body_attempts_monotonic_when_a_body_node_retries_across_iterations() -> None:
    runner = ScriptedRunner({"g__b": [NodeFailedError("transient"), "no", "done"]})

    _, recorder = run_group(a_group(body_shell("b")), runner)

    assert [(e.attempt, e.status) for e in recorder.ends if e.node == "g__b"] == [
        (1, "failed"),
        (2, "ok"),
        (3, "ok"),
    ]


def test_skips_the_whole_body_when_the_group_condition_is_false() -> None:
    report, recorder = run_group(
        a_group(body_shell("b"), until_when="$b.output == 'x'", when=NEVER), ScriptedRunner()
    )

    assert steps(recorder) == [("g", 1, "skipped")]
    assert report.status == "done"


def group_problems(*nodes: dict[str, object]) -> list[tuple[str, str]]:
    with pytest.raises(WorkflowLoadError) as caught:
        a_plan(*nodes, inputs={"mode": {"default": "off"}})
    return [(problem.key, problem.message) for problem in caught.value.problems]


@pytest.mark.parametrize(
    ("nodes", "expected"),
    [
        (
            [body_shell("b"), a_group(body_shell("b"))],
            ("nodes[1].nodes[0].id", 'the body id "b" is already a node id'),
        ),
        (
            [body_shell("x"), a_group(body_shell("b", "x"), until_when="$b.output == 'y'")],
            ("nodes[1].nodes[0].depends_on[0]", 'no body node has the id "x"'),
        ),
        (
            [a_group(body_shell("b", command=["echo", "$LOOP_PREV.c.output"]))],
            ("nodes[0].nodes[0].command[1]", 'no body node has the id "c"'),
        ),
        (
            [body_shell("x"), a_group(body_shell("b", command=["echo", "$x.output"]))],
            ("nodes[1].nodes[0].command[1]", 'the node "x" is not upstream'),
        ),
        (
            [a_group(body_shell("a", command=["echo", "$b.output"]), body_shell("b"))],
            ("nodes[0].nodes[0].command[1]", 'the node "b" is not upstream'),
        ),
        (
            [a_group(body_shell("b")), body_shell("c", "g", command=["echo", "$g.output.z"])],
            ("nodes[1].command[1]", 'the path "z" is not in the output of "g"'),
        ),
        (
            [a_group(body_shell("b"), until_when="$c.output == 'x'")],
            ("nodes[0].until_when", 'no node has the id "c"'),
        ),
    ],
)
def test_refuses_the_group_when_its_body_breaks_a_rule(
    nodes: list[dict[str, object]], expected: tuple[str, str]
) -> None:
    assert expected in group_problems(*nodes)


def test_allows_upstream_reads_from_the_body_when_the_group_waits_for_them() -> None:
    plan = a_plan(
        body_shell("x"),
        a_group(
            body_shell("b", command=["echo", "$x.output"]),
            depends_on=["x"],
            until_when="$b.output == 'y'",
        ),
        body_shell("c", "g", command=["echo", "$g.output.b"]),
    )

    [group] = [node for node in plan.document.nodes if node.id == "g"]
    assert [node.id for node in group.nodes] == ["g__b"]
    assert plan.bodies["g"] == (("g__b",),)


def test_refuses_the_group_when_it_has_no_until_channel() -> None:
    [(_, message)] = group_problems(
        {"id": "g", "type": "loop_group", "max_iterations": 2, "nodes": [body_shell("b")]}
    )

    assert message == "give at least one of 'until_bash' or 'until_when'"


def test_keeps_body_ids_local_when_an_included_workflow_holds_a_group() -> None:
    inner = {
        "version": 1,
        "name": "inner",
        "revision": 1,
        "nodes": [
            body_shell("x"),
            a_group(
                body_shell("b", command=["echo", "$x.output", "$LOOP_PREV.b.output"]),
                depends_on=["x"],
                until_when="$b.output == 'done'",
            ),
        ],
    }
    raw = {
        "version": 1,
        "name": "main",
        "revision": 1,
        "nodes": [{"id": "i", "type": "include", "include": "inner"}],
    }

    plan = plan_workflow(parse_workflow(raw), includes=lambda name: parse_workflow(inner))

    [_, group] = plan.document.nodes
    assert group.id == "i__g"
    [body] = group.nodes
    assert body.id == "i__g__b"
    assert body.command == ("echo", "$i__x.output", "$LOOP_PREV.i__g__b.output")
    assert group.until_when == "$i__g__b.output == 'done'"


def test_reuses_the_group_without_running_its_body_when_a_run_resumes_after_it() -> None:
    plan = a_plan(
        a_group(body_shell("b")), body_shell("after", "g", command=["echo", "$g.output.b"])
    )
    prior = RunState(
        nodes={
            "g": NodeResult("completed", {"b": "done"}),
            "g__b": NodeResult("completed", "done"),
        },
        attempts={"g": 1, "g__b": 1},
    )
    runner = ScriptedRunner()
    ports = EnginePorts(runner, ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5)

    run_workflow(plan, {}, ports, prior=prior)

    assert runner.ran() == ["after"]
    assert runner.calls[0].argv == ("echo", "done")


def test_refuses_the_run_when_a_group_body_holds_an_approval() -> None:
    approval = {"id": "ok", "type": "approval", "message": "Ship?"}
    plan = a_plan(a_group(approval, until_when="$ok.output.decision == 'approve'"))
    ports = EnginePorts(ScriptedRunner(), ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5)

    with pytest.raises(WorkflowEngineError, match="approval"):
        run_workflow(plan, {}, ports)


def test_renders_a_body_prompt_file_in_the_body_scope_when_a_group_iterates() -> None:
    writer = {"id": "w", "type": "agent", "prompt_file": "w.md", "depends_on": ["x"]}
    group = a_group(body_shell("x"), writer, until_when="$w.output == 'done'")
    runner = ScriptedRunner({"g__x": ["X1", "X2"], "g__w": ["no", "done"]})

    run_group(group, runner)

    template = "$x.output after $LOOP_PREV.x.output"
    calls = [call for call in runner.calls if call.node.id == "g__w"]
    assert [call.scope.render(template, call.context) for call in calls] == [
        "X1 after ",
        "X2 after X1",
    ]


def included_group() -> dict[str, object]:
    writer = {"id": "w", "type": "agent", "prompt_file": "w.md", "depends_on": ["b"]}
    return {
        "version": 1,
        "name": "inner",
        "revision": 1,
        "inputs": {"issue": {"required": True}},
        "nodes": [
            body_shell("prep"),
            a_group(body_shell("b"), writer, depends_on=["prep"], until_when="$w.output == 'x'"),
        ],
    }


def test_renders_an_included_body_prompt_file_in_its_scope_when_the_group_runs() -> None:
    raw = {
        "version": 1,
        "name": "main",
        "revision": 1,
        "nodes": [
            body_shell("b"),
            {"id": "i", "type": "include", "include": "inner", "with": {"issue": "CHILD"}},
        ],
    }
    plan = plan_workflow(parse_workflow(raw), includes=lambda _: parse_workflow(included_group()))
    runner = ScriptedRunner({"i__prep": ["P"], "i__g__b": ["B"], "i__g__w": ["x"]})
    ports = EnginePorts(runner, ListRecorder(), FakeClock(), KeysOutputs(), lambda: 0.5)

    run_workflow(plan, {}, ports)

    [call] = [call for call in runner.calls if call.node.id == "i__g__w"]
    template = "$INPUTS.issue: $prep.output, $b.output"
    assert call.scope.render(template, call.context) == "CHILD: P, B"
