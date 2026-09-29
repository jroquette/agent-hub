"""``HubConfig``: the frozen model of ``hub.json`` (docs/design/project-config.md § Fields)."""

import json
from collections.abc import Iterator
from typing import Annotated, Final, Literal

from pydantic import BeforeValidator, ConfigDict, Field
from pydantic_core import InitErrorDetails, PydanticCustomError

from agent_hub.core.hub_config.config_object import (
    COMMENT_KEYS_SCHEMA,
    ConfigObject,
    absent_by_default,
)
from agent_hub.core.hub_config.doctor_rules import RULE_MODULES, DoctorRules

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


class ModuleSettings(ConfigObject):
    """The settings of a selected module; none in Phase 1, so only ``{}`` (and ``_`` keys)."""


class Modules(ConfigObject):
    """The optional modules this hub selects: a key present means the module is selected."""

    cloud: ModuleSettings | None = absent_by_default()
    bench: ModuleSettings | None = absent_by_default()
    contract_sync: ModuleSettings | None = absent_by_default(alias="contract-sync")
    marketplace: ModuleSettings | None = absent_by_default()


# The closed module ids in their JSON spelling (``contract-sync``), as ``hub.lock`` and
# ``mk/<id>.mk`` use them. Derived from ``Modules``, so a new module field cannot be left out.
MODULE_IDS: Final[tuple[str, ...]] = tuple(
    sorted(field.alias or name for name, field in Modules.model_fields.items())
)


class Doctor(ConfigObject):
    """How ``hub doctor`` is tuned for this project (docs/design/hub-doctor.md)."""

    rules: DoctorRules = Field(default_factory=DoctorRules)


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
    # A factory, not an instance: the schema would export its unset keys as nulls.
    modules: Modules = Field(default_factory=Modules)
    doctor: Doctor = Field(default_factory=Doctor)

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Unique repo dirs (ignoring case), known ``ask_before_edit`` roots, selected modules."""
        return [
            *self._duplicate_repo_dirs(),
            *self._unknown_guard_roots(),
            *self._rules_of_unselected_modules(),
        ]

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

    def _rules_of_unselected_modules(self) -> Iterator[InitErrorDetails]:
        # Dumped by alias, so the keys are the JSON keys: module and rule ids.
        selected = self.modules.model_dump(exclude_none=True).keys()
        for rule_id, settings in self.doctor.rules.model_dump(exclude_none=True).items():
            module = RULE_MODULES.get(rule_id)
            if module is not None and module not in selected:
                yield InitErrorDetails(
                    type=PydanticCustomError(
                        "module_not_selected",
                        "rule {rule} belongs to module {module}, which is not selected;"
                        " add {module} to modules or remove the rule",
                        {"rule": json.dumps(rule_id), "module": json.dumps(module)},
                    ),
                    loc=("doctor", "rules", rule_id),
                    input=settings,
                )
