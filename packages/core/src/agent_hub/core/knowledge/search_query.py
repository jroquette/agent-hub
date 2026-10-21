"""The words of a ``hub search`` query and how they reach FTS5 (AGH-391, D-query).

A word is a run of Unicode letters and digits in the NFC-composed text, and every other character
separates words: FTS5's ``unicode61`` split, except that it keeps private-use characters inside a
word where this split does not (a known gap). Each word reaches FTS5 as a quoted string and the
strings are joined with FTS5's implicit AND, so no caller text is FTS5 syntax and no query is a
syntax error.
"""

import re
import unicodedata
from typing import Final

# At most this many results per search (D-query).
MAX_RESULTS: Final = 50
# A result's snippet is one line of at most this many characters (D-output).
MAX_SNIPPET_CHARS: Final = 160

_WORD: Final = re.compile(r"[^\W_]+")


def query_words(text: str) -> tuple[str, ...]:
    """The words of ``text`` once NFC-composed (a decomposed accent stays in its word), in order;
    empty when it holds no letter or digit."""
    return tuple(_WORD.findall(unicodedata.normalize("NFC", text)))


def fts5_match(words: tuple[str, ...]) -> str:
    """The FTS5 ``MATCH`` expression requiring every word of ``words``, the non-empty output of
    ``query_words`` (so no word holds a ``"``): each one quoted."""
    return " ".join(f'"{word}"' for word in words)


def snippet_line(text: str) -> str:
    """``text`` as one line of at most ``MAX_SNIPPET_CHARS`` characters: each run of whitespace,
    line breaks included, becomes one space, and a longer line ends in ``…`` where cut."""
    line = " ".join(text.split())
    if len(line) <= MAX_SNIPPET_CHARS:
        return line
    return line[: MAX_SNIPPET_CHARS - 1] + "…"
