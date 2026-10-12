"""GitHub names in git and gh output: the ``owner/name`` an ``origin`` url points at and the pull
request url ``gh pr create`` prints."""

import re
from typing import Final

_GITHUB_URL: Final = re.compile(
    r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<repo>[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+?)(?:\.git)?/?",
    re.IGNORECASE,
)
_PULL_URL: Final = re.compile(r"https://github\.com/(?P<repo>[^/\s]+/[^/\s]+)/pull/\d+")


def github_repo(url: str) -> str | None:
    """The ``owner/name`` of a GitHub url (https or ssh, ``.git`` optional), or None for any
    other url (another host, a local path, a url carrying credentials)."""
    found = _GITHUB_URL.fullmatch(url.strip())
    return None if found is None else found.group("repo")


def pull_request_url(stdout: bytes, *, hub_repo: str) -> str | None:
    """The pull request url that ends ``stdout`` (its last word) when it is
    ``https://github.com/<hub_repo>/pull/<n>`` (owner and name compared without case)."""
    words = stdout.decode("utf-8", errors="replace").split()
    if not words:
        return None
    found = _PULL_URL.fullmatch(words[-1])
    if found is None or found.group("repo").lower() != hub_repo.lower():
        return None
    return found.group(0)
