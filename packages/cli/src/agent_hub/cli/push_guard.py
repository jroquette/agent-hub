"""The push's guard: no repo-side git config key a push would act on, and origin is the repo.

The implementing session can edit the repo's git config, and the push runs with the GitHub
tokens: a credential helper, an ``sshCommand``, a filter or a rewritten remote set by the
session, or by an earlier run's session, would run with them or send the branch elsewhere.
Right before every push (owner decision, 2026-10-02: risky keys only, so husky's
``core.hooksPath`` or a submodule's url never stop a run) ``hub run`` lists the config at local
and worktree scope, includes followed, and refuses the push when a ``RISKY`` key is set there,
or when the effective ``remote.origin.url`` is not the GitHub url of the repo's
``github`` (``owner/name``) in ``hub.json``, a source the session cannot change. Only key names
are ever shown, never values.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Final

REPO_SCOPES: Final = frozenset({"local", "worktree"})
REMOTE_URL: Final = "remote.origin.url"
# The remote keys a push may use as they are; any other remote.* key is refused.
ALLOWED_REMOTE_KEYS: Final = frozenset({REMOTE_URL, "remote.origin.fetch"})
# Keys a push (or what it runs) would act on, as git config --list writes them (lowercased).
_RISKY_SECTIONS: Final = (
    "credential.",
    "include.",
    "includeif.",
    "http.",
    "gpg.",
    "push.",
    "filter.",
    "protocol.",
)
_RISKY_NAMES: Final = frozenset(
    {"core.sshcommand", "core.askpass", "core.gitproxy", "core.fsmonitor"}
)
_RISKY_URL_SUFFIXES: Final = (".insteadof", ".pushinsteadof")
_GITHUB_URL = re.compile(
    r"(?:https://github\.com/|ssh://git@github\.com/|git@github\.com:)"
    r"(?P<repo>[^/\s]+/[^/\s]+?)(?:\.git)?/?",
    re.IGNORECASE,
)


def parse_scoped_list(output: str) -> list[tuple[str, str]]:
    """``git config --list --show-scope -z`` read: ``(scope, key)`` per entry, in order."""
    items = output.split("\0")
    return [
        (scope, entry.partition("\n")[0])
        for scope, entry in zip(items[0::2], items[1::2], strict=False)
        if scope and entry
    ]


def risky_keys(entries: Iterable[tuple[str, str]]) -> list[str]:
    """The keys a push would act on that are set at local or worktree scope, sorted."""
    return sorted({key for scope, key in entries if scope in REPO_SCOPES and _is_risky(key)})


def names_github_repo(urls: Sequence[str], *, github: str) -> bool:
    """Whether ``urls`` is exactly one GitHub url (https or ssh, ``.git`` optional) of
    ``github`` (``owner/name``, compared without case, as GitHub does)."""
    if len(urls) != 1:
        return False
    found = _GITHUB_URL.fullmatch(urls[0].strip())
    return found is not None and found.group("repo").lower() == github.lower()


def _is_risky(key: str) -> bool:
    key = key.lower()
    if key in _RISKY_NAMES or key.startswith(_RISKY_SECTIONS):
        return True
    if key.startswith("remote."):
        return key not in ALLOWED_REMOTE_KEYS
    return key.startswith("url.") and key.endswith(_RISKY_URL_SUFFIXES)
