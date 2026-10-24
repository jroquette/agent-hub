"""The workflow engine (ADR 0032): a pure interpreter of a plan over its ports.

Layers run in order, a failure never stopping later layers; a layer's nodes run concurrently in
threads, except a layer holding a ``halt`` (or a group whose body does), which runs one node at a
time and stops at the halt. At most ``EnginePorts.max_parallel`` attempts run at once across the
run, nested group layers included. Nodes record as they go, through one lock, so records follow
the order things happen; the run's ``reason`` stays the first failed node in declaration order.
An interrupted concurrent layer calls ``EnginePorts.interrupt`` to stop its running children.
Planning keeps read-only nodes (``mutates_checkout: false``) and nodes resuming one session out
of a shared layer. A read-only node's attempt reads the ``CheckoutProbe`` before and after: a
change fails it ``config`` (never retried).

Each node goes through: the resume cache, run control, its ``trigger_rule``, its ``when:``, then
its attempts. A resumed run reuses a node that completed before (``prior_success``) unless it is
``always_run`` or an ancestor now ends differently. Every visit takes the node's next
``attempt``, counted over the whole run and its resumes, so no two steps share one. A failed
attempt asks ``retry_decision`` and waits through the ``Clock``; each retry is recorded, and a
loop's retry starts the loop again from its first turn. A ``halt`` ends the run ``cancelled``.
An ``approval`` or ``wait`` node opens a gate (``gates.py``) and, until it has its answer or its
time, pauses the run: once its layer ends, the report is ``paused``, with no end, and later
layers wait for the resume, which takes up the same gate. Planning lets at most
one gate be open at a time (two suspendable nodes are always ordered). A gate in a ``loop_group``
body pauses its iteration once the body layer ends; the group's step stays open, and the resume
goes on in that iteration with the body nodes it already ended and the same ``$LOOP_PREV``.
Rejecting an approval with the default decisions ends the run ``cancelled`` like a ``halt``,
unless the workflow reads the decision.

Run control (``run_control.py``, ``EnginePorts.control``) pauses a run before a node no gate
holds. While it is ``debugging()``, each layer asks it about the nodes this pass may run. It is
not asked about an end an earlier pass left that this one reuses, keeps or skips again, nor a
group or gate left open. A failure or stale node a resume runs again is asked again.

A layer holding a node to pause at runs one node at a time in declaration order and stops
before that node. Once the layer ends, the report is ``paused`` with ``RunState.pause`` and no
gate of the pass open. A body node's pause holds its iteration as a body gate does.

The resume takes up the pause: the first visit of the node it stopped before runs, and so does
that of any node paused for the same block. It goes on where that pass stopped: it reuses what
completed (``always_run`` too) and keeps what failed. What the pass had not reached stays as an
earlier pass left it: a gate stays open, and an end owed a rerun is in ``RunState.rerun``. What
a rerun changes is found on the resume itself, through ``stale``. A gate open in the same pass
wins: the report is the gate's, and the nodes the pass stopped before are asked again on its
resume.

A ``loop_group`` is one step around its body's: each iteration runs the body's layers (body ids
as recorded, ``<group>__<id>``, each visit a new attempt), with ``$LOOP_PREV`` reading the
iteration before (empty at first). A failed body node does not stop the iteration, so ``all_done``
body nodes still run; then the group fails with that node's kind. Otherwise ``until_when`` (over
the iteration's outputs), then ``until_bash`` (exit 0, through the runner as a shell call under
the group's id) end it, with an output mapping each body id to its output; past
``max_iterations`` it fails ``max_iterations``. A group is never retried. Without
``fresh_context``, a body agent resumes its own session of the iteration before, unless it sets
``context: fresh``.

An ``action`` node is one runner call with its ``with`` values as ``NodeCall.inputs``; its output
must be one JSON value (else ``output_contract``). An ``expect`` node polls its action every
``every`` (``Clock.sleep``) until ``until_when`` holds over ``$self.output``, at most
``MAX_EXPECT_POLLS`` times in a run (its attempts together), then fails ``timeout`` (detail
``expect_timeout: …``) once its window has passed. Each poll and each ``capture:`` value goes to
``EnginePorts.trace``; without an explicit ``retry`` neither node is retried.
"""

