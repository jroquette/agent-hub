"""Workflow gates (docs/design/workflow-schema.md § Nodes): ``approval`` and ``wait``.

A gate node pauses its run. On its first visit the engine opens a gate (``gate_id``
``<run>:<node>:<attempt>``) and records its request; on each resume it asks ``GateAnswers`` for
the answer a person gave, and a timed wait ends once its due time has passed. Without an answer
the run pauses again on the same gate. A gate's ``form`` says what answers it: ``decision`` (an
approval's decision id), ``choice`` (an attention wait's option id), ``text`` (an attention wait
without options) or ``timer`` (``duration`` or ``until``: no person answers it).

The output is ``{decision}`` (plus ``text`` under ``capture_response``), ``{at}``, ``{text}`` or
``{choice, text}``; ``when:`` and ``until_when`` read it like any other output. A ``reject`` of an
approval with the default decisions cancels the run, unless a ``when:`` or ``until_when`` reads
its decision (the workflow then routes the reject itself). An ``until`` is at most 7 days after
the gate opens.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal, Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.nodes import (
    MAX_DURATION_SECONDS,
    ApprovalNode,
    GateNode,
    Node,
    WaitNode,
    duration_seconds,
)
from agent_hub.core.workflows.substitution import (
    LoopPrevRef,
    NodeRef,
    SubstitutionError,
    echo,
    find_refs,
)

type GateKind = Literal["approval", "wait"]
type GateForm = Literal["decision", "choice", "text", "timer"]


class GateError(AgentHubError):
    """A gate that cannot open (an ``until`` that is no instant) or an answer it cannot take."""


def gate_id(run: str, node: str, attempt: int) -> str:
    """The id a gate is requested and decided by: one per node attempt, never reused."""
    return f"{run}:{node}:{attempt}"


@dataclass(frozen=True)
class GateAnswer:
    """What a person answered: ``choice`` (a decision or option id) and ``text``. A dry run's
    ``{}`` stub is an answer with neither: it ends a timed wait."""

    choice: str | None = None
    text: str | None = None


@dataclass(frozen=True)
class OpenGate:
    """A gate a paused run left open: its node's attempt and a timed wait's due time."""

    attempt: int
    due: datetime | None = None


class GateAnswers(Protocol):
    """The answers given to a run's gates (the run's record; a dry run's stubs)."""

    def answer(self, node: str, attempt: int) -> GateAnswer | None:
        """The answer to ``node``'s gate of ``attempt``, or ``None`` while it has none."""
        ...


class NoAnswers:
    """``GateAnswers`` for a run nobody answers yet."""

    def answer(self, node: str, attempt: int) -> GateAnswer | None:
        return None


def gate_kind(node: GateNode) -> GateKind:
    return "approval" if isinstance(node, ApprovalNode) else "wait"


def gate_form(node: GateNode) -> GateForm:
    if isinstance(node, ApprovalNode):
        return "decision"
    if node.attention is None:
        return "timer"
    return "text" if node.options is None else "choice"


def gate_choices(node: GateNode) -> tuple[str, ...]:
    """The ids an answer may choose: an approval's decisions, an attention wait's options."""
    choices = node.decisions if isinstance(node, ApprovalNode) else node.options or ()
    return tuple(choice.id for choice in choices)


def gate_template(node: GateNode) -> str:
    """The text the engine renders when the gate opens: a message, or a wait's ``until``."""
    if isinstance(node, ApprovalNode):
        return node.message
    return node.attention or node.until or ""


def wait_due(node: GateNode, rendered: str, now: datetime) -> datetime | None:
    """When a timed wait ends: ``now`` plus its ``duration``, or its rendered ``until``."""
    if not isinstance(node, WaitNode) or node.attention is not None:
        return None
    if node.duration is not None:
        return now + timedelta(seconds=duration_seconds(node.duration))
    try:
        due = datetime.fromisoformat(rendered)
    except ValueError:
        due = None
    if due is None or due.tzinfo is None:
        msg = f"until {echo(rendered)} is not an ISO-8601 instant with an offset"
        raise GateError(msg)
    if due - now > timedelta(seconds=MAX_DURATION_SECONDS):
        msg = f"until {echo(rendered)} is more than 7 days after the gate opened"
        raise GateError(msg)
    return due


def reject_cancels(node: GateNode, nodes: Sequence[Node]) -> bool:
    """Whether a ``reject`` of ``node`` cancels the run: an approval with the default decisions
    whose decision no ``when:`` or ``until_when`` reads (``$<gate>`` or ``$LOOP_PREV.<gate>``)."""
    if not isinstance(node, ApprovalNode) or "decisions" in node.model_fields_set:
        return False
    wanted = {NodeRef(node.id, ("decision",)), LoopPrevRef(node.id, ("decision",))}
    for other in nodes:
        for text in (other.when, getattr(other, "until_when", None)):
            if isinstance(text, str) and wanted.intersection(_refs(text)):
                return False
    return True


def _refs(text: str) -> list[object]:
    try:
        return list(find_refs(text))
    except SubstitutionError:
        return []


def answer_problem(form: GateForm, choices: tuple[str, ...], answer: GateAnswer) -> str | None:
    """Why ``answer`` cannot answer a gate of ``form`` offering ``choices``; ``None`` if it can."""
    if form == "timer":
        return "a timed wait takes no answer; it ends at its time"
    if form == "text":
        if answer.choice is not None:
            return "this wait takes no option, only a text answer"
        return None if answer.text and answer.text.strip() else "this wait needs a text answer"
    noun = "decision" if form == "decision" else "option"
    if answer.choice is None:
        article = "a" if form == "decision" else "an"
        return f"this gate needs {article} {noun}: one of {', '.join(choices)}"
    if answer.choice not in choices:
        return f"no {noun} {echo(answer.choice)}: one of {', '.join(choices)}"
    return None


def gate_output(
    node: GateNode, answer: GateAnswer | None, *, due: datetime | None, now: datetime
) -> JsonValue:
    """The gate's output once it ends, or ``None`` while it stays open.

    Raises ``GateError`` when the answer does not fit the gate.
    """
    form = gate_form(node)
    if form == "timer":
        ended = answer is not None or (due is not None and now >= due)
        return {"at": now.isoformat()} if ended else None
    if answer is None:
        return None
    if (problem := answer_problem(form, gate_choices(node), answer)) is not None:
        raise GateError(problem)
    text = answer.text or ""
    if form == "text":
        return {"text": text}
    if form == "choice":
        return {"choice": answer.choice, "text": text}
    output: dict[str, JsonValue] = {"decision": answer.choice}
    if isinstance(node, ApprovalNode) and node.capture_response:
        output["text"] = text
    return output
