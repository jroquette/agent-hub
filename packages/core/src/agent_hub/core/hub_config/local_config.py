"""``hub.local.json``: one developer's identity, transport and own rules, beside ``hub.json``.

The file is per developer and never committed. It holds ``project.branch_prefix``,
``project.author_name``, ``project.author_email`` and ``tracker.transport``; the developer's
``environments``, their endpoints on ``hub.json``'s repos (``repos: [{dir, services}]``) and
more blocked entries (``guard.blocked_words``, ``blocked_words_files``, ``blocked_words_env``).
Each value is checked with the same rule as in ``hub.json``; any other ``hub.json`` key is
refused with a message that says so (docs/design/developer-identity.md). The rules across both
files (new names only, ``access`` only tightened) are ``effective_environments.py``'s.
"""

import json
from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import Annotated, ClassVar, Final, Literal

from pydantic import BaseModel, BeforeValidator, Field, StrictBool, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from agent_hub.core.hub_config.config_object import ConfigObject, absent_by_default
from agent_hub.core.hub_config.doctor_rules import drop_map_comment_keys
from agent_hub.core.hub_config.document_check import validation_problems
from agent_hub.core.hub_config.environments import (
    MAX_BLOCKED_ENV,
    MAX_BLOCKED_GLOBS,
    MAX_BLOCKED_WORDS,
    Access,
    BlockedWord,
    Credentials,
    EnvironmentName,
    EnvVarPattern,
    NoSecretText,
    Services,
    WordFileGlob,
    comment_keyed_map,
)
from agent_hub.core.hub_config.model import (
    BranchPrefix,
    EmailAddress,
    FreeString,
    Guard,
    HubConfig,
    Project,
    Repo,
    RepoDir,
    Tracker,
)
from agent_hub.core.hub_config.problems import NOT_AN_OBJECT_MESSAGE, ROOT_PATH, ConfigProblem

LOCAL_FILE: Final = "hub.local.json"
# Four short keys: the cap keeps a stray big file from being read on every call.
LOCAL_FILE_MAX_BYTES: Final = 65_536

# The identity keys in the order ``hub setup`` writes them (``effective_identity`` imports this
# module, so the order is spelled here).
_IDENTITY_ORDER: Final = ("branch_prefix", "author_name", "author_email")

NO_IDENTITY_MESSAGE: Final = (
    "holds no identity value: set branch_prefix, author_name or author_email"
)
# Written bytes the reader would refuse: no file is better than one every command rejects.
TOO_LARGE_MESSAGE: Final = f"larger than {LOCAL_FILE_MAX_BYTES} bytes once written"
HUB_ONLY_MESSAGE: Final = (
    "set only in hub.json (hub.local.json's keys: docs/design/developer-identity.md)"
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


class LocalEnvironment(ConfigObject):
    """A developer's own environment, or (``access`` alone) a stricter access on a committed one.

    Every key is optional here: what each case needs is checked across the two files.
    """

    access: Access | None = absent_by_default()
    production: StrictBool | None = absent_by_default()
    description: NoSecretText | None = absent_by_default()
    credentials: Credentials | None = absent_by_default()


LocalEnvironments = Annotated[
    dict[EnvironmentName, LocalEnvironment],
    BeforeValidator(drop_map_comment_keys),
    Field(json_schema_extra=comment_keyed_map),
]


class LocalRepo(ConfigObject):
    """The developer's services and endpoints on one of ``hub.json``'s repos."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(
        Repo, local_keys=("dir", "services")
    )

    dir: RepoDir
    services: Services = Field(default_factory=dict)


class LocalGuard(ConfigObject):
    """More blocked entries, added to ``hub.json``'s; no other ``guard`` key is local."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(
        Guard, local_keys=("blocked_words", "blocked_words_files", "blocked_words_env")
    )

    blocked_words: Annotated[tuple[BlockedWord, ...], Field(max_length=MAX_BLOCKED_WORDS)] = ()
    blocked_words_files: Annotated[
        tuple[WordFileGlob, ...], Field(max_length=MAX_BLOCKED_GLOBS)
    ] = ()
    blocked_words_env: Annotated[tuple[EnvVarPattern, ...], Field(max_length=MAX_BLOCKED_ENV)] = ()


class LocalConfig(ConfigObject):
    """The whole ``hub.local.json``; an absent file is ``LocalConfig()``, which sets nothing."""

    rejected_keys: ClassVar[Mapping[str, str]] = _hub_only_keys(
        HubConfig, local_keys=("project", "tracker", "environments", "repos", "guard")
    )

    # Factories, not instances, as in ``HubConfig``.
    project: LocalProject = Field(default_factory=LocalProject)
    tracker: LocalTracker = Field(default_factory=LocalTracker)
    environments: LocalEnvironments = Field(default_factory=dict)
    repos: tuple[LocalRepo, ...] = ()
    guard: LocalGuard = Field(default_factory=LocalGuard)

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Each local repo dir once, ignoring case, as in ``hub.json``."""
        first_index: dict[str, int] = {}
        problems = []
        for index, repo in enumerate(self.repos):
            key = repo.dir.lower()
            if key in first_index:
                problems.append(
                    InitErrorDetails(
                        type=PydanticCustomError(
                            "duplicate_repo_dir",
                            "repo dir {dir} is already used by repos[{first}], ignoring case",
                            {"dir": json.dumps(repo.dir), "first": first_index[key]},
                        ),
                        loc=("repos", index, "dir"),
                        input=repo.dir,
                    )
                )
            first_index.setdefault(key, index)
        return problems


def check_local_document(document: object) -> LocalConfig | tuple[ConfigProblem, ...]:
    """The local config, or its problems, one per error, on the same paths as ``hub.json``'s."""
    if not isinstance(document, dict):
        return (ConfigProblem(ROOT_PATH, NOT_AN_OBJECT_MESSAGE),)
    try:
        return LocalConfig.model_validate(document)
    except ValidationError as error:
        return validation_problems(error, document)


def local_identity_bytes(values: Mapping[str, str]) -> bytes | tuple[ConfigProblem, ...]:
    """The bytes of a ``hub.local.json`` holding ``values`` under ``project``, or their problems.

    Keys come out in the order ``branch_prefix``, ``author_name``, ``author_email`` whatever the
    mapping's order, indented 2, UTF-8 and not escaped, with a final newline. An empty mapping
    is a problem at ``project``, as an invalid value is: such a file would set nothing. Bytes
    over ``LOCAL_FILE_MAX_BYTES``, which the reader refuses, are a problem at the root.
    """
    if not values:
        return (ConfigProblem("project", NO_IDENTITY_MESSAGE),)
    checked = check_local_document({"project": dict(values)})
    if not isinstance(checked, LocalConfig):
        return checked
    project = {key: values[key] for key in _IDENTITY_ORDER if key in values}
    text = json.dumps({"project": project}, indent=2, ensure_ascii=False) + "\n"
    content = text.encode("utf-8")
    if len(content) > LOCAL_FILE_MAX_BYTES:
        return (ConfigProblem(ROOT_PATH, TOO_LARGE_MESSAGE),)
    return content
