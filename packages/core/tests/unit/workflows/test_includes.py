"""``include``: expansion at load, namespacing, ``with`` and ``inputs``, the primary sink, the
include's graph keys on the block's roots, depth 3 and cycles (AC-213.17)."""

from collections.abc import Mapping
from typing import Any

import pytest

from agent_hub.core.testing.workflow_fakes import KeysOutputs
from agent_hub.core.workflows.document import WorkflowDocument, WorkflowLoadError, parse_workflow
from agent_hub.core.workflows.dry_run import Stub, dry_run
from agent_hub.core.workflows.includes import MAX_INCLUDE_DEPTH
from agent_hub.core.workflows.nodes import AgentNode, FromBinding, ShellNode
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow

DELIVERY = {
    "type": "object",
    "properties": {"delivery": {"type": "string", "enum": ["delivered", "failed"]}},
    "required": ["delivery"],
}


def shell(node_id: str, *depends_on: str, **keys: object) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "shell",
        "command": ["true"],
        "depends_on": list(depends_on),
    } | keys


def include(node_id: str, name: str, *depends_on: str, **keys: object) -> dict[str, Any]:
    return {
        "id": node_id,
        "type": "include",
        "include": name,
        "depends_on": list(depends_on),
    } | keys


def document(name: str, *nodes: dict[str, Any], **top: object) -> dict[str, Any]:
    return {"version": 1, "name": name, "revision": 1, "nodes": list(nodes)} | top


# A block: ``check`` runs ``make $INPUTS.target``, then ``report`` reads it; ``report`` returns.
REVIEW = document(
    "review",
    shell("check", command=["make", "$INPUTS.target"]),
    shell("notes"),
    shell("report", "check", command=["echo", "$check.output"], output_format=DELIVERY),
    inputs={"target": {"required": True}, "mode": {"default": "fast"}},
    returns="report",
)
# Two sinks and no ``returns``.
FORK = document("fork", shell("left"), shell("right"))


def resolver(*documents: dict[str, Any]) -> Any:
    known: Mapping[str, dict[str, Any]] = {raw["name"]: raw for raw in documents}

    def resolve(name: str) -> WorkflowDocument | None:
        raw = known.get(name)
        return None if raw is None else parse_workflow(raw)

    return resolve


def plan_of(
    *nodes: dict[str, Any], library: tuple[dict[str, Any], ...] = (REVIEW, FORK), **top: object
) -> WorkflowPlan:
    return plan_workflow(
        parse_workflow(document("main", *nodes, **top)), includes=resolver(*library)
    )


def problems_of(*nodes: dict[str, Any], **keys: Any) -> list[tuple[str, str]]:
    with pytest.raises(WorkflowLoadError) as caught:
        plan_of(*nodes, **keys)
    return [(problem.key, problem.message) for problem in caught.value.problems]


def nodes_of(plan: WorkflowPlan) -> dict[str, Any]:
    return {node.id: node for node in plan.document.nodes}


def test_namespaces_the_block_when_a_workflow_is_included() -> None:
    plan = plan_of(shell("plan"), include("rev", "review", "plan", **with_target()))

    nodes = nodes_of(plan)
    assert list(nodes) == ["plan", "rev__check", "rev__notes", "rev__report"]
    assert nodes["rev__report"].depends_on == ("rev__check",)
    assert nodes["rev__report"].command == ("echo", "$rev__check.output")
    assert plan.layers == (("plan",), ("rev__check", "rev__notes"), ("rev__report",))


def with_target(target: object = "lint") -> dict[str, Any]:
    return {"with": {"target": target}}


def test_gives_each_include_its_own_namespace_when_one_workflow_is_included_twice() -> None:
    plan = plan_of(include("a", "review", **with_target()), include("b", "review", **with_target()))

    assert {"a__check", "b__check", "a__report", "b__report"} <= set(nodes_of(plan))


def test_replaces_inputs_with_the_with_values_when_the_block_reads_them() -> None:
    plan = plan_of(include("rev", "review", **with_target(3)))

    assert nodes_of(plan)["rev__check"].command == ("make", "3")


def test_fills_the_default_when_with_leaves_an_optional_input_out() -> None:
    fast = document(
        "fast", shell("go", command=["run", "$INPUTS.mode"]), inputs={"mode": {"default": "fast"}}
    )

    plan = plan_of(include("f", "fast"), library=(fast,))

    assert nodes_of(plan)["f__go"].command == ("run", "fast")


