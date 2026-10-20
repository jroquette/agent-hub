"""Planning: Kahn layers, graph errors, references and the outcome declaration (AC-213.3)."""

import pytest

import agent_hub.core.workflows.plan as planning
from agent_hub.core.workflows.document import WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

REPORT_SCHEMA = {
    "type": "object",
    "properties": {
        "delivery": {"type": "string", "enum": ["delivered", "no_changes", "blocked", "failed"]},
        "merged": {"type": "boolean"},
        "url": {"type": "string"},
        "notes": {"type": "string"},
        "files": {"type": "array", "items": {"type": "object", "properties": {"path": {}}}},
    },
    "required": ["delivery", "merged", "url"],
}


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    return {
        "id": node_id,
        "type": "shell",
        "command": ["true"],
        "depends_on": list(depends_on),
    } | keys


def plan_of(*nodes: dict[str, object], **top: object) -> WorkflowPlan:
    document = {"version": 1, "name": "flow", "revision": 1, "nodes": list(nodes)} | top
    return plan_workflow(parse_workflow(document))


def problems_of(*nodes: dict[str, object], **top: object) -> list[tuple[str, str]]:
    with pytest.raises(WorkflowLoadError) as caught:
        plan_of(*nodes, **top)
    return [(problem.key, problem.message) for problem in caught.value.problems]


@pytest.mark.parametrize(
    ("nodes", "layers"),
    [
        ([shell("a")], [["a"]]),
        ([shell("a"), shell("b", "a"), shell("c", "b")], [["a"], ["b"], ["c"]]),
        ([shell("a"), shell("c", "a"), shell("b", "a")], [["a"], ["c", "b"]]),
        ([shell("a"), shell("b"), shell("c", "a", "b")], [["a", "b"], ["c"]]),
        (
            [shell("a"), shell("b", "a"), shell("c", "a"), shell("d", "b", "c")],
            [["a"], ["b", "c"], ["d"]],
        ),
        (
            [shell("x"), shell("a"), shell("y", "x"), shell("b", "a")],
            [["x", "a"], ["y", "b"]],
        ),
        ([shell("d", "c"), shell("c", "a"), shell("a")], [["a"], ["c"], ["d"]]),
    ],
)
def test_layers_nodes_in_declaration_order_when_graph_is_acyclic(
    nodes: list[dict[str, object]], layers: list[list[str]]
) -> None:
    assert plan_of(*nodes).layers == tuple(tuple(layer) for layer in layers)


def test_names_the_nodes_when_graph_has_a_cycle() -> None:
    problems = problems_of(shell("a"), shell("b", "a", "c"), shell("c", "b"))

    assert problems == [("nodes[1].depends_on", "a cycle runs through the nodes b, c")]


def test_reports_a_cycle_when_node_depends_on_itself() -> None:
    assert problems_of(shell("a", "a")) == [
        ("nodes[0].depends_on", "a cycle runs through the nodes a")
    ]


def test_names_the_dependency_when_depends_on_target_is_unknown() -> None:
    assert problems_of(shell("a"), shell("b", "a", "ghost")) == [
        ("nodes[1].depends_on[1]", 'no node has the id "ghost"')
    ]


def test_stops_before_the_cycle_check_when_an_id_repeats() -> None:
    assert problems_of(shell("a"), shell("a", "a")) == [("nodes[1].id", 'the id "a" is repeated')]


@pytest.mark.parametrize(
    "node",
    [
        shell("b", "a", when="$a.output == 'ok'"),
        shell("b", "a", command=["gh", "pr", "view", "$a.output"]),
        shell("b", "a", cwd="$a.output"),
        shell("b", "a", env={"URL": "$a.output.url"}),
        {"id": "b", "type": "halt", "reason": "$a.output", "depends_on": ["a"]},
    ],
)
def test_accepts_reference_when_producer_is_upstream(node: dict[str, object]) -> None:
    producer = shell("a", output_format=REPORT_SCHEMA)

    assert plan_of(producer, node).layers == (("a",), ("b",))


