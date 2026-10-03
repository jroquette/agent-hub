from collections.abc import Mapping

import pytest

from agent_hub.core.hub_config.effective_identity import (
    IdentityKey,
    IdentityValues,
    Source,
    Sourced,
    derived_prefix,
    effective_config,
    no_prefix_lines,
    resolve_branch_prefix,
    resolve_identity,
)
from agent_hub.core.hub_config.local_config import LocalConfig, LocalProject, LocalTracker
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

ALL_KEYS = frozenset(IdentityKey)
NONE = IdentityValues(branch_prefix=None, author_name=None, author_email=None)
LOCAL = IdentityValues(branch_prefix="me/", author_name="Jane Roe", author_email="me@example.com")
HUB = IdentityValues(branch_prefix="jdoe/", author_name="Jane Doe", author_email="jdoe@example.com")
NO_PREFIX_LINES = [
    "no branch prefix for this developer; set one of:",
    "  hub.local.json → project.branch_prefix",
    "  hub.json → project.branch_prefix",
    "  git config user.email in the hub (its local part plus /)",
]


class RecordingGit:
    """A fake git: answers from ``values`` and records each set of keys it is asked."""

    def __init__(self, **values: str) -> None:
        self.values = values
        self.asked: list[frozenset[str]] = []

    def __call__(self, keys: frozenset[str]) -> Mapping[str, str]:
        self.asked.append(keys)
        return {key: value for key, value in self.values.items() if key in keys}


def only(key: IdentityKey, values: IdentityValues) -> IdentityValues:
    return NONE._replace(**{key.value: getattr(values, key.value)})


def a_hub_config() -> HubConfig:
    return HubConfig.model_validate(a_hub_document())


@pytest.mark.parametrize("key", list(IdentityKey), ids=[key.value for key in IdentityKey])
def test_takes_local_value_when_local_sets_key(key: IdentityKey) -> None:
    git = RecordingGit(author_name="Git Name", author_email="git@example.com")

    resolved = resolve_identity(local=only(key, LOCAL), hub=HUB, keys={key}, read_git=git)

    assert resolved.values == {key: Sourced(getattr(LOCAL, key.value), Source.LOCAL, key)}
    assert git.asked == []


@pytest.mark.parametrize("key", list(IdentityKey), ids=[key.value for key in IdentityKey])
def test_takes_hub_value_when_only_hub_sets_key(key: IdentityKey) -> None:
    git = RecordingGit(author_name="Git Name", author_email="git@example.com")

    resolved = resolve_identity(local=NONE, hub=only(key, HUB), keys={key}, read_git=git)

    assert resolved.values == {key: Sourced(getattr(HUB, key.value), Source.HUB, key)}
    assert git.asked == []


def test_reads_git_once_when_no_file_sets_name_or_email() -> None:
    git = RecordingGit(author_name="Jane Doe", author_email="jane.doe@example.com")

    resolved = resolve_identity(local=NONE, hub=NONE, keys=ALL_KEYS, read_git=git)

    assert git.asked == [frozenset({"author_name", "author_email"})]
    assert resolved.values[IdentityKey.AUTHOR_NAME] == Sourced(
        "Jane Doe", Source.GIT, IdentityKey.AUTHOR_NAME
    )
    assert resolved.values[IdentityKey.AUTHOR_EMAIL] == Sourced(
        "jane.doe@example.com", Source.GIT, IdentityKey.AUTHOR_EMAIL
    )