import dataclasses
import json
import threading
from collections.abc import Callable, Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import timedelta
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.conditions import WhenFail, WhenSkip, evaluate_when
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord, retry_decision
from agent_hub.core.workflows.gates import (
    GateAnswers,
    GateError,
    NoAnswers,
    OpenGate,
    gate_choices,
    gate_form,
    gate_kind,
    gate_output,
    gate_template,
    reject_cancels,
    wait_due,
)
from agent_hub.core.workflows.loops import (
    MaxIterationsError,
    Turn,
    check_turn,
    local_id,
    next_session,
    until_met,
)
from agent_hub.core.workflows.nodes import (
    ActionNode,
    AgentNode,
    ApprovalNode,
    ExecutableNode,
    ExpectNode,
    FromBinding,
    GateNode,
    HaltNode,
    IncludeNode,
    LoopGroupNode,
    LoopNode,
    Node,
    ScriptNode,
    ShellNode,
    WaitNode,
    duration_seconds,
)
from agent_hub.core.workflows.plan import WorkflowPlan
from agent_hub.core.workflows.ports import (
    CheckoutProbe,
    Clock,
    ContextCapture,
    ExpectPoll,
    GateRequest,
    NodeCall,
    NodeRunner,
    OutputValidator,
    RunEnd,
    RunRecorder,
    RunTrace,
    SkipCause,
    StepEnd,
    StepStart,
)
from agent_hub.core.workflows.run_control import DebugPause, PauseReason, RunControl
from agent_hub.core.workflows.run_state import (
    HeldGroup,
    NodeEnd,
    RunReport,
    RunState,
    authored_outcome,
    run_status,
    trigger_skip,
)
from agent_hub.core.workflows.scope import RefScope
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

# The nodes the runner runs from their own keys (argv, prompt), not an action call.
type _CommandNode = AgentNode | ShellNode | ScriptNode | LoopNode
# The most attempts that run at once in a run.
MAX_PARALLEL: Final = 4
# The most threads one layer starts; they wait for the run's permits.
MAX_LAYER_THREADS: Final = 64
# The most polls of one ``expect`` attempt, whatever its window.
MAX_EXPECT_POLLS: Final = 1000


class WorkflowEngineError(AgentHubError):
    """A run the engine refuses to start: unsupported nodes, inputs that do not fit."""


@dataclass(frozen=True)
class EnginePorts:
    runner: NodeRunner
    recorder: RunRecorder
    clock: Clock
    outputs: OutputValidator
    jitter: Callable[[], float]
    checkout: CheckoutProbe | None = None
    max_parallel: int = MAX_PARALLEL
    # Called when a concurrent layer is interrupted: stops the children its nodes run.
    interrupt: Callable[[], None] | None = None
    gates: GateAnswers = NoAnswers()
    # A scenario run's polls and captures; ``None`` when no one keeps them.
    trace: RunTrace | None = None
    # Breakpoints and step mode; ``None`` (or not debugging): the run never pauses before a node.
    control: RunControl | None = None


