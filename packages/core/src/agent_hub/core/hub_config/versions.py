"""The lenient version pre-check of ``hub.json``: the pin, then ``schema_version``.

It reads the plain JSON document, before the model, so a CLI facing a file of another release
reports the pin mismatch, whose fix settles both, not the keys it does not know
(docs/design/project-config.md § Versioning).
"""

import json
import re
from itertools import accumulate
from typing import Final

from agent_hub.core.hub_config.platform_repository import (
    DEFAULT_PLATFORM_REPOSITORY,
    is_platform_repository,
)
from agent_hub.core.hub_config.problems import (
    NOT_AN_OBJECT_MESSAGE,
    ROOT_PATH,
    ConfigProblem,
    one_line,
)

SUPPORTED_SCHEMA_VERSION: Final = 1
# How a hub runs the release it is pinned to (ADR 0013); format it with ``repository=`` and
# ``version=``. ``PINNED_RELEASE_COMMAND`` is the command of a hub that sets no repository.
_RELEASE_COMMAND = "uvx --from {repository}@v{version}#subdirectory=packages/agent-hub hub"
PINNED_RELEASE_COMMAND: Final = (
    f"uvx --from {DEFAULT_PLATFORM_REPOSITORY}@v{{version}}#subdirectory=packages/agent-hub hub"
)
# ASCII digits only; ``fullmatch``, because ``$`` also matches before a final newline.
_RELEASE_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
# The most characters of a value from the file that a message repeats.
ECHO_LIMIT: Final = 80
# One character of escaped text, an escape sequence (``\n``, ``é``) counting as one.
_ESCAPED_CHARACTER = re.compile(r"\\(?:u[0-9a-fA-F]{4}|x[0-9a-fA-F]{2}|U[0-9a-fA-F]{8}|.)|.", re.S)
_VERSION_PATH = "platform.version"
_SCHEMA_VERSION_PATH = "schema_version"


def pinned_release(document: object) -> str | None:
    """The pinned release of a parsed ``hub.json`` when it is well formed, else None."""
    if not isinstance(document, dict):
        return None
    platform = document.get("platform")
    if not isinstance(platform, dict):
        return None
    return _well_formed_release(platform.get("version"))


def pinned_repository(document: object) -> str | None:
    """The repository a parsed ``hub.json`` installs its release from, or None when it is bad.

    Lenient, like ``pinned_release``: a document, ``platform`` or key that is absent or not an
    object gives the default. A key present with a value outside the accepted form gives None,
    so that value is never echoed; the model reports it once the pin matches.
    """
    if not isinstance(document, dict):
        return DEFAULT_PLATFORM_REPOSITORY
    platform = document.get("platform")
    if not isinstance(platform, dict):
        return DEFAULT_PLATFORM_REPOSITORY
    return _platform_repository(platform)


def pinned_release_command(
    pinned: str, *, repository: str | None = DEFAULT_PLATFORM_REPOSITORY
) -> str | None:
    """The command that runs the pinned release from ``repository``.

    None when the repository is bad (None) or the pin is too long to echo.
    """
    if repository is None or len(pinned) > ECHO_LIMIT:
        return None
    return _RELEASE_COMMAND.format(repository=repository, version=pinned)


def find_version_problem(document: object, *, running_version: str) -> ConfigProblem | None:
    """The first version problem of a parsed ``hub.json``, or None when both are supported."""
    if not isinstance(document, dict):
        return ConfigProblem(ROOT_PATH, NOT_AN_OBJECT_MESSAGE)
    pinned = document.get("platform")
    if not isinstance(pinned, dict):
        return _platform_problem(pinned, is_present="platform" in document)
    version_problem = _pin_problem(pinned, running_version=running_version)
    if version_problem is not None:
        return version_problem
    return _schema_version_problem(document)


def _platform_problem(platform: object, *, is_present: bool) -> ConfigProblem:
    if is_present:
        return ConfigProblem("platform", f"must be an object, not {_shown(platform)}")
    return ConfigProblem("platform", 'required: the pinned release, as {"version": "1.2.3"}')


def _pin_problem(platform: dict[str, object], *, running_version: str) -> ConfigProblem | None:
    if "version" not in platform:
        return ConfigProblem(_VERSION_PATH, "required: the pinned release, such as 1.2.3")
    pinned = _well_formed_release(platform["version"])
    if pinned is None:
        return ConfigProblem(
            _VERSION_PATH,
            f"must be three numbers such as 1.2.3, not {_shown(platform['version'])}",
        )
    if pinned != running_version:
        # Digits and dots only (the pattern), so only its length needs bounding.
        return ConfigProblem(
            _VERSION_PATH,
            f"this hub is pinned to {cut_echo(pinned)} but this hub command is {running_version};"
            f" run the pinned release"
            f"{_pinned_command(pinned, repository=_platform_repository(platform))}",
        )
    return None


def _schema_version_problem(document: dict[str, object]) -> ConfigProblem | None:
    supported = SUPPORTED_SCHEMA_VERSION
    if _SCHEMA_VERSION_PATH not in document:
        return ConfigProblem(_SCHEMA_VERSION_PATH, f"required: the integer {supported}")
    schema_version = document[_SCHEMA_VERSION_PATH]
    # ``bool`` is an ``int`` subclass and ``1.0 == 1``: only a JSON integer is a version.
    if type(schema_version) is not int:
        return ConfigProblem(
            _SCHEMA_VERSION_PATH, f"must be the integer {supported}, not {_shown(schema_version)}"
        )
    if schema_version != supported:
        # The pin matches this hub command, so running the pinned release changes nothing.
        shown = _shown(schema_version)
        return ConfigProblem(
            _SCHEMA_VERSION_PATH,
            f"schema version {shown} is not supported: this hub command reads schema"
            f" version {supported}; update the file to schema version {supported}, or pin a"
            f" release that reads schema version {shown}",
        )
    return None


def _well_formed_release(value: object) -> str | None:
    if isinstance(value, str) and _RELEASE_VERSION.fullmatch(value):
        return value
    return None


def _platform_repository(platform: dict[str, object]) -> str | None:
    if "repository" not in platform:
        return DEFAULT_PLATFORM_REPOSITORY
    value = platform["repository"]
    # A valid value holds no user, port, query or ``@ref``, so it may be echoed (the form).
    return value if isinstance(value, str) and is_platform_repository(value) else None


def _pinned_command(pinned: str, *, repository: str | None) -> str:
    """``: <the uvx command>`` for a pin short enough to print from a good repository, else ""."""
    command = pinned_release_command(pinned, repository=repository)
    return "" if command is None else f": {command}"


def _shown(value: object) -> str:
    """A value from the file as JSON text, escaped onto one line and cut to ``ECHO_LIMIT``."""
    return cut_echo(one_line(json.dumps(value)))


def cut_echo(text: str) -> str:
    """The escaped text, cut to ``ECHO_LIMIT`` with ``…``, never inside an escape sequence."""
    if len(text) <= ECHO_LIMIT:
        return text
    characters = _ESCAPED_CHARACTER.findall(text)
    ends = accumulate(len(character) for character in characters)
    kept = (
        character for character, end in zip(characters, ends, strict=True) if end <= ECHO_LIMIT - 1
    )
    return "".join(kept) + "…"