@pytest.mark.parametrize(
    ("keys", "message"),
    [
        ({}, 'the input "target" of "review" is required'),
        ({"with": {"target": "x", "typo": 1}}, '"review" has no input named "typo"'),
    ],
)
def test_refuses_the_include_when_with_does_not_fit_the_inputs(
    keys: dict[str, Any], message: str
) -> None:
    assert problems_of(include("rev", "review", **keys)) == [("nodes[0].with", message)]


def test_keeps_a_with_reference_in_the_parent_when_it_reads_a_parent_node() -> None:
    plan = plan_of(shell("plan"), include("rev", "review", "plan", **with_target("$plan.output")))

    assert nodes_of(plan)["rev__check"].command == ("make", "$plan.output")


def test_refuses_a_with_reference_when_the_include_does_not_wait_for_its_node() -> None:
    [(key, message)] = problems_of(
        shell("plan"), include("rev", "review", **with_target("$plan.output"))
    )

    assert key == "nodes[1].include"
    assert message == '"rev__check": command[1]: the node "plan" is not upstream'


def test_attaches_the_include_graph_keys_to_the_block_roots_when_it_has_them() -> None:
    plan = plan_of(
        shell("plan"),
        include(
            "rev",
            "review",
            "plan",
            when="$plan.output == 'go'",
            trigger_rule="all_done",
            **with_target(),
        ),
    )

    nodes = nodes_of(plan)
    for root in ("rev__check", "rev__notes"):
        assert nodes[root].depends_on == ("plan",)
        assert nodes[root].when == "$plan.output == 'go'"
        assert nodes[root].trigger_rule == "all_done"
    assert nodes["rev__report"].depends_on == ("rev__check",)
    assert nodes["rev__report"].when is None
    assert nodes["rev__report"].trigger_rule == "all_success"


def test_joins_both_conditions_when_a_root_has_its_own_when() -> None:
    gated = document("gated", shell("go", when="$INPUTS.flag == 'on'"), inputs={"flag": {}})

    plan = plan_of(
        shell("plan"),
        include(
            "g", "gated", "plan", when="$plan.output == 'go'", **{"with": {"flag": "$plan.output"}}
        ),
        library=(gated,),
    )

    assert nodes_of(plan)["g__go"].when == "$plan.output == 'go' && $plan.output == 'on'"


def test_keeps_the_root_trigger_rule_when_the_root_sets_its_own() -> None:
    own = document("own", shell("a"), shell("b", trigger_rule="one_success"))

    plan = plan_of(shell("p"), include("o", "own", "p", trigger_rule="all_done"), library=(own,))

    assert nodes_of(plan)["o__b"].trigger_rule == "one_success"
    assert nodes_of(plan)["o__a"].trigger_rule == "all_done"


@pytest.mark.parametrize(
    ("include_when", "own_when"),
    [
        ("$p.output == 'a' || $p.output == 'b'", "$INPUTS.flag == 'on'"),
        ("$p.output == 'a'", "$INPUTS.flag == 'on' || $INPUTS.flag == 'x'"),
    ],
)
def test_refuses_the_join_when_either_condition_holds_an_or(
    include_when: str, own_when: str
) -> None:
    gated = document("gated", shell("go", when=own_when), inputs={"flag": {}})

    [(key, message)] = problems_of(
        shell("p"),
        include("g", "gated", "p", when=include_when, **{"with": {"flag": "$p.output"}}),
        library=(gated,),
    )

    assert key == "nodes[1].when"
    assert "'||'" in message


def test_refuses_the_include_when_a_substitution_breaks_a_when() -> None:
    gated = document("gated", shell("go", when="$INPUTS.flag == 'on'"), inputs={"flag": {}})

    [(key, message)] = problems_of(
        include("g", "gated", **{"with": {"flag": "on"}}), library=(gated,)
    )

    assert key == "nodes[0].include"
    assert message.startswith('"g__go": when: no longer parses once "with" is filled in')


def test_waits_for_every_sink_when_a_node_depends_on_the_include() -> None:
    plan = plan_of(include("f", "fork"), shell("after", "f"))

    assert nodes_of(plan)["after"].depends_on == ("f__left", "f__right")


def test_reads_the_returned_node_when_a_node_reads_the_include_output() -> None:
    plan = plan_of(
        include("rev", "review", **with_target()),
        shell("after", "rev", command=["echo", "$rev.output.delivery"]),
    )

    after = nodes_of(plan)["after"]
    assert after.depends_on == ("rev__notes", "rev__report")
    assert after.command == ("echo", "$rev__report.output.delivery")


