"""The verdict and exit code cross-checks of an eval output (AGH-139 D4, D11, S6, E10): pure.

Each check runs only when the fields it reads pass their model's own rule (S2). Order (P7): the
``SHIP`` rules (every result and gate passes, then neither list is empty), the
``SHIP-WITH-OWNER-STEPS`` rule, then each run's exit code against its status (results, then
gates). ``NO-SHIP`` is free, and ``red_on_parent`` gates no verdict (D11).
"""

import json
from collections.abc import Iterator
from typing import Any, Final, NamedTuple

from pydantic import BaseModel, TypeAdapter

from agent_hub.core.features.output_models import AcResult, GateResult, OutputProblem
from agent_hub.core.features.output_shape import field_adapter, output_path, well_formed

# The exit code each status needs; a ``fail`` may carry any.
_EXIT_CODE_OF: Final = {"pass": 0, "not-run": None}
_OWNER_STEPS_NEEDED: Final = "SHIP-WITH-OWNER-STEPS needs at least one owner step"


class _Runs(NamedTuple):
    """One list of runs of an eval output: its key, the noun of an item, and its field rules."""

    key: str
    noun: str
    status: TypeAdapter[Any]
    exit_code: TypeAdapter[Any]


def _runs(key: str, noun: str, model: type[BaseModel]) -> _Runs:
    return _Runs(key, noun, field_adapter(model, "status"), field_adapter(model, "exit_code"))


_RUNS: Final = (_runs("results", "result", AcResult), _runs("gates", "gate", GateResult))


def eval_cross_problems(document: dict[str, object]) -> Iterator[OutputProblem]:
    """Every verdict and exit code problem of an eval document, in P7's order."""
    verdict = document.get("verdict")
    if verdict == "SHIP":
        yield from _ship_problems(document)
    elif verdict == "SHIP-WITH-OWNER-STEPS" and document.get("owner_steps") == []:
        yield OutputProblem("owner_steps", _OWNER_STEPS_NEEDED)
    for runs in _RUNS:
        yield from _exit_code_problems(runs, document.get(runs.key))


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
