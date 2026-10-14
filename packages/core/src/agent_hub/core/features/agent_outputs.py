"""Check the JSON outputs agents hand to ``/feature`` (AGH-139): pure, bytes in, problems out.

``review_problems`` and ``eval_problems`` return every problem of an output, uncapped: first the
root problem (bytes that are not a JSON object), else every shape problem against
``ReviewOutput`` or ``EvalOutput``, then every cross-check problem (``review_output_checks``,
``eval_output_checks``) in S2's order. The caller decides how many to show.

The JSON Schemas of both outputs ship as package data beside this module (``review.v1.json``,
``eval.v1.json``), regenerated with ``make output-schemas`` whenever a model changes; unit tests
fail while a shipped file differs from the export.
"""

import json
from collections.abc import Callable, Iterator, Mapping
from importlib.resources import files
from typing import Any, Final, Literal

from pydantic import BaseModel, ValidationError

from agent_hub.core.features.eval_output_checks import eval_cross_problems
from agent_hub.core.features.output_models import (
    MAX_EVAL_ACS,
    MAX_EVAL_TICKETS,
    MAX_FINDING_ACS,
    MAX_FINDINGS,
    MAX_GATES,
    MAX_OWNER_STEPS,
    MAX_RED_ON_PARENT,
    MAX_RESULTS,
    EvalOutput,
    OutputProblem,
    ReviewOutput,
)
from agent_hub.core.features.output_shape import (
    output_path,
    overlong_problem,
    parse_document,
    shape_problems,
)
from agent_hub.core.features.review_output_checks import review_cross_problems

type _Document = dict[str, object]
type OutputKind = Literal["review", "eval"]

OUTPUT_SCHEMA_PACKAGE: Final = "agent_hub.core.features"
OUTPUT_SCHEMA_FILES: Final[Mapping[OutputKind, str]] = {
    "review": "review.v1.json",
    "eval": "eval.v1.json",
}
_OUTPUT_MODELS: Final[Mapping[OutputKind, type[BaseModel]]] = {
    "review": ReviewOutput,
    "eval": EvalOutput,
}

# Each list of an eval output and its bound, in the model's field order.
_EVAL_LISTS: Final[tuple[tuple[str, int], ...]] = (
    ("tickets", MAX_EVAL_TICKETS),
    ("acs", MAX_EVAL_ACS),
    ("results", MAX_RESULTS),
    ("gates", MAX_GATES),
    ("red_on_parent", MAX_RED_ON_PARENT),
    ("owner_steps", MAX_OWNER_STEPS),
)


def review_problems(
    content: bytes, *, file_name: str, folder_name: str
) -> tuple[OutputProblem, ...]:
    """Every problem of a review output saved as ``<folder_name>/<file_name>``; () when valid.

    ``file_name`` and ``folder_name`` are the file's own name and its ticket folder's name.
    """
    document = parse_document(content)
    if isinstance(document, OutputProblem):
        return (document,)
    shape = _shape(document, model=ReviewOutput, overlong=_overlong_review_lists)
    cross = review_cross_problems(document, file_name=file_name, folder_name=folder_name)
    return (*shape, *cross)


def eval_problems(
    content: bytes, *, file_name: str, sibling_head: bytes | None, record: bytes | None
) -> tuple[OutputProblem, ...]:
    """Every problem of an eval output saved as ``evals/<file_name>``; () when valid.

    ``sibling_head`` is the first bytes of the sibling ``evals/<stem>.md`` (None when absent) and
    ``record`` the feature's ``features.json`` (None when absent).
    """
    del file_name, sibling_head, record  # The stem, sibling and record cross-checks come next.
    document = parse_document(content)
    if isinstance(document, OutputProblem):
        return (document,)
    shape = _shape(document, model=EvalOutput, overlong=_overlong_eval_lists)
    return (*shape, *eval_cross_problems(document))


def _shape(
    document: _Document,
    *,
    model: type[BaseModel],
    overlong: Callable[[_Document], Iterator[OutputProblem]],
) -> tuple[OutputProblem, ...]:
    """The shape problems of ``document`` against ``model``, then each overlong list they miss."""
    try:
        model.model_validate(document)
    except ValidationError as error:
        shape = shape_problems(error)
        reported = {problem.path for problem in shape}
        missed = (found for found in overlong(document) if found.path not in reported)
        return (*shape, *missed)
    return ()


def _overlong_review_lists(document: _Document) -> Iterator[OutputProblem]:
    findings = document.get("findings")
    yield from overlong_problem("findings", findings, MAX_FINDINGS)
    for index, finding in enumerate(findings if isinstance(findings, list) else ()):
        if isinstance(finding, dict):
            path = output_path(("findings", index, "acs"))
            yield from overlong_problem(path, finding.get("acs"), MAX_FINDING_ACS)


def _overlong_eval_lists(document: _Document) -> Iterator[OutputProblem]:
    for name, limit in _EVAL_LISTS:
        yield from overlong_problem(name, document.get(name), limit)


def export_output_schema_text(kind: OutputKind) -> str:
    """The JSON Schema of one output as its shipped file holds it: indented, one final newline."""
    schema = _OUTPUT_MODELS[kind].model_json_schema()
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def read_shipped_output_schema(kind: OutputKind) -> dict[str, Any]:
    """The JSON Schema of one output shipped with the package, read as package data."""
    package_file = files(OUTPUT_SCHEMA_PACKAGE).joinpath(OUTPUT_SCHEMA_FILES[kind])
    schema: dict[str, Any] = json.loads(package_file.read_text(encoding="utf-8"))
    return schema
