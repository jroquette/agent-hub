"""The ACs an eval output's results must cover (AGH-139 D10, S6, E6): pure, the record as bytes.

Without a feature record, a list scope is covered exactly once each, and with ``"all"`` or a
tickets-only scope (``acs: []``) no result AC repeats; whether a ``SHIP`` has any result is the
verdict rules' to say. With ``features.json``, ``"all"`` is every live AC and a tickets-only
scope the live ACs of those tickets (``scope_rules.named_scope``, a plan key and its tracker id
being one ticket); a listed id must be a live AC; ``results`` name each in-scope AC exactly once,
no other, and no withdrawn AC. A record over ``MAX_RECORD_BYTES``, or one that does not parse, is
one problem naming it, and the scope is then checked as without a record.

Order (P7): the record, then ``acs`` (withdrawn or unknown ids), then ``results`` (missing,
outside the scope, repeated, withdrawn). An id reported at ``acs`` is not reported again for its
result. The scope is checked only when ``acs``, ``tickets`` and every result's ``ac`` pass their
model's own rule (S2).
"""

from collections import Counter
from collections.abc import Iterator
from typing import Final, Literal, NamedTuple

from pydantic import TypeAdapter

from agent_hub.core.features.feature_record import (
    MAX_RECORD_BYTES,
    RECORD_FILE,
    FeatureRecordFile,
    record_from_bytes,
)
from agent_hub.core.features.output_models import (
    MAX_RESULTS,
    AcId,
    EvalOutput,
    OutputProblem,
)
from agent_hub.core.features.output_shape import echo, field_adapter, well_formed
from agent_hub.core.features.scope_rules import ALL_ACS, named_scope, ticket_aliases
from agent_hub.core.hub_config.problems import ROOT_PATH

_ACS: Final = field_adapter(EvalOutput, "acs")
_TICKETS: Final = field_adapter(EvalOutput, "tickets")
_AC_ID: Final[TypeAdapter[str]] = TypeAdapter(AcId)
_OVER_BOUND: Final = f"{RECORD_FILE} is over {MAX_RECORD_BYTES} bytes"

# An eval's ``acs``: ``all``, or the listed ids (empty: the scope is its tickets).
type _Named = tuple[str, ...] | Literal["all"]


class _Scope(NamedTuple):
    """What the results are held to.

    ``expected``: the ids they cover exactly once each (None: any, none repeated);
    ``withdrawn``: ids they must not name; ``reported``: ids already reported at ``acs``.
    """

    expected: tuple[str, ...] | None
    withdrawn: frozenset[str]
    reported: frozenset[str]


def eval_scope_problems(
    document: dict[str, object], *, record: bytes | None
) -> Iterator[OutputProblem]:
    """Every record and scope problem of an eval document, with ``record`` as ``features.json``
    (None when absent), in P7's order."""
    parsed = _record(record)
    if isinstance(parsed, OutputProblem):
        yield parsed
        parsed = None
    acs, tickets = document.get("acs"), document.get("tickets")
    ids = _result_ids(document.get("results"))
    if ids is None or not well_formed(_ACS, acs) or not well_formed(_TICKETS, tickets):
        return
    named: _Named = ALL_ACS if acs == ALL_ACS else tuple(dict.fromkeys(_listed(acs)))
    if parsed is None:
        listed = named if isinstance(named, tuple) and named else None
        scope = _Scope(listed, frozenset(), frozenset())
    else:
        acs_problems, scope = _record_scope(parsed, named=named, tickets=tuple(_listed(tickets)))
        yield from acs_problems
    yield from _coverage_problems(Counter(ids), scope)


def _record(content: bytes | None) -> FeatureRecordFile | OutputProblem | None:
    """The record ``content`` holds; one problem naming it when over its bound or unparseable."""
    if content is None:
        return None
    if len(content) > MAX_RECORD_BYTES:
        return OutputProblem(ROOT_PATH, _OVER_BOUND)
    parsed = record_from_bytes(content)
    return OutputProblem(ROOT_PATH, parsed) if isinstance(parsed, str) else parsed


def _listed(items: object) -> Iterator[str]:
    for item in items if isinstance(items, list) else ():
        yield str(item)


def _result_ids(results: object) -> tuple[str, ...] | None:
    """Each result's ``ac``; None unless ``results`` is a list within its bound of results whose
    ``ac`` is each a valid id."""
    if not isinstance(results, list) or len(results) > MAX_RESULTS:
        return None
    ids = tuple(result.get("ac") if isinstance(result, dict) else None for result in results)
    if all(isinstance(ac, str) and well_formed(_AC_ID, ac) for ac in ids):
        return tuple(str(ac) for ac in ids)
    return None


def _record_scope(
    record: FeatureRecordFile, *, named: _Named, tickets: tuple[str, ...]
) -> tuple[tuple[OutputProblem, ...], _Scope]:
    """D10: the problems of a listed scope against the record, and what the results are held to."""
    live = tuple(ac for ac in record.acs if not ac.withdrawn)
    live_ids = frozenset(ac.id for ac in live)
    withdrawn = frozenset(ac.id for ac in record.acs if ac.withdrawn) - live_ids
    if isinstance(named, tuple) and named:
        problems = tuple(_acs_problems(named, live_ids=live_ids, withdrawn=withdrawn))
        expected = tuple(ac for ac in named if ac in live_ids)
        return problems, _Scope(expected, withdrawn, frozenset(named) - live_ids)
    aliases = ticket_aliases(record.tickets)
    expanded = named_scope(acs=named, tickets=tickets, live=live, aliases=aliases)
    return (), _Scope(expanded, withdrawn, frozenset())


def _acs_problems(
    listed: tuple[str, ...], *, live_ids: frozenset[str], withdrawn: frozenset[str]
) -> Iterator[OutputProblem]:
    for ac in listed:
        if ac in withdrawn:
            yield OutputProblem("acs", f"{echo(ac)} is withdrawn in {RECORD_FILE}")
        elif ac not in live_ids:
            yield OutputProblem("acs", f"{echo(ac)} is not an AC of {RECORD_FILE}")


def _coverage_problems(counts: Counter[str], scope: _Scope) -> Iterator[OutputProblem]:
    """The ``results`` problems: missing, outside the scope, repeated, withdrawn (P7)."""
    if scope.expected is not None:
        yield from _held_problems(counts, expected=scope.expected, scope=scope)
    for ac in counts:
        if counts[ac] > 1 and (scope.expected is None or ac in scope.expected):
            yield OutputProblem("results", f"more than one result for {echo(ac)}")
    for ac in counts:
        if ac in scope.withdrawn - scope.reported:
            yield OutputProblem("results", f"the result for {echo(ac)} names a withdrawn AC")


def _held_problems(
    counts: Counter[str], *, expected: tuple[str, ...], scope: _Scope
) -> Iterator[OutputProblem]:
    """Each ``expected`` id without a result, then each result id outside them."""
    for ac in dict.fromkeys(expected):
        if not counts[ac]:
            yield OutputProblem("results", f"no result for {echo(ac)}, which the scope names")
    skipped = frozenset(expected) | scope.withdrawn | scope.reported
    for ac in counts:
        if ac not in skipped:
            yield OutputProblem("results", f"the result for {echo(ac)} is outside the scope")
