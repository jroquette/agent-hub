"""A registered hub's ``hub.json`` as the control plane reads it: lenient about the pin (Q4).

The read-only control plane shows hubs that upgrade on their own schedule: a well-formed pin
other than the running release is no error, only the warning "pinned X, running Y", and the
document is checked as its own release would (``schema_version``, then the model). A file that
cannot be read, is no JSON, has a malformed pin or does not match the schema is invalid, its
problems located by JSON pointers (RFC 6901).
"""

import json
import re
from dataclasses import dataclass
from typing import Final

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.hub_config.versions import pinned_release
from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.hubs.registered_hub import ValidationProblem
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

# One segment of a JSON path: ``.name`` (or a leading ``name``), ``[0]`` or ``["any key"]``.
_SEGMENT: Final = re.compile(r'\.?([^.\[\]]+)|\[(\d+)\]|\[("(?:[^"\\]|\\.)*")\]')


@dataclass(frozen=True, kw_only=True, slots=True)
class HubDocument:
    """What a hub's ``hub.json`` holds: the config when valid, else its problems.

    ``project`` and ``pin`` are read leniently, so an invalid hub still names them when it can.
    """

    config: HubConfig | None
    project: str | None
    pin: str | None
    problems: tuple[ValidationProblem, ...] = ()
    warnings: tuple[str, ...] = ()
    is_missing: bool = False

    @property
    def valid(self) -> bool:
        """Whether the document is a usable config."""
        return self.config is not None


def read_hub_document(read: bytes | UnreadHubFile, *, running_version: str) -> HubDocument:
    """The config in the bytes read, checked against its own pin, or why it cannot be used."""
    if isinstance(read, UnreadHubFile):
        problem = ValidationProblem(pointer="", message=read.message)
        return HubDocument(
            config=None, project=None, pin=None, problems=(problem,), is_missing=read.is_missing
        )
    try:
        document = load_json_bytes(read)
    except InvalidJsonError as error:
        problem = ValidationProblem(pointer="", message=error.message)
        return HubDocument(config=None, project=None, pin=None, problems=(problem,))
    pin = pinned_release(document)
    checked = check_hub_document(document, running_version=pin or running_version)
    if not isinstance(checked, HubConfig):
        return HubDocument(
            config=None,
            project=_project_name(document),
            pin=pin,
            problems=tuple(_located(problem) for problem in checked),
        )
    warnings = () if pin == running_version else (pin_warning(pin, running_version),)
    return HubDocument(config=checked, project=checked.project.name, pin=pin, warnings=warnings)


def pin_warning(pinned: str | None, running: str) -> str:
    """The warning a hub pinned to another release shows."""
    return f"pinned {pinned}, running {running}"


def json_pointer(path: str) -> str:
    """The JSON pointer of a problem's JSON path: ``repos[0].dir`` → ``/repos/0/dir``."""
    if path == ROOT_PATH:
        return ""
    tokens: list[str] = []
    for match in _SEGMENT.finditer(path):
        name, index, quoted = match.groups()
        tokens.append(name or index or json.loads(quoted))
    return "".join("/" + token.replace("~", "~0").replace("/", "~1") for token in tokens)


def _located(problem: ConfigProblem) -> ValidationProblem:
    return ValidationProblem(pointer=json_pointer(problem.path), message=problem.message)


def _project_name(document: JsonValue) -> str | None:
    project = document.get("project") if isinstance(document, dict) else None
    name = project.get("name") if isinstance(project, dict) else None
    return name if isinstance(name, str) and name else None