def run_workflow(
    plan: WorkflowPlan,
    inputs: Mapping[str, JsonValue],
    ports: EnginePorts,
    *,
    prior: RunState | None = None,
) -> RunReport:
    """Run ``plan`` with ``inputs``, resuming ``prior`` when given; the run's report."""
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
        # The gate node the run pauses on, and its open gate.
        self.paused: tuple[str, OpenGate] | None = None
        # The groups paused around that gate, and the gates a resume already took up once.
        self.held: dict[str, HeldGroup] = {}
        self.taken: set[str] = set()
        # The first node run control stopped this pass before, and the nodes whose first visit
        # took up the debug pause the run resumes from.
        self.debug: DebugPause | None = None
        self.released: set[str] = set()
        # Each body node's group, and each running group's previous iteration.
        self.owner = {
            body.id: node
            for node in plan.document.nodes
            if isinstance(node, LoopGroupNode)
            for body in node.nodes
        }
        self.loop_prevs: dict[str, dict[str, NodeResult]] = {}
        self.lock = threading.Lock()
        self.trace_lock = threading.Lock()
        # Each expect node's polls in this run, all its attempts together.
        self.polls: dict[str, int] = dict(prior.polls)
        # Concurrent nodes record through one lock, as they end; at most ``max_parallel``
        # attempts run at once across the run, nested group layers included.
        self.recorder: RunRecorder = _LockedRecorder(ports.recorder)
        self.permits = threading.BoundedSemaphore(max(1, ports.max_parallel))
        # Set when a concurrent layer is interrupted: no attempt, retry or iteration starts after.
        self.stopped = threading.Event()

    def execute(self) -> RunReport:
        nodes = {node.id: node for node in self.plan.document.nodes}
        for layer in self.plan.layers:
            for node_id in layer:
                if any(d in self.changed or d in self.stale for d in nodes[node_id].depends_on):
                    self.stale.add(node_id)
            self._run_layer([nodes[node_id] for node_id in layer])
            for node_id in layer:
                end = self.ends.get(node_id)
                if end is not None and end.result != self.prior.nodes.get(node_id):
                    self.changed.add(node_id)
            if self.halted_by is not None:
                return self._finish()
            if (paused := self._pause()) is not None:
                return paused
        return self._finish()

    def _run_layer(self, nodes: Sequence[Node]) -> None:
        """Visit a layer's nodes, concurrently unless one may halt the run or run control pauses
        before one (then in order)."""
        stops = self._stops(nodes)
        sequential = self.ports.max_parallel <= 1 or len(nodes) == 1 or bool(stops)
        if sequential or any(_may_halt(node) for node in nodes):
            self._run_in_order(nodes, stops)
            return
        # A thread per node: the run-wide permits bound how many attempts run at once.
        with ThreadPoolExecutor(max_workers=min(len(nodes), MAX_LAYER_THREADS)) as pool:
            futures = [pool.submit(self._visit, node) for node in nodes]
            try:
                for future in futures:
                    future.result()
            except BaseException:
                # Ctrl-C (or an engine bug): nothing new starts, and the running children stop
                # before the pool waits for its threads.
                self.stopped.set()
                for future in futures:
                    future.cancel()
                if self.ports.interrupt is not None:
                    self.ports.interrupt()
                raise

    def _finish(self) -> RunReport:
        # In declaration order: the ends of a concurrent layer arrive in any order.
        ends = {
            node.id: self.ends[node.id] for node in self.plan.all_nodes() if node.id in self.ends
        }
        status, reason = run_status(ends, self.halted_by)
        document = self.plan.document
        outcome = authored_outcome(document.returns, document.outcome_field, self.ends)
        self.ports.recorder.run_ended(RunEnd(status, self.ports.clock.now(), outcome, reason))
        nodes = {**self.prior.nodes, **self.results}
        state = RunState(nodes, self.attempts, self.sessions, polls=dict(self.polls))
        return RunReport(status, outcome, reason, state)

    def _run_in_order(self, nodes: Sequence[Node], stops: Mapping[str, PauseReason]) -> None:
        """Visit ``nodes`` one at a time, up to a halt or the first node of ``stops``."""
        for node in nodes:
            if (stop := stops.get(node.id)) is not None:
                self._pause_before(node, stop)
                return
            self._visit(node)
            if self.halted_by is not None:
                return

    def _pause(self) -> RunReport | None:
        """The report of a pass stopped on an open gate, or before a node by run control (a gate
        wins, and its resume asks run control again), else ``None``: no end is recorded."""
        gates: dict[str, OpenGate] = {}
        debug: DebugPause | None = None
        groups = dict(self.held)
        rerun: frozenset[str] = frozenset()
        if self.paused is not None:
            node, gate = self.paused
            gates[node] = gate
        elif self.debug is not None:
            node, debug = self.debug.node, self.debug
            # What an earlier pass left that this one stopped before reaching stays as it was for
            # the resume: a gate open (taken up with any answer it has) with the groups around
            # it, and each end this pass would have run again.
            with self.lock:
                gates = {g: open_ for g, open_ in self.prior.gates.items() if g not in self.taken}
                left = self.prior.groups.items()
                groups |= {g: held for g, held in left if g not in groups and g not in self.ends}
                rerun = self._owed()
        else:
            return None
        nodes = {**self.prior.nodes, **self.results}
        polls = dict(self.polls)
        state = RunState(nodes, self.attempts, self.sessions, gates, groups, polls, debug, rerun)
        return RunReport("paused", None, node, state)

    def _owed(self) -> frozenset[str]:
        """The ends from before that this pass stopped before reaching and would have run again:
        one its rule does not keep, or one stale in it (below a changed or stale node, through
        the layers it never reached), a skip from an earlier pass included: it is evaluated
        again, so it is asked again."""
        nodes = {node.id: node for node in self.plan.document.nodes}
        below = self.changed | self.stale
        owed: set[str] = set()
        for layer in self.plan.layers:
            for node in (nodes[node_id] for node_id in layer):
                if any(d in below for d in node.depends_on):
                    below.add(node.id)
                before = self.prior.nodes.get(node.id)
                if (
                    node.id in self.ends
                    or before is None
                    or isinstance(node, HaltNode | IncludeNode)
                ):
                    continue
                skipped = before.state == "skipped"
                if node.id in below or (not skipped and not self._kept(node, before)):
                    owed.add(node.id)
        return frozenset(owed)

    def _stops(self, nodes: Sequence[Node]) -> dict[str, PauseReason]:
        """The nodes of a layer run control pauses before, with why: none unless it is
        debugging, never one the run reached in an earlier pass, nor the first visit of a node
        taking up the pause the run resumes from."""
        control = self.ports.control
        if control is None or not control.debugging():
            return {}
        stops: dict[str, PauseReason] = {}
        for node in nodes:
            if self._reached(node):
                continue
            stop = control.pause_before(node.id)
            if stop is not None and not self._takes_up_pause(node, stop):
                stops[node.id] = stop
        return stops

    def _reached(self, node: Node) -> bool:
        """A node the run reached in an earlier pass and does not run again in this one: it ended
        then and is reused or kept, or it was skipped and its ancestry is unchanged (a body
        node's ends count in their iteration, which a held group restores), or it is a held
        group or a gate not yet taken up. A failure or a stale node this resume runs again is
        not reached: it is asked again.

        A skip is reached when it is not stale in this pass. On a resume from a debug pause it
        must also be one the paused pass did not owe a rerun (``RunState.rerun``)."""
        with self.lock:
            open_gate = node.id in self.prior.gates and node.id not in self.taken
            if open_gate or node.id in self.prior.groups:
                return True
        before = self.prior.nodes.get(node.id)
        if before is None or node.id in self.owner:
            return False
        # ``stale`` is read without the lock: it changes only between layers, on this thread.
        if self._reusable(node):
            return True
        # A skip below a node this pass ran again and changed is stale, whether or not the
        # paused pass owed it a rerun: what a rerun changes is found on the resume itself.
        unchanged = node.id not in self.stale
        if self.prior.pause is not None:
            unchanged = unchanged and node.id not in self.prior.rerun
        return before.state == "skipped" and unchanged

    def _takes_up_pause(self, node: Node, stop: PauseReason) -> bool:
        """Whether this visit takes up the debug pause the run resumes from: the first visit of
        the node it stopped before, or of a node paused for the same block (an If's or a
        Together's other entry nodes)."""
        resumed = self.prior.pause
        if resumed is None or (node.id != resumed.node and stop.block != resumed.block):
            return False
        with self.lock:
            if node.id in self.released:
                return False
            self.released.add(node.id)
            return True

    def _pause_before(self, node: Node, stop: PauseReason) -> None:
        """End the pass before ``node``: nothing of it starts or is recorded."""
        with self.lock:
            if self.debug is None:
                self.debug = DebugPause(node.id, stop.block, stop.reason)

    def _end(self, node: Node, end: NodeEnd) -> None:
        with self.lock:
            self.ends[node.id] = end
            self.results[node.id] = end.result

    def _visit(self, node: Node) -> None:
        if self._reusable(node):
            self._reuse(node)
        elif (blocked := trigger_skip(node, self.ends)) is not None:
            self._skip(node, *blocked)
        elif node.when is None or not self._stopped_by_when(node, node.when):
            self._run_node(node)

    def _run_node(self, node: Node) -> None:
        if isinstance(node, HaltNode):
            self._halt(node)
        elif isinstance(node, LoopNode):
            self._complete(node, self._retrying(node, lambda: self._loop_once(node)))
        elif isinstance(node, LoopGroupNode):
            self._group(node)
        elif isinstance(node, ApprovalNode | WaitNode):
            self._gate(node)
        elif isinstance(node, AgentNode | ShellNode | ScriptNode):
            self._complete(node, self._retrying(node, lambda: self._execute_once(node)))
        elif isinstance(node, ActionNode):
            self._complete(node, self._retrying(node, lambda: self._action_once(node)))
        elif isinstance(node, ExpectNode):
            self._complete(node, self._retrying(node, lambda: self._expect_once(node)))

    def _stopped_by_when(self, node: Node, expr: str) -> bool:
        """Skip or fail ``node`` by its ``when:``; whether it stopped the node."""
        when = evaluate_when(expr, self._context(node))
        if isinstance(when, WhenFail):
            attempt = self._attempt(node)
            self.recorder.step_started(StepStart(node.id, attempt, self.ports.clock.now()))
            self._record_failure(node, attempt, NodeFailedError("config", str(when.error)))
            self._end(node, NodeEnd(NodeResult("failed"), failure_kind="config"))
        elif isinstance(when, WhenSkip):
            self._skip(node, "condition_parse_error")
        elif not when.holds:
            self._skip(node, "condition")
        else:
            return False
        return True

    def _reusable(self, node: Node) -> bool:
        """A node this pass's rule keeps (``_kept``) that has no changed ancestor."""
        before = self.prior.nodes.get(node.id)
        # References reach only ancestors (planning), so an unchanged ancestry reads the same.
        return before is not None and self._kept(node, before) and node.id not in self.stale

    def _kept(self, node: Node, before: NodeResult) -> bool:
        """Whether this pass keeps ``node``'s end from before while its ancestry is unchanged:
        one that completed and is not ``always_run``. On a resume from a debug pause, one that
        completed or failed before, unless the paused pass owed it a rerun (``RunState.rerun``,
        a stale completed end included): that pass goes on where it stopped, so a pause never
        changes what runs."""
        if node.id in self.owner or isinstance(node, HaltNode | IncludeNode):
            return False
        if self.prior.pause is not None:
            return before.state != "skipped" and node.id not in self.prior.rerun
        return before.state == "completed" and not getattr(node, "always_run", False)

    def _reuse(self, node: Node) -> None:
        """``node``'s end from before: a completed one reused (``prior_success``), a failure kept
        with nothing recorded (the record already holds its end). A kept failure drops its
        ``failure_kind``: only a group body reads it, and ``_kept`` never keeps a body node."""
        before = self.prior.nodes[node.id]
        if before.state == "completed":
            self._skip(node, "prior_success", result=before)
        else:
            self._end(node, NodeEnd(before))

    def _attempt(self, node: Node) -> int:
        with self.lock:
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
        self.recorder.step_ended(
            StepEnd(node.id, attempt, "skipped", at, skip_cause=cause, origin=origin)
        )
        self._end(node, NodeEnd(result or NodeResult("skipped"), cause, origin))

    def _record_failure(self, node: Node, attempt: int, failure: NodeFailedError) -> None:
        output = failure.output if isinstance(failure, MaxIterationsError) else None
        self.recorder.step_ended(
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
        recorder, now = self.recorder, self.ports.clock.now()
        attempt = self._attempt(node)
        recorder.step_started(StepStart(node.id, attempt, now))
        try:
            detail = render(node.reason, self._context(node))
        except SubstitutionError as error:
            detail = str(error)
        recorder.step_ended(StepEnd(node.id, attempt, "ok", now, detail=detail))
        self._end(node, NodeEnd(NodeResult("completed")))
        self.halted_by = node.id

    def _gate(self, node: GateNode) -> None:
        """Take up the gate a pause left open, else open one; end the node once answered. A
        stopped run opens or takes up nothing."""
        self._check_stop()
        clock, recorder = self.ports.clock, self.recorder
        with self.lock:
            # A body gate is visited once per iteration: only the first visit takes it up.
            held = None if node.id in self.taken else self.prior.gates.get(node.id)
            self.taken.add(node.id)
        if held is not None:
            attempt, due = held.attempt, held.due
        else:
            attempt, now = self._attempt(node), clock.now()
            recorder.step_started(StepStart(node.id, attempt, now))
            try:
                text = render(gate_template(node), self._context(node))
                due = wait_due(node, text, now)
            except (SubstitutionError, GateError) as error:
                self._gate_failed(node, attempt, NodeFailedError("config", str(error)))
                return
            kind, form, choices = gate_kind(node), gate_form(node), gate_choices(node)
            recorder.gate_requested(
                GateRequest(node.id, attempt, kind, form, now, choices, text, due)
            )
        try:
            answer = self.ports.gates.answer(node.id, attempt)
            output = gate_output(node, answer, due=due, now=clock.now())
        except GateError as error:
            self._gate_failed(node, attempt, NodeFailedError("config", str(error)))
            return
        except Exception as error:  # noqa: BLE001 - a port's unexpected error ends the step
            self._gate_failed(node, attempt, NodeFailedError("unknown", type(error).__name__))
            return
        if output is None:
            with self.lock:
                self.paused = (node.id, OpenGate(attempt, due))
            return
        recorder.step_ended(StepEnd(node.id, attempt, "ok", clock.now(), output=output))
        self._end(node, NodeEnd(NodeResult("completed", output)))
        rejected = isinstance(output, dict) and output.get("decision") == "reject"
        if rejected and reject_cancels(node, list(self.plan.all_nodes())):
            self.halted_by = node.id

    def _gate_failed(self, node: GateNode, attempt: int, failure: NodeFailedError) -> None:
        self._record_failure(node, attempt, failure)
        self._end(node, NodeEnd(NodeResult("failed"), failure_kind=failure.kind))

    def _action_once(self, node: ActionNode) -> Turn:
        """One action call: the runner runs it; its output is one JSON value (the action's
        ``output_format`` is the runner's to check)."""

        def run(attempt: int) -> tuple[Turn, bool]:
            reply = self.ports.runner.run(self._action_call(node, attempt))
            output = _json_value(reply.text)
            self._capture(node, attempt, output)
            return Turn(output, reply.text, None), True

        return self._step(node, run)[0]

    def _expect_once(self, node: ExpectNode) -> Turn:
        """Polls of one attempt, ``every`` apart, until ``until_when`` holds over the output;
        past the window, or once the node's polls in this run reach ``MAX_EXPECT_POLLS`` (its
        attempts together), the node fails ``timeout``."""
        every = timedelta(seconds=duration_seconds(node.every))

        def run(attempt: int) -> tuple[Turn, bool]:
            clock = self.ports.clock
            deadline = clock.now() + timedelta(seconds=duration_seconds(node.timeout))
            poll = 0
            while self._take_poll(node):
                poll += 1
                reply = self.ports.runner.run(self._action_call(node, attempt, poll))
                output = _json_value(reply.text)
                held = self._holds(node, output)
                self._traced(ExpectPoll(node.id, attempt, poll, held, clock.now(), output))
                if held:
                    self._capture(node, attempt, output)
                    return Turn(output, reply.text, None), True
                if clock.now() + every > deadline or self.polls[node.id] >= MAX_EXPECT_POLLS:
                    break
                clock.sleep(every, self.stopped)
                self._check_stop()
            detail = f"expect_timeout: until_when did not hold in {node.timeout} ({poll} polls)"
            raise NodeFailedError("timeout", detail)

        return self._step(node, run)[0]

    def _take_poll(self, node: ExpectNode) -> bool:
        """Count one more poll of ``node``, unless its run-wide budget is spent."""
        with self.lock:
            done = self.polls.get(node.id, 0)
            if done >= MAX_EXPECT_POLLS:
                return False
            self.polls[node.id] = done + 1
            return True

    def _holds(self, node: ExpectNode, output: JsonValue) -> bool:
        when = evaluate_when(node.until_when, self._own_context(node, output))
        if isinstance(when, WhenFail):
            raise NodeFailedError("config", str(when.error))
        if isinstance(when, WhenSkip):
            raise NodeFailedError("config", when.detail)
        return when.holds

    def _capture(self, node: ActionNode | ExpectNode, attempt: int, output: JsonValue) -> None:
        """Each ``capture:`` value read from ``output``, traced; one that cannot be read fails
        the attempt ``config``."""
        context = self._own_context(node, output)
        for name, ref in node.capture.items():
            value = resolve(parse_ref(ref, scenario=True), context, ref)
            self._traced(ContextCapture(node.id, attempt, name, self.ports.clock.now(), value))

    def _own_context(self, node: Node, output: JsonValue) -> RefContext:
        context = self._context(node)
        own = NodeResult("completed", output)
        return dataclasses.replace(context, self_output=own, scenario=True)

    def _traced(self, item: ExpectPoll | ContextCapture) -> None:
        trace = self.ports.trace
        if trace is None:
            return
        with self.trace_lock:
            if isinstance(item, ExpectPoll):
                trace.expect_polled(item)
            else:
                trace.context_captured(item)

    def _action_call(self, node: ActionNode | ExpectNode, attempt: int, poll: int = 0) -> NodeCall:
        context = self._context(node)
        inputs = {name: _action_value(value, context) for name, value in node.with_.items()}
        return NodeCall(node, attempt, context, inputs=inputs, poll=poll)

    def _execute_once(self, node: _CommandNode) -> Turn:
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
        """One attempt, once it holds a permit and the run has not stopped, from its start to
        its end; a failure ends it and raises again.

        Any error a port raises fails the attempt ``unknown``, its type named but not its
        message (it may hold output text). A recorder's own error is not caught: it is the
        composition root's bug.
        """
        with self.permits:
            self._check_stop()
            return self._attempt_step(node, run)

    def _attempt_step(
        self, node: ExecutableNode, run: Callable[[int], tuple[Turn, bool]]
    ) -> tuple[Turn, bool]:
        attempt = self._attempt(node)
        self.recorder.step_started(StepStart(node.id, attempt, self.ports.clock.now()))
        try:
            before = self._checkout_status(node)
            turn, done = run(attempt)
            if before is not None and self._checkout_status(node) != before:
                detail = "the checkout changed, though the node declares mutates_checkout: false"
                raise NodeFailedError("config", detail)
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
        self.recorder.step_ended(
            StepEnd(node.id, attempt, "ok", self.ports.clock.now(), output=turn.output)
        )
        return turn, done

    def _checkout_status(self, node: ExecutableNode) -> str | None:
        """The checkout's status for a read-only node (``mutates_checkout: false``), else None."""
        if isinstance(node, ActionNode | ExpectNode) or node.mutates_checkout:
            return None
        if self.ports.checkout is None:
            raise NodeFailedError("config", "no checkout probe to check mutates_checkout: false")
        return self.ports.checkout.status()

    def _retrying(self, node: ExecutableNode, once: Callable[[], Turn]) -> Turn | NodeFailedError:
        """``once`` again while ``retry_decision`` allows; the last failure once none is left."""
        retries = 0
        while True:
            try:
                return once()
            except NodeFailedError as failure:
                if not self._wait_for_retry(node, failure, retries):
                    return failure
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
        # Stopped: no retry is scheduled. A stop during the backoff wakes it, and the next
        # attempt's check (after its permit) ends the node.
        self._check_stop()
        record = RetryRecord(self.attempts[node.id], failure.kind, decision.delay)
        self.recorder.retry_scheduled(node.id, record)
        try:
            self.ports.clock.sleep(decision.delay, self.stopped)
        except Exception:  # noqa: BLE001 - a port's unexpected error: no retry
            return False
        return True

    def _check_stop(self) -> None:
        if self.stopped.is_set():
            raise _RunStoppedError

    def _complete(self, node: ExecutableNode, turn: Turn | NodeFailedError) -> None:
        if isinstance(turn, NodeFailedError):
            self._end(node, NodeEnd(NodeResult("failed"), failure_kind=turn.kind))
            return
        self._end(node, NodeEnd(NodeResult("completed", turn.output)))
        if turn.session is not None:
            with self.lock:
                self.sessions[node.id] = turn.session

    def _resumed_session(self, node: _CommandNode) -> str | None:
        if not isinstance(node, AgentNode | LoopNode):
            return None
        if not isinstance(node.context, str):
            return self.sessions.get(node.context.resume)
        group = self.owner.get(node.id)
        # A group's body agent: its own session of the iteration before (popped at the start),
        # unless the group or the agent itself (an explicit ``context: fresh``) asks for a new one.
        if group is None or group.fresh_context or "context" in node.model_fields_set:
            return None
        return self.sessions.get(node.id)

    def _call(
        self, node: _CommandNode, attempt: int, *, iteration: int, resume: str | None
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
        scope = self.plan.scopes.get(node.id, RefScope())
        return NodeCall(
            node,
            attempt,
            context,
            iteration,
            cwd=cwd,
            prompt=prompt,
            resume_session=resume,
            scope=scope,
        )

    def _context(self, node: Node) -> RefContext:
        """What ``node`` reads: ``$LOOP_PREV`` inside a group (its body or its channels)."""
        group = self.owner.get(node.id, node)
        with self.lock:
            results = dict(self.results)
            loop_prev = self.loop_prevs.get(group.id)
        scenario = self.plan.document.kind == "scenario"
        return RefContext(
            self.inputs, results, loop_prev, ctx=self._captured(results), scenario=scenario
        )

    def _captured(self, results: Mapping[str, NodeResult]) -> dict[str, NodeResult]:
        """Each ``$CTX`` name whose node has ended, read again from that node's result: a
        resumed run recomputes it from the results it reuses. A skipped node's reads as empty,
        a failed one's fails the reader."""
        ctx: dict[str, NodeResult] = {}
        for name, capture in self.plan.captures.items():
            result = results.get(capture.node)
            if result is None or result.state != "completed":
                if result is not None:
                    ctx[name] = NodeResult(result.state)
                continue
            own = RefContext(self.inputs, results, self_output=result)
            try:
                ctx[name] = NodeResult(
                    "completed", resolve(parse_ref(capture.ref, scenario=True), own, capture.ref)
                )
            except SubstitutionError:
                ctx[name] = NodeResult("failed")
        return ctx

    def _node_context(self, node: _CommandNode) -> RefContext:
        """The context of an attempt: an agent's ``with`` values resolved (``$WITH``)."""
        context = self._context(node)
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
        return RefContext(context.inputs, context.nodes, context.loop_prev, values)

    def _group(self, group: LoopGroupNode) -> None:
        recorder, held = self.recorder, self.prior.groups.get(group.id)
        if held is None:
            attempt = self._attempt(group)
            recorder.step_started(StepStart(group.id, attempt, self.ports.clock.now()))
        else:
            attempt = held.attempt
        end = self._iterate(group, attempt, held)
        with self.lock:
            self.loop_prevs.pop(group.id, None)
        if isinstance(end, _Paused):
            return
        if isinstance(end, NodeFailedError):
            self._record_failure(group, attempt, end)
            self._end(group, NodeEnd(NodeResult("failed"), failure_kind=end.kind))
            return
        recorder.step_ended(StepEnd(group.id, attempt, "ok", self.ports.clock.now(), output=end))
        self._end(group, NodeEnd(NodeResult("completed", end)))

    def _iterate(
        self, group: LoopGroupNode, attempt: int, held: HeldGroup | None
    ) -> JsonValue | NodeFailedError | _Paused:
        """The group's iterations: the output map once done, why the group failed, or a pause
        (the group then held for the resume)."""
        body = {node.id: node for node in group.nodes}
        iteration, restored = self._start_iterations(group, held)
        while True:
            iteration += 1
            failure = self._run_body(group, body, iteration, restored=restored)
            restored = {}
            if isinstance(failure, _Paused):
                self._hold(group, attempt, iteration)
                return failure
            if failure is not None:
                return failure
            # Stopped during the body: no ``until_bash`` child and no next iteration.
            self._check_stop()
            output = {local_id(group, n): self.results[n].output for n in body}
            try:
                if self._group_done(group, iteration):
                    return output
            except NodeFailedError as failure:
                return failure
            if iteration >= group.max_iterations:
                detail = f"{group.max_iterations} iterations did not end the group"
                return MaxIterationsError(detail, output)
            with self.lock:
                self.loop_prevs[group.id] = {n: self.results[n] for n in body}

    def _start_iterations(
        self, group: LoopGroupNode, held: HeldGroup | None
    ) -> tuple[int, dict[str, NodeEnd]]:
        """The iteration before the first to run, and the body ends a pause left of it."""
        with self.lock:
            if held is None:
                for body in group.nodes:
                    self.sessions.pop(body.id, None)
                self.loop_prevs[group.id] = {}
                return 0, {}
            self.loop_prevs[group.id] = dict(held.previous)
        return held.iteration - 1, dict(held.current)

    def _hold(self, group: LoopGroupNode, attempt: int, iteration: int) -> None:
        """Keep the paused iteration for the resume: what it ended, and ``$LOOP_PREV``."""
        with self.lock:
            current = {n.id: self.ends[n.id] for n in group.nodes if n.id in self.ends}
            previous = dict(self.loop_prevs[group.id])
        self.held[group.id] = HeldGroup(attempt, iteration, previous, current)

    def _run_body(
        self,
        group: LoopGroupNode,
        body: Mapping[str, Node],
        iteration: int,
        *,
        restored: Mapping[str, NodeEnd],
    ) -> NodeFailedError | _Paused | None:
        """One iteration of the body's layers, after the nodes ``restored`` from a pause; why
        it fails the group, if it does, or a pause once a body layer leaves a gate open."""
        with self.lock:
            for node_id in body:
                self.ends.pop(node_id, None)
                self.results.pop(node_id, None)
            for node_id, end in restored.items():
                self.ends[node_id], self.results[node_id] = end, end.result
        for layer in self.plan.bodies[group.id]:
            self._check_stop()
            if waiting := [body[node_id] for node_id in layer if node_id not in restored]:
                self._run_layer(waiting)
            if self.halted_by is not None:
                return NodeFailedError("cancelled", "a halt in the body ended the run")
            if self.paused is not None or self.debug is not None:
                return _Paused()
        failed = next((n for n in body if self.ends[n].result.state == "failed"), None)
        if failed is None:
            return None
        kind = self.ends[failed].failure_kind or "unknown"
        return NodeFailedError(kind, f"{failed} failed in iteration {iteration}")

    def _group_done(self, group: LoopGroupNode, iteration: int) -> bool:
        """Whether the iteration ends the group: ``until_when``, then ``until_bash``."""
        context = self._context(group)
        if group.until_when is not None:
            when = evaluate_when(group.until_when, context)
            if isinstance(when, WhenFail | WhenSkip):
                detail = str(when.error) if isinstance(when, WhenFail) else when.detail
                raise NodeFailedError("config", detail)
            if when.holds:
                return True
        if group.until_bash is None:
            return False
        try:
            argv = render_argv(group.until_bash, context)
            check = ShellNode.model_construct(id=group.id, type="shell", command=tuple(argv))
            call = NodeCall(check, self.attempts[group.id], context, iteration, tuple(argv))
            return self.ports.runner.until_exit(argv, call) == 0
        except NodeFailedError:
            raise
        except SubstitutionError as error:
            raise NodeFailedError("config", str(error)) from None
        except Exception as error:  # noqa: BLE001 - a port's unexpected error ends the group
            raise NodeFailedError("unknown", type(error).__name__) from None

    def _output(self, node: _CommandNode, text: str) -> JsonValue:
        """The text, or the one JSON value it holds checked against ``output_format``."""
        if node.output_format is None:
            return text
        value = _json_value(text)
        self.ports.outputs.check(node.output_format, value)
        return value


class _Paused:
    """A group iteration stopped on an open gate, or before a node, in its body."""


class _RunStoppedError(BaseException):
    """The run stopped (an interrupted concurrent layer): a thread's work ends here."""


class _LockedRecorder:
    """``recorder`` for concurrent nodes: one call at a time, in the order they come."""

    def __init__(self, recorder: RunRecorder) -> None:
        self.recorder, self.lock = recorder, threading.Lock()

    def step_started(self, start: StepStart) -> None:
        with self.lock:
            self.recorder.step_started(start)

    def step_ended(self, end: StepEnd) -> None:
        with self.lock:
            self.recorder.step_ended(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        with self.lock:
            self.recorder.retry_scheduled(node, retry)

    def run_ended(self, end: RunEnd) -> None:
        with self.lock:
            self.recorder.run_ended(end)

    def gate_requested(self, request: GateRequest) -> None:
        with self.lock:
            self.recorder.gate_requested(request)


def _may_halt(node: Node) -> bool:
    """A halt, or a group whose body holds one: its layer runs one node at a time."""
    if isinstance(node, LoopGroupNode):
        return any(isinstance(child, HaltNode) for child in node.nodes)
    return isinstance(node, HaltNode)


def _refuse_constant(name: str) -> JsonValue:
    msg = f"{name} is not a JSON number"
    raise ValueError(msg)


def _json_value(text: str) -> JsonValue:
    """The one JSON value ``text`` holds, else ``output_contract``."""
    try:
        value: JsonValue = json.loads(text, parse_constant=_refuse_constant)
    except ValueError, RecursionError:
        raise NodeFailedError("output_contract", "the output is not one JSON value") from None
    return value


def _action_value(value: JsonValue, context: RefContext) -> JsonValue:
    """A ``with`` value for an action: a whole reference's value as is, other text rendered."""
    if isinstance(value, str):
        try:
            ref = parse_ref(value, scenario=context.scenario)
        except SubstitutionError:
            return render(value, context)
        return resolve(ref, context, value)
    if isinstance(value, list):
        return [_action_value(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _action_value(item, context) for key, item in value.items()}
    return value


def _rendered(value: JsonValue, context: RefContext) -> JsonValue:
    if isinstance(value, str):
        return render(value, context)
    if isinstance(value, list):
        return [_rendered(item, context) for item in value]
    if isinstance(value, dict):
        return {key: _rendered(item, context) for key, item in value.items()}
    return value
