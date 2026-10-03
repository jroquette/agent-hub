"""``hub.local.json``: one developer's identity and transport, beside the hub's ``hub.json``.

The file is per developer and never committed. It holds only ``project.branch_prefix``,
``project.author_name``, ``project.author_email`` and ``tracker.transport``, each checked with
the same rule as in ``hub.json``; any other ``hub.json`` key is refused with a message that
says so (docs/design/developer-identity.md).
"""

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import ClassVar, Final, Literal

from pydantic import BaseModel, Field, ValidationError

from agent_hub.core.hub_config.config_object import ConfigObject, absent_by_default
from agent_hub.core.hub_config.document_check import validation_problems
from agent_hub.core.hub_config.model import (
    BranchPrefix,
    EmailAddress,
    FreeString,
    HubConfig,
    Project,
    Tracker,
)
from agent_hub.core.hub_config.problems import ConfigProblem

LOCAL_FILE: Final = "hub.local.json"
# Four short keys: the cap keeps a stray big file from being read on every call.
LOCAL_FILE_MAX_BYTES: Final = 65_536

HUB_ONLY_MESSAGE: Final = (
    "set only in hub.json; hub.local.json holds project.branch_prefix, author_name,"
    " author_email and tracker.transport"
)


def _hub_only_keys(hub_model: type[BaseModel], *, local_keys: Iterable[str]) -> Mapping[str, str]:
    """The JSON keys of ``hub_model`` that are not local, each with the hub-only message.

    Derived from the ``hub.json`` model, so a key added there is refused here by name.
    """
    keys = {field.alias or name for name, field in hub_model.model_fields.items()}
    return MappingProxyType({key: HUB_ONLY_MESSAGE for key in sorted(keys - set(local_keys))})


class LocalProject(ConfigObject):
    """The developer's identity: each key, when set, replaces ``hub.json``'s."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(
        Project, local_keys=("branch_prefix", "author_name", "author_email")
    )

    branch_prefix: BranchPrefix | None = absent_by_default()
    author_name: FreeString | None = absent_by_default()
    author_email: EmailAddress | None = absent_by_default()


class LocalTracker(ConfigObject):
    """How this developer's CLI reaches the tracker."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(Tracker, local_keys=("transport",))

    transport: Literal["api", "mcp"] | None = absent_by_default()


class LocalConfig(ConfigObject):
    """The whole ``hub.local.json``; an absent file is ``LocalConfig()``, which sets nothing."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(
        HubConfig, local_keys=("project", "tracker")
    )

    # Factories, not instances, as in ``HubConfig``.
    project: LocalProject = Field(default_factory=LocalProject)
    tracker: LocalTracker = Field(default_factory=LocalTracker)


def check_local_document(document: object) -> LocalConfig | tuple[ConfigProblem, ...]:
    """The local config, or its problems, one per error, on the same paths as ``hub.json``'s."""
    try:
        return LocalConfig.model_validate(document)
    except ValidationError as error:
        return validation_problems(error, document)
