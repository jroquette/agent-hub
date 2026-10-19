"""The Hub config screen's read: each value a project's agents act with, and where it comes from.

Two layers meet here: the team's ``hub.json`` (committed in the hub, changed through a hub pull
request) and this developer's ``hub.local.json`` (never committed), with ``git config`` as the
identity fallback (docs/design/developer-identity.md). Each value says its source, so the
screen can tell a team rule from a local one and a configured value from a built-in default.
Pure: the caller reads the files and passes a git reader.
"""

from collections.abc import Callable
from typing import Final, Literal

from agent_hub.core.hub_config.conventions import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_TITLE,
    PatternError,
    fill_pattern,
    pattern_parts,
)
from agent_hub.core.hub_config.effective_identity import (
    GitReader,
    IdentityKey,
    IdentityValues,
    Source,
    Sourced,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LOCAL_FILE, LocalConfig
from agent_hub.core.hub_config.model import Conventions, HubConfig, Repo
from agent_hub.core.hub_config.model_tiers import AGENT_NAMES
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.readmodels.view_types import ViewModel

HUB_FILE: Final = "hub.json"

type ValueSource = Literal["team", "local", "git", "derived", "default"]
type PatternSource = Literal["repo", "project", "default", "commit_title"]

# Sample values a pattern's example is rendered with.
_SAMPLE_TYPE: Final = "feat"
_SAMPLE_SCOPE: Final = "api"
_SAMPLE_SUMMARY: Final = "add the hub config view"
_SAMPLE_SLUG: Final = "hub-config"
_SAMPLE_NUMBER: Final = 42
_TIERS: Final = ("small", "medium", "large")
_GIT_KEYS: Final = {IdentityKey.AUTHOR_NAME: "user.name", IdentityKey.AUTHOR_EMAIL: "user.email"}
_SOURCES: Final[dict[Source, ValueSource]] = {
    Source.LOCAL: "local",
    Source.HUB: "team",
    Source.GIT: "git",
}


class SourcedValue(ViewModel):
    """An effective value (None when no source gives one) and where it comes from."""

    value: str | None
    source: ValueSource
    where: str
    # What hub.json says for a key this developer's layer may override; None when it says nothing.
    team_value: str | None = None


class PatternView(ViewModel):
    """An effective convention pattern, which layer sets it, and a rendered example."""

    pattern: str
    source: PatternSource
    where: str
    example: str | None


class RepoConfigView(ViewModel):
    """One repo of ``hub.json`` with its effective branch and conventions."""

    index: int
    dir: str
    github: str
    role: str
    default_branch: SourcedValue
    branch: PatternView
    commit_title: PatternView
    pr_title: PatternView
    check_fast: str | None
    check_fast_timeout: int | None
    check: str


class LayeredList(ViewModel):
    """A list the team sets and this developer adds to."""

    team: tuple[str, ...]
    local: tuple[str, ...]


class GuardConfigView(ViewModel):
    """The guard's lists: the blocked entries are layered, the rest are team only."""

    blocked_words: LayeredList
    blocked_words_files: LayeredList
    blocked_words_env: LayeredList
    deny_paths: tuple[str, ...]
    ask_before_edit: tuple[str, ...]
    deny_hosts: tuple[str, ...]
    secret_env_files: tuple[str, ...]
    readable_env_files: tuple[str, ...]
    infra_on: bool


class TrackerConfigView(ViewModel):
    """How the hub reaches its tracker."""

    kind: str
    teams: tuple[str, ...]
    transport: SourcedValue
    ready_label: str
    failed_label: str
    blocked_label: str | None
    started_state: str
    review_state: str


class AgentModelView(ViewModel):
    """A plugin agent's tier, when ``models.agents`` moves it off its template's."""

    agent: str
    tier: str


class ConfigFileView(ViewModel):
    """One of the two files: its path and, when it cannot be used, its problems."""

    name: str
    path: str
    problems: tuple[str, ...] = ()


class HubConfigView(ViewModel):
    """The whole Hub config screen of one project."""

    project: str
    hub_path: str
    hub_repo: str
    team_file: ConfigFileView
    local_file: ConfigFileView
    author_name: SourcedValue
    author_email: SourcedValue
    branch_prefix: SourcedValue
    default_branch: SourcedValue
    conventions: tuple[PatternView, PatternView, PatternView]
    repos: tuple[RepoConfigView, ...]
    tracker: TrackerConfigView
    guard: GuardConfigView
    model_tiers: dict[str, str]
    agent_models: tuple[AgentModelView, ...]
    modules: tuple[str, ...]
    platform_version: str


def hub_config_view(
    *,
    hub_path: str,
    config: HubConfig,
    local: LocalConfig | tuple[ConfigProblem, ...],
    read_git: GitReader,
) -> HubConfigView:
    """The project's config as its agents read it, each value with its source."""
    problems: tuple[str, ...] = ()
    if not isinstance(local, LocalConfig):
        problems = tuple(f"{problem.path}: {problem.message}" for problem in local)
        local = LocalConfig()
    resolved = resolve_identity(
        local=IdentityValues.of(local.project),
        hub=IdentityValues.of(config.project),
        keys=tuple(IdentityKey),
        read_git=read_git,
    ).values
    prefix = resolved[IdentityKey.BRANCH_PREFIX]
    issue = f"{config.tracker.team_keys[0]}-{_SAMPLE_NUMBER}"
    example = _Examples(prefix="" if prefix is None else prefix.value, issue=issue)
    project = config.project
    project_branch = _sourced_hub(
        project.default_branch,
        configured="default_branch" in project.model_fields_set,
        key="project.default_branch",
        default_note="main",
    )
    return HubConfigView(
        project=project.name,
        hub_path=hub_path,
        hub_repo=project.hub_repo,
        team_file=ConfigFileView(name=HUB_FILE, path=f"{hub_path}/{HUB_FILE}"),
        local_file=ConfigFileView(
            name=LOCAL_FILE, path=f"{hub_path}/{LOCAL_FILE}", problems=problems
        ),
        author_name=_identity(resolved[IdentityKey.AUTHOR_NAME], project.author_name),
        author_email=_identity(resolved[IdentityKey.AUTHOR_EMAIL], project.author_email),
        branch_prefix=_identity(prefix, project.branch_prefix),
        default_branch=project_branch,
        conventions=_patterns(project.conventions, None, example, where="project.conventions"),
        repos=tuple(
            _repo(index, repo, config=config, project_branch=project_branch, example=example)
            for index, repo in enumerate(config.repos)
        ),
        tracker=_tracker(config, local),
        guard=_guard(config, local),
        model_tiers={tier: config.models.model_for(tier) for tier in _TIERS},
        agent_models=tuple(
            AgentModelView(agent=agent, tier=tier)
            for agent in AGENT_NAMES
            if (tier := config.models.agent_tier(agent)) is not None
        ),
        modules=tuple(sorted(config.modules.model_dump(by_alias=True, exclude_none=True))),
        platform_version=config.platform.version,
    )


class _Examples:
    """Renders a pattern with sample values, the developer's own prefix and the team's key."""

    def __init__(self, *, prefix: str, issue: str) -> None:
        self._values = {
            "prefix": prefix,
            "ISSUE": issue,
            "issue_lower": issue.lower(),
            "slug": _SAMPLE_SLUG,
            "type": _SAMPLE_TYPE,
            "scope": _SAMPLE_SCOPE,
            "summary": _SAMPLE_SUMMARY,
        }

    def __call__(self, pattern: str) -> str | None:
        try:
            parts = pattern_parts(pattern)
            return fill_pattern(parts, self._values)
        except PatternError, KeyError:
            return None


def _identity(found: Sourced | None, team: str | None) -> SourcedValue:
    if found is None:
        return SourcedValue(value=None, source="default", where="not set", team_value=team)
    if found.derived:
        email = _place(IdentityKey.AUTHOR_EMAIL, found.source)
        return SourcedValue(
            value=found.value, source="derived", where=f"derived from {email}", team_value=team
        )
    where = _place(found.key, found.source)
    return SourcedValue(
        value=found.value, source=_SOURCES[found.source], where=where, team_value=team
    )


def _place(key: IdentityKey, source: Source) -> str:
    if source is Source.GIT:
        return f"git config {_GIT_KEYS[key]}"
    return f"{source.value} → project.{key.value}"


def _sourced_hub(value: str, *, configured: bool, key: str, default_note: str) -> SourcedValue:
    if configured:
        return SourcedValue(value=value, source="team", where=f"{HUB_FILE} → {key}")
    return SourcedValue(value=value, source="default", where=f"built-in default ({default_note})")


def _repo(
    index: int,
    repo: Repo,
    *,
    config: HubConfig,
    project_branch: SourcedValue,
    example: Callable[[str], str | None],
) -> RepoConfigView:
    if repo.default_branch is not None:
        branch = SourcedValue(
            value=repo.default_branch,
            source="team",
            where=f"{HUB_FILE} → repos[{index}].default_branch",
        )
    else:
        branch = project_branch
    branch_pattern, commit_title, pr_title = _patterns(
        config.project.conventions,
        repo.conventions,
        example,
        where=f"repos[{index}].conventions",
    )
    return RepoConfigView(
        index=index,
        dir=repo.dir,
        github=repo.github,
        role=repo.role,
        default_branch=branch,
        branch=branch_pattern,
        commit_title=commit_title,
        pr_title=pr_title,
        check_fast=repo.check_fast,
        check_fast_timeout=repo.check_fast_timeout,
        check=repo.check,
    )


def _patterns(
    project: Conventions | None,
    repo: Conventions | None,
    example: Callable[[str], str | None],
    *,
    where: str,
) -> tuple[PatternView, PatternView, PatternView]:
    """Branch, commit title and PR title as ``effective_conventions`` layers them."""

    def pick(key: str, default: str) -> PatternView:
        layers: tuple[tuple[Conventions | None, PatternSource, str], ...] = (
            (repo, "repo", where),
            (project, "project", "project.conventions"),
        )
        for layer, source, path in layers:
            value: str | None = None if layer is None else getattr(layer, key)
            if value is not None:
                return PatternView(
                    pattern=value,
                    source=source,
                    where=f"{HUB_FILE} → {path}.{key}",
                    example=example(value),
                )
        return PatternView(
            pattern=default, source="default", where="built-in default", example=example(default)
        )

    branch = pick("branch", DEFAULT_BRANCH)
    commit = pick("commit_title", DEFAULT_COMMIT_TITLE)
    pr = pick("pr_title", commit.pattern)
    if pr.source == "default":
        pr = PatternView(
            pattern=commit.pattern,
            source="commit_title",
            where="follows the commit title",
            example=commit.example,
        )
    return branch, commit, pr


def _tracker(config: HubConfig, local: LocalConfig) -> TrackerConfigView:
    tracker = config.tracker
    if local.tracker.transport is not None:
        transport = SourcedValue(
            value=local.tracker.transport,
            source="local",
            where=f"{LOCAL_FILE} → tracker.transport",
            team_value=tracker.transport,
        )
    else:
        transport = _sourced_hub(
            tracker.transport,
            configured="transport" in tracker.model_fields_set,
            key="tracker.transport",
            default_note="api",
        )
    return TrackerConfigView(
        kind=tracker.kind,
        teams=tracker.team_keys,
        transport=transport,
        ready_label=tracker.ready_label,
        failed_label=tracker.failed_label,
        blocked_label=tracker.blocked_label,
        started_state=tracker.states.started,
        review_state=tracker.states.review,
    )


def _guard(config: HubConfig, local: LocalConfig) -> GuardConfigView:
    guard, mine = config.guard, local.guard
    return GuardConfigView(
        blocked_words=LayeredList(team=guard.blocked_words, local=mine.blocked_words),
        blocked_words_files=LayeredList(
            team=guard.blocked_words_files, local=mine.blocked_words_files
        ),
        blocked_words_env=LayeredList(team=guard.blocked_words_env, local=mine.blocked_words_env),
        deny_paths=guard.deny_paths,
        ask_before_edit=guard.ask_before_edit,
        deny_hosts=guard.deny_hosts,
        secret_env_files=guard.secret_env_files,
        readable_env_files=guard.readable_env_files,
        infra_on=guard.infra is not None,
    )
