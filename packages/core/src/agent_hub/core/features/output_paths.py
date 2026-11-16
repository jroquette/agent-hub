"""The JSON path of a location in an agent output, each key escaped once and kept short.

It loads no output model, so the workflow loader can name a problem's path with it cheaply.
``output_shape`` re-exports ``output_path``, and ``output_models`` the two tags of ``acs``.
"""

import json
from collections.abc import Iterator, Sequence
from typing import Final

from agent_hub.core.hub_config.problems import PLAIN_KEY, ROOT_PATH
from agent_hub.core.hub_config.versions import ECHO_LIMIT, cut_echo

# The tags of an eval's ``acs`` union; pydantic puts the chosen one in an error's ``loc``.
ACS_ALL_TAG: Final = "all"
ACS_LIST_TAG: Final = "ids"
_TAGGED_UNIONS: Final = {"acs": frozenset({ACS_ALL_TAG, ACS_LIST_TAG})}


def output_path(loc: Sequence[int | str]) -> str:
    """The JSON path of a location, each key escaped once: ``findings[0].acs``, ``["a\\n"]``.

    A plain key of at most ``ECHO_LIMIT`` characters follows a dot; any other key is written as
    an escaped JSON string cut to ``ECHO_LIMIT``. ``hub_config.problems.json_path`` is not used:
    it escapes the whole key, unbounded. The tag pydantic adds after a top-level tagged union
    (``acs``'s ``all`` or ``ids``) is not a key of the document and is dropped.
    """
    return "".join(_path_parts(_untagged(loc))) or ROOT_PATH


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
