"""Check the JSON outputs agents hand to ``/feature`` (AGH-139): pure, bytes in, problems out.

``review_problems`` returns every problem of a review output, uncapped: first the root problem
(bytes that are not a JSON object), else every shape problem against ``ReviewOutput``. The
caller decides how many to show.
"""

from collections.abc import Iterator

from pydantic import ValidationError

from agent_hub.core.features.output_models import (
    MAX_FINDING_ACS,
    MAX_FINDINGS,
    OutputProblem,
    ReviewOutput,
)
from agent_hub.core.features.output_shape import (
    output_path,
    overlong_problem,
    parse_document,
    shape_problems,
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
    try:
        ReviewOutput.model_validate(document)
    except ValidationError as error:
        shape = shape_problems(error)
        reported = {problem.path for problem in shape}
        overlong = (found for found in _overlong_lists(document) if found.path not in reported)
        return (*shape, *overlong)
    return ()


def _overlong_lists(document: dict[str, object]) -> Iterator[OutputProblem]:
    findings = document.get("findings")
    yield from overlong_problem("findings", findings, MAX_FINDINGS)
    for index, finding in enumerate(findings if isinstance(findings, list) else ()):
        if isinstance(finding, dict):
            path = output_path(("findings", index, "acs"))
            yield from overlong_problem(path, finding.get("acs"), MAX_FINDING_ACS)
