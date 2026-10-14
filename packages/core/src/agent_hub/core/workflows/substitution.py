"""Output references and single-pass substitution (workflow-schema.md, ADR 0032).

Reference grammar, one token at each ``$``:

- ``$INPUTS.<name>`` and ``$WITH.<name>``, ``<name>`` matching ``[a-z][a-z0-9_]*``; no path.
- ``$<id>.output`` and ``$LOOP_PREV.<id>.output``, ``<id>`` matching ``[a-z][a-z0-9_-]*`` (so
  ``-`` and the include namespace ``__`` belong to it), then a path of ``.<segment>``, a segment
  being ``[A-Za-z0-9_]+``; an all-digit segment indexes an array (``.0``).
- ``$$`` is one literal ``$`` and starts nothing.

A path stops at the first character that cannot continue it: the dot ending the sentence
``$plan.output.summary.`` stays text, and ``$plan.output-x`` is the reference then ``-x``. A ``$``
that starts none of these (``$1``, ``${HOME}``, ``$plan.outputs``) stays text. ``INPUTS``, ``WITH``
and ``LOOP_PREV`` followed by anything but a valid token, and ``[`` or ``?.`` right after a
reference, are ``malformed`` errors, never text.

Values render as canonical text (``canonical_text``), in one left-to-right pass: inserted text is
never scanned again. A skipped producer, an absent key or item, and ``$LOOP_PREV`` before a first
iteration read as empty text; a failed producer, a node with no result, an unknown input or
``with`` name, a path through a scalar, and a NaN or infinity are errors. In argv a reference
must be a whole element, never the program nor a ``-c`` script (``check_argv``).
"""

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue

type NodeState = Literal["completed", "failed", "skipped"]
type SubstitutionErrorCode = Literal[
    "malformed",
    "unknown_input",
    "unknown_with",
    "unknown_node",
    "producer_failed",
    "bad_path",
    "not_in_loop",
    "non_finite",
    "partial_argv",
    "argv_program",
    "argv_script",
]

_NAME = r"[a-z][a-z0-9_]*"
_ID = r"[a-z][a-z0-9_-]*"
# Possessive, so a path never gives back a segment to slip past the lookahead after it.
_PATH = r"(?:\.[A-Za-z0-9_]++)*+"
_TOKEN = re.compile(
    rf"\$(?:(?P<dollar>\$)"
    rf"|INPUTS\.(?P<input>{_NAME})(?![A-Za-z0-9_.])"
    rf"|WITH\.(?P<with>{_NAME})(?![A-Za-z0-9_.])"
    rf"|LOOP_PREV\.(?P<prev>{_ID})\.output(?P<prev_path>{_PATH})(?![A-Za-z0-9_\[]|\?\.)"
    rf"|(?P<node>{_ID})\.output(?P<path>{_PATH})(?![A-Za-z0-9_\[]|\?\.))"
)
_RESERVED = re.compile(r"\$(?:INPUTS|WITH|LOOP_PREV)(?![A-Za-z0-9_])")
_BAD_SUFFIX = re.compile(rf"\$(?:LOOP_PREV\.)?{_ID}\.output{_PATH}(?:\[|\?\.)")


@dataclass(frozen=True)
class InputRef:
    name: str


@dataclass(frozen=True)
class WithRef:
    name: str


@dataclass(frozen=True)
class NodeRef:
    node: str
    path: tuple[str, ...]


@dataclass(frozen=True)
class LoopPrevRef:
    node: str
    path: tuple[str, ...]


type Ref = InputRef | WithRef | NodeRef | LoopPrevRef


@dataclass(frozen=True)
class NodeResult:
    """A node's end as references see it: its state and output (parsed JSON, or the text)."""

    state: NodeState
    output: JsonValue = None


@dataclass(frozen=True)
class RefContext:
    """What references resolve against; ``loop_prev`` is ``None`` outside a ``loop_group`` body."""

    inputs: Mapping[str, JsonValue]
    nodes: Mapping[str, NodeResult]
    loop_prev: Mapping[str, NodeResult] | None = None
    with_values: Mapping[str, JsonValue] = field(default_factory=dict)


class SubstitutionError(AgentHubError):
    """A reference that cannot be read; ``code`` says why and ``ref`` is its text."""

    def __init__(self, code: SubstitutionErrorCode, ref: str, detail: str) -> None:
        self.code: SubstitutionErrorCode = code
        self.ref = ref
        super().__init__(f"{ref}: {detail}")


def canonical_text(value: JsonValue) -> str:
    """Strings as is, null as empty, else compact JSON with sorted keys (UTF-8, not escaped)."""
    if isinstance(value, str):
        return value
    if value is None:
        return ""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


@dataclass(frozen=True)
class ArgvProblem:
    """Why the argv element at ``index`` cannot hold its reference."""

    index: int
    error: SubstitutionError


def parse_ref(text: str) -> Ref:
    """Return the one reference ``text`` is, whole; anything else is ``malformed``."""
    match = _TOKEN.fullmatch(text)
    if match is None or match["dollar"]:
        raise SubstitutionError("malformed", text, "not one whole reference")
    return _ref_of(match)


def find_refs(template: str) -> list[Ref]:
    """Return the references of ``template`` in order, without resolving them."""
    return [ref for _, _, ref in _scan(template) if ref is not None]


