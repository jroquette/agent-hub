"""``HubConfig``: the frozen model of ``hub.json`` (docs/design/project-config.md § Fields)."""

import json
import re
from collections.abc import Iterator
from typing import Annotated, Final, Literal

from pydantic import AfterValidator, BeforeValidator, ConfigDict, Field, StrictInt
from pydantic_core import InitErrorDetails, PydanticCustomError

from agent_hub.core.hub_config.config_object import (
    COMMENT_KEYS_SCHEMA,
    ConfigObject,
    absent_by_default,
)
from agent_hub.core.hub_config.conventions import (
    BRANCH_PLACEHOLDERS,
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_TITLE,
    TITLE_PLACEHOLDERS,
    EffectiveConventions,
    branch_pattern_problem,
    effective_conventions,
    pattern_parts,
    title_pattern_problem,
)
from agent_hub.core.hub_config.doctor_rules import RULE_MODULES, DoctorRules
from agent_hub.core.hub_config.platform_repository import (
    DEFAULT_PLATFORM_REPOSITORY,
    MAX_PLATFORM_REPOSITORY_CHARS,
    PLATFORM_REPOSITORY_MESSAGE,
    PLATFORM_REPOSITORY_PATTERN,
    is_platform_repository,
)

HUB_ROOT = "@hub"
JSON_SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

# Plain aliases, not ``type`` statements: pydantic inlines them, so the schema's ``$defs`` hold
# only the object models.
# Free text still lands in files and commands, so a control character is never part of it.
FreeString = Annotated[str, Field(min_length=1, pattern=r"^[^\x00-\x1f\x7f]+$")]
# A repo's fast gate may be empty or blank: no Stop gate (project-config.md).
CommandString = Annotated[str, Field(pattern=r"^[^\x00-\x1f\x7f]*$")]
# ``str.isspace`` outside the control characters, spelled out: JSON Schema's ``\s`` (ECMA) and
# Python's disagree on U+0085 and U+FEFF.
_SPACES = r"\x20\x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000"
_NOT_BLANK_COMMAND = rf"^[^\x00-\x1f\x7f]*[^\x00-\x1f\x7f{_SPACES}][^\x00-\x1f\x7f]*$"
# The Stop hook's total budget (stop_gate.py.tmpl ``BUDGET``): no repo may ask for more.
MAX_CHECK_FAST_TIMEOUT: Final = 160

# Rendered values (project-config.md): values that land in shell, Make or YAML text. Pydantic's
# Rust regex has no look-around, and ``[0-9]`` is spelled out because ``\d`` takes any digit.
# A safe segment: no leading ``-`` or ``.`` (an option or a hidden path), no ``..``, no trailing
# punctuation. The separator class leaves out ``_``, already a segment character: the hooks'
# reader copies this pattern into Python's ``re``, which backtracks exponentially on an overlap.
_SAFE_SEGMENT = r"[A-Za-z0-9_]+(?:[.-][A-Za-z0-9_]+)*"
_HOST_LABEL = r"[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?"
KebabName = Annotated[str, Field(pattern=r"^[a-z0-9]+(-[a-z0-9]+)*$")]
RepoDir = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}$")]
GitHubRepo = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}/{_SAFE_SEGMENT}$")]
BranchPrefix = Annotated[str, Field(pattern=rf"^{_SAFE_SEGMENT}/$")]
_BRANCH_NAME = rf"^{_SAFE_SEGMENT}(?:/{_SAFE_SEGMENT})*$"
BranchName = Annotated[str, Field(pattern=_BRANCH_NAME)]
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


def _not_blank(value: str) -> str:
    if not value.strip():
        raise PydanticCustomError("blank_command", "must hold a non-space character")
    return value


# A repo's full gate: free text with at least one non-space character. The validator gives the
# readable error; the exported schema states the same rule as a pattern.
RequiredCommand = Annotated[
    CommandString,
    AfterValidator(_not_blank),
    Field(json_schema_extra={"pattern": _NOT_BLANK_COMMAND}),
]


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


def _platform_repository(value: object) -> object:
    """One value-free problem for any bad value, whatever its type: the value may hold a secret."""
    if not is_platform_repository(value):
        raise PydanticCustomError("platform_repository", PLATFORM_REPOSITORY_MESSAGE)
    return value


# The before-validator checks every value first; the ``Field``, listed before it so pydantic
# keeps its constraints on the string schema, puts the same rule in the exported schema.
PlatformRepository = Annotated[
    str,
    Field(pattern=rf"^{PLATFORM_REPOSITORY_PATTERN}$", max_length=MAX_PLATFORM_REPOSITORY_CHARS),
    BeforeValidator(_platform_repository),
]


