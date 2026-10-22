"""The variable names a dotenv file declares, never their values.

hub web shows which variables an environment's env file holds, so a person sees what scripted
actions will get without the screen ever holding a secret (docs/design/environments.md). The
parser keeps a name and drops its value at once: ``NAME=value``, ``export NAME=value``, comments
and blank lines; a quoted value that spans lines is skipped to its closing quote, so a line inside
it is never read as a name. A line that is not ``NAME=`` is ignored, and so is a name that is not
a shell variable's shape.
"""

import re
from typing import Final

from agent_hub.core.readmodels.view_types import ViewModel

MAX_ENV_FILE_BYTES: Final = 64 * 1024
MAX_KEYS: Final = 200
_LINE: Final = re.compile(r"^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=(.*)$")
_QUOTES: Final = ("'", '"')


class EnvFileKeys(ViewModel):
    """What hub web may show of an env file: whether it is found where it may be, whether git
    ignores it, and its variable names. ``problem`` says, in words, why no names are shown."""

    path: str
    exists: bool
    # The hub's or a declared repo's dir holding the file; None when it is outside all of them.
    holder: str | None
    # Whether git ignores it there; None when there is no holder or git cannot answer.
    ignored: bool | None
    keys: tuple[str, ...] = ()
    # More names than MAX_KEYS: the rest are not listed.
    truncated: bool = False
    problem: str | None = None


def dotenv_keys(content: bytes) -> tuple[tuple[str, ...], bool]:
    """The names ``content`` declares, in file order, each once, at most ``MAX_KEYS``; and
    whether there were more."""
    keys: dict[str, None] = {}
    closing: str | None = None
    for raw in content.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if closing is not None:
            if line.endswith(closing):
                closing = None
            continue
        match = _LINE.match(line)
        if match is None or line.startswith("#"):
            continue
        keys.setdefault(match.group(1))
        value = match.group(2).strip()
        if value[:1] in _QUOTES and not _closes(value):
            closing = value[0]
    names = tuple(keys)
    return names[:MAX_KEYS], len(names) > MAX_KEYS


def _closes(value: str) -> bool:
    """Whether a quoted value ends on its own line."""
    return len(value) > 1 and value.rstrip().endswith(value[0])
