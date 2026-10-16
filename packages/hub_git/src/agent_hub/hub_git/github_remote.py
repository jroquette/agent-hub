"""GitHub names in git and gh output: the ``owner/name`` an ``origin`` url points at, the pull
request url ``gh pr create`` prints and the open pull request ``gh pr list --json url`` names."""

import json
import re
from typing import Final

# An ssh host alias ``github.com-<account>`` (a ``Host`` entry of ``~/.ssh/config``, the usual way to
# keep two GitHub accounts on one machine) names GitHub too.
_SSH_HOST: Final = r"github\.com(?:-[A-Za-z0-9_]+)*"
_GITHUB_URL: Final = re.compile(
    rf"(?:https://github\.com/|ssh://git@{_SSH_HOST}/|git@{_SSH_HOST}:)"
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)
_PULL_URL: Final = re.compile(r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/pull/\d+")


class UnexpectedOutputError(ValueError):
    """gh printed something other than what was asked for."""


def github_repo(url: str) -> str | None:
    """The ``owner/name`` of a GitHub url (https or ssh, ``.git`` optional, ssh through a
    ``github.com-<account>`` host alias too), or None for any other url (another host, a local path, a url carrying credentials)."""
    found = _GITHUB_URL.fullmatch(url.strip())
    return None if found is None else found.group("repo")


def pull_request_url(stdout: bytes, *, hub_repo: str) -> str | None:
    """The pull request url that ends ``stdout`` (its last word) when it is
    ``https://github.com/<hub_repo>/pull/<n>`` (owner and name compared without case)."""
    words = stdout.decode("utf-8", errors="replace").split()
    return _hub_pull_url(words[-1], hub_repo=hub_repo) if words else None


def _hub_pull_url(text: str, *, hub_repo: str) -> str | None:
    found = _PULL_URL.fullmatch(text)
    if found is None or found.group("repo").lower() != hub_repo.lower():
        return None
    return found.group(0)


def open_pull_request_url(stdout: bytes, *, hub_repo: str) -> str | None:
    """The first url of ``gh pr list --json url`` output, or None when it lists none.

    The output must be a JSON list of objects whose ``url`` is
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
        url = item.get("url") if isinstance(item, dict) else None
        found = _hub_pull_url(url, hub_repo=hub_repo) if isinstance(url, str) else None
        if found is None:
            raise UnexpectedOutputError
        urls.append(found)
    return urls[0] if urls else None