class Platform(ConfigObject):
    """The platform release this hub is pinned to."""

    version: ReleaseVersion
    # The schema names the default by role: hub.schema.json is rendered into every hub (ADR 0009).
    repository: PlatformRepository | None = absent_by_default(
        description="The platform's git source: the repository root as git+https://<host>/<path>,"
        f" at most {MAX_PLATFORM_REPOSITORY_CHARS} characters. The hub runs"
        " <repository>@v<platform.version>#subdirectory=packages/agent-hub. Absent: the"
        " agent-hub release repository (docs/design/project-config.md)."
    )

    @property
    def effective_repository(self) -> str:
        """The repository as written, else the default."""
        return self.repository if self.repository is not None else DEFAULT_PLATFORM_REPOSITORY


# A branch pattern's sample renders must be valid branch names: the same rule, in Python's re.
_BRANCH_NAME_RE = re.compile(_BRANCH_NAME)


def _branch_pattern(value: str) -> str:
    problem = branch_pattern_problem(value, branch_name=_BRANCH_NAME_RE)
    if problem is not None:
        raise PydanticCustomError("convention_pattern", problem)
    return value


def _title_pattern(value: str) -> str:
    problem = title_pattern_problem(value)
    if problem is not None:
        raise PydanticCustomError("convention_pattern", problem)
    return value


# One problem per pattern, at the pattern's own key (conventions.py names it).
BranchPattern = Annotated[str, AfterValidator(_branch_pattern)]
TitlePattern = Annotated[str, AfterValidator(_title_pattern)]


def _placeholder_list(names: tuple[str, ...]) -> str:
    return ", ".join(f"{{{name}}}" for name in names)


def _placeholders(pattern: str) -> list[str]:
    return [part.placeholder for part in pattern_parts(pattern) if part.placeholder is not None]


class Conventions(ConfigObject):
    """Branch and title patterns; each absent key keeps today's shape."""

    branch: BranchPattern | None = absent_by_default(
        description=f"Branch pattern: {_placeholder_list(BRANCH_PLACEHOLDERS)}; needs {{ISSUE}}"
        f" or {{issue_lower}}. Default {DEFAULT_BRANCH}."
    )
    commit_title: TitlePattern | None = absent_by_default(
        description=f"Commit title pattern: {_placeholder_list(TITLE_PLACEHOLDERS)}; needs"
        f" {{summary}}. Default {DEFAULT_COMMIT_TITLE}."
    )
    pr_title: TitlePattern | None = absent_by_default(
        description=f"PR title pattern: {_placeholder_list(TITLE_PLACEHOLDERS)}; needs"
        " {summary}. Default: the effective commit_title."
    )


# The identity keys are per developer: absent here, each comes from hub.local.json or git config.
_DESIGN = "(docs/design/developer-identity.md)"
_PER_DEVELOPER = f"Per developer: hub.local.json, else this, else git config {_DESIGN}."
# How doctor fixes and rendered text name the branch prefix of a hub that leaves it to each one.
PREFIX_PLACEHOLDER: Final = "<prefix>"


class Project(ConfigObject):
    """Project identity, authorship and branch rules."""

    name: KebabName
    hub_repo: GitHubRepo
    branch_prefix: BranchPrefix | None = absent_by_default(
        description="Per developer: hub.local.json, else this, else the effective author email's"
        f" local part plus / {_DESIGN}."
    )
    default_branch: BranchName = "main"
    author_name: FreeString | None = absent_by_default(description=_PER_DEVELOPER)
    author_email: EmailAddress | None = absent_by_default(description=_PER_DEVELOPER)
    conventions: Conventions | None = absent_by_default(
        description="Branch and title patterns for every repo; absent keys keep today's shapes."
    )


# Several team keys: at least one, unique ignoring case (``Tracker``), the first the default.
TeamKeys = Annotated[
    tuple[TeamKey, ...],
    BeforeValidator(at_least_one_item),
    Field(json_schema_extra={"minItems": 1}),
]


class TrackerStates(ConfigObject):
    """The workflow state names the CLI moves issues to; `review` is reserved for review."""

    started: FreeString = "In Progress"
    review: FreeString = "In Review"


