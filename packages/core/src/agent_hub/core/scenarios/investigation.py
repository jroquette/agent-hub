"""An interactive scenario run's investigation: its gate, its answers and the proposal an agent
records for it (P-5, P-8, AM-1, AM-3, AM-11; docs/design/scenarios.md § Investigation).

A divergence of an ``action`` or ``expect`` step (not a ``config`` failure) pauses an
interactive scenario run at the gate ``<step>__investigation`` (``investigation_gate``), a
``choice`` answered with ``pick`` (the option id as text), ``retry`` or ``stop``. A scenario run
opens at most ``MAX_INVESTIGATIONS``; the next divergence fails it as in regression mode. Which
gate is an investigation's comes from the run's record (an ``investigation`` line names its
``gate``), never from the id's suffix.

``parse_proposal`` reads what ``hub scenario propose`` gets on stdin, a fixed schema of
untrusted text: ``{"findings": [{"title", "text", "evidence"?}], "options": [{"summary",
"steps": [{"action", "with"?}]}]}``, unknown keys refused, every bound of
``docs/design/scenarios.md`` § Events and bounds checked (the first problem is the error), then
every text redacted of the secret shapes (``secret_shapes.redact_shapes``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.secret_shapes import redact_shapes

INVESTIGATION_SUFFIX: Final = "__investigation"
# The ``reason`` of an investigation's ``gate.request`` event.
INVESTIGATION_REASON: Final = "investigation"
PICK: Final = "pick"
RETRY: Final = "retry"
STOP: Final = "stop"
CHOICES: Final = (PICK, RETRY, STOP)
MAX_INVESTIGATIONS: Final = 10
MAX_PROPOSAL_BYTES: Final = 256 * 1024
MAX_FINDINGS: Final = 20
MAX_TITLE_CHARS: Final = 120
MAX_TEXT_CHARS: Final = 2000
MAX_OPTIONS: Final = 5
MAX_SUMMARY_CHARS: Final = 300
MAX_STEPS: Final = 10
_SHOWN_KEY_CHARS: Final = 40


class ProposalError(AgentHubError):
    """A proposal that does not fit the schema or its bounds: the first problem, plainly."""


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    title: str
    text: str
    evidence: str = ""


@dataclass(frozen=True, kw_only=True, slots=True)
class ProposedStep:
    """One step of an option: an action reference and its ``with`` values."""

    action: str
    inputs: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, kw_only=True, slots=True)
class Option:
    summary: str
    steps: tuple[ProposedStep, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class Proposal:
    findings: tuple[Finding, ...]
    options: tuple[Option, ...]


def investigation_gate(step: str) -> str:
    """The id of the investigation gate after ``step`` (both as recorded)."""
    return f"{step}{INVESTIGATION_SUFFIX}"


def option_id(index: int) -> str:
    """The id an option is picked by: ``o<n>``, its place in the proposal from 1."""
    return f"o{index}"


def parse_proposal(data: bytes) -> Proposal:
    """The proposal ``data`` holds, its texts redacted; raises ``ProposalError``."""
    if len(data) > MAX_PROPOSAL_BYTES:
        raise ProposalError(f"the proposal is larger than {MAX_PROPOSAL_BYTES} bytes")
    try:
        value = load_json_bytes(data, strict=True)
    except InvalidJsonError:
        raise ProposalError("the proposal is not one JSON value in UTF-8") from None
    top = _object(value, "the proposal", required=("findings", "options"), allowed=())
    findings = _items(top["findings"], "findings", MAX_FINDINGS)
    options = _items(top["options"], "options", MAX_OPTIONS)
    return Proposal(
        findings=tuple(_finding(item, n) for n, item in enumerate(findings, 1)),
        options=tuple(_option(item, n) for n, item in enumerate(options, 1)),
    )


def _finding(value: JsonValue, number: int) -> Finding:
    where = f"finding {number}"
    given = _object(value, where, required=("title", "text"), allowed=("evidence",))
    return Finding(
        title=_text(given["title"], f"{where}: title", MAX_TITLE_CHARS, empty=False),
        text=_text(given["text"], f"{where}: text", MAX_TEXT_CHARS),
        evidence=_text(given.get("evidence", ""), f"{where}: evidence", MAX_TEXT_CHARS),
    )


def _option(value: JsonValue, number: int) -> Option:
    where = f"option {number}"
    given = _object(value, where, required=("summary", "steps"), allowed=())
    steps = _items(given["steps"], f"{where}: steps", MAX_STEPS)
    return Option(
        summary=_text(given["summary"], f"{where}: summary", MAX_SUMMARY_CHARS, empty=False),
        steps=tuple(_step(item, f"{where} step {n}") for n, item in enumerate(steps, 1)),
    )


def _step(value: JsonValue, where: str) -> ProposedStep:
    given = _object(value, where, required=("action",), allowed=("with",))
    action = _text(given["action"], f"{where}: action", MAX_TITLE_CHARS, empty=False)
    raw = given.get("with", {})
    if not isinstance(raw, dict) or not all(
        isinstance(item, str | int | float) for item in raw.values()
    ):
        raise ProposalError(f"{where}: with must map names to text, numbers or booleans")
    inputs = {
        redact_shapes(key): redact_shapes(item) if isinstance(item, str) else item
        for key, item in raw.items()
    }
    return ProposedStep(action=action, inputs=inputs)


def _object(
    value: JsonValue, where: str, *, required: Sequence[str], allowed: Sequence[str]
) -> dict[str, JsonValue]:
    if not isinstance(value, dict):
        raise ProposalError(f"{where} must be an object")
    if unknown := [key for key in value if key not in (*required, *allowed)]:
        shown = unknown[0][:_SHOWN_KEY_CHARS]
        raise ProposalError(f"{where} has an unknown key {shown!r}")
    if missing := [key for key in required if key not in value]:
        raise ProposalError(f"{where} needs {missing[0]}")
    return value


def _items(value: JsonValue, where: str, most: int) -> list[JsonValue]:
    if not isinstance(value, list):
        raise ProposalError(f"{where} must be a list")
    if len(value) > most:
        raise ProposalError(f"{where}: at most {most}")
    return value


def _text(value: JsonValue, where: str, most: int, *, empty: bool = True) -> str:
    if not isinstance(value, str) or len(value) > most or (not empty and not value.strip()):
        least = 0 if empty else 1
        raise ProposalError(f"{where} must be text of {least} to {most} characters")
    return redact_shapes(value)
