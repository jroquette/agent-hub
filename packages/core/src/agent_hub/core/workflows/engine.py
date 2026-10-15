"""The workflow engine (ADR 0032): a pure interpreter of a plan over its ports.

Layers run in order and, in v1, one node at a time; a failure never stops later layers. Each
node goes through: the resume cache, its ``trigger_rule``, its ``when:``, then its attempts. A
resumed run reuses a node that completed before (``prior_success``) unless it is ``always_run``
or an ancestor now ends differently. Every visit takes the node's next ``attempt``, counted over
the whole run and its resumes, so no two steps share one. A failed attempt asks
``retry_decision`` and waits through the ``Clock``; each retry is recorded, and a loop's retry
starts the loop again from its first turn. A ``halt`` ends the
run ``cancelled``. ``approval`` nodes come later: a plan holding one is refused before any step.
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.conditions import WhenFail, WhenSkip, evaluate_when
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord, retry_decision
from agent_hub.core.workflows.loops import (
    MaxIterationsError,
    Turn,
    check_turn,
    next_session,
    until_met,
)
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
        # The results references read, kept beside ``ends`` as nodes end.
        self.results: dict[str, NodeResult] = {}
        # Nodes whose result differs from the prior run's, and nodes below one (stale): neither
        # is reused. One flag per node, set in layer order.
        self.changed: set[str] = set()
        self.stale: set[str] = set()
        self.attempts = dict(prior.attempts)
        self.sessions = dict(prior.sessions)
        self.halted_by: str | None = None

    def execute(self) -> RunReport:
        nodes = {node.id: node for node in self.plan.document.nodes}
        for layer in self.plan.layers:
            for node_id in layer:
                node = nodes[node_id]
                if any(dep in self.changed or dep in self.stale for dep in node.depends_on):
                    self.stale.add(node_id)
                self._visit(node)
                if self.ends[node_id].result != self.prior.nodes.get(node_id):
                    self.changed.add(node_id)
                if self.halted_by is not None:
                    return self._finish()
        return self._finish()

    def _finish(self) -> RunReport:
        status, reason = run_status(self.ends, self.halted_by)
        document = self.plan.document
        outcome = authored_outcome(document.returns, document.outcome_field, self.ends)
        self.ports.recorder.run_ended(RunEnd(status, self.ports.clock.now(), outcome, reason))
        state = RunState({**self.prior.nodes, **self.results}, self.attempts, self.sessions)
        return RunReport(status, outcome, reason, state)

    def _end(self, node: Node, end: NodeEnd) -> None:
        self.ends[node.id] = end
        self.results[node.id] = end.result

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
            self._complete(node, self._retrying(node, lambda: self._loop_once(node)))
        elif not isinstance(node, ApprovalNode):
            self._complete(node, self._retrying(node, lambda: self._execute_once(node)))

    def _stopped_by_when(self, node: Node, expr: str) -> bool:
        """Skip or fail ``node`` by its ``when:``; whether it stopped the node."""
        when = evaluate_when(expr, self._context())
        if isinstance(when, WhenFail):
            attempt = self._attempt(node)
            self.ports.recorder.step_started(StepStart(node.id, attempt, self.ports.clock.now()))
            self._record_failure(node, attempt, NodeFailedError("config", str(when.error)))
            self._end(node, NodeEnd(NodeResult("failed")))
        elif isinstance(when, WhenSkip):
            self._skip(node, "condition_parse_error")
        elif not when.holds:
            self._skip(node, "condition")
        else:
            return False
        return True

    def _reusable(self, node: Node) -> bool:
        """A node that completed before, is not ``always_run``, and has no changed ancestor."""
        before = self.prior.nodes.get(node.id)
        if before is None or before.state != "completed":
            return False
        if isinstance(node, HaltNode | ApprovalNode) or node.always_run:
            return False
        # References reach only ancestors (planning), so an unchanged ancestry reads the same.
        return node.id not in self.stale

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
        self._end(node, NodeEnd(result or NodeResult("skipped"), cause, origin))

    def _record_failure(self, node: Node, attempt: int, failure: NodeFailedError) -> None:
        output = failure.output if isinstance(failure, MaxIterationsError) else None
        self.ports.recorder.step_ended(
            StepEnd(
                node.id,
                attempt,
                "failed",
                self.ports.clock.now(),
                failure.kind,
                output=output,
                detail=failure.detail,
            )
        )

    def _halt(self, node: HaltNode) -> None:
        recorder, now = self.ports.recorder, self.ports.clock.now()
        attempt = self._attempt(node)
        recorder.step_started(StepStart(node.id, attempt, now))
        try:
            detail = render(node.reason, self._context())
        except SubstitutionError as error:
            detail = str(error)
        recorder.step_ended(StepEnd(node.id, attempt, "ok", now, detail=detail))
        self._end(node, NodeEnd(NodeResult("completed")))
        self.halted_by = node.id

    def _execute_once(self, node: ExecutableNode) -> Turn:
        resume = self._resumed_session(node)

        def run(attempt: int) -> tuple[Turn, bool]:
            call = self._call(node, attempt, iteration=0, resume=resume)
            reply = self.ports.runner.run(call)
            return Turn(self._output(node, reply.text), reply.text, reply.session), True

        return self._step(node, run)[0]

    def _loop_once(self, node: LoopNode) -> Turn:
        """The loop from its first turn; a retry of the node starts here again, afresh."""
        session = self._resumed_session(node)
        iteration = 0
        while True:
            iteration += 1

            def run(
                attempt: int, number: int = iteration, resume: str | None = session
            ) -> tuple[Turn, bool]:
                call = self._call(node, attempt, iteration=number, resume=resume)
                reply = self.ports.runner.run(call)
                turn = Turn(self._output(node, reply.text), reply.text, reply.session)
                done = until_met(node, turn, lambda: self._until_exit(node, call))
                check_turn(node, number, turn, done=done)
                return turn, done

            turn, done = self._step(node, run)
            if done:
                return turn
            session = next_session(node, turn)

    def _until_exit(self, node: LoopNode, call: NodeCall) -> int:
        argv = render_argv(node.until_bash or (), call.context)
        return self.ports.runner.until_exit(argv, call)

    def _step(
        self, node: ExecutableNode, run: Callable[[int], tuple[Turn, bool]]
    ) -> tuple[Turn, bool]:
        """One attempt, from its start to its end; a failure ends it and raises again.

        Any error a port raises fails the attempt ``unknown``, its type named but not its
        message (it may hold output text). A recorder's own error is not caught: it is the
        composition root's bug.
        """
        attempt = self._attempt(node)
        self.ports.recorder.step_started(StepStart(node.id, attempt, self.ports.clock.now()))
        try:
            turn, done = run(attempt)
        except NodeFailedError as failure:
            self._record_failure(node, attempt, failure)
            raise
        except SubstitutionError as error:
            config = NodeFailedError("config", str(error))
            self._record_failure(node, attempt, config)
            raise config from None
        except Exception as error:  # noqa: BLE001 - a port's unexpected error ends the step
            unknown = NodeFailedError("unknown", type(error).__name__)
            self._record_failure(node, attempt, unknown)
            raise unknown from None
        self.ports.recorder.step_ended(
            StepEnd(node.id, attempt, "ok", self.ports.clock.now(), output=turn.output)
        )
        return turn, done

    def _retrying(self, node: ExecutableNode, once: Callable[[], Turn]) -> Turn | None:
        """``once`` again while ``retry_decision`` allows; ``None`` once no retry is left."""
        retries = 0
        while True:
            try:
                return once()
            except NodeFailedError as failure:
                if not self._wait_for_retry(node, failure, retries):
                    return None
                retries += 1

    def _wait_for_retry(self, node: ExecutableNode, failure: NodeFailedError, retries: int) -> bool:
        """Whether to try again, after the wait. A jitter or clock that raises leaves the node
        failed with the kind its attempt ended with, and the run goes on."""
        try:
            decision = retry_decision(
                failure.kind,
                node.retry,
                node_type=node.type,
                retries_done=retries,
                jitter=self.ports.jitter,
            )
        except Exception:  # noqa: BLE001 - a port's unexpected error: no retry
            return False
        if not decision.retry:
            return False
        record = RetryRecord(self.attempts[node.id], failure.kind, decision.delay)
        self.ports.recorder.retry_scheduled(node.id, record)
        try:
            self.ports.clock.sleep(decision.delay)
        except Exception:  # noqa: BLE001 - a port's unexpected error: no retry
            return False
        return True

    def _complete(self, node: ExecutableNode, turn: Turn | None) -> None:
        if turn is None:
            self._end(node, NodeEnd(NodeResult("failed")))
            return
        self._end(node, NodeEnd(NodeResult("completed", turn.output)))
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
        cwd = render(node.cwd, context) if node.cwd is not None else None
        if isinstance(node, ShellNode | ScriptNode):
            argv = (
                render_argv(node.command, context)
                if isinstance(node, ShellNode)
                else [render(arg, context) for arg in node.args]
            )
            env = {name: render(value, context) for name, value in node.env.items()}
            stdin = render(node.stdin, context) if node.stdin is not None else None
            return NodeCall(node, attempt, context, iteration, tuple(argv), cwd, env, stdin=stdin)
        prompt = render(node.prompt, context) if node.prompt is not None else None
        return NodeCall(
            node, attempt, context, iteration, cwd=cwd, prompt=prompt, resume_session=resume
        )

    def _context(self) -> RefContext:
        return RefContext(self.inputs, self.results)

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