@pytest.mark.parametrize(
    ("node", "key"),
    [
        (shell("b", when="$a.output == 'ok'"), "nodes[1].when"),
        (shell("b", command=["echo", "$a.output"]), "nodes[1].command[1]"),
        ({"id": "b", "type": "agent", "prompt": "Use $a.output"}, "nodes[1].prompt"),
        (
            {"id": "b", "type": "agent", "prompt": "x", "with": {"p": {"from": "$a.output"}}},
            "nodes[1].with.p.from",
        ),
        (
            {"id": "b", "type": "agent", "prompt": "x", "with": {"p": ["$a.output"]}},
            "nodes[1].with.p",
        ),
        ({"id": "b", "type": "approval", "message": "See $a.output"}, "nodes[1].message"),
        (
            {"id": "b", "type": "script", "runtime": "sh", "script": "s.sh", "args": ["$a.output"]},
            "nodes[1].args[0]",
        ),
        (
            {
                "id": "b",
                "type": "loop",
                "prompt": "x",
                "max_iterations": 2,
                "until_bash": ["test", "$a.output"],
            },
            "nodes[1].until_bash[1]",
        ),
    ],
)
def test_refuses_reference_when_producer_is_not_upstream(node: dict[str, object], key: str) -> None:
    assert problems_of(shell("a"), node) == [(key, 'the node "a" is not upstream')]


def test_refuses_reference_when_producer_is_downstream() -> None:
    nodes = (shell("a", when="$b.output == 'x'"), shell("b", "a"))

    assert problems_of(*nodes) == [("nodes[0].when", 'the node "b" is not upstream')]


def test_refuses_reference_when_node_reads_its_own_output() -> None:
    assert problems_of(shell("a", when="$a.output == 'x'")) == [
        ("nodes[0].when", 'the node "a" is not upstream')
    ]


def test_refuses_reference_when_node_id_is_unknown() -> None:
    assert problems_of(shell("a", cwd="$ghost.output")) == [
        ("nodes[0].cwd", 'no node has the id "ghost"')
    ]


def test_refuses_input_reference_when_input_is_not_declared() -> None:
    node = {"id": "a", "type": "agent", "prompt": "Do $INPUTS.issue in $INPUTS.repo"}

    assert problems_of(node, inputs={"issue": {"required": True}}) == [
        ("nodes[0].prompt", 'the input "repo" is not declared')
    ]


@pytest.mark.parametrize("path", ["delivery", "files.0.path", "notes"])
def test_accepts_output_path_when_producer_schema_declares_it(path: str) -> None:
    nodes = (shell("a", output_format=REPORT_SCHEMA), shell("b", "a", cwd=f"$a.output.{path}"))

    assert plan_of(*nodes).layers == (("a",), ("b",))


@pytest.mark.parametrize("schema", [REPORT_SCHEMA, None])
def test_refuses_output_path_when_producer_schema_lacks_it(schema: object) -> None:
    nodes = (shell("a", output_format=schema), shell("b", "a", cwd="$a.output.missing.x"))

    assert problems_of(*nodes) == [
        ("nodes[1].cwd", 'the path "missing.x" is not in the output of "a"')
    ]


def test_reads_the_decision_when_producer_is_an_approval() -> None:
    gate = {"id": "gate", "type": "approval", "message": "Ship?"}
    nodes = (gate, shell("b", "gate", when="$gate.output.decision == 'approve'"))

    assert plan_of(*nodes).layers == (("gate",), ("b",))


@pytest.mark.parametrize(
    "element", ["--title=$a.output", "$a.output.url,", 'gh pr view "$a.output"']
)
def test_refuses_argv_element_when_reference_is_only_part_of_it(element: str) -> None:
    nodes = (shell("a", output_format=REPORT_SCHEMA), shell("b", "a", command=["x", element]))

    [(key, message)] = problems_of(*nodes)
    assert key == "nodes[1].command[1]"
    assert message.endswith("a reference must fill a whole element")


def test_accepts_positional_parameter_when_a_shell_script_reads_a_reference() -> None:
    command = ["sh", "-c", 'gh pr view "$1"', "sh", "$a.output.url"]
    nodes = (shell("a", output_format=REPORT_SCHEMA), shell("b", "a", command=command))

    assert plan_of(*nodes).layers == (("a",), ("b",))


def test_refuses_referenced_cwd_when_node_is_a_hub_step() -> None:
    step = shell("pr", "a", command=["hub", "step", "pr"], cwd="$a.output")

    assert problems_of(shell("a"), step) == [
        ("nodes[1].cwd", "a hub step node's cwd takes no reference")
    ]


