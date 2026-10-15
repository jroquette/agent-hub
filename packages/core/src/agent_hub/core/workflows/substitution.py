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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.versions import cut_echo
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
# Index syntax that is not ours (``[0]``, ``.[0]``, ``?.``), refused right after a reference.
_FOREIGN = r"(?:\[|\.\[|\?\.)"
_TOKEN = re.compile(
    rf"\$(?:(?P<dollar>\$)"
    rf"|INPUTS\.(?P<input>{_NAME})(?![A-Za-z0-9_.])"
    rf"|WITH\.(?P<with>{_NAME})(?![A-Za-z0-9_.])"
    rf"|LOOP_PREV\.(?P<prev>{_ID})\.output(?P<prev_path>{_PATH})(?![A-Za-z0-9_]|{_FOREIGN})"
    rf"|(?P<node>{_ID})\.output(?P<path>{_PATH})(?![A-Za-z0-9_]|{_FOREIGN}))"
)
_RESERVED = re.compile(r"\$(?:INPUTS|WITH|LOOP_PREV)(?![A-Za-z0-9_])")
_BAD_SUFFIX = re.compile(rf"\$(?:LOOP_PREV\.)?{_ID}\.output{_PATH}{_FOREIGN}")
_LEADING_ZERO = re.compile(r"0[0-9]+")
# A short-option cluster (``-e``, ``+ec``); one holding ``c`` is a script flag. No ``*`` around
# the ``c``: that pattern backtracks quadratically on a long cluster that does not match.
_CLUSTER = re.compile(r"[-+][A-Za-z]+")


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
        super().__init__(f"{echo(ref)}: {detail}")


def echo(text: str) -> str:
    """``text`` quoted and escaped as JSON, cut to the repo's echo limit, for messages."""
    return cut_echo(json.dumps(text))


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


def rewrite_refs(template: str, replace: Callable[[Ref, str], str]) -> str:
    """Replace each reference by ``replace(ref, spelling)``, in one pass; ``$$`` stays ``$$``."""
    parts: list[str] = []
    last = 0
    for start, end, ref in _scan(template):
        parts.append(template[last:start])
        parts.append(template[start:end] if ref is None else replace(ref, template[start:end]))
        last = end
    parts.append(template[last:])
    return "".join(parts)


def spell(ref: NodeRef | LoopPrevRef) -> str:
    """The spelling of a node reference: ``$<node>.output[.path]``, or its ``$LOOP_PREV`` form."""
    start = "$LOOP_PREV." if isinstance(ref, LoopPrevRef) else "$"
    return f"{start}{ref.node}.output" + "".join(f".{segment}" for segment in ref.path)


def check_argv(argv: Sequence[str]) -> list[ArgvProblem]:
    """Return the references argv refuses, by index, without resolving any.

    A reference must fill a whole element and never be the program (``argv[0]``). Shell option
    grammar is not modelled; once argv holds a reference, the rule fails closed. A script flag is
    a short-option cluster, prefixed by ``-`` or ``+``, holding ``c`` (``-c``, ``-lc``, ``+ec``).
    The flag is refused when it also holds ``o`` or ``O``, or when the element after it is
    missing, starts with ``-`` or ``+``, or is a reference: shell options go before ``-c``, and
    the element right after it is the literal script. A reference at or before the last flag's
    script is refused too; the ones after it are positional parameters, the only way a script
    gets values.
    """
    problems, whole = _whole_references(argv)
    if not problems and not whole:
        return []
    reach = _check_script_flags(argv, set(whole), problems)
    for index in whole:
        if index == 0:
            problems.append(_problem(argv, index, code="argv_program", detail="not the program"))
        elif index <= reach:
            problems.append(
                _problem(argv, index, code="argv_script", detail="pass it after the script")
            )
    return sorted(problems, key=lambda problem: problem.index)


def _whole_references(argv: Sequence[str]) -> tuple[list[ArgvProblem], list[int]]:
    """Problems of malformed and partial references, and the indexes of whole ones."""
    problems: list[ArgvProblem] = []
    whole: list[int] = []
    for index, element in enumerate(argv):
        try:
            tokens = _scan(element)
        except SubstitutionError as malformed:
            problems.append(ArgvProblem(index, malformed))
            continue
        refs = [(start, end) for start, end, ref in tokens if ref is not None]
        if refs and (len(tokens) > 1 or refs[0] != (0, len(element))):
            text = element[refs[0][0] : refs[0][1]]
            error = SubstitutionError("partial_argv", text, "a reference must fill a whole element")
            problems.append(ArgvProblem(index, error))
        elif refs:
            whole.append(index)
    return problems, whole


def _check_script_flags(argv: Sequence[str], whole: set[int], problems: list[ArgvProblem]) -> int:
    """Add a problem for each ill-placed script flag; return the last flag's script index."""
    reach = -1
    for index, element in enumerate(argv):
        if "c" not in element or _CLUSTER.fullmatch(element) is None:
            continue
        reach = index + 1
        after = argv[reach] if reach < len(argv) else None
        if reach in whole:
            continue
        if "o" in element.lower() or after is None or after.startswith(("-", "+")):
            detail = "put shell options before -c; the element right after -c is the literal script"
            problems.append(_problem(argv, index, code="argv_script", detail=detail))
    return reach


def _problem(
    argv: Sequence[str], index: int, *, code: SubstitutionErrorCode, detail: str
) -> ArgvProblem:
    return ArgvProblem(index, SubstitutionError(code, argv[index], detail))


def render_argv(argv: Sequence[str], context: RefContext) -> list[str]:
    """Render each element, after refusing what ``check_argv`` reports (its first problem)."""
    if problems := check_argv(argv):
        raise problems[0].error
    return [render(element, context) for element in argv]


def resolve_text(ref: Ref, context: RefContext, text: str) -> str:
    """Return the canonical text of the value ``ref`` reads; a NaN or infinity is an error."""
    value = resolve(ref, context, text)
    try:
        return canonical_text(value)
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
                raise SubstitutionError("unknown_node", text, f"node {echo(node)} has no result")
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
        raise SubstitutionError(code, text, f"no value named {echo(name)} (known: {echo(known)})")
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
            raise SubstitutionError("bad_path", text, f"cannot read {echo(segment)} there")
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
        return LoopPrevRef(match["prev"], _segments(match["prev_path"], match[0]))
    return NodeRef(match["node"], _segments(match["path"], match[0]))


def _segments(path: str, text: str) -> tuple[str, ...]:
    segments = tuple(path.split(".")[1:])
    if any(_LEADING_ZERO.fullmatch(segment) for segment in segments):
        raise SubstitutionError("malformed", text, "an index is 0 or has no leading zero")
    return segments
