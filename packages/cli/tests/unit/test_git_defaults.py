from pathlib import Path

import pytest

from agent_hub.cli.git_defaults import hub_repo_from_remote, read_git_defaults


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:acme/demo-hub.git",
        "ssh://git@github.com/acme/demo-hub",
        "https://github.com/acme/demo-hub.git",
        "https://x-access-token:SECRET123@github.com/acme/demo-hub",
        "https://github.com/acme/demo-hub",
        "git@github.com:acme/demo-hub",
        "ssh://git@github.com/acme/demo-hub.git",
    ],
)
def test_parses_owner_and_name_when_github_url_given(url: str) -> None:
    assert hub_repo_from_remote(url) == "acme/demo-hub"


def test_keeps_dotted_name_when_url_has_no_git_suffix() -> None:
    assert hub_repo_from_remote("https://github.com/acme/demo.hub") == "acme/demo.hub"


@pytest.mark.parametrize(
    "url",
    [
        # Host: exactly github.com, in every form.
        "https://gitlab.com/acme/demo-hub.git",
        "https://github.com.evil.io/acme/demo-hub",
        "git@github.com.evil.io:acme/demo-hub.git",
        "ssh://git@github.com.evil.io/acme/demo-hub",
        "https://evilgithub.com/acme/demo-hub",
        # Scheme: https only for the URL form, ssh only with ssh://.
        "http://github.com/acme/demo-hub",
        "git://github.com/acme/demo-hub",
        "ftp://github.com/acme/demo-hub",
        # The ssh and scp forms take the user git only.
        "ssh://evil@github.com/acme/demo-hub",
        "evil@github.com:acme/demo-hub",
        # Userinfo: RFC 3986 characters only, so the host cannot hide after a fragment or query.
        "https://evil.io#@github.com/acme/demo-hub",
        "https://evil.io?@github.com/acme/demo-hub",
        "https://evil.io/@github.com/acme/demo-hub",
        "https://a@b@github.com/acme/demo-hub",
        # A port changes the host part.
        "ssh://git@github.com:22/acme/demo-hub",
        # owner/name shape.
        "https://github.com/acme",
        "https://github.com/acme/demo-hub/extra",
        "https://github.com/acme/demo-hub/",
        "https://github.com/acme/.git",
        "https://github.com/-acme/demo-hub",
        "https://github.com/acme/demo hub",
        "git@github.com:",
        "https://github.com/",
        # Anchored at both ends.
        " https://github.com/acme/demo-hub",
        "xhttps://github.com/acme/demo-hub",
        "https://github.com/acme/demo-hub\n",
        "",
    ],
)
def test_returns_none_when_url_not_github(url: str) -> None:
    assert hub_repo_from_remote(url) is None


@pytest.mark.parametrize(
    "url",
    [
        "https://x-access-token:SECRET123@github.com/acme/demo-hub",
        "https://SECRET123@github.com/acme/demo-hub.git",
        "https://user:SECRET123@gitlab.com/acme/demo-hub.git",
        "https://user:SECRET123@github.com/acme",
    ],
)
def test_drops_credentials_when_url_has_userinfo(url: str) -> None:
    result = hub_repo_from_remote(url)

    assert "SECRET123" not in repr(result)
    assert result in {"acme/demo-hub", None}


def test_raises_when_key_not_a_git_default(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="branch_prefix"):
        read_git_defaults(missing=frozenset({"branch_prefix"}), target=tmp_path)
