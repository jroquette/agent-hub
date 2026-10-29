import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HubLock
from agent_hub.core.hub_files.release_commit import (
    commit_from_ls_remote,
    kept_release,
    needs_lookup,
)
from agent_hub.core.testing.builders import a_hub_document

# The builder's pin, and the default repository as docs/design/project-config.md names it.
PIN = "0.2.0"
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
FORK = "git+https://github.com/acme/agent-hub"
TAG_OBJECT = "1111111111111111111111111111111111111111"
PEELED = "2222222222222222222222222222222222222222"
LIGHTWEIGHT = "3333333333333333333333333333333333333333"
UPPERCASE = "0123456789ABCDEF0123456789ABCDEF01234567"
LOCKED = "0123456789abcdef0123456789abcdef01234567"


def a_config(repository: str | None = None) -> HubConfig:
    document = a_hub_document()
    if repository is not None:
        document["platform"]["repository"] = repository
    config = HubConfig.model_validate(document)
    assert config.platform.version == PIN
    return config


def a_lock(
    *, version: str = PIN, commit: str | None = None, repository: str | None = None
) -> HubLock:
    value: dict[str, object] = {
        "lock_version": 1,
        "platform_version": version,
        "schema_version": 1,
        "modules": [],
        "files": {"hub.json": {"ownership": "seeded"}},
    }
    if commit is not None:
        value |= {"platform_commit": commit, "platform_repository": repository}
    return HubLock.model_validate(value)


@pytest.mark.parametrize(
    "output",
    [
        f"{TAG_OBJECT}\trefs/tags/v0.2.0\n{PEELED}\trefs/tags/v0.2.0^{{}}\n",
        f"{PEELED}\trefs/tags/v0.2.0^{{}}\n{TAG_OBJECT}\trefs/tags/v0.2.0\n",
        f"{TAG_OBJECT}\trefs/tags/v0.2.0\n{PEELED}\trefs/tags/v0.2.0^{{}}",
    ],
    ids=["tag-first", "peeled-first", "no-final-newline"],
)
def test_returns_peeled_commit_when_tag_is_annotated(output: str) -> None:
    assert commit_from_ls_remote(output, PIN) == PEELED


def test_returns_tag_commit_when_tag_is_lightweight() -> None:
    assert commit_from_ls_remote(f"{LIGHTWEIGHT}\trefs/tags/v0.2.0\n", PIN) == LIGHTWEIGHT


@pytest.mark.parametrize(
    "output",
    [
        "",
        f"{LIGHTWEIGHT}\trefs/tags/v0.2.10\n",
        f"{LIGHTWEIGHT}\trefs/tags/v0.2.0rc1\n",
        f"{LIGHTWEIGHT}\trefs/tags/v0x2x0\n",
        f"{LIGHTWEIGHT}\trefs/heads/v0.2.0\n",
        f"{LIGHTWEIGHT[:-1]}\trefs/tags/v0.2.0\n",
        f"{UPPERCASE}\trefs/tags/v0.2.0\n",
        f"{LIGHTWEIGHT} refs/tags/v0.2.0\n",
        f"{LIGHTWEIGHT}\trefs/tags/v0.2.0 extra\n",
    ],
    ids=[
        "empty",
        "longer-version",
        "suffixed-version",
        "dots-as-any-character",
        "branch",
        "short-hash",
        "uppercase-hash",
        "space-not-tab",
        "trailing-text",
    ],
)
def test_finds_no_commit_when_output_has_no_tag_line(output: str) -> None:
    assert commit_from_ls_remote(output, PIN) is None


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        (f"{TAG_OBJECT[25:]}\trefs/tags/v0.2.0\n{PEELED}\trefs/tags/v0.2.0^{{}}\n", PEELED),
        (f"s/v0.2.0\n{LIGHTWEIGHT}\trefs/tags/v0.2.0\n", LIGHTWEIGHT),
        (f"{PEELED[30:]}\trefs/tags/v0.2.0^{{}}\n", None),
    ],
    ids=["cut-in-hash", "cut-in-ref", "only-the-cut-line"],
)
def test_ignores_partial_first_line_when_output_is_cut_at_the_cap(
    output: str, expected: str | None
) -> None:
    # run_child keeps the last bytes of a long output, so its first line may be cut anywhere.
    assert commit_from_ls_remote(output, PIN) == expected


@pytest.mark.parametrize(
    ("written", "repository"),
    [(FORK, FORK), (None, DEFAULT_REPOSITORY)],
    ids=["repository-written", "repository-default"],
)
def test_keeps_commit_when_lock_matches_version_and_repository(
    written: str | None, repository: str
) -> None:
    lock = a_lock(commit=LOCKED, repository=repository)

    kept = kept_release(lock, a_config(written))

    assert kept is not None
    assert (kept.commit, kept.repository) == (LOCKED, repository)


@pytest.mark.parametrize(
    ("written", "in_use", "locked_repository"),
    [(FORK, FORK, DEFAULT_REPOSITORY), (None, DEFAULT_REPOSITORY, FORK)],
    ids=["fork-in-config", "fork-in-lock"],
)
def test_drops_commit_when_repository_differs(
    *, written: str | None, in_use: str, locked_repository: str
) -> None:
    config = a_config(written)
    # The commit under the config's own version and repository is kept: only the change drops it.
    assert kept_release(a_lock(commit=LOCKED, repository=in_use), config) is not None

    lock = a_lock(commit=LOCKED, repository=locked_repository)

    assert kept_release(lock, config) is None


def test_drops_commit_when_version_differs() -> None:
    config = a_config()
    # The commit under the config's own version and repository is kept: only the change drops it.
    assert kept_release(a_lock(commit=LOCKED, repository=DEFAULT_REPOSITORY), config) is not None

    lock = a_lock(version="0.1.9", commit=LOCKED, repository=DEFAULT_REPOSITORY)

    assert kept_release(lock, config) is None


@pytest.mark.parametrize(
    "header",
    [
        {"version": "0.1.9"},
        {"version": "0.1.9", "commit": LOCKED, "repository": DEFAULT_REPOSITORY},
        {"version": "1.0.0", "commit": LOCKED, "repository": DEFAULT_REPOSITORY},
    ],
    ids=["older-lock-without-commit", "older-lock-with-commit", "newer-lock"],
)
def test_asks_for_lookup_when_lock_version_differs_from_pin(header: dict[str, str]) -> None:
    assert needs_lookup(a_lock(**header), a_config()) is True


def test_asks_for_lookup_when_lock_repository_differs_from_pin() -> None:
    assert needs_lookup(a_lock(commit=LOCKED, repository=FORK), a_config()) is True


def test_asks_for_no_lookup_when_lock_without_commit_matches_pin() -> None:
    assert needs_lookup(a_lock(), a_config()) is False


def test_asks_for_no_lookup_when_lock_commit_matches_pin() -> None:
    lock = a_lock(commit=LOCKED, repository=DEFAULT_REPOSITORY)

    assert needs_lookup(lock, a_config()) is False
