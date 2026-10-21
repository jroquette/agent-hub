"""The words of a ``hub search`` query and how they reach FTS5 (AGH-391, D-query).

A word is a run of Unicode letters and digits, the split of FTS5's ``unicode61`` tokenizer; every
other character separates words. Each word reaches FTS5 as a quoted string and the strings are
joined with FTS5's implicit AND, so no caller text is FTS5 syntax and no query is a syntax error.
"""

import re
from typing import Final

# At most this many results per search (D-query).
MAX_RESULTS: Final = 50
# A result's snippet is one line of at most this many characters (D-output).
MAX_SNIPPET_CHARS: Final = 160

_WORD: Final = re.compile(r"[^\W_]+")


def query_words(text: str) -> tuple[str, ...]:
    """The words of ``text``, in order; empty when it holds no letter or digit."""
    return tuple(_WORD.findall(text))


def fts5_match(words: tuple[str, ...]) -> str:
    """The FTS5 ``MATCH`` expression requiring every word: each one quoted, inner ``"`` doubled."""
    return " ".join('"' + word.replace('"', '""') + '"' for word in words)


def snippet_line(text: str) -> str:
    """``text`` as one line of at most ``MAX_SNIPPET_CHARS`` characters: each run of whitespace,
    line breaks included, becomes one space, and a longer line ends in ``…`` where cut."""
    line = " ".join(text.split())
    if len(line) <= MAX_SNIPPET_CHARS:
        return line
    return line[: MAX_SNIPPET_CHARS - 1] + "…"
