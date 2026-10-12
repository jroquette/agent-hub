import pytest

from agent_hub.hub_git.github_remote import github_repo, pull_request_url


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo-hub.git",
        "https://github.com/acme/demo-hub",
        "https://github.com/acme/demo-hub/",
        "git@github.com:acme/demo-hub.git",
        "ssh://git@github.com/acme/demo-hub.git",
        "  https://GitHub.com/acme/demo-hub.git\n",
    ],
)
def test_names_repo_when_url_is_github(url: str) -> None:
    assert github_repo(url) == "acme/demo-hub"


@pytest.mark.parametrize(
    "url",
    [
        "https://gitlab.com/acme/demo-hub.git",
        "/srv/git/demo-hub.git",
        "https://github.com.evil.example/acme/demo-hub.git",
        "https://user:secret@github.com/acme/demo-hub.git",
        "https://github.com/acme",
        "",
    ],
)
def test_names_no_repo_when_url_not_github(url: str) -> None:
    assert github_repo(url) is None


def test_finds_pull_request_when_last_line_names_hub_repo() -> None:
    stdout = b"Creating pull request\nhttps://github.com/acme/demo-hub/pull/12\n"

    assert pull_request_url(stdout, hub_repo="Acme/Demo-Hub") == (
        "https://github.com/acme/demo-hub/pull/12"
    )


@pytest.mark.parametrize(
    "stdout",
    [
        b"",
        b"https://github.com/other/repo/pull/12\n",
        b"https://github.com/acme/demo-hub/pull/12/files\n",
        b"https://github.com/acme/demo-hub/issues/12\n",
        b"\xff\xfe",
    ],
)
def test_finds_no_pull_request_when_output_unexpected(stdout: bytes) -> None:
    assert pull_request_url(stdout, hub_repo="acme/demo-hub") is None
