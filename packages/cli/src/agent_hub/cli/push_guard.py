"""The push's guard: the repo-side git config the push reads must be what it was (D10).

The implementing session can edit the repo's git config (the common dir's ``config``, or the
worktree's ``config.worktree``), and the push runs with the GitHub tokens: a credential helper,
an ``sshCommand`` or a rewritten remote url set by the session would run with them, or send the
branch elsewhere. So ``hub run`` takes a snapshot before the session (``--from verify``: before
the gate) and compares it right before the push; any difference refuses the push. Only key names
are ever shown, never values.

With ``--from verify`` an earlier run's session may already have changed the config, so the push
is also refused when a key a push would use (``RISKY_KEYS``) is set at local or worktree scope,
or when the worktree's ``remote.origin.url`` differs from the repo main checkout's local one.
"""

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

LOCAL: Final = "local"
WORKTREE: Final = "worktree"
CONFIG_FILE: Final = "the config file"
REMOTE_URL: Final = "remote.origin.url"
REMOTE_KEYS: Final = (REMOTE_URL, "remote.origin.pushurl")
# Keys a push would act on, as git config --list writes them (sections lowercased).
_RISKY_SECTIONS: Final = ("credential.", "include.", "includeif.", "http.")
_RISKY_NAMES: Final = frozenset({"core.sshcommand", "core.askpass"})
_RISKY_URL_SUFFIXES: Final = (".insteadof", ".pushinsteadof")


@dataclass(frozen=True, kw_only=True, slots=True)
class ConfigSnapshot:
    """The repo-side config: ``(scope, key)`` -> values, and each config file's digest."""

    entries: Mapping[tuple[str, str], tuple[str, ...]]
    files: Mapping[str, str]


def parse_config_list(output: str, *, scope: str) -> dict[tuple[str, str], tuple[str, ...]]:
    """``git config --list -z`` read: ``key\\nvalue`` items ended by NUL; a key may repeat."""
    found: dict[tuple[str, str], list[str]] = {}
    for item in output.split("\0"):
        if item:
            key, _, value = item.partition("\n")
            found.setdefault((scope, key), []).append(value)
    return {key: tuple(values) for key, values in found.items()}


def file_digest(content: bytes | None) -> str:
    """A config file's SHA-256, or ``absent``."""
    return "absent" if content is None else hashlib.sha256(content).hexdigest()


def changed_keys(before: ConfigSnapshot, after: ConfigSnapshot) -> list[str]:
    """The key names whose values differ, sorted; ``the config file`` when only a file's bytes
    changed (a comment, a key git does not list)."""
    keys = before.entries.keys() | after.entries.keys()
    names = sorted(
        {
            key
            for scope, key in keys
            if before.entries.get((scope, key)) != after.entries.get((scope, key))
        }
    )
    if not names and before.files != after.files:
        return [CONFIG_FILE]
    return names


def risky_keys(snapshot: ConfigSnapshot) -> list[str]:
    """The keys a push would use that are set at local or worktree scope, sorted."""
    return sorted({key for _, key in snapshot.entries if _is_risky(key.lower())})


def _is_risky(key: str) -> bool:
    if key in _RISKY_NAMES or key.startswith(_RISKY_SECTIONS):
        return True
    return key.startswith("url.") and key.endswith(_RISKY_URL_SUFFIXES)