@pytest.mark.parametrize(
    ("local", "git_email", "expected", "described", "asked"),
    [
        (
            NONE,
            "jane.doe@example.com",
            Sourced("jane.doe/", Source.GIT, IdentityKey.BRANCH_PREFIX, derived=True),
            "derived from git config user.email",
            [frozenset({"author_email"})],
        ),
        (
            NONE._replace(author_email="me@example.com"),
            "x@example.com",
            Sourced("me/", Source.LOCAL, IdentityKey.BRANCH_PREFIX, derived=True),
            "derived from author_email in hub.local.json",
            [],
        ),
    ],
    ids=["git-email", "local-email"],
)
def test_derives_prefix_from_effective_email_when_no_file_sets_prefix(
    *,
    local: IdentityValues,
    git_email: str,
    expected: Sourced,
    described: str,
    asked: list[frozenset[str]],
) -> None:
    git = RecordingGit(author_email=git_email)

    prefix = resolve_branch_prefix(local=local, hub=NONE, read_git=git)

    assert prefix == expected
    assert prefix.prefix_source == "derived"
    assert prefix.describe() == described
    assert git.asked == asked


@pytest.mark.parametrize(
    ("email", "is_email_address"),
    [("j+x@example.com", True), (".a@example.com", True), ("jé@example.com", False)],
    ids=["plus", "leading-dot", "non-ascii"],
)
def test_gives_no_prefix_when_derived_prefix_invalid(*, email: str, is_email_address: bool) -> None:
    git = RecordingGit(author_email=email)

    resolved = resolve_identity(
        local=NONE, hub=NONE, keys={IdentityKey.BRANCH_PREFIX}, read_git=git
    )

    assert resolved.values == {IdentityKey.BRANCH_PREFIX: None}
    if is_email_address:
        assert resolved.email == Sourced(email, Source.GIT, IdentityKey.AUTHOR_EMAIL)
        assert resolved.rejected == frozenset()
    else:
        assert resolved.email is None
        assert resolved.rejected == {IdentityKey.AUTHOR_EMAIL}
    assert resolve_branch_prefix(local=NONE, hub=NONE, read_git=git) is None
    assert derived_prefix(email) is None


@pytest.mark.parametrize(
    ("local", "hub", "keys"),
    [
        (NONE._replace(branch_prefix="me/"), NONE, {IdentityKey.BRANCH_PREFIX}),
        (NONE, NONE._replace(branch_prefix="jdoe/"), {IdentityKey.BRANCH_PREFIX}),
        (NONE, HUB, ALL_KEYS),
        (LOCAL, NONE, ALL_KEYS),
        (
            NONE._replace(branch_prefix="me/"),
            HUB._replace(branch_prefix=None),
            ALL_KEYS,
        ),
    ],
    ids=["local-prefix", "hub-prefix", "hub-all", "local-all", "mixed-all"],
)
def test_reads_no_git_when_files_set_requested_keys(
    local: IdentityValues, hub: IdentityValues, keys: frozenset[IdentityKey]
) -> None:
    git = RecordingGit(author_name="Git Name", author_email="git@example.com")

    resolved = resolve_identity(local=local, hub=hub, keys=keys, read_git=git)

    assert git.asked == []
    assert all(resolved.values[key] is not None for key in keys)


def test_asks_git_only_for_missing_keys_when_some_set() -> None:
    git = RecordingGit(author_name="Git Name", author_email="jane@example.com")
    hub = NONE._replace(author_name="Jane Doe")

    resolved = resolve_identity(local=NONE, hub=hub, keys=ALL_KEYS, read_git=git)

    assert git.asked == [frozenset({"author_email"})]
    assert resolved.values == {
        IdentityKey.BRANCH_PREFIX: Sourced(
            "jane/", Source.GIT, IdentityKey.BRANCH_PREFIX, derived=True
        ),
        IdentityKey.AUTHOR_NAME: Sourced("Jane Doe", Source.HUB, IdentityKey.AUTHOR_NAME),
        IdentityKey.AUTHOR_EMAIL: Sourced("jane@example.com", Source.GIT, IdentityKey.AUTHOR_EMAIL),
    }


@pytest.mark.parametrize(
    "email",
    ["not-an-email", "jane@exa_mple.com", "Jane <jane@example.com>", "jane@example.com "],
    ids=["no-at", "underscore-domain", "display-name", "trailing-space"],
)
def test_ignores_git_value_when_shape_invalid(email: str) -> None:
    git = RecordingGit(author_name="a\u0007", author_email=email)

    resolved = resolve_identity(local=NONE, hub=NONE, keys=ALL_KEYS, read_git=git)

    assert resolved.values == {key: None for key in IdentityKey}
    assert resolved.email is None
    assert resolved.rejected == {IdentityKey.AUTHOR_NAME, IdentityKey.AUTHOR_EMAIL}


