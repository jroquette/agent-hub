"""The cross-checks of an eval output against itself, its file and its sibling (AGH-139 D4, D11,
S6, E10, E11): pure.

Each check runs only when the fields it reads pass their model's own rule (S2). Order (P7): the
``SHIP`` rules (every result and gate passes, then neither list is empty), the
``SHIP-WITH-OWNER-STEPS`` rule, each run's exit code against its status (results, then gates),
repeated ``tickets`` and ``acs`` items, the file stem against ``delivery``, then the sibling
``evals/<stem>.md`` (missing, malformed, or per field: ``verdict``, ``tickets``, ``acs``,
``commit``). ``NO-SHIP`` is free, and ``red_on_parent`` gates no verdict (D11). The sibling is
read as ``feature_evals`` reads every eval record, from its first ``EVAL_HEAD_BYTES``; its
``delivery`` is its file stem by that rule, so the stem check covers it. A malformed sibling's
problem, which may echo a value, is relayed cut to ``ECHO_LIMIT``.
"""

import json
from collections.abc import Iterator
from typing import Any, Final, NamedTuple

from pydantic import BaseModel, TypeAdapter

from agent_hub.core.features.feature_evals import (
    DELIVERY_PATTERN,
    EVAL_HEAD_BYTES,
    EVALS_FOLDER,
    NOTE_SUFFIX,
    eval_records,
)
from agent_hub.core.features.feature_record import TicketKey
from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.feature_view import EvalRecord
from agent_hub.core.features.output_models import (
    AcId,
    AcResult,
    EvalOutput,
    GateResult,
    OutputProblem,
)
from agent_hub.core.features.output_shape import echo, field_adapter, output_path, well_formed
from agent_hub.core.hub_config.problems import ROOT_PATH

# The exit code each status needs; a ``fail`` may carry any.
_EXIT_CODE_OF: Final = {"pass": 0, "not-run": None}
_OWNER_STEPS_NEEDED: Final = "SHIP-WITH-OWNER-STEPS needs at least one owner step"
_JSON_SUFFIX: Final = ".json"
_STEM_FORM: Final = f"<delivery>.json ({DELIVERY_PATTERN.pattern})"
_DELIVERY: Final = field_adapter(EvalOutput, "delivery")
# The fields compared with the sibling's, in P7's order; lists compare as sets.
_SIBLING_FIELDS: Final = tuple(
    (name, field_adapter(EvalOutput, name)) for name in ("verdict", "tickets", "acs", "commit")
)
_LISTS: Final = frozenset({"tickets", "acs"})
# The lists whose items must not repeat: key, the noun of an item, and an item's rule.
_UNIQUE: Final[tuple[tuple[str, str, TypeAdapter[Any]], ...]] = (
    ("tickets", "ticket", TypeAdapter(TicketKey)),
    ("acs", "AC", TypeAdapter(AcId)),
)


class _Runs(NamedTuple):
    """One list of runs of an eval output: its key, the noun of an item, and its field rules."""

    key: str
    noun: str
    status: TypeAdapter[Any]
    exit_code: TypeAdapter[Any]


def _runs(key: str, noun: str, model: type[BaseModel]) -> _Runs:
    return _Runs(key, noun, field_adapter(model, "status"), field_adapter(model, "exit_code"))


_RUNS: Final = (_runs("results", "result", AcResult), _runs("gates", "gate", GateResult))


def eval_cross_problems(
    document: dict[str, object], *, file_name: str, sibling_head: bytes | None
) -> Iterator[OutputProblem]:
    """Every problem of an eval document saved as ``evals/<file_name>`` against itself, its file
    name and its sibling's head (None when absent), in P7's order.

    A file name that is not ``<delivery>.json`` is one problem at the root, and the ``delivery``
    and sibling checks, which need its stem, are skipped (E11).
    """
    verdict = document.get("verdict")
    if verdict == "SHIP":
        yield from _ship_problems(document)
    elif verdict == "SHIP-WITH-OWNER-STEPS" and document.get("owner_steps") == []:
        yield OutputProblem("owner_steps", _OWNER_STEPS_NEEDED)
    for runs in _RUNS:
        yield from _exit_code_problems(runs, document.get(runs.key))
    for key, noun, rule in _UNIQUE:
        yield from _repeat_problems(document.get(key), key=key, noun=noun, rule=rule)
    stem = _stem(file_name)
    if stem is None:
        yield OutputProblem(ROOT_PATH, f"the file name {echo(file_name)} is not {_STEM_FORM}")
        return
    delivery = document.get("delivery")
    if well_formed(_DELIVERY, delivery) and delivery != stem:
        message = f"the delivery is {delivery} but the file name says {stem}"
        yield OutputProblem("delivery", message)
    yield from _sibling_problems(document, stem, sibling_head)


