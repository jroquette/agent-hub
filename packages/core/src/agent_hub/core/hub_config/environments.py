"""Declared environments and services, and the guard's blocked words (docs/design/environments.md).

The value shapes of ``hub.json``'s ``environments``, ``repos[].services`` and
``guard.blocked_words*``; ``model.py`` puts them in ``HubConfig`` and checks across them (names
unique ignoring case, endpoints on declared environments). Credentials are referenced by name
only. No behaviour comes from a name: ``production`` is a flag.
"""

from typing import Annotated, Final, Literal

from pydantic import AfterValidator, BeforeValidator, ConfigDict, Field, StrictBool
from pydantic_core import PydanticCustomError

from agent_hub.core.hub_config.config_object import (
    COMMENT_KEYS_SCHEMA,
    ConfigObject,
    absent_by_default,
)
from agent_hub.core.hub_config.doctor_rules import drop_map_comment_keys
from agent_hub.core.hub_config.text_shapes import FREE_TEXT_PATTERN, SAFE_SEGMENT
from agent_hub.core.secret_shapes import secret_kind

MAX_NAME_CHARS: Final = 40
MAX_CREDENTIAL_ENV: Final = 10
MAX_URL_CHARS: Final = 200
MAX_KIND_CHARS: Final = 32


def _no_secret_shape(value: str) -> str:
    """Reject text with a secret's shape, naming the kind and never the text."""
    kind = secret_kind(value)
    if kind is not None:
        raise PydanticCustomError(
            "secret_shape",
            "looks like a secret ({kind}); reference a profile or variable name instead",
            {"kind": kind},
        )
    return value


# Every string under ``environments`` and ``services`` is checked for a secret's shape.
NoSecret = AfterValidator(_no_secret_shape)
NoSecretText = Annotated[str, Field(min_length=1, pattern=FREE_TEXT_PATTERN), NoSecret]
# An environment's or a service's name: a safe segment, as repo dirs are.
EnvironmentName = Annotated[
    str, Field(pattern=rf"^{SAFE_SEGMENT}$", max_length=MAX_NAME_CHARS), NoSecret
]
ServiceName = EnvironmentName
# What the agent may do there; rendered as an instruction, never checked by the guard.
Access = Literal["read", "write", "ask"]
AwsProfile = Annotated[str, Field(pattern=r"^[A-Za-z0-9_.-]{1,64}$"), NoSecret]
_ENV_VAR_NAME = r"[A-Z_][A-Z0-9_]{0,63}"
EnvVarName = Annotated[str, Field(pattern=rf"^{_ENV_VAR_NAME}$"), NoSecret]
# ``scheme://host[:port][/path]`` in printable ASCII: no space, and no ``@``, ``?`` or ``#``,
# so no user info, query or fragment can carry a credential.
_URL_PATH_CHAR = r'[!"$->A-~]'
Url = Annotated[
    str,
    Field(
        pattern=rf"^[A-Za-z][A-Za-z0-9+.-]*://[A-Za-z0-9.-]+(?::[0-9]{{1,5}})?"
        rf"(?:/{_URL_PATH_CHAR}*)?$",
        max_length=MAX_URL_CHARS,
    ),
    NoSecret,
]
ServiceKind = Annotated[
    str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$", max_length=MAX_KIND_CHARS), NoSecret
]


# The guard's blocked words (docs/design/environments.md § Blocked words). The hooks' reader
# keeps its own copy of these shapes.
MAX_BLOCKED_WORDS: Final = 200
MAX_BLOCKED_GLOBS: Final = 100
MAX_BLOCKED_ENV: Final = 50
MAX_GLOB_CHARS: Final = 200
BlockedWord = Annotated[
    str, Field(min_length=2, max_length=64, pattern=r"^[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)*$")
]


def _no_parent_segment(value: str) -> str:
    # Pydantic's regex has no look-around, so the ``..`` segment is refused here.
    if ".." in value.split("/"):
        raise PydanticCustomError("parent_segment", "must not hold a .. segment")
    return value


# Printable ASCII without space, never starting with ``/``; a glob without ``/`` matches a file's
# last path component, one with ``/`` a trailing run of segments.
WordFileGlob = Annotated[
    str,
    Field(pattern=r"^[!-.0-~][!-~]*$", max_length=MAX_GLOB_CHARS),
    AfterValidator(_no_parent_segment),
]
# A variable name whose value the guard scans; a trailing ``*`` matches names by prefix.
EnvVarPattern = Annotated[str, Field(pattern=rf"^{_ENV_VAR_NAME}\*?$")]


class Credentials(ConfigObject):
    """Where the credentials of an environment come from: names, never values."""

    aws_profile: AwsProfile | None = absent_by_default(description="An AWS profile name.")
    env: Annotated[tuple[EnvVarName, ...], Field(max_length=MAX_CREDENTIAL_ENV)] = Field(
        default=(), description="Names of the environment variables that hold credentials."
    )


class Environment(ConfigObject):
    """A place the agent may reach, and what it may do there."""

    access: Access
    production: StrictBool = False
    description: NoSecretText | None = absent_by_default()
    credentials: Credentials | None = absent_by_default(
        description="Names of the credentials to use; never a value."
    )


class Endpoint(ConfigObject):
    """How a service is reached in one environment: a ``url`` or a ``resource`` name, or both."""

    model_config = ConfigDict(
        # A subclass's json_schema_extra replaces the base's, so the comment keys are repeated.
        json_schema_extra={
            **COMMENT_KEYS_SCHEMA,
            "anyOf": [{"required": ["url"]}, {"required": ["resource"]}],
        }
    )
    required_one_of = ("url", "resource")

    url: Url | None = absent_by_default(
        description="scheme://host[:port][/path], at most 200 characters; no user info, query"
        " or fragment."
    )
    resource: NoSecretText | None = absent_by_default(
        description="A resource name, such as a table or a function."
    )
    note: NoSecretText | None = absent_by_default()
    credentials: Credentials | None = absent_by_default(
        description="Names of the credentials to use here; never a value."
    )


# A map keyed by name whose ``_`` keys are comments, as in every fixed-key object; the schema
# says so too (a plain alias, as in model.py). ``dict`` keeps the file's order; frozen is shallow.
Endpoints = Annotated[
    dict[EnvironmentName, Endpoint],
    BeforeValidator(drop_map_comment_keys),
    Field(json_schema_extra=COMMENT_KEYS_SCHEMA),
]


class Service(ConfigObject):
    """A service a repo runs, with its endpoint in each declared environment."""

    kind: ServiceKind | None = absent_by_default(
        description="What the service is (api, dynamodb, lambda, ...): informational."
    )
    description: NoSecretText | None = absent_by_default()
    endpoints: Endpoints = Field(
        default_factory=dict, description="Keyed by a declared environment's name."
    )


Services = Annotated[
    dict[ServiceName, Service],
    BeforeValidator(drop_map_comment_keys),
    Field(json_schema_extra=COMMENT_KEYS_SCHEMA),
]
Environments = Annotated[
    dict[EnvironmentName, Environment],
    BeforeValidator(drop_map_comment_keys),
    Field(json_schema_extra=COMMENT_KEYS_SCHEMA),
]