def test_keeps_hub_prefix_when_local_sets_only_email() -> None:
    git = RecordingGit(author_email="git@example.com")
    local = NONE._replace(author_email="me@example.com")

    prefix = resolve_branch_prefix(local=local, hub=HUB, read_git=git)

    assert prefix == Sourced("jdoe/", Source.HUB, IdentityKey.BRANCH_PREFIX)
    assert git.asked == []


@pytest.mark.parametrize(
    ("sourced", "described"),
    [
        (
            Sourced("me/", Source.LOCAL, IdentityKey.BRANCH_PREFIX),
            "branch_prefix in hub.local.json",
        ),
        (Sourced("Jane Doe", Source.HUB, IdentityKey.AUTHOR_NAME), "author_name in hub.json"),
        (Sourced("Jane Doe", Source.GIT, IdentityKey.AUTHOR_NAME), "git config user.name"),
        (
            Sourced("jane/", Source.HUB, IdentityKey.BRANCH_PREFIX, derived=True),
            "derived from author_email in hub.json",
        ),
    ],
    ids=["local", "hub", "git", "derived-hub"],
)
def test_names_source_when_described(sourced: Sourced, described: str) -> None:
    assert sourced.describe() == described


def test_overrides_transport_and_identity_when_effective_config_built() -> None:
    config = a_hub_config()
    local = LocalConfig(
        project=LocalProject(branch_prefix="me/", author_email="me@example.com"),
        tracker=LocalTracker(transport="mcp"),
    )

    merged = effective_config(config, local)

    assert merged.project == config.project.model_copy(
        update={"branch_prefix": "me/", "author_email": "me@example.com"}
    )
    assert merged.project.author_name == config.project.author_name
    assert merged.tracker == config.tracker.model_copy(update={"transport": "mcp"})
    assert merged.repos == config.repos
    assert merged.guard == config.guard


def test_keeps_config_equal_when_local_empty() -> None:
    config = a_hub_config()

    assert effective_config(config, LocalConfig()) == config


def test_takes_file_values_when_identity_values_built() -> None:
    config = a_hub_config()
    local = LocalProject(author_email="me@example.com")

    assert IdentityValues.of(config.project) == IdentityValues(
        branch_prefix=config.project.branch_prefix,
        author_name=config.project.author_name,
        author_email=config.project.author_email,
    )
    assert IdentityValues.of(local) == NONE._replace(author_email="me@example.com")


@pytest.mark.parametrize(
    ("email", "is_email_rejected", "git_problem", "extra"),
    [
        (None, False, None, []),
        (
            Sourced("j+x@example.com", Source.GIT, IdentityKey.AUTHOR_EMAIL),
            False,
            None,
            ['  git\'s user.email gives "j+x", not a valid prefix'],
        ),
        (
            Sourced("j+x@example.com", Source.LOCAL, IdentityKey.AUTHOR_EMAIL),
            False,
            None,
            ['  hub.local.json\'s project.author_email gives "j+x", not a valid prefix'],
        ),
        (None, True, None, ["  git's user.email is not an email address"]),
        (None, False, "git timed out", ["  git: git timed out"]),
    ],
    ids=[
        "no-email",
        "git-email-invalid",
        "local-email-invalid",
        "git-email-rejected",
        "git-problem",
    ],
)
def test_names_three_sources_when_no_prefix(
    *,
    email: Sourced | None,
    is_email_rejected: bool,
    git_problem: str | None,
    extra: list[str],
) -> None:
    lines = no_prefix_lines(
        email=email, is_email_rejected=is_email_rejected, git_problem=git_problem
    )

    assert lines == [*NO_PREFIX_LINES, *extra]