def _ship_problems(document: dict[str, object]) -> Iterator[OutputProblem]:
    """D4, S6: ``SHIP`` rests on runs that all pass, and on at least one result and one gate."""
    for runs in _RUNS:
        for index, _, status in _checked_runs(runs, document.get(runs.key)):
            if status != "pass":
                run = output_path((runs.key, index))
                message = f"SHIP needs every {runs.noun} to pass, but {run} is {status}"
                yield OutputProblem("verdict", message)
    for runs in _RUNS:
        if document.get(runs.key) == []:
            yield OutputProblem("verdict", f"SHIP needs at least one {runs.noun}")


def _checked_runs(runs: _Runs, items: object) -> Iterator[tuple[int, dict[str, object], object]]:
    """Each run of ``items`` that has a valid status: its index, the run, and the status."""
    for index, item in enumerate(items if isinstance(items, list) else ()):
        status = item.get("status") if isinstance(item, dict) else None
        if isinstance(item, dict) and well_formed(runs.status, status):
            yield index, item, status


def _exit_code_problems(runs: _Runs, items: object) -> Iterator[OutputProblem]:
    """E10: a ``pass`` needs exit code 0 and a ``not-run`` null, for results and gates alike."""
    for index, run, status in _checked_runs(runs, items):
        exit_code = run.get("exit_code")
        if status not in _EXIT_CODE_OF or not well_formed(runs.exit_code, exit_code):
            continue
        expected = _EXIT_CODE_OF[str(status)]
        if exit_code != expected:
            path = output_path((runs.key, index, "exit_code"))
            shown = f"{json.dumps(expected)}, not {json.dumps(exit_code)}"
            yield OutputProblem(path, f"a {status} needs exit code {shown}")


def _repeat_problems(
    items: object, *, key: str, noun: str, rule: TypeAdapter[Any]
) -> Iterator[OutputProblem]:
    """A problem at each valid item of the list ``items`` that an earlier item already is."""
    first: dict[str, int] = {}
    for index, item in enumerate(items if isinstance(items, list) else ()):
        if not isinstance(item, str) or not well_formed(rule, item):
            continue
        if item in first:
            earlier = output_path((key, first[item]))
            message = f"the {noun} {echo(item)} repeats {earlier}"
            yield OutputProblem(output_path((key, index)), message)
        else:
            first[item] = index


def _stem(file_name: str) -> str | None:
    """The delivery a file name ``<delivery>.json`` says; None when it says none.

    ``fullmatch`` ends the match at the end of the stem itself, so a final line break never
    passes (N6).
    """
    stem = file_name.removesuffix(_JSON_SUFFIX)
    if stem == file_name or DELIVERY_PATTERN.fullmatch(stem) is None:
        return None
    return stem


def _sibling_problems(
    document: dict[str, object], stem: str, sibling_head: bytes | None
) -> Iterator[OutputProblem]:
    """D4: the sibling exists, parses as an eval record, and holds the document's scope."""
    name = f"{EVALS_FOLDER}/{stem}{NOTE_SUFFIX}"
    if sibling_head is None:
        yield OutputProblem(ROOT_PATH, f"{name} is missing")
        return
    head = RecordHead(
        name=f"{stem}{NOTE_SUFFIX}", head=sibling_head[:EVAL_HEAD_BYTES], problem=None
    )
    (sibling,) = eval_records((head,), None, slug="-")
    if sibling.problem is not None:
        yield OutputProblem(ROOT_PATH, f"{name}: {echo(sibling.problem)}")
        return
    for key, rule in _SIBLING_FIELDS:
        yield from _field_problems(document.get(key), key=key, rule=rule, sibling=(name, sibling))


def _field_problems(
    found: object, *, key: str, rule: TypeAdapter[Any], sibling: tuple[str, EvalRecord]
) -> Iterator[OutputProblem]:
    name, record = sibling
    theirs: object = getattr(record, key)
    if not well_formed(rule, found) or _compared(found) == _compared(theirs):
        return
    verb = "are" if key in _LISTS else "is"
    said = "has none" if theirs is None else f"says {_shown(theirs)}"
    yield OutputProblem(key, f"the {key} {verb} {_shown(found)} but {name} {said}")


def _compared(value: object) -> object:
    """A list as the set of its items; any other value as it is."""
    return frozenset(value) if isinstance(value, list | tuple) else value


def _shown(value: object) -> str:
    """A field's value on one line: a list as ``[a, b]``, cut to ``ECHO_LIMIT``."""
    if isinstance(value, list | tuple):
        return echo("[" + ", ".join(map(str, value)) + "]")
    return echo(str(value))
