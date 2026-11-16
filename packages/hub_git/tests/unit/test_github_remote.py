import pytest

from agent_hub.hub_git.github_remote import (
    UnexpectedOutputError,
    github_repo,
    open_pull_request_url,
    pull_request_url,
)


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo-hub.git",
        "https://github.com/acme/demo-hub",
        "https://github.com/acme/demo-hub/",
        "git@github.com:acme/demo-hub.git",
        "ssh://git@github.com/acme/demo-hub.git",
        "git@github.com-acme:acme/demo-hub.git",
        "ssh://git@github.com-work-account/acme/demo-hub.git",
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
        "git@github.com.evil.example:acme/demo-hub.git",
        "https://github.com-acme/acme/demo-hub.git",
        "git@github.com-x.evil.example:acme/demo-hub.git",
        "https://user:secret@github.com/acme/demo-hub.git",
        "https://github.com/acme",
        "",
    ],
)
def test_names_no_repo_when_url_not_github(url: str) -> None:
    assert github_repo(url) is None


def test_finds_pull_request_when_created_object_names_hub_repo() -> None:
    stdout = (
        b'{"url": "https://api.github.com/repos/acme/demo-hub/pulls/12",'
        b' "html_url": "https://github.com/acme/demo-hub/pull/12", "number": 12}\n'
    )

    assert pull_request_url(stdout, hub_repo="Acme/Demo-Hub") == (
        "https://github.com/acme/demo-hub/pull/12"
    )


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"https://github.com/acme/demo-hub/pull/12\n", id="text_not_json"),
        pytest.param(b'[{"html_url": "https://github.com/acme/demo-hub/pull/12"}]', id="list"),
        pytest.param(b'{"url": "https://github.com/acme/demo-hub/pull/12"}', id="no_html_url"),
        pytest.param(b'{"html_url": "https://github.com/other/repo/pull/12"}', id="other_repo"),
        pytest.param(b'{"html_url": "https://github.com/acme/demo-hub/pull/12/files"}', id="files"),
        pytest.param(b'{"html_url": "https://github.com/acme/demo-hub/issues/12"}', id="issue"),
        pytest.param(b'{"html_url": 12}', id="url_not_text"),
        pytest.param(b"\xff\xfe", id="not_utf8"),
    ],
)
def test_finds_no_pull_request_when_output_unexpected(stdout: bytes) -> None:
    assert pull_request_url(stdout, hub_repo="acme/demo-hub") is None


@pytest.mark.parametrize(
    ("stdout", "found"),
    [
        pytest.param(b"[]\n", None, id="none"),
        pytest.param(
            b'[{"url": "https://api.github.com/repos/Acme/Demo-Hub/pulls/7",'
            b' "html_url": "https://github.com/Acme/Demo-Hub/pull/7"}]\n',
            "https://github.com/Acme/Demo-Hub/pull/7",
            id="one",
        ),
    ],
)
def test_reads_open_pull_request_when_list_well_formed(stdout: bytes, found: str | None) -> None:
    assert open_pull_request_url(stdout, hub_repo="acme/demo-hub") == found


@pytest.mark.parametrize(
    "stdout",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"not json", id="not_json"),
        pytest.param(b'{"html_url": "https://github.com/acme/demo-hub/pull/1"}', id="not_list"),
        pytest.param(b'[{"href": "https://github.com/acme/demo-hub/pull/1"}]', id="no_url"),
        pytest.param(b'[{"url": "https://github.com/acme/demo-hub/pull/1"}]', id="api_url_only"),
        pytest.param(b'[{"html_url": 1}]', id="url_not_text"),
        pytest.param(b'[{"html_url": "https://github.com/other/hub/pull/1"}]', id="other_repo"),
        pytest.param(b'[{"html_url": "https://github.com/acme/demo-hub/pull/1 x"}]', id="trailing"),
        pytest.param(
            b'[{"html_url": "https://evil.example/acme/demo-hub/pull/1"}]', id="other_host"
        ),
        pytest.param(b"[1]", id="item_not_object"),
        pytest.param(b"\xff", id="not_utf8"),
    ],
)
def test_refuses_open_pull_request_list_when_output_unexpected(stdout: bytes) -> None:
    with pytest.raises(UnexpectedOutputError):
        open_pull_request_url(stdout, hub_repo="acme/demo-hub")
