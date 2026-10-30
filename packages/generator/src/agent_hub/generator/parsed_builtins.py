"""The built-in workflows, pre-parsed by the strict loader and shipped as package data (AGH-636).

Stub for the RED tests of plan commit 32: every function raises ``NotImplementedError`` until
plan commit 33 implements the module.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from importlib.resources.abc import Traversable
from typing import Final

from agent_hub.core.json_form import JsonValue
from agent_hub.generator.errors import GeneratorError

TABLE_FILE: Final = "parsed_builtins.json"

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
    raise NotImplementedError


def load_table(resource: Traversable) -> Mapping[bytes, ParsedBuiltin]:
    """The entries of the table in ``resource``, by raw SHA-256 digest.

    Raises ``ParsedBuiltinsError`` naming the file when it cannot be read or decoded.
    """
    raise NotImplementedError


def lookup(digest: bytes) -> ParsedBuiltin | None:
    """The shipped entry for the raw SHA-256 ``digest`` of a file's bytes, or ``None``.

    Reads the shipped table once per process, through ``load_table``.
    """
    raise NotImplementedError
