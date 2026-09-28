"""``HubConfig``: the frozen model of ``hub.json`` (docs/design/project-config.md § Fields)."""

import json
from collections.abc import Iterator
from typing import Annotated, Literal

from pydantic import BeforeValidator, ConfigDict, Field
from pydantic_core import InitErrorDetails, PydanticCustomError

from agent_hub.core.hub_config.config_object import (
    COMMENT_KEYS_SCHEMA,
    ConfigObject,
    absent_by_default,
)

HUB_ROOT = "@hub"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Plain aliases, not ``type`` statements: pydantic inlines them, so the schema's ``$defs`` hold
# only the object models.
# Free text still lands in files and commands, so a control character is never part of it.
FreeString = Annotated[str, Field(min_length=1, pattern=r"^[^\x00-\x1f\x7f]+$")]

# Rendered values (project-config.md): values that land in shell, Make or YAML text. Pydantic's
# Rust regex has no look-around, and ``[0-9]`` is spelled out because ``\d`` takes any digit.
# A safe segment: no leading ``-`` or ``.`` (an option or a hidden path), no ``..``, no trailing
# punctuation.
_SAFE_SEGMENT = r"[A-Za-z0-9_]+(?:[._-][A-Za-z0-9_]+)*"
_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
KebabName = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
RepoDir = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}$")]
GitHubRepo = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}/{_SAFE_SEGMENT}$")]
BranchPrefix = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}/$")]
BranchName = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}(?:/{_SAFE_SEGMENT})*$")]
EmailAddress = Annotated[str, Field(pattern=r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+$")]
HostName = Annotated[str, Field(pattern=rf"^{_HOST_LABEL}(?:\.{_HOST_LABEL})*$")]
TeamKey = Annotated[str, Field(pattern=r"^[A-Za-z0-9]+$")]
ReleaseVersion = Annotated[str, Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")]
# Relative, normalized, POSIX: segments of printable ASCII (no space, ``/`` or ``\``) that are
# not empty, ``.`` or ``..``, so an absolute path, ``//`` and a trailing ``/`` fail too. The
# root is cross-field.
_PATH_CHAR = r"[!-.0-\[\]-~]"
_PATH_CHAR_NOT_DOT = r"[!-\-0-\[\]-~]"
_GUARD_SEGMENT = rf"(?:{_PATH_CHAR}*{_PATH_CHAR_NOT_DOT}{_PATH_CHAR}*|\.{{3,}})"
GuardPath = Annotated[str, Field(pattern=rf"^{_GUARD_SEGMENT}(?:/{_GUARD_SEGMENT})*$")]


def exact_int(value: object) -> object:
    """Reject anything but a JSON integer: ``Literal[1]`` alone also takes ``true`` and ``1.0``."""
    if type(value) is not int:
        raise PydanticCustomError("int_type", "must be an integer")
    return value


def at_least_one_item(value: object) -> object:
    """Reject an empty list before its items are validated.

    ``Field(min_length=1)`` counts only the items that validated, so one bad repo would also
    report an empty list.
    """
    if isinstance(value, list | tuple) and not value:
        raise PydanticCustomError("empty_list", "must hold at least one item")
    return value


class Platform(ConfigObject):
    """The platform release this hub is pinned to."""

    version: ReleaseVersion


class Project(ConfigObject):
    """Project identity, authorship and branch rules."""

    name: KebabName
    hub_repo: GitHubRepo
    branch_prefix: BranchPrefix
    default_branch: BranchName = "main"
    author_name: FreeString
    author_email: EmailAddress


class Tracker(ConfigObject):
    """The task tracker and the labels the runner uses."""

    kind: Literal["linear"]
    team: TeamKey
    ready_label: FreeString = "agent-ready"
    failed_label: FreeString = "agent-failed"


class Repo(ConfigObject):
    """A repo managed by the hub, checked out next to it."""

    dir: RepoDir
    github: GitHubRepo
    role: FreeString = "app"
    check_fast: FreeString
    check: FreeString


class Guard(ConfigObject):
    """Paths and hosts the hub's guard hook asks about or denies."""

    ask_before_edit: tuple[GuardPath, ...] = ()
    deny_hosts: tuple[HostName, ...] = ()
    deny_paths: tuple[GuardPath, ...] = ()


class HubConfig(ConfigObject):
    """The whole ``hub.json``; the CLI and ``hub doctor`` validate with it."""

    model_config = ConfigDict(
        title="hub.json",
        # A subclass's json_schema_extra replaces the base's, so the comment keys are repeated.
        json_schema_extra={"$schema": JSON_SCHEMA_DIALECT, **COMMENT_KEYS_SCHEMA},
    )

    schema_uri: FreeString | None = absent_by_default(alias="$schema")
    schema_version: Annotated[Literal[1], BeforeValidator(exact_int)]
    platform: Platform
    project: Project
    tracker: Tracker
    repos: Annotated[
        tuple[Repo, ...],
        BeforeValidator(at_least_one_item),
        Field(json_schema_extra={"minItems": 1}),
    ]
    guard: Guard = Guard()

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Unique repo dirs (ignoring case) and known ``ask_before_edit`` roots."""
        return [*self._duplicate_repo_dirs(), *self._unknown_guard_roots()]

    def _duplicate_repo_dirs(self) -> Iterator[InitErrorDetails]:
        # Case-insensitive: on macOS's default file system, ``demo-api`` and ``Demo-api`` are
        # the same directory.
        first_index: dict[str, int] = {}
        for index, repo in enumerate(self.repos):
            key = repo.dir.lower()
            if key in first_index:
                yield InitErrorDetails(
                    type=PydanticCustomError(
                        "duplicate_repo_dir",
                        "repo dir {dir} is already used by repos[{first}], ignoring case",
                        {"dir": json.dumps(repo.dir), "first": first_index[key]},
                    ),
                    loc=("repos", index, "dir"),
                    input=repo.dir,
                )
            first_index.setdefault(key, index)

    def _unknown_guard_roots(self) -> Iterator[InitErrorDetails]:
        roots = {repo.dir for repo in self.repos} | {HUB_ROOT}
        for index, path in enumerate(self.guard.ask_before_edit):
            root = path.split("/", 1)[0]
            if root not in roots:
                yield InitErrorDetails(
                    type=PydanticCustomError(
                        "unknown_guard_root",
                        "first segment {root} is neither a repos[].dir nor " + HUB_ROOT,
                        {"root": json.dumps(root)},
                    ),
                    loc=("guard", "ask_before_edit", index),
                    input=path,
                )