@pytest.mark.parametrize(("target", "depends_on"), [("a", ["a"]), ("plan", []), ("ghost", [])])
def test_refuses_resume_when_target_is_not_an_upstream_agent(
    target: str, depends_on: list[str]
) -> None:
    resumer = {
        "id": "fix",
        "type": "agent",
        "prompt": "Fix",
        "depends_on": depends_on,
        "context": {"resume": target},
    }
    plan = {"id": "plan", "type": "agent", "prompt": "Plan"}

    assert problems_of(shell("a"), plan, resumer) == [
        ("nodes[2].context.resume", f'"{target}" is not an upstream agent or loop node')
    ]


def test_accepts_resume_when_target_is_an_upstream_agent() -> None:
    plan = {"id": "plan", "type": "agent", "prompt": "Plan"}
    fix = {
        "id": "fix",
        "type": "agent",
        "prompt": "Fix",
        "depends_on": ["plan"],
        "context": {"resume": "plan"},
    }

    assert plan_of(plan, fix).layers == (("plan",), ("fix",))


@pytest.mark.parametrize("field", ["delivery", "merged"])
def test_accepts_outcome_when_field_is_a_required_boolean_or_enum(field: str) -> None:
    plan = plan_of(
        shell("report", output_format=REPORT_SCHEMA), returns="report", outcome_field=field
    )

    assert plan.document.outcome_field == field


def test_accepts_returns_when_no_outcome_field_is_given() -> None:
    assert plan_of(shell("a"), returns="a").document.returns == "a"


@pytest.mark.parametrize("field", ["url", "notes", "ghost"])
def test_refuses_outcome_field_when_it_is_not_a_required_boolean_or_enum(field: str) -> None:
    [(key, message)] = problems_of(
        shell("report", output_format=REPORT_SCHEMA), returns="report", outcome_field=field
    )

    assert key == "outcome_field"
    assert message.startswith("must be a required boolean, or a string with an enum")


def test_refuses_outcome_field_when_returns_has_no_output_format() -> None:
    [(key, _)] = problems_of(shell("a"), returns="a", outcome_field="delivery")

    assert key == "outcome_field"


def test_refuses_outcome_field_when_returns_is_absent() -> None:
    assert problems_of(shell("a"), outcome_field="delivery") == [
        ("outcome_field", "'outcome_field' needs 'returns'")
    ]


def test_refuses_returns_when_it_names_no_node() -> None:
    assert problems_of(shell("a"), returns="ghost") == [("returns", 'no node has the id "ghost"')]


@pytest.mark.parametrize(
    ("command", "index", "ending"),
    [
        (["$a.output", "x"], 0, "not the program"),
        (["sh", "-c", "$a.output"], 2, "pass it after the script"),
        (["bash", "-lc", "$a.output", "bash"], 2, "pass it after the script"),
        (
            ["sh", "-e", "-c", "-x", "$a.output"],
            2,
            "the element right after -c is the literal script",
        ),
    ],
)
def test_refuses_argv_reference_when_it_is_the_program_or_a_script(
    command: list[str], index: int, ending: str
) -> None:
    [(key, message)] = problems_of(shell("a"), shell("b", "a", command=command))

    assert key == f"nodes[1].command[{index}]"
    assert message.endswith(ending)


def test_refuses_until_bash_reference_when_it_is_partial() -> None:
    loop = {
        "id": "l",
        "type": "loop",
        "prompt": "x",
        "max_iterations": 2,
        "depends_on": ["a"],
        "until_bash": ["test", "-f", "x$a.output"],
    }

    [(key, _)] = problems_of(shell("a"), loop)

    assert key == "nodes[1].until_bash[2]"


@pytest.mark.parametrize("text", ["Use $INPUTS here", "Read $a.output[0]"])
def test_refuses_reference_when_it_is_malformed(text: str) -> None:
    node = {"id": "b", "type": "agent", "prompt": text, "depends_on": ["a"]}

    [(key, message)] = problems_of(shell("a"), node)

    assert key == "nodes[1].prompt"
    assert "malformed reference" in message


def test_accepts_reference_when_producer_is_a_transitive_ancestor() -> None:
    nodes = (shell("a"), shell("b", "a"), shell("c", "b", cwd="$a.output"))

    assert plan_of(*nodes).layers == (("a",), ("b",), ("c",))


