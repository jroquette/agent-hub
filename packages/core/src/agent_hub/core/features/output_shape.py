"""An agent output's bytes to a document, and pydantic's errors to problems (AGH-139 S2, P6).

Pure: bytes in, a parsed object or one root problem out. Each shape error becomes one problem
at its JSON path. A key echoed in a path is escaped once and cut to ``ECHO_LIMIT``, never inside
an escape sequence, so a document of long or unprintable keys cannot make a long line. The
cross-checks ask ``well_formed`` whether a raw field passes its model's own rule (S2).
"""

from collections.abc import Iterator
from typing import Annotated, Any

from pydantic import BaseModel, TypeAdapter, ValidationError

from agent_hub.core.features.output_models import (
    MAX_OUTPUT_BYTES,
    OutputProblem,
)
from agent_hub.core.features.output_paths import output_path as output_path
from agent_hub.core.hub_config.problems import (
    NOT_AN_OBJECT_MESSAGE,
    ROOT_PATH,
    one_line,
)
from agent_hub.core.hub_config.versions import cut_echo
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
        OutputProblem(output_path(detail["loc"]), one_line(detail["msg"]))
        for detail in error.errors(include_url=False, include_input=False)
    )


def field_adapter(model: type[BaseModel], name: str) -> TypeAdapter[Any]:
    """A validator of one field of ``model``: its annotation and its constraints.

    pydantic moves the constraints of an ``Annotated`` field (a list's ``max_length``) from its
    annotation to its metadata, so they are put back.
    """
    info = model.model_fields[name]
    if not info.metadata:
        return TypeAdapter(info.annotation)
    return TypeAdapter(Annotated[(info.annotation, *info.metadata)])


def well_formed(adapter: TypeAdapter[Any], value: object) -> bool:
    """Whether a raw value passes the rule of the field ``adapter`` validates."""
    try:
        adapter.validate_python(value)
    except ValidationError:
        return False
    return True


def echo(text: str) -> str:
    """A text from the file or its name, escaped onto one line and cut to ``ECHO_LIMIT``."""
    return cut_echo(one_line(text))


def overlong_problem(path: str, items: object, limit: int) -> Iterator[OutputProblem]:
    """The too-long problem of the list ``items`` at ``path``, worded as pydantic's.

    pydantic drops a list's length error when the list's items fail too, so a caller reports
    it again from the raw document unless the shape problems already hold it.
    """
    if isinstance(items, list) and len(items) > limit:
        message = f"Tuple should have at most {limit} items after validation, not {len(items)}"
        yield OutputProblem(path, message)