def render(template: str, context: RefContext) -> str:
    """Replace every reference by its value's canonical text, in one pass."""
    parts: list[str] = []
    last = 0
    for start, end, ref in _scan(template):
        parts.append(template[last:start])
        parts.append("$" if ref is None else resolve_text(ref, context, template[start:end]))
        last = end
    parts.append(template[last:])
    return "".join(parts)


def check_argv(argv: Sequence[str]) -> list[ArgvProblem]:
    """Return the references argv refuses, without resolving any.

    A reference must fill a whole element, and never the program (``argv[0]``) nor the element
    right after a ``-c`` (a script for ``sh``, ``bash``, ``python`` alike): a script gets values
    only as positional parameters.
    """
    problems: list[ArgvProblem] = []
    for index, element in enumerate(argv):
        try:
            tokens = _scan(element)
        except SubstitutionError as malformed:
            problems.append(ArgvProblem(index, malformed))
            continue
        refs = [(start, end) for start, end, ref in tokens if ref is not None]
        if not refs:
            continue
        text = element[refs[0][0] : refs[0][1]]
        if len(tokens) > 1 or refs[0] != (0, len(element)):
            error = SubstitutionError("partial_argv", text, "a reference must fill a whole element")
        elif index == 0:
            error = SubstitutionError("argv_program", text, "a reference cannot be the program")
        elif argv[index - 1] == "-c":
            error = SubstitutionError("argv_script", text, "pass it as a positional parameter")
        else:
            continue
        problems.append(ArgvProblem(index, error))
    return problems


def render_argv(argv: Sequence[str], context: RefContext) -> list[str]:
    """Render each element, after refusing what ``check_argv`` reports (its first problem)."""
    if problems := check_argv(argv):
        raise problems[0].error
    return [render(element, context) for element in argv]


def resolve_text(ref: Ref, context: RefContext, text: str) -> str:
    """Return the canonical text of the value ``ref`` reads; a NaN or infinity is an error."""
    try:
        return canonical_text(resolve(ref, context, text))
    except ValueError as error:
        raise SubstitutionError("non_finite", text, "the value holds a NaN or infinity") from error


def resolve(ref: Ref, context: RefContext, text: str) -> JsonValue:
    """Return the value ``ref`` reads in ``context``; ``text``, its spelling, names it in errors."""
    match ref:
        case InputRef(name):
            return _named(context.inputs, name, text, code="unknown_input")
        case WithRef(name):
            return _named(context.with_values, name, text, code="unknown_with")
        case LoopPrevRef(node, path):
            if context.loop_prev is None:
                raise SubstitutionError("not_in_loop", text, "$LOOP_PREV outside a loop_group body")
            result = context.loop_prev.get(node)
            return None if result is None else _read(result, path, text)
        case NodeRef(node, path):
            if node not in context.nodes:
                raise SubstitutionError("unknown_node", text, f"node {node!r} has no result")
            return _read(context.nodes[node], path, text)


def _named(
    values: Mapping[str, JsonValue],
    name: str,
    text: str,
    *,
    code: Literal["unknown_input", "unknown_with"],
) -> JsonValue:
    if name not in values:
        known = ", ".join(sorted(values)) or "none"
        raise SubstitutionError(code, text, f"no value named {name!r} (known: {known})")
    return values[name]


def _read(result: NodeResult, path: tuple[str, ...], text: str) -> JsonValue:
    if result.state == "failed":
        raise SubstitutionError("producer_failed", text, "its producer failed")
    if result.state == "skipped":
        return None
    value = result.output
    for segment in path:
        if isinstance(value, dict):
            value = value.get(segment)
        elif isinstance(value, list) and segment.isdigit():
            # More digits than any list length is absent (and int() refuses over 4300 digits).
            index = int(segment) if len(segment) <= len(str(len(value))) else len(value)
            value = value[index] if index < len(value) else None
        elif value is None:
            return None
        else:
            raise SubstitutionError("bad_path", text, f"cannot read {segment!r} there")
    return value


def _scan(template: str) -> list[tuple[int, int, Ref | None]]:
    """Return ``(start, end, ref)`` for each token, ``ref`` ``None`` for ``$$``."""
    tokens: list[tuple[int, int, Ref | None]] = []
    position = template.find("$")
    while position != -1:
        match = _TOKEN.match(template, position)
        if match is not None:
            tokens.append((position, match.end(), None if match["dollar"] else _ref_of(match)))
            position = template.find("$", match.end())
            continue
        bad = _RESERVED.match(template, position) or _BAD_SUFFIX.match(template, position)
        if bad is not None:
            raise SubstitutionError(
                "malformed", template[position : bad.end()], "malformed reference"
            )
        position = template.find("$", position + 1)
    return tokens


def _ref_of(match: re.Match[str]) -> Ref:
    if match["input"]:
        return InputRef(match["input"])
    if match["with"]:
        return WithRef(match["with"])
    if match["prev"]:
        return LoopPrevRef(match["prev"], _segments(match["prev_path"]))
    return NodeRef(match["node"], _segments(match["path"]))


def _segments(path: str) -> tuple[str, ...]:
    return tuple(path.split(".")[1:])
