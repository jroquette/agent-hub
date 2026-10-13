"""An agent output's bytes to a document, and pydantic's errors to problems (AGH-139 S2, P6).

Pure: bytes in, a parsed object or one root problem out. Each shape error becomes one problem
at its JSON path; a key echoed in a path is escaped and cut to ``ECHO_LIMIT``, so a document of
long unknown keys cannot make a line of unbounded length.
"""

from collections.abc import Sequence

from pydantic import ValidationError

from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES, OutputProblem
from agent_hub.core.hub_config.problems import (
    NOT_AN_OBJECT_MESSAGE,
    ROOT_PATH,
    json_path,
    one_line,
)
from agent_hub.core.hub_config.versions import ECHO_LIMIT, cut_echo
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes

_OVER_BOUND = f"the file is over {MAX_OUTPUT_BYTES} bytes"


def parse_document(content: bytes) -> dict[str, object] | OutputProblem:
    """The JSON object ``content`` holds, or one problem at the root saying why it is unusable."""
    if len(content) > MAX_OUTPUT_BYTES:
        return OutputProblem(ROOT_PATH, _OVER_BOUND)
    try:
        document = load_json_bytes(content, strict=True)
    except InvalidJsonError as error:
        return OutputProblem(ROOT_PATH, one_line(error.message))
    if not isinstance(document, dict):
        return OutputProblem(ROOT_PATH, NOT_AN_OBJECT_MESSAGE)
    return dict(document)


def shape_problems(error: ValidationError) -> tuple[OutputProblem, ...]:
    """One problem per error of a model's validation, in pydantic's order, at its JSON path."""
    return tuple(
        OutputProblem(json_path(_shown_location(detail["loc"])), one_line(detail["msg"]))
        for detail in error.errors()
    )


def _shown_location(loc: Sequence[int | str]) -> tuple[int | str, ...]:
    return tuple(_shown_segment(segment) for segment in loc)


def _shown_segment(segment: int | str) -> int | str:
    if isinstance(segment, str) and len(segment) > ECHO_LIMIT:
        return cut_echo(one_line(segment))
    return segment
