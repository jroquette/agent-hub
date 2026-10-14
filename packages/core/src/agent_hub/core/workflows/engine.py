"""The workflow engine (ADR 0032): a pure interpreter of a plan over its ports.

Layers run in order and, in v1, one node at a time; a failure never stops later layers. Each
node goes through: the resume cache, its ``trigger_rule``, its ``when:``, then its attempts. A
resumed run reuses a node that completed before (``prior_success``) unless it is ``always_run``
or a dependency now ends differently. Every visit takes the node's next ``attempt``, counted over
the whole run and its resumes, so no two steps share one. A failed attempt asks
``retry_decision`` and waits through the ``Clock``; each retry is recorded. A ``halt`` ends the
run ``cancelled``. ``approval`` nodes come later: a plan holding one is refused before any step.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.conditions import WhenFail, WhenSkip, evaluate_when
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord, retry_decision
from agent_hub.core.workflows.loops import Turn, check_turn, next_session, until_met
from agent_hub.core.workflows.nodes import (
    AgentNode,
    ApprovalNode,
    ExecutableNode,
    FromBinding,
    HaltNode,
    LoopNode,
    Node,
    ScriptNode,
    ShellNode,
)
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import (
    Clock,
    NodeCall,
    NodeRunner,
    OutputValidator,
    RunEnd,
    RunRecorder,
    SkipCause,
    StepEnd,
    StepStart,
)
from agent_hub.core.workflows.run_state import (
    NodeEnd,
    RunReport,
    RunState,
    authored_outcome,
    run_status,
    trigger_skip,
)
from agent_hub.core.workflows.substitution import (
    NodeRef,
    NodeResult,
    RefContext,
    SubstitutionError,
    echo,
    parse_ref,
    render,
    render_argv,
    resolve,
)


class WorkflowEngineError(AgentHubError):
    """A run the engine refuses to start: unsupported nodes, inputs that do not fit."""


@dataclass(frozen=True)
class EnginePorts:
    runner: NodeRunner
    recorder: RunRecorder
    clock: Clock
    outputs: OutputValidator
    jitter: Callable[[], float]


def run_workflow(
    plan: WorkflowPlan,
    inputs: Mapping[str, JsonValue],
    ports: EnginePorts,
    *,
    prior: RunState | None = None,
) -> RunReport:
    """Run ``plan`` with ``inputs``, resuming ``prior`` when given; the run's report."""
    for node in plan.document.nodes:
        if isinstance(node, ApprovalNode):
            msg = f"the node {echo(node.id)} is an approval, which this engine does not run yet"
            raise WorkflowEngineError(msg)
    return _Run(plan, start_inputs(plan, inputs), ports, prior=prior or RunState()).execute()


def start_inputs(plan: WorkflowPlan, given: Mapping[str, JsonValue]) -> dict[str, JsonValue]:
    """``given`` with each declared default filled in; a missing or unknown input is refused."""
    declared = plan.document.inputs
    if unknown := sorted(set(given) - set(declared)):
        raise WorkflowEngineError(f"no input is named {echo(unknown[0])}")
    values = dict(given)
    for name, spec in declared.items():
        if name not in values and spec.required:
            raise WorkflowEngineError(f"the input {echo(name)} is required")
        values.setdefault(name, spec.default)
    return values


