"""Check the JSON outputs agents hand to ``/feature`` (AGH-139): pure, bytes in, problems out.

``review_problems`` and ``eval_problems`` return every problem of an output, uncapped: first the
root problem (bytes that are not a JSON object), else every shape problem against
``ReviewOutput`` or ``EvalOutput``. The caller decides how many to show.
"""

from collections.abc import Callable, Iterator
from typing import Final

from pydantic import BaseModel, ValidationError

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

type _Document = dict[str, object]

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
    del file_name, folder_name  # The cross-checks against the file's name come next.
    document = parse_document(content)
    if isinstance(document, OutputProblem):
        return (document,)
    return _shape(document, model=ReviewOutput, overlong=_overlong_review_lists)


def eval_problems(
    content: bytes, *, file_name: str, sibling_head: bytes | None, record: bytes | None
) -> tuple[OutputProblem, ...]:
    """Every problem of an eval output saved as ``evals/<file_name>``; () when valid.

    ``sibling_head`` is the first bytes of the sibling ``evals/<stem>.md`` (None when absent) and
    ``record`` the feature's ``features.json`` (None when absent).
    """
    del file_name, sibling_head, record  # The sibling and record cross-checks come next.
    document = parse_document(content)
    if isinstance(document, OutputProblem):
        return (document,)
    return _shape(document, model=EvalOutput, overlong=_overlong_eval_lists)


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
