"""An agent output's bytes to a document, and pydantic's errors to problems (AGH-139 S2, P6).

Pure: bytes in, a parsed object or one root problem out. Each shape error becomes one problem
at its JSON path. A key echoed in a path is escaped once and cut to ``ECHO_LIMIT``, never inside
an escape sequence, so a document of long or unprintable keys cannot make a long line.
"""

import json
from collections.abc import Iterator, Sequence
from typing import Final

from pydantic import ValidationError

from agent_hub.core.features.output_models import (
    ACS_ALL_TAG,
    ACS_LIST_TAG,
    MAX_OUTPUT_BYTES,
    OutputProblem,
)
from agent_hub.core.hub_config.problems import (
    NOT_AN_OBJECT_MESSAGE,
    PLAIN_KEY,
    ROOT_PATH,
    one_line,
)
from agent_hub.core.hub_config.versions import ECHO_LIMIT, cut_echo
from agent_hub.core.json_form import InvalidJsonError, load_json_bytes

_OVER_BOUND = f"the file is over {MAX_OUTPUT_BYTES} bytes"
_TAGGED_UNIONS: Final = {"acs": frozenset({ACS_ALL_TAG, ACS_LIST_TAG})}


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


def output_path(loc: Sequence[int | str]) -> str:
    """The JSON path of a location, each key escaped once: ``findings[0].acs``, ``["a\\n"]``.

    A plain key of at most ``ECHO_LIMIT`` characters follows a dot; any other key is written as
    an escaped JSON string cut to ``ECHO_LIMIT``. ``hub_config.problems.json_path`` is not used:
    it escapes the whole key, unbounded. The tag pydantic adds after a top-level tagged union
    (``acs``'s ``all`` or ``ids``) is not a key of the document and is dropped.
    """
    return "".join(_path_parts(_untagged(loc))) or ROOT_PATH


def overlong_problem(path: str, items: object, limit: int) -> Iterator[OutputProblem]:
    """The too-long problem of the list ``items`` at ``path``, worded as pydantic's.

    pydantic drops a list's length error when the list's items fail too, so a caller reports
    it again from the raw document unless the shape problems already hold it.
    """
    if isinstance(items, list) and len(items) > limit:
        message = f"Tuple should have at most {limit} items after validation, not {len(items)}"
        yield OutputProblem(path, message)


def _untagged(loc: Sequence[int | str]) -> Sequence[int | str]:
    if (
        len(loc) > 1
        and isinstance(loc[0], str)
        and loc[1] in _TAGGED_UNIONS.get(loc[0], frozenset())
    ):
        return (loc[0], *loc[2:])
    return loc


def _path_parts(loc: Sequence[int | str]) -> Iterator[str]:
    for index, segment in enumerate(loc):
        if isinstance(segment, int):
            yield f"[{segment}]"
        elif PLAIN_KEY.fullmatch(segment) and len(segment) <= ECHO_LIMIT:
            yield f".{segment}" if index else segment
        else:
            yield '["' + cut_echo(json.dumps(segment)[1:-1]) + '"]'
