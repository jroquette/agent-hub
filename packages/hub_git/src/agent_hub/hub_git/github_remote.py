"""GitHub names in git and gh output: the ``owner/name`` an ``origin`` url points at, and the pull
request urls GitHub's REST API answers through ``gh api``: the one it created
(``POST repos/<owner>/<name>/pulls``) and the open one it lists (``GET …/pulls``).

The REST API, not ``gh pr`` (GraphQL), because a cloud session's proxy refuses GraphQL.
"""

import json
import re
from typing import Final

# An ssh host alias ``github.com-<account>`` (a ``Host`` entry of ``~/.ssh/config``, the usual
# way to keep two GitHub accounts on one machine) names GitHub too.
_SSH_HOST: Final = r"github\.com(?:-[A-Za-z0-9_]+)*"
_GITHUB_URL: Final = re.compile(
    rf"(?:https://github\.com/|ssh://git@{_SSH_HOST}/|git@{_SSH_HOST}:)"
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)
_PULL_URL: Final = re.compile(r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/pull/\d+")
# A pull request's page; its ``url`` is the API's.
HTML_URL: Final = "html_url"


class UnexpectedOutputError(ValueError):
    """gh printed something other than what was asked for."""


def github_repo(url: str) -> str | None:
    """The ``owner/name`` of a GitHub url (https or ssh, ``.git`` optional, ssh through a
    ``github.com-<account>`` host alias too), or None for any other url (another host, a local
    path, a url carrying credentials)."""
    found = _GITHUB_URL.fullmatch(url.strip())
    return None if found is None else found.group("repo")


def pull_request_url(stdout: bytes, *, hub_repo: str) -> str | None:
    """The ``html_url`` of the pull request object ``gh api`` printed when it is
    ``https://github.com/<hub_repo>/pull/<n>`` (owner and name compared without case)."""
    try:
        created = json.loads(stdout.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        return None
    url = created.get(HTML_URL) if isinstance(created, dict) else None
    return _hub_pull_url(url, hub_repo=hub_repo) if isinstance(url, str) else None


def _hub_pull_url(text: str, *, hub_repo: str) -> str | None:
    found = _PULL_URL.fullmatch(text)
    if found is None or found.group("repo").lower() != hub_repo.lower():
        return None
    return found.group(0)


def open_pull_request_url(stdout: bytes, *, hub_repo: str) -> str | None:
    """The first ``html_url`` of the pull request list ``gh api`` printed, or None when it lists
    none.

    The output must be a JSON list of objects whose ``html_url`` is
    ``https://github.com/<hub_repo>/pull/<n>``; anything else raises ``UnexpectedOutputError``.
    """
    try:
        listed = json.loads(stdout.decode("utf-8"))
    except UnicodeDecodeError, ValueError:
        raise UnexpectedOutputError from None
    if not isinstance(listed, list):
        raise UnexpectedOutputError
    urls: list[str] = []
    for item in listed:
        url = item.get(HTML_URL) if isinstance(item, dict) else None
        found = _hub_pull_url(url, hub_repo=hub_repo) if isinstance(url, str) else None
        if found is None:
            raise UnexpectedOutputError
        urls.append(found)
    return urls[0] if urls else None