def test_plans_a_long_chain_when_nodes_are_declared_in_reverse() -> None:
    count = 1000
    nodes = [shell(f"n{index}", f"n{index - 1}") for index in range(count - 1, 0, -1)]
    nodes[0]["cwd"] = "$n0.output"
    nodes.append(shell("n0"))

    plan = plan_of(*nodes)

    assert len(plan.layers) == count
    assert plan.layers[0] == ("n0",)
    assert plan.layers[-1] == (f"n{count - 1}",)


def test_names_only_the_cycle_when_other_nodes_wait_on_it() -> None:
    nodes = (shell("a", "b"), shell("b", "a"), shell("c", "a"), shell("d", "c"))

    assert problems_of(*nodes) == [("nodes[0].depends_on", "a cycle runs through the nodes a, b")]


def test_cuts_the_echoed_id_when_it_is_long() -> None:
    [(_, message)] = problems_of(shell("a", "x" * 500))

    assert len(message) < 120


def test_shows_ten_names_then_a_count_when_the_cycle_is_long() -> None:
    count = 12
    nodes = [shell(f"n{index}", f"n{(index + 1) % count}") for index in range(count)]

    [(_, message)] = problems_of(*nodes)

    names = ", ".join(f"n{index}" for index in range(10))
    assert message == f"a cycle runs through the nodes {names} and 2 more"


GATE = {"id": "ok", "type": "approval", "message": "Ship?"}


@pytest.mark.parametrize(
    ("nodes", "key"),
    [
        (
            (
                shell("a"),
                GATE | {"depends_on": ["a"]},
                {"id": "nap", "type": "wait", "duration": "1h", "depends_on": ["a"]},
            ),
            "nodes[2]",
        ),
        (
            (
                {
                    "id": "g",
                    "type": "loop_group",
                    "max_iterations": 2,
                    "until_when": "$ok.output.decision == 'approve'",
                    "nodes": [GATE],
                },
                {"id": "nap", "type": "wait", "duration": "1h"},
            ),
            "nodes[1]",
        ),
        (
            (
                {
                    "id": "g",
                    "type": "loop_group",
                    "max_iterations": 2,
                    "until_when": "$ok.output.decision == 'approve'",
                    "nodes": [GATE, {"id": "ask", "type": "wait", "attention": "Why?"}],
                },
            ),
            "nodes[0].nodes[1]",
        ),
    ],
)
def test_refuses_two_suspendable_nodes_when_neither_is_upstream_of_the_other(
    nodes: tuple[dict[str, object], ...], key: str
) -> None:
    [(found, message)] = problems_of(*nodes)

    assert found == key
    assert "no order between" in message


def test_accepts_two_suspendable_nodes_when_one_depends_on_the_other() -> None:
    nap = {"id": "nap", "type": "wait", "duration": "1h", "depends_on": ["ok"]}

    assert plan_of(GATE, nap).layers == (("ok",), ("nap",))


def test_refuses_reference_when_agent_cwd_names_unknown_node() -> None:
    node = {"id": "a", "type": "loop", "prompt": "Go.", "max_iterations": 1, "until": "DONE"}

    assert problems_of({**node, "cwd": "$ghost.output.path"}) == [
        ("nodes[0].cwd", 'no node has the id "ghost"')
    ]


def test_refuses_stdin_reference_when_unknown_or_not_whole() -> None:
    nodes = (
        shell("a"),
        shell("b", "a", stdin="$ghost.output"),
        shell("c", "a", stdin="x $a.output"),
    )

    assert problems_of(*nodes) == [
        ("nodes[1].stdin", 'no node has the id "ghost"'),
        ("nodes[2].stdin", "a reference fills the whole stdin, or none is used"),
    ]


def action(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "action", "action": "send-queue-message"}
    return node | {"depends_on": list(depends_on)} | keys


def expect(node_id: str, *depends_on: str, **keys: object) -> dict[str, object]:
    node = {"id": node_id, "type": "expect", "action": "get-order", "every": "10s"}
    node |= {"timeout": "1m", "until_when": "$self.output.status == 'ON_HOLD'"}
    return node | {"depends_on": list(depends_on)} | keys


def reads(text: str) -> dict[str, object]:
    return {"with": {"order": text}}


