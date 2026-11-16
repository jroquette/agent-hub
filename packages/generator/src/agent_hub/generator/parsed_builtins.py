"""The built-in workflows, pre-parsed by the strict loader and shipped as package data.

``parsed_builtins.json`` sits next to this module, never under a folder seeded into hubs. It
holds, for each pack-level built-in ``*.yaml``, what ``workflow_yaml.read_workflow_strictly``
reads from its bytes, keyed by their SHA-256: ``{"format": 1, "entries": [...]}``, one entry per
line, sorted by ``source``; an entry holds ``sha256`` (hex), ``source`` (``<pack>/<file>.yaml``,
for review only), ``document`` and ``lines`` (``[[key path], line]`` pairs). ``table_text`` is the
one writer of the format, and ``make parsed-builtins`` (``scripts/export_parsed_builtins.py``)
regenerates the file; a drift test fails while it is stale.

``lookup`` finds an entry only by the exact digest of a file's bytes, so a file that differs by
one byte takes the strict path. It reads the shipped table once per process, at the first call;
a table that cannot be read or decoded is a broken install, and raises ``ParsedBuiltinsError``
naming the file. An entry is shared by every caller: its document must not be changed. This
module imports nothing from ``workflow_yaml``, so the two have no cycle.
"""

import json
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources import files
from importlib.resources.abc import Traversable
from types import MappingProxyType
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.generator.errors import GeneratorError

TABLE_FILE: Final = "parsed_builtins.json"
TABLE_FORMAT: Final = 1
_DIGEST_HEX_LENGTH: Final = 64

type KeyPath = tuple[str | int, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class ParsedBuiltin:
    """One built-in file as the strict loader reads it: ``sha256`` is the hex digest of its bytes,
    ``source`` is ``<pack>/<file>.yaml`` (for review only)."""

    sha256: str
    source: str
    document: dict[str, JsonValue]
    lines: Mapping[KeyPath, int]


class ParsedBuiltinsError(GeneratorError):
    """The shipped table cannot be read or decoded; the message names the file."""


def table_text(entries: Iterable[ParsedBuiltin]) -> str:
    """The table's text: ``{"format": 1, "entries": [...]}``, one entry per line, by source."""
    rows = [
        json.dumps(
            {
                "sha256": entry.sha256,
                "source": entry.source,
                "document": entry.document,
                "lines": [[list(path), line] for path, line in entry.lines.items()],
            },
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        for entry in sorted(entries, key=lambda entry: entry.source)
    ]
    return f'{{"format": {TABLE_FORMAT}, "entries": [\n' + ",\n".join(rows) + "\n]}\n"


def load_table(resource: Traversable) -> Mapping[bytes, ParsedBuiltin]:
    """The entries of the table in ``resource``, by raw SHA-256 digest.

    Raises ``ParsedBuiltinsError`` naming the file when it cannot be read or decoded.
    """
    try:
        with resource.open("rb") as stream:
            raw = json.load(stream)
    except OSError as error:
        raise _broken(resource, f"it cannot be read ({type(error).__name__})") from None
    except ValueError:
        raise _broken(resource, "it is not valid JSON") from None
    if not isinstance(raw, dict) or raw.get("format") != TABLE_FORMAT:
        raise _broken(resource, f'it is not a {{"format": {TABLE_FORMAT}}} table')
    rows = raw.get("entries")
    if not isinstance(rows, list):
        raise _broken(resource, "its entries are not a list")
    table: dict[bytes, ParsedBuiltin] = {}
    for index, row in enumerate(rows):
        entry = _entry(row)
        if entry is None:
            raise _broken(resource, f"entry {index} is not a valid entry")
        table[bytes.fromhex(entry.sha256)] = entry
    return MappingProxyType(table)


def lookup(digest: bytes) -> ParsedBuiltin | None:
    """The shipped entry for the raw SHA-256 ``digest`` of a file's bytes, or ``None``.

    Reads the shipped table once per process, through ``load_table``.
    """
    return _shipped_table().get(digest)


_TABLE_LOCK: Final = threading.Lock()
_loaded: list[Mapping[bytes, ParsedBuiltin]] = []


def _shipped_table() -> Mapping[bytes, ParsedBuiltin]:
    # One read per process; a failed read is not stored, so it raises again on the next call.
    with _TABLE_LOCK:
        if not _loaded:
            _loaded.append(load_table(files("agent_hub.generator").joinpath(TABLE_FILE)))
        return _loaded[0]


def _broken(resource: Traversable, reason: str) -> ParsedBuiltinsError:
    return ParsedBuiltinsError(
        f"the pre-parsed built-in workflows table {resource} is broken: {reason}; "
        f"reinstall agent-hub (in its repo, run make parsed-builtins)"
    )


def _entry(row: object) -> ParsedBuiltin | None:
    if not isinstance(row, dict):
        return None
    sha256, source = row.get("sha256"), row.get("source")
    document, pairs = row.get("document"), row.get("lines")
    if not (
        isinstance(sha256, str)
        and len(sha256) == _DIGEST_HEX_LENGTH
        and all(char in "0123456789abcdef" for char in sha256)
        and isinstance(source, str)
        and isinstance(document, dict)
        and isinstance(pairs, list)
    ):
        return None
    lines: dict[KeyPath, int] = {}
    for pair in pairs:
        path = _line_pair(pair)
        if path is None:
            return None
        lines[path[0]] = path[1]
    return ParsedBuiltin(
        sha256=sha256, source=source, document=document, lines=MappingProxyType(lines)
    )


def _line_pair(pair: object) -> tuple[KeyPath, int] | None:
    if not (isinstance(pair, list) and len(pair) == 2):  # noqa: PLR2004 - a [path, line] pair
        return None
    path, line = pair
    if not isinstance(path, list) or type(line) is not int:
        return None
    if not all(isinstance(part, str) or type(part) is int for part in path):
        return None
    return tuple(path), line