def test_reads_the_single_sink_when_the_included_workflow_returns_nothing() -> None:
    line = document("line", shell("a"), shell("b", "a"))

    plan = plan_of(
        include("l", "line"), shell("after", "l", command=["echo", "$l.output"]), library=(line,)
    )

    assert nodes_of(plan)["after"].command == ("echo", "$l__b.output")


def test_refuses_the_include_output_when_the_block_has_several_sinks_and_no_returns() -> None:
    [(key, message)] = problems_of(
        include("f", "fork"), shell("after", "f", command=["echo", "$f.output"])
    )

    assert key == "nodes[1].command[1]"
    assert message == '"$f.output": "fork" has several sinks and no \'returns\''


def test_rebinds_returns_and_bindings_to_the_primary_sink_when_they_name_the_include() -> None:
    plan = plan_of(
        include("rev", "review", **with_target()),
        {
            "id": "sum",
            "type": "agent",
            "prompt": "Sum $WITH.r",
            "depends_on": ["rev"],
            "with": {"r": {"from": "$rev.output"}},
        },
        returns="rev",
        outcome_field="delivery",
    )

    assert plan.document.returns == "rev__report"
    summary = nodes_of(plan)["sum"]
    assert isinstance(summary, AgentNode)
    binding = summary.with_["r"]
    assert isinstance(binding, FromBinding)
    assert binding.from_ == "$rev__report.output"


def test_refuses_a_reference_to_a_caller_node_when_the_included_workflow_holds_one() -> None:
    leaky = document("leaky", shell("go", command=["echo", "$plan.output"]))

    [(key, message)] = problems_of(shell("plan"), include("l", "leaky", "plan"), library=(leaky,))

    assert key == "nodes[1].include"
    assert message == '"leaky" reads "$plan.output", which is not one of its nodes'


def test_refuses_the_include_when_no_workflow_has_its_name() -> None:
    assert problems_of(include("x", "nowhere")) == [
        ("nodes[0].include", 'no workflow is named "nowhere"')
    ]


def test_refuses_the_include_when_no_resolver_is_given() -> None:
    raw = document("main", include("x", "review"))

    with pytest.raises(WorkflowLoadError) as caught:
        plan_workflow(parse_workflow(raw))

    assert caught.value.problems[0].message == "this workflow cannot include others here"


def test_refuses_the_include_when_its_id_repeats_a_node_id() -> None:
    assert problems_of(shell("rev"), include("rev", "fork")) == [
        ("nodes[1].id", 'the id "rev" is repeated')
    ]


def chain(length: int) -> tuple[dict[str, Any], ...]:
    """``w1`` includes ``w2`` … includes ``w<length>``, which holds one shell node."""
    last = document(f"w{length}", shell("leaf"))
    return (*(document(f"w{n}", include("inc", f"w{n + 1}")) for n in range(1, length)), last)


def test_expands_three_levels_when_includes_nest_to_the_depth_limit() -> None:
    plan = plan_of(include("inc", "w1"), library=chain(MAX_INCLUDE_DEPTH))

    assert [node.id for node in plan.document.nodes] == ["inc__inc__inc__leaf"]


def test_refuses_the_include_when_nesting_passes_the_depth_limit() -> None:
    [(key, message)] = problems_of(include("inc", "w1"), library=chain(MAX_INCLUDE_DEPTH + 1))

    assert key == "nodes[0].include"
    assert "more than 3 levels" in message


def test_refuses_the_include_when_workflows_include_each_other() -> None:
    ping = document("ping", include("p", "pong"))
    pong = document("pong", include("p", "ping"))

    [(key, message)] = problems_of(include("x", "ping"), library=(ping, pong))

    assert key == "nodes[0].include"
    assert "an include cycle: ping → pong → ping" in message


def test_runs_the_expanded_block_when_a_dry_run_stubs_namespaced_ids() -> None:
    plan = plan_of(
        include("rev", "review", **with_target()),
        shell("after", "rev", command=["echo", "$rev.output.delivery"]),
        returns="rev",
        outcome_field="delivery",
    )
    stubs = {
        "rev__check": Stub(text="ok"),
        "rev__notes": Stub(text="n"),
        "rev__report": Stub(output={"delivery": "delivered"}),
        "after": Stub(text="done"),
    }

    report = dry_run(plan, {}, stubs, outputs=KeysOutputs())

    assert report.run.status == "done"
    assert report.outcome == "delivered"
    assert report.reached == ("rev__check", "rev__notes", "rev__report", "after")


def test_keeps_the_document_when_it_includes_nothing() -> None:
    raw = parse_workflow(document("main", shell("a")))

    assert plan_workflow(raw, includes=resolver()).document is raw
    assert isinstance(raw.nodes[0], ShellNode)
