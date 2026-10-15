"""Fakes for the workflow engine's ports: scripted nodes, a clock that never sleeps, a recorder,
gate answers.

``ScriptedRunner`` answers each node from a list, one item per attempt: a ``NodeReply``, a
string (the reply's text) or an exception to raise. ``KeysOutputs`` checks only an
object schema's ``required`` keys; JSON Schema itself is ``generator``'s, tested there.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from threading import Event

from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.failures import NodeFailedError, RetryRecord
from agent_hub.core.workflows.gates import GateAnswer
from agent_hub.core.workflows.plan import WorkflowPlan, plan_workflow
from agent_hub.core.workflows.ports import (
    GateRequest,
    NodeCall,
    NodeReply,
    RunEnd,
    StepEnd,
    StepStart,
)

START = datetime(2026, 10, 15, 9, 0, tzinfo=UTC)

type Scripted = NodeReply | str | Exception


def a_plan(*nodes: Mapping[str, object], **top: object) -> WorkflowPlan:
    """The plan of a document holding ``nodes`` (``top`` adds or overrides top-level keys)."""
    document = {"version": 1, "name": "demo", "revision": 1, "nodes": list(nodes), **top}
    return plan_workflow(parse_workflow(document))


class FakeClock:
    """A clock whose ``sleep`` only moves it on and remembers the delay."""

    def __init__(self, now: datetime = START) -> None:
        self.current = now
        self.sleeps: list[timedelta] = []

    def now(self) -> datetime:
        return self.current

    def sleep(self, delay: timedelta, stop: Event | None = None) -> None:
        self.sleeps.append(delay)
        self.current += delay


@dataclass
class ScriptedRunner:
    """Answers each node's attempts in order; a node with nothing left answers ``""``."""

    replies: Mapping[str, Sequence[Scripted]] = field(default_factory=dict)
    exits: Mapping[str, Sequence[int]] = field(default_factory=dict)
    calls: list[NodeCall] = field(default_factory=list)
    until_calls: list[tuple[str, tuple[str, ...]]] = field(default_factory=list)

    def run(self, call: NodeCall) -> NodeReply:
        done = sum(1 for earlier in self.calls if earlier.node.id == call.node.id)
        self.calls.append(call)
        script = self.replies.get(call.node.id, ())
        reply: Scripted = script[done] if done < len(script) else ""
        if isinstance(reply, Exception):
            raise reply
        return NodeReply(reply) if isinstance(reply, str) else reply

    def until_exit(self, argv: Sequence[str], call: NodeCall) -> int:
        done = sum(1 for node, _ in self.until_calls if node == call.node.id)
        self.until_calls.append((call.node.id, tuple(argv)))
        script = self.exits.get(call.node.id, ())
        return script[done] if done < len(script) else 1

    def ran(self) -> list[str]:
        """The node ids of every attempt, in order."""
        return [call.node.id for call in self.calls]


class KeysOutputs:
    """An ``OutputValidator`` that checks an object schema's ``required`` keys only."""

    def schema_problems(self, schema: Mapping[str, JsonValue]) -> tuple[str, ...]:
        return ()

    def check(self, schema: Mapping[str, JsonValue], value: JsonValue) -> None:
        required = schema.get("required")
        if schema.get("type") != "object" or not isinstance(required, list):
            return
        if not isinstance(value, dict) or any(key not in value for key in required):
            raise NodeFailedError("output_contract", "$: breaks 'required'")


@dataclass
class ListRecorder:
    """Keeps every call a run makes, in order."""

    starts: list[StepStart] = field(default_factory=list)
    ends: list[StepEnd] = field(default_factory=list)
    retries: list[tuple[str, RetryRecord]] = field(default_factory=list)
    run_ends: list[RunEnd] = field(default_factory=list)
    gates: list[GateRequest] = field(default_factory=list)

    def step_started(self, start: StepStart) -> None:
        self.starts.append(start)

    def step_ended(self, end: StepEnd) -> None:
        self.ends.append(end)

    def retry_scheduled(self, node: str, retry: RetryRecord) -> None:
        self.retries.append((node, retry))

    def run_ended(self, end: RunEnd) -> None:
        self.run_ends.append(end)

    def gate_requested(self, request: GateRequest) -> None:
        self.gates.append(request)

    def end_of(self, node: str) -> StepEnd:
        """The last end recorded for ``node``."""
        return [end for end in self.ends if end.node == node][-1]


@dataclass
class AnswerBook:
    """The ``GateAnswers`` of a test: an answer per ``(node, attempt)``."""

    answers: Mapping[tuple[str, int], GateAnswer] = field(default_factory=dict)

    def answer(self, node: str, attempt: int) -> GateAnswer | None:
        return self.answers.get((node, attempt))
