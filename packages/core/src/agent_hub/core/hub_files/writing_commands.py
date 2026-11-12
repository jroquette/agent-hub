"""A model of Claude Code's permission rules, and the writing commands no allow rule may let run."""

from collections.abc import Iterable
from typing import Final

WRITING_COMMANDS: Final[tuple[str, ...]] = ()
WRITING_TOOL_WORDS: Final[tuple[str, ...]] = ()


def matches(rule: str, command: str) -> bool:
    raise NotImplementedError


def effective_allows(allow: Iterable[str], deny: Iterable[str], command: str) -> bool:
    raise NotImplementedError
