"""Check a parsed ``hub.json``: the pin, then ``schema_version``, then the whole ``HubConfig``.

The CLI prints what this returns and ``hub doctor``'s ``config.schema`` rule reports it, so
both see the same problems, on the same paths (docs/design/project-config.md § Versioning).
"""

from pydantic import ValidationError

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem, json_path, one_line
from agent_hub.core.hub_config.versions import find_version_problem

type Location = tuple[int | str, ...]

# The segment pydantic appends to a location when the error is about a map's key, not its value.
KEY_MARKER = "[key]"


def check_hub_document(
    document: object, *, running_version: str
) -> HubConfig | tuple[ConfigProblem, ...]:
    """The config, or its problems: only the version one when there is one, else one per error."""
    version_problem = find_version_problem(document, running_version=running_version)
    if version_problem is not None:
        return (version_problem,)
    try:
        return HubConfig.model_validate(document)
    except ValidationError as error:
        return validation_problems(error, document)


def validation_problems(error: ValidationError, document: object) -> tuple[ConfigProblem, ...]:
    """One problem per error of a config object's validation, at the bad key's JSON path."""
    return tuple(
        ConfigProblem(json_path(_path_to_key(detail["loc"], document)), one_line(detail["msg"]))
        for detail in error.errors()
    )


def _path_to_key(loc: Location, document: object) -> Location:
    """The location without pydantic's key marker, so the path ends at the bad key.

    A key the file really spells ``[key]`` stays: it is in the file where the location says.
    """
    if loc and loc[-1] == KEY_MARKER and not _holds_key(document, loc):
        return loc[:-1]
    return loc


def _holds_key(document: object, loc: Location) -> bool:
    parent = document
    for segment in loc[:-1]:
        parent = _child(parent, segment)
    return isinstance(parent, dict) and loc[-1] in parent


def _child(parent: object, segment: int | str) -> object:
    if isinstance(parent, dict):
        return parent.get(segment)
    if isinstance(parent, list) and isinstance(segment, int) and 0 <= segment < len(parent):
        return parent[segment]
    return None
