"""An environment's env file, read as dotenv (docs/design/scenarios.md § Credentials).

The grammar is small on purpose: ``NAME=value`` lines, blank lines, ``#`` comments, an optional
``export `` before the name, a value bare (a `` #`` after a space starts a comment), in single
quotes (literal) or in double quotes (``\\"``, ``\\\\`` and ``\\n`` escapes). Nothing is
interpolated: ``$NAME`` stays as written. A line outside it refuses the whole file, naming the
line by number only: its text may hold a value. Only the action runner calls this, on bytes it
read in memory (``cli.env_files_loader``).
"""

import re
from typing import Final

from agent_hub.core.errors import AgentHubError

MAX_ENV_FILE_BYTES: Final = 64 * 1024
MAX_ENV_FILE_VARIABLES: Final = 200
_NAME: Final = re.compile(r"[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*")
_ESCAPES: Final = {'"': '"', "\\": "\\", "n": "\n"}


class EnvFileError(AgentHubError):
    """Why an env file cannot be used: ``reason`` never holds a value."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def parse_env_file(content: bytes) -> dict[str, str]:
    """Each variable of ``content`` (the last of a repeated name wins); raises
    ``EnvFileError`` at the first line outside the grammar, or past ``MAX_ENV_FILE_VARIABLES``."""
    variables: dict[str, str] = {}
    for number, raw in enumerate(content.split(b"\n"), start=1):
        try:
            line = raw.decode("utf-8").removesuffix("\r")
        except UnicodeDecodeError:
            raise _broken(number) from None
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        parsed = _variable(line)
        if parsed is None:
            raise _broken(number)
        name, value = parsed
        variables[name] = value
        if len(variables) > MAX_ENV_FILE_VARIABLES:
            raise EnvFileError(f"too large (more than {MAX_ENV_FILE_VARIABLES} variables)")
    return variables


def _broken(number: int) -> EnvFileError:
    return EnvFileError(f"not a dotenv file (line {number})")


def _variable(line: str) -> tuple[str, str] | None:
    if "\0" in line or (match := _NAME.match(line)) is None:
        return None
    rest = line[match.end() :]
    if rest.startswith("'"):
        end = rest.find("'", 1)
        value, tail = (rest[1:end], rest[end + 1 :]) if end > 0 else (None, "")
    elif rest.startswith('"'):
        value, tail = _double_quoted(rest)
    else:
        value, tail = re.split(r"[ \t]#", rest, maxsplit=1)[0].rstrip(" \t"), ""
    if value is None or not _is_blank_or_comment(tail):
        return None
    return match.group(1), value


def _double_quoted(rest: str) -> tuple[str | None, str]:
    """The value of ``"…"`` at the start of ``rest`` and what follows it; ``None`` unclosed."""
    value: list[str] = []
    index = 1
    while index < len(rest):
        char = rest[index]
        if char == '"':
            return "".join(value), rest[index + 1 :]
        if char == "\\" and index + 1 < len(rest):
            index += 1
            value.append(_ESCAPES.get(rest[index], "\\" + rest[index]))
        else:
            value.append(char)
        index += 1
    return None, ""


def _is_blank_or_comment(tail: str) -> bool:
    stripped = tail.lstrip(" \t")
    return not stripped or (stripped.startswith("#") and stripped != tail)
