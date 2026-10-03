"""The developer's effective identity: ``hub.local.json``, else ``hub.json``, else git config.

Per key, the first source that sets it wins. ``branch_prefix`` has no git key: when no file sets
it, it is derived from the effective ``author_email`` (its local part plus ``/``), and an email
whose local part is not a valid prefix gives none. Git is reached only through a ``GitReader``
the caller supplies, called at most once and only for the keys no file sets, so core runs no
subprocess (docs/design/developer-identity.md).
"""

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Final, NamedTuple

from pydantic import TypeAdapter, ValidationError

from agent_hub.core.hub_config.local_config import LocalConfig, LocalProject
from agent_hub.core.hub_config.model import (
    BranchPrefix,
    EmailAddress,
    FreeString,
    HubConfig,
    Project,
)


class IdentityKey(StrEnum):
    """An identity key of ``project``, in ``hub.json`` and ``hub.local.json`` alike."""

    BRANCH_PREFIX = "branch_prefix"
    AUTHOR_NAME = "author_name"
    AUTHOR_EMAIL = "author_email"


class Source(StrEnum):
    """Where an effective identity value comes from."""

    LOCAL = "hub.local.json"
    HUB = "hub.json"
    GIT = "git config"


# Takes the git keys wanted (``author_name``, ``author_email``) and gives the raw values git holds.
type GitReader = Callable[[frozenset[str]], Mapping[str, str]]

DERIVED: Final = "derived"
_GIT_CONFIG_KEYS: Final = {
    IdentityKey.AUTHOR_NAME: "user.name",
    IdentityKey.AUTHOR_EMAIL: "user.email",
}
_GIT_SHAPES: Final[Mapping[IdentityKey, TypeAdapter[str]]] = {
    IdentityKey.AUTHOR_NAME: TypeAdapter(FreeString),
    IdentityKey.AUTHOR_EMAIL: TypeAdapter(EmailAddress),
}
_BRANCH_PREFIX: TypeAdapter[str] = TypeAdapter(BranchPrefix)
_NO_PREFIX_LINES: Final = (
    "no branch prefix for this developer; set one of:",
    "  hub.local.json → project.branch_prefix",
    "  hub.json → project.branch_prefix",
    "  git config user.email in the hub (its local part plus /)",
)


@dataclass(frozen=True, slots=True)
class Sourced:
    """An effective value of ``key`` and its source; a derived prefix keeps its email's source."""

    value: str
    source: Source
    key: IdentityKey
    derived: bool = False

    @property
    def prefix_source(self) -> str:
        """``hub.local.json``, ``hub.json`` or ``derived``."""
        return DERIVED if self.derived else self.source.value

    def describe(self) -> str:
        """Where the value comes from, e.g. ``git config user.email``."""
        if self.derived:
            return f"derived from {_place(IdentityKey.AUTHOR_EMAIL, self.source)}"
        return _place(self.key, self.source)


class IdentityValues(NamedTuple):
    """The identity keys one file sets; ``None`` for each key it leaves out."""

    branch_prefix: str | None
    author_name: str | None
    author_email: str | None

    @classmethod
    def of(cls, project: Project | LocalProject) -> IdentityValues:
        """The identity keys of ``hub.json``'s or ``hub.local.json``'s ``project``."""
        return cls(
            branch_prefix=project.branch_prefix,
            author_name=project.author_name,
            author_email=project.author_email,
        )

    def get(self, key: IdentityKey) -> str | None:
        """The value of ``key`` in this file."""
        value: str | None = getattr(self, key.value)
        return value


class ResolvedIdentity(NamedTuple):
    """The requested keys' effective values, and what git gave that had the wrong shape.

    ``email`` is the effective ``author_email`` whenever it was resolved, requested or needed
    for the prefix, so a caller can say why no prefix was derived. ``rejected`` holds the git
    keys whose value is not a valid ``author_name`` or ``author_email`` (never quoted).
    """

    values: Mapping[IdentityKey, Sourced | None]
    email: Sourced | None
    rejected: frozenset[IdentityKey]


