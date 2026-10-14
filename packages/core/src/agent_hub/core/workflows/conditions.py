"""The ``when:`` grammar and its evaluation (workflow-schema.md, ADR 0032).

``expr := clause ('||' clause)*``, ``clause := atom ('&&' atom)*``, so ``&&`` binds tighter; no
parentheses, negation, functions or arithmetic. ``atom := <ref> <op> <literal>``: the reference is
one whole ``$INPUTS``, ``$<id>.output`` or ``$LOOP_PREV`` token of ``substitution``'s grammar
(``$WITH`` is for prompts), ``op`` one of ``== != <= >= < >`` (longest first),
and the literal ``'text'`` (``''`` inside is one quote), a number ``-?\\d+(\\.\\d+)?``, ``true`` or
``false``. A quoted literal is always text, even ``'80'``; ordering needs a number literal.

The whole expression is parsed before any reference is read; then clauses run left to right,
short-circuiting, so a reference in a clause never reached is never resolved. A number literal
compares numerically against the value's canonical text read as a JSON number (``1 == 1.0``); a
value that is not one is a parse failure. Other literals compare canonical text exactly.
"""

import json
import operator
import re
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.workflows.substitution import (
    Ref,
    RefContext,
    SubstitutionError,
    WithRef,
    parse_ref,
    resolve_text,
)

type Op = Literal["==", "!=", "<=", ">=", "<", ">"]

_OPS: tuple[Op, ...] = ("==", "!=", "<=", ">=", "<", ">")
_REF = re.compile(r"\$[A-Za-z0-9_.\-]*")
_NUMBER = re.compile(r"-?[0-9]+(?:\.[0-9]+)?(?![A-Za-z0-9_.])")
_BOOLEAN = re.compile(r"(?:true|false)(?![A-Za-z0-9_])")
_JSON_NUMBER = re.compile(r"-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?")
_COMPARE: dict[Op, Callable[[Decimal, Decimal], bool]] = {
    "==": operator.eq,
    "!=": operator.ne,
    "<=": operator.le,
    ">=": operator.ge,
    "<": operator.lt,
    ">": operator.gt,
}


class ConditionParseError(AgentHubError):
    """An expression outside the ``when:`` grammar."""


@dataclass(frozen=True)
class Atom:
    """``ref op literal``; a number literal is a ``Decimal``, a boolean its text."""

    ref: Ref
    ref_text: str
    op: Op
    literal: str | Decimal


@dataclass(frozen=True)
class Condition:
    """Clauses joined by ``||``, each a tuple of atoms joined by ``&&``."""

    clauses: tuple[tuple[Atom, ...], ...]


@dataclass(frozen=True)
class WhenValue:
    """The condition evaluated; ``False`` skips the node with cause ``condition``."""

    holds: bool


@dataclass(frozen=True)
class WhenSkip:
    """The expression, or a value it compares, does not parse: the node is skipped."""

    detail: str
    cause: Literal["condition_parse_error"] = "condition_parse_error"


@dataclass(frozen=True)
class WhenFail:
    """A reference cannot be read: the node fails."""

    error: SubstitutionError


type WhenResult = WhenValue | WhenSkip | WhenFail


class _NotANumberError(Exception):
    """A value compared with a number literal is not a number (a parse failure, not false)."""


@dataclass(frozen=True)
class _Join:
    text: str


@dataclass(frozen=True)
class _RefToken:
    ref: Ref
    text: str


@dataclass(frozen=True)
class _OpToken:
    op: Op


@dataclass(frozen=True)
class _Literal:
    value: str | Decimal


type _Token = _Join | _RefToken | _OpToken | _Literal


def evaluate_when(expr: str, context: RefContext) -> WhenResult:
    """Parse ``expr`` whole, then evaluate it lazily against ``context``."""
    try:
        condition = parse_condition(expr)
    except ConditionParseError as error:
        return WhenSkip(str(error))
    try:
        return WhenValue(
            any(all(_holds(atom, context) for atom in clause) for clause in condition.clauses)
        )
    except SubstitutionError as error:
        return WhenFail(error)
    except _NotANumberError as error:
        return WhenSkip(str(error))