class Tracker(ConfigObject):
    """The task tracker, how the CLI reaches it and the labels the runner uses."""

    model_config = ConfigDict(
        # A subclass's json_schema_extra replaces the base's, so the comment keys are repeated.
        json_schema_extra={
            **COMMENT_KEYS_SCHEMA,
            "oneOf": [{"required": ["team"]}, {"required": ["teams"]}],
        }
    )
    required_one_of = ("team", "teams")

    kind: Literal["linear"]
    team: TeamKey | None = absent_by_default(
        description="The tracker's team key. Never with tracker.teams."
    )
    teams: TeamKeys | None = absent_by_default(
        description="Several team keys, the first being the default. Never with tracker.team."
    )
    # The adapter: "api" is Linear's GraphQL API with LINEAR_API_KEY, "mcp" the Linear MCP
    # server through claude -p (ADR 0015).
    transport: Literal["api", "mcp"] = "api"
    ready_label: FreeString = "agent-ready"
    failed_label: FreeString = "agent-failed"
    # A factory, not an instance: the schema would export its unset keys as nulls.
    states: TrackerStates = Field(default_factory=TrackerStates)

    @property
    def team_keys(self) -> tuple[str, ...]:
        """The configured team keys in order, derived from the fields when read.

        ``teams``, else ``(team,)``, else none (validation requires one of the two keys).
        """
        if self.teams is not None:
            return self.teams
        if self.team is not None:
            return (self.team,)
        return ()

    @property
    def default_team(self) -> str:
        """The first team key: the default team.

        Raises ``ValueError`` on a tracker with no team key, which validation never builds.
        """
        keys = self.team_keys
        if not keys:
            raise ValueError("tracker has no team key")
        return keys[0]

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Not both team keys, and no team key repeated ignoring case."""
        if self.team is not None and self.teams is not None:
            return [
                InitErrorDetails(
                    type=PydanticCustomError(
                        "team_and_teams", "set tracker.team or tracker.teams, not both"
                    ),
                    loc=("teams",),
                    input=self.teams,
                )
            ]
        return list(self._duplicate_team_keys())

    def _duplicate_team_keys(self) -> Iterator[InitErrorDetails]:
        first_index: dict[str, int] = {}
        for index, key in enumerate(self.teams or ()):
            folded = key.lower()
            if folded in first_index:
                yield InitErrorDetails(
                    type=PydanticCustomError(
                        "duplicate_team_key",
                        "team key {key} is already used by teams[{first}], ignoring case",
                        {"key": json.dumps(key), "first": first_index[folded]},
                    ),
                    loc=("teams", index),
                    input=key,
                )
            first_index.setdefault(folded, index)


class Repo(ConfigObject):
    """A repo managed by the hub, checked out next to it."""

    dir: RepoDir
    github: GitHubRepo
    role: FreeString = "app"
    check_fast: CommandString | None = absent_by_default(
        description="The fast gate the Stop hook runs. Absent, empty or blank: no Stop gate."
    )
    check_fast_timeout: Annotated[StrictInt, Field(ge=1, le=MAX_CHECK_FAST_TIMEOUT)] | None = (
        absent_by_default(
            description="Seconds the Stop hook gives check_fast, within its 160 s budget."
            " Absent: 150."
        )
    )
    check: RequiredCommand
    default_branch: BranchName | None = absent_by_default(
        description="The repo's default branch: worktree and PR base, push guard."
        " Absent: project.default_branch."
    )
    conventions: Conventions | None = absent_by_default(
        description="Overrides project.conventions key by key."
    )


def _python_regex(value: str) -> str:
    try:
        re.compile(value)
    except (re.error, OverflowError, RecursionError) as error:
        raise PydanticCustomError(
            "python_regex", "not a Python regex: {error}", {"error": str(error)}
        ) from error
    return value


# A guard pattern: non-blank free text that compiles with Python's ``re``.
InfraPattern = Annotated[RequiredCommand, AfterValidator(_python_regex)]


class GuardInfra(ConfigObject):
    """Regexes the guard hook matches against infra commands: allowed environments and production
    markers."""

    allow: tuple[InfraPattern, ...] = ()
    prod_markers: tuple[InfraPattern, ...] = ()


class Guard(ConfigObject):
    """Paths and hosts the hub's guard hook asks about or denies."""

    ask_before_edit: tuple[GuardPath, ...] = ()
    deny_hosts: tuple[HostName, ...] = ()
    deny_paths: tuple[GuardPath, ...] = ()
    infra: GuardInfra | None = absent_by_default(
        description="Turns on the guard's infra classification: Python re patterns, searched with"
        " no flags. Absent: the fixed infra rule."
    )


class ModuleSettings(ConfigObject):
    """The settings of a module that takes none: only ``{}`` (and ``_`` keys)."""


class ContractSyncSettings(ModuleSettings):
    """``contract-sync``: the repo that exports the contract and the repo that imports it.

    Both are ``repos[].dir`` entries, checked by ``HubConfig``, which knows the repos.
    """

    source: RepoDir
    target: RepoDir

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """A source that is also the target syncs nothing."""
        if self.source != self.target:
            return []
        return [
            InitErrorDetails(
                type=PydanticCustomError(
                    "same_repo_dir",
                    "target {dir} is the source too; give two different repos",
                    {"dir": json.dumps(self.target)},
                ),
                loc=("target",),
                input=self.target,
            )
        ]


