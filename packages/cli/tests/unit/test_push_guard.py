import pytest

from agent_hub.cli.push_guard import names_github_repo, parse_scoped_list, risky_keys

LISTED = (
    "system\0filter.lfs.clean\ngit-lfs clean -- %f\0"
    "local\0core.bare\nfalse\0"
    "local\0remote.origin.url\nhttps://github.com/acme/demo-api.git\0"
    "worktree\0core.hookspath\n.husky\0"
    "local\0flag\0"
)


def test_reads_scope_and_key_when_config_listed() -> None:
    assert parse_scoped_list(LISTED) == [
        ("system", "filter.lfs.clean"),
        ("local", "core.bare"),
        ("local", "remote.origin.url"),
        ("worktree", "core.hookspath"),
        ("local", "flag"),
    ]


@pytest.mark.parametrize(
    "key",
    [
        "credential.helper",
        "credential.https://github.com.username",
        "core.sshCommand",
        "core.askPass",
        "core.gitProxy",
        "core.fsmonitor",
        "url.git@x:.insteadOf",
        "url.git@x:.pushInsteadOf",
        "include.path",
        "includeIf.gitdir:/x.path",
        "http.extraHeader",
        "gpg.program",
        "push.gpgSign",
        "filter.x.clean",
        "protocol.allow",
        "remote.origin.pushurl",
        "remote.origin.receivepack",
        "remote.origin.vcs",
        "remote.origin.proxy",
        "remote.origin.gh-resolved",
        "remote.upstream.url",
    ],
)
def test_flags_key_when_push_would_use_it(key: str) -> None:
    assert risky_keys([("local", key), ("local", "core.bare")]) == [key]
    assert risky_keys([("worktree", key)]) == [key]


@pytest.mark.parametrize("scope", ["global", "system", "command"])
def test_ignores_key_when_scope_outside_repo(scope: str) -> None:
    assert risky_keys([(scope, "credential.helper"), (scope, "filter.lfs.clean")]) == []


def test_flags_nothing_when_keys_benign() -> None:
    benign = [
        ("local", "core.hooksPath"),
        ("local", "submodule.x.url"),
        ("local", "remote.origin.url"),
        ("local", "remote.origin.fetch"),
        ("local", "branch.jdoe/dem-1.remote"),
        ("local", "url.x.other"),
    ]

    assert risky_keys(benign) == []


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo-api.git",
        "https://github.com/acme/demo-api",
        "https://GitHub.com/Acme/Demo-API.git",
        "git@github.com:acme/demo-api.git",
        "ssh://git@github.com/acme/demo-api",
    ],
)
def test_accepts_url_when_it_names_the_repo(url: str) -> None:
    assert names_github_repo([url], github="acme/demo-api")


@pytest.mark.parametrize(
    "urls",
    [
        [],
        ["https://github.com/acme/other.git"],
        ["https://github.com/acme/demo-api.git", "https://github.com/acme/demo-api.git"],
        ["https://example.com/acme/demo-api.git"],
        ["https://github.com.evil/acme/demo-api.git"],
        ["/srv/origins/demo-api.git"],
        ["https://github.com/acme/demo-api/extra"],
    ],
    ids=["none", "other", "two", "host", "lookalike", "path", "deeper"],
)
def test_refuses_url_when_it_names_another_repo(urls: list[str]) -> None:
    assert not names_github_repo(urls, github="acme/demo-api")