class _Run:
    def __init__(
        self,
        plan: WorkflowPlan,
        inputs: dict[str, JsonValue],
        ports: EnginePorts,
        *,
        prior: RunState,
    ) -> None:
        self.plan, self.inputs, self.ports, self.prior = plan, inputs, ports, prior
        self.ends: dict[str, NodeEnd] = {}
        self.attempts = dict(prior.attempts)
        self.sessions = dict(prior.sessions)
        self.halted_by: str | None = None

    def execute(self) -> RunReport:
        nodes = {node.id: node for node in self.plan.document.nodes}
        for layer in self.plan.layers:
            for node_id in layer:
                self._visit(nodes[node_id])
                if self.halted_by is not None:
                    return self._finish()
        return self._finish()

    def _finish(self) -> RunReport:
        status, reason = run_status(self.ends, self.halted_by)
        document = self.plan.document
        outcome = authored_outcome(document.returns, document.outcome_field, self.ends)
        self.ports.recorder.run_ended(RunEnd(status, self.ports.clock.now(), outcome, reason))
        results = {**self.prior.nodes, **{n: end.result for n, end in self.ends.items()}}
        state = RunState(results, self.attempts, self.sessions)
        return RunReport(status, outcome, reason, state)

    def _visit(self, node: Node) -> None:
        if self._reusable(node):
            self._skip(node, "prior_success", result=self.prior.nodes[node.id])
        elif (blocked := trigger_skip(node, self.ends)) is not None:
            self._skip(node, *blocked)
        elif node.when is not None and self._stopped_by_when(node, node.when):
            return
        elif isinstance(node, HaltNode):
            self._halt(node)
        elif isinstance(node, LoopNode):
            self._loop(node)
        elif not isinstance(node, ApprovalNode):
            self._execute(node)

    def _stopped_by_when(self, node: Node, expr: str) -> bool:
        """Skip or fail ``node`` by its ``when:``; whether it stopped the node."""
        when = evaluate_when(expr, self._context())
        if isinstance(when, WhenFail):
            self._fail_unstarted(node, NodeFailedError("config", str(when.error)))
        elif isinstance(when, WhenSkip):
            self._skip(node, "condition_parse_error")
        elif not when.holds:
            self._skip(node, "condition")
        else:
            return False
        return True

    def _reusable(self, node: Node) -> bool:
        before = self.prior.nodes.get(node.id)
        if (
            before is None
            or before.state != "completed"
            or isinstance(node, HaltNode | ApprovalNode)
        ):
            return False
        if node.always_run:
            return False
        # A dependency that now ends differently from before invalidates the cached result.
        return all(
            dep in self.ends and self.ends[dep].result == self.prior.nodes.get(dep)
            for dep in node.depends_on
        )

    def _attempt(self, node: Node) -> int:
        self.attempts[node.id] = self.attempts.get(node.id, 0) + 1
        return self.attempts[node.id]

    def _skip(
        self,
        node: Node,
        cause: SkipCause,
        origin: str | None = None,
        *,
        result: NodeResult | None = None,
    ) -> None:
        at, attempt = self.ports.clock.now(), self._attempt(node)
        self.ports.recorder.step_ended(
            StepEnd(node.id, attempt, "skipped", at, skip_cause=cause, origin=origin)
        )
        self.ends[node.id] = NodeEnd(result or NodeResult("skipped"), cause, origin)

    def _fail_unstarted(self, node: Node, failure: NodeFailedError) -> None:
        now = self.ports.clock.now()
        attempt = self._attempt(node)
        self.ports.recorder.step_ended(
            StepEnd(node.id, attempt, "failed", now, failure.kind, detail=failure.detail)
        )
        self.ends[node.id] = NodeEnd(NodeResult("failed"))

    def _halt(self, node: HaltNode) -> None:
        recorder, now = self.ports.recorder, self.ports.clock.now()
        attempt = self._attempt(node)
        recorder.step_started(StepStart(node.id, attempt, now))
        try:
            detail = render(node.reason, self._context())
        except SubstitutionError as error:
            detail = str(error)
        recorder.step_ended(StepEnd(node.id, attempt, "ok", now, detail=detail))
        self.ends[node.id] = NodeEnd(NodeResult("completed"))
        self.halted_by = node.id

    def _execute(self, node: ExecutableNode) -> None:
        resume = self._resumed_session(node)

        def once(attempt: int) -> tuple[Turn, bool]:
            call = self._call(node, attempt, iteration=0, resume=resume)
            reply = self.ports.runner.run(call)
            return Turn(self._output(node, reply.text), reply.text, reply.session), True

        turn, _ = self._with_retries(node, once)
        self._complete(node, turn)

    def _loop(self, node: LoopNode) -> None:
        session, iteration = self._resumed_session(node), 0
        while True:
            iteration += 1

            def once(
                attempt: int, turn_number: int = iteration, resume: str | None = session
            ) -> tuple[Turn, bool]:
                call = self._call(node, attempt, iteration=turn_number, resume=resume)
                reply = self.ports.runner.run(call)
                turn = Turn(self._output(node, reply.text), reply.text, reply.session)
                done = until_met(node, turn, lambda: self._until_exit(node, call))
                check_turn(node, turn_number, done=done)
                return turn, done

            turn, done = self._with_retries(node, once)
            if turn is None or done:
                self._complete(node, turn)
                return
            session = next_session(node, turn)

    def _until_exit(self, node: LoopNode, call: NodeCall) -> int:
        argv = render_argv(node.until_bash or (), call.context)
        return self.ports.runner.until_exit(argv, call)

    def _with_retries(
        self, node: ExecutableNode, once: Callable[[int], tuple[Turn, bool]]
    ) -> tuple[Turn | None, bool]:
        """Attempts of one turn until one ends ``ok`` or no retry is left (``None``)."""
        recorder, clock = self.ports.recorder, self.ports.clock
        retries = 0
        while True:
            attempt = self._attempt(node)
            recorder.step_started(StepStart(node.id, attempt, clock.now()))
            try:
                try:
                    turn, done = once(attempt)
                except SubstitutionError as error:
                    raise NodeFailedError("config", str(error)) from None
            except NodeFailedError as failure:
                recorder.step_ended(
                    StepEnd(
                        node.id, attempt, "failed", clock.now(), failure.kind, detail=failure.detail
                    )
                )
                decision = retry_decision(
                    failure.kind,
                    node.retry,
                    node_type=node.type,
                    retries_done=retries,
                    jitter=self.ports.jitter,
                )
                if not decision.retry:
                    return None, False
                recorder.retry_scheduled(
                    node.id, RetryRecord(attempt, failure.kind, decision.delay)
                )
                clock.sleep(decision.delay)
                retries += 1
                continue
            recorder.step_ended(StepEnd(node.id, attempt, "ok", clock.now(), output=turn.output))
            return turn, done

    def _complete(self, node: ExecutableNode, turn: Turn | None) -> None:
        if turn is None:
            self.ends[node.id] = NodeEnd(NodeResult("failed"))
            return
        self.ends[node.id] = NodeEnd(NodeResult("completed", turn.output))
        if turn.session is not None:
            self.sessions[node.id] = turn.session

    def _resumed_session(self, node: ExecutableNode) -> str | None:
        if isinstance(node, AgentNode | LoopNode) and not isinstance(node.context, str):
            return self.sessions.get(node.context.resume)
        return None

    def _call(
        self, node: ExecutableNode, attempt: int, *, iteration: int, resume: str | None
    ) -> NodeCall:
        context = self._node_context(node)
        if isinstance(node, ShellNode | ScriptNode):
            argv = (
                render_argv(node.command, context)
                if isinstance(node, ShellNode)
                else [render(arg, context) for arg in node.args]
            )
            cwd = render(node.cwd, context) if node.cwd is not None else None
            env = {name: render(value, context) for name, value in node.env.items()}
            return NodeCall(node, attempt, context, iteration, tuple(argv), cwd, env)
        prompt = render(node.prompt, context) if node.prompt is not None else None
        return NodeCall(node, attempt, context, iteration, prompt=prompt, resume_session=resume)

    def _context(self) -> RefContext:
        results = {node_id: end.result for node_id, end in self.ends.items()}
        return RefContext(self.inputs, results)

    def _node_context(self, node: ExecutableNode) -> RefContext:
        """The context of an attempt: an agent's ``with`` values resolved (``$WITH``)."""
        context = self._context()
        if not isinstance(node, AgentNode | LoopNode):
            return context
        values: dict[str, JsonValue] = {}
        for name, binding in node.with_.items():
            if not isinstance(binding, FromBinding):
                values[name] = _rendered(binding, context)
                continue
            ref = parse_ref(binding.from_)
            producer = context.nodes.get(ref.node) if isinstance(ref, NodeRef) else None
            skipped = producer is not None and producer.state == "skipped"
            values[name] = binding.if_skipped if skipped else resolve(ref, context, binding.from_)
        return RefContext(context.inputs, context.nodes, with_values=values)

    def _output(self, node: ExecutableNode, text: str) -> JsonValue:
        """The text, or the one JSON value it holds checked against ``output_format``."""
        if node.output_format is None:
            return text
        try:
            value: JsonValue = json.loads(text, parse_constant=_refuse_constant)
        except ValueError, RecursionError:
            raise NodeFailedError("output_contract", "the output is not one JSON value") from None
        self.ports.outputs.check(node.output_format, value)
        return value


def _refuse_constant(name: str) -> JsonValue:
    msg = f"{name} is not a JSON number"
    raise ValueError(msg)


def _rendered(value: JsonValue, context: RefContext) -> JsonValue:
    if isinstance(value, str):
        return render(value, context)
    if isinstance(value, list):
        return [_rendered(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _rendered(item, context) for key, item in value.items()}
    return value