def parse_condition(expr: str) -> Condition:
    """Return the parsed ``expr``, or raise ``ConditionParseError``."""
    tokens = _tokens(expr)
    clauses: list[tuple[Atom, ...]] = []
    atoms: list[Atom] = []
    index = 0
    while True:
        atoms.append(_atom(tokens[index : index + 3], expr))
        index += 3
        joiner = tokens[index] if index < len(tokens) else None
        if joiner is None or joiner == _Join("||"):
            clauses.append(tuple(atoms))
            atoms = []
        if joiner is None:
            return Condition(tuple(clauses))
        if not isinstance(joiner, _Join):
            raise ConditionParseError(f"{_echo(expr)}: expected && or || after an atom")
        index += 1


def _atom(tokens: list[_Token], expr: str) -> Atom:
    match tokens:
        case [_RefToken(ref, text), _OpToken(op), _Literal(literal)]:
            if isinstance(literal, str) and op not in ("==", "!="):
                raise ConditionParseError(f"{_echo(expr)}: {op} needs a number literal")
            return Atom(ref, text, op, literal)
    raise ConditionParseError(f"{_echo(expr)}: each atom is <reference> <operator> <literal>")


def _tokens(expr: str) -> list[_Token]:
    tokens: list[_Token] = []
    index = 0
    while index < len(expr):
        if expr[index].isspace():
            index += 1
            continue
        token, index = _token(expr, index)
        tokens.append(token)
    return tokens


def _token(expr: str, index: int) -> tuple[_Token, int]:
    if expr.startswith(("&&", "||"), index):
        return _Join(expr[index : index + 2]), index + 2
    if expr[index] == "'":
        return _quoted(expr, index)
    if ref := _REF.match(expr, index):
        try:
            parsed = parse_ref(ref[0])
        except SubstitutionError as error:
            raise ConditionParseError(f"{_echo(expr)}: bad reference {_echo(ref[0])}") from error
        if isinstance(parsed, WithRef):
            raise ConditionParseError(f"{_echo(expr)}: $WITH is for prompts, not conditions")
        return _RefToken(parsed, ref[0]), ref.end()
    for op in _OPS:
        if expr.startswith(op, index):
            return _OpToken(op), index + len(op)
    return _bare_literal(expr, index)


def _bare_literal(expr: str, index: int) -> tuple[_Token, int]:
    if number := _NUMBER.match(expr, index):
        return _Literal(Decimal(number[0])), number.end()
    if boolean := _BOOLEAN.match(expr, index):
        return _Literal(boolean[0]), boolean.end()
    raise ConditionParseError(f"{_echo(expr)}: unexpected text at column {index + 1}")


def _quoted(expr: str, index: int) -> tuple[_Token, int]:
    chars: list[str] = []
    index += 1
    while index < len(expr):
        if expr[index] != "'":
            chars.append(expr[index])
            index += 1
        elif expr.startswith("''", index):
            chars.append("'")
            index += 2
        else:
            return _Literal("".join(chars)), index + 1
    raise ConditionParseError(f"{_echo(expr)}: unterminated quoted literal")


def _holds(atom: Atom, context: RefContext) -> bool:
    text = resolve_text(atom.ref, context, atom.ref_text)
    if isinstance(atom.literal, str):
        return (text == atom.literal) == (atom.op == "==")
    if _JSON_NUMBER.fullmatch(text) is None:
        raise _NotANumberError(f"{atom.ref_text} is not a number")
    return _COMPARE[atom.op](Decimal(text), atom.literal)


def _echo(text: str) -> str:
    """``text`` quoted and escaped as JSON, cut to the repo's echo limit."""
    return cut_echo(json.dumps(text))
