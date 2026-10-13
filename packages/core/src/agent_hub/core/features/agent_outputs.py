"""Check the JSON outputs agents hand to ``/feature`` (AGH-139): pure, bytes in, problems out.

``review_problems`` returns every problem of a review output, uncapped: first the root problem
(bytes that are not a JSON object), else every shape problem against ``ReviewOutput``. The
caller decides how many to show.
"""

from pydantic import ValidationError

from agent_hub.core.features.output_models import OutputProblem, ReviewOutput
from agent_hub.core.features.output_shape import parse_document, shape_problems


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
        return shape_problems(error)
    return ()