class Modules(ConfigObject):
    """The optional modules this hub selects: a key present means the module is selected."""

    cloud: ModuleSettings | None = absent_by_default()
    bench: ModuleSettings | None = absent_by_default()
    contract_sync: ContractSyncSettings | None = absent_by_default(alias="contract-sync")
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
    # A factory, not an instance: the schema would export its unset keys as nulls.
    guard: Guard = Field(default_factory=Guard)
    # A factory, not an instance: the schema would export its unset keys as nulls.
    modules: Modules = Field(default_factory=Modules)
    doctor: Doctor = Field(default_factory=Doctor)

    def default_branch_for(self, repo_dir: str) -> str:
        """The effective default branch of the repo at ``repo_dir``: its own, else the project's.

        Raises ``KeyError`` when no repo has that dir: every caller holds a ``repos[].dir``.
        """
        for repo in self.repos:
            if repo.dir == repo_dir:
                # The inherited value: the only per-repo read of the project branch.
                return repo.default_branch or self.project.default_branch
        raise KeyError(repo_dir)

    def conventions_for(self, repo_dir: str) -> EffectiveConventions:
        """The effective conventions of the repo at ``repo_dir``: its keys over the project's.

        The only reader of ``project.conventions`` and ``repos[].conventions`` (with
        ``workspace.shown_conventions``, the rendered texts' source). Raises ``KeyError`` when
        no repo has that dir.
        """
        for repo in self.repos:
            if repo.dir == repo_dir:
                return effective_conventions(self.project.conventions, repo.conventions)
        raise KeyError(repo_dir)

    @property
    def project_conventions(self) -> EffectiveConventions:
        """The project's effective conventions: its keys over the defaults, no repo's."""
        return effective_conventions(self.project.conventions, None)

    @property
    def sets_conventions(self) -> bool:
        """Whether ``project.conventions`` or a ``repos[].conventions`` is set, even ``{}``."""
        return self.project.conventions is not None or any(
            repo.conventions is not None for repo in self.repos
        )

    def cross_field_problems(self) -> list[InitErrorDetails]:
        """Unique repo dirs, known guard roots and contract-sync repos, rules of chosen modules,
        and an explicit ``pr_title`` that its repo's ``commit_title`` cannot fill."""
        return [
            *self._duplicate_repo_dirs(),
            *self._unknown_guard_roots(),
            *self._contract_sync_repos(),
            *self._rules_of_unselected_modules(),
            *self._unfillable_pr_titles(),
        ]

    def _unfillable_pr_titles(self) -> Iterator[InitErrorDetails]:
        # Per repo, on the effective patterns; an unset pr_title is the commit_title, so only an
        # explicit one can need a part ({ISSUE} aside: the run's id) that the commit lacks. One
        # error per pr_title key, with one clause per distinct clash.
        clashes: dict[tuple[str | int, ...], tuple[str, list[str]]] = {}
        for index, repo in enumerate(self.repos):
            conventions = self.conventions_for(repo.dir)
            if not conventions.pr_title_explicit:
                continue
            commit_parts = _placeholders(conventions.commit_title)
            missing = [
                name
                for name in _placeholders(conventions.pr_title)
                if name != "ISSUE" and name not in commit_parts
            ]
            if not missing:
                continue
            own = repo.conventions or Conventions()
            loc: tuple[str | int, ...] = (
                ("repos", index, "conventions", "pr_title")
                if own.pr_title is not None
                else ("project", "conventions", "pr_title")
            )
            # A project pr_title clashing with a repo's own commit_title names that repo (E15).
            source = (
                f"repos[{index}].conventions."
                if own.pr_title is None and own.commit_title is not None
                else ""
            )
            clause = (
                f"pr_title needs {_placeholder_list(tuple(missing))}, which"
                f" {source}commit_title `{conventions.commit_title}` lacks"
            )
            _, clauses = clashes.setdefault(loc, (conventions.pr_title, []))
            if clause not in clauses:
                clauses.append(clause)
        for loc, (pr_title, clauses) in clashes.items():
            yield InitErrorDetails(
                type=PydanticCustomError(
                    "unfillable_pr_title", "{clashes}", {"clashes": "; ".join(clauses)}
                ),
                loc=loc,
                input=pr_title,
            )

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

    def _contract_sync_repos(self) -> Iterator[InitErrorDetails]:
        settings = self.modules.contract_sync
        if settings is None:
            return
        dirs = {repo.dir for repo in self.repos}
        for key, value in (("source", settings.source), ("target", settings.target)):
            if value not in dirs:
                yield InitErrorDetails(
                    type=PydanticCustomError(
                        "unknown_repo_dir",
                        "repo dir {dir} is not in repos",
                        {"dir": json.dumps(value)},
                    ),
                    loc=("modules", "contract-sync", key),
                    input=value,
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