def resolve_identity(
    *,
    local: IdentityValues,
    hub: IdentityValues,
    keys: Iterable[IdentityKey],
    read_git: GitReader,
) -> ResolvedIdentity:
    """Each requested key's effective value, or ``None`` when no source gives a valid one.

    ``read_git`` is called at most once, with exactly the git keys that the requested keys need
    and no file sets; the prefix needs the email only when no file sets the prefix.
    """
    wanted = frozenset(keys)
    from_files = {key: _from_files(key, local=local, hub=hub) for key in IdentityKey}
    needed = set(wanted - {IdentityKey.BRANCH_PREFIX})
    if IdentityKey.BRANCH_PREFIX in wanted and from_files[IdentityKey.BRANCH_PREFIX] is None:
        needed.add(IdentityKey.AUTHOR_EMAIL)
    from_git, rejected = _read_git(
        frozenset(key for key in needed if from_files[key] is None), read_git=read_git
    )
    effective = {key: from_files[key] or from_git.get(key) for key in IdentityKey}
    if effective[IdentityKey.BRANCH_PREFIX] is None:
        effective[IdentityKey.BRANCH_PREFIX] = _derived(effective[IdentityKey.AUTHOR_EMAIL])
    return ResolvedIdentity(
        values={key: effective[key] for key in IdentityKey if key in wanted},
        email=effective[IdentityKey.AUTHOR_EMAIL]
        if IdentityKey.AUTHOR_EMAIL in needed | wanted
        else None,
        rejected=rejected,
    )


def resolve_branch_prefix(
    *, local: IdentityValues, hub: IdentityValues, read_git: GitReader
) -> Sourced | None:
    """The effective branch prefix, or ``None`` when no source gives one."""
    resolved = resolve_identity(
        local=local, hub=hub, keys=(IdentityKey.BRANCH_PREFIX,), read_git=read_git
    )
    return resolved.values[IdentityKey.BRANCH_PREFIX]


def derived_prefix(email: str) -> str | None:
    """The local part of ``email`` plus ``/``, or ``None`` when that is not a valid prefix.

    Never normalized: an email whose local part fails ``BranchPrefix`` gives no prefix.
    """
    try:
        return _BRANCH_PREFIX.validate_python(f"{_local_part(email)}/")
    except ValidationError:
        return None


def effective_config(config: HubConfig, local: LocalConfig) -> HubConfig:
    """``config`` with each value ``hub.local.json`` sets in place of ``hub.json``'s."""
    project = local.project.model_dump(exclude_none=True, by_alias=False)
    tracker = local.tracker.model_dump(exclude_none=True, by_alias=False)
    if not project and not tracker:
        return config
    return config.model_copy(
        update={
            "project": config.project.model_copy(update=project),
            "tracker": config.tracker.model_copy(update=tracker),
        }
    )


def no_prefix_lines(
    *, email: Sourced | None, git_problem: str | None, is_email_rejected: bool = False
) -> list[str]:
    """Why there is no branch prefix: the three sources, then what the email or git gave.

    ``is_email_rejected``: git holds a ``user.email`` that is not an email address; its value is
    not repeated.
    """
    lines = list(_NO_PREFIX_LINES)
    if email is not None:
        giver = (
            "git's user.email"
            if email.source is Source.GIT
            else f"{email.source.value}'s project.author_email"
        )
        lines.append(f'  {giver} gives "{_local_part(email.value)}", not a valid prefix')
    if is_email_rejected:
        lines.append("  git's user.email is not an email address")
    if git_problem is not None:
        lines.append(f"  git: {git_problem}")
    return lines


def _from_files(key: IdentityKey, *, local: IdentityValues, hub: IdentityValues) -> Sourced | None:
    for values, source in ((local, Source.LOCAL), (hub, Source.HUB)):
        value = values.get(key)
        if value is not None:
            return Sourced(value, source, key)
    return None


def _read_git(
    keys: frozenset[IdentityKey], *, read_git: GitReader
) -> tuple[dict[IdentityKey, Sourced], frozenset[IdentityKey]]:
    """The git values of ``keys`` that have their key's shape, and the keys whose value has not.

    Git is not run for no keys.
    """
    if not keys:
        return {}, frozenset()
    raw = read_git(frozenset(key.value for key in keys))
    values: dict[IdentityKey, Sourced] = {}
    rejected: set[IdentityKey] = set()
    for key in keys:
        value = raw.get(key.value)
        if value is None:
            continue
        try:
            values[key] = Sourced(_GIT_SHAPES[key].validate_python(value), Source.GIT, key)
        except ValidationError:
            # The error would quote git's value: only the key is kept.
            rejected.add(key)
    return values, frozenset(rejected)


def _derived(email: Sourced | None) -> Sourced | None:
    if email is None:
        return None
    prefix = derived_prefix(email.value)
    if prefix is None:
        return None
    return Sourced(prefix, email.source, IdentityKey.BRANCH_PREFIX, derived=True)


def _place(key: IdentityKey, source: Source) -> str:
    if source is Source.GIT:
        return f"git config {_GIT_CONFIG_KEYS[key]}"
    return f"{key.value} in {source.value}"


def _local_part(email: str) -> str:
    return email.rpartition("@")[0]