def test_reports_missing_when_run_context_not_captured() -> None:
    captured = {"capture": {"order_id": "$self.output.order_id"}}
    group = {"id": "poll", "type": "loop_group", "max_iterations": 2, "until_when": "$CTX.n == 1"}
    group |= {"nodes": [expect("check", **{"capture": {"n": "$self.output.n"}})]}

    missing = [action("a"), action("b", "a", **reads("$CTX.order_id"))]
    assert problems_of(*missing, kind="scenario") == [
        ("nodes[1].with.order", "$CTX.order_id is not captured upstream")
    ]
    later = [action("a", **reads("$CTX.order_id")), expect("b", "a", **captured)]
    assert problems_of(*later, kind="scenario") == [
        ("nodes[0].with.order", "$CTX.order_id is not captured upstream")
    ]
    plan = plan_of(
        expect("a", **captured),
        action("b", "a", **reads("x $CTX.order_id")),
        group,
        action("c", "poll", **reads("$CTX.n")),
        kind="scenario",
    )
    assert plan.captures == {
        "order_id": planning.Capture("a", "$self.output.order_id"),
        "n": planning.Capture("poll__check", "$self.output.n"),
    }


def test_reports_twice_when_run_context_captured_twice_on_path() -> None:
    captured = {"capture": {"order_id": "$self.output.order_id"}}

    assert problems_of(expect("a", **captured), expect("b", "a", **captured)) == [
        ("nodes[1].capture.order_id", '$CTX.order_id is already captured by "a"')
    ]


@pytest.mark.parametrize(
    ("node", "key"),
    [
        (action("a", **reads("$self.output.id")), "nodes[0].with.order"),
        (action("a", when="$self.output.id == 'x'"), "nodes[0].when"),
        (expect("a", when="$self.output.id == 'x'"), "nodes[0].when"),
        (
            {
                "id": "poll",
                "type": "loop_group",
                "max_iterations": 2,
                "until_when": "$self.output.id == 'x'",
                "nodes": [action("a")],
            },
            "nodes[0].until_when",
        ),
    ],
)
def test_reports_self_when_run_context_self_outside_until(
    node: dict[str, object], key: str
) -> None:
    message = "$self reads only in an expect's until_when or a capture"
    assert problems_of(node, kind="scenario") == [(key, message)]


def test_checks_with_refs_when_action_node_texts_read() -> None:
    problems = problems_of(
        action("a", **{"with": {"id": "$nope.output", "items": ["x", {"y": "$INPUTS.gone"}]}}),
        expect("b", until_when="$ghost.output == 'x'"),
        action("c", capture={"y": "$other.output"}),
    )

    assert problems == [
        ("nodes[0].with.id", 'no node has the id "nope"'),
        ("nodes[0].with.items", 'the input "gone" is not declared'),
        ("nodes[1].until_when", 'no node has the id "ghost"'),
        ("nodes[2].capture.y", 'no node has the id "other"'),
    ]
    assert plan_of(action("a"), action("b", "a", **reads("$a.output.message_id"))).layers


def test_keeps_layers_when_action_nodes_beside_readonly_shell() -> None:
    plan = plan_of(
        shell("look", mutates_checkout=False), action("send"), expect("wait"), shell("write")
    )

    assert plan.layers == (("look", "send", "wait"), ("write",))


def test_reports_ctx_when_run_context_read_in_capture() -> None:
    first = expect("a", capture={"order_id": "$self.output.order_id"})
    second = action("b", "a", capture={"copy": "$CTX.order_id"})

    assert problems_of(first, second) == [
        ("nodes[1].capture.copy", "a capture reads no $CTX: capture from $self or node outputs")
    ]
    assert plan_of(first, action("b", "a", capture={"copy": "$a.output.order_id"})).captures


def test_keeps_workflow_text_when_run_context_tokens_in_plain_workflow() -> None:
    plan = plan_of(
        shell("self", command=["echo", "cost $CTX and $CTX.total"]),
        shell("b", "self", command=["echo", "$self.output"]),
    )

    assert plan.layers == (("self",), ("b",))
    assert plan.captures == {}


def test_refuses_tokens_when_run_context_tokens_in_scenario() -> None:
    assert problems_of(action("a", **reads("cost $CTX")), kind="scenario") == [
        ("nodes[0].with.order", '"$CTX": malformed reference')
    ]
    assert problems_of(action("self"), kind="scenario") == [
        ("nodes[0].id", "the id self is reserved: $self reads a node's own output")
    ]
