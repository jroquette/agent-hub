"""The words of a query and their FTS5 form (AGH-391, D-query): no caller text is FTS5 syntax."""

import pytest

from agent_hub.core.knowledge.search_query import (
    MAX_SNIPPET_CHARS,
    fts5_match,
    query_words,
    snippet_line,
)


@pytest.mark.parametrize(
    ("query", "words", "match"),
    [
        ("a OR b", ("a", "OR", "b"), '"a" "OR" "b"'),
        ("NEAR(a b)", ("NEAR", "a", "b"), '"NEAR" "a" "b"'),
        ('"unclosed', ("unclosed",), '"unclosed"'),
        ("title:foo", ("title", "foo"), '"title" "foo"'),
        ("foo*", ("foo",), '"foo"'),
        ("-foo", ("foo",), '"foo"'),
        ("^foo", ("foo",), '"foo"'),
        ("a AND", ("a", "AND"), '"a" "AND"'),
        ("(", (), ""),
    ],
)
def test_quotes_each_word_when_query_has_fts_syntax(
    query: str, words: tuple[str, ...], match: str
) -> None:
    assert query_words(query) == words
    assert fts5_match(query_words(query)) == match


def test_doubles_inner_quote_when_word_holds_one() -> None:
    assert fts5_match(('a"b', "c")) == '"a""b" "c"'


@pytest.mark.parametrize("query", ["", "   ", "!!!"])
def test_finds_no_words_when_query_blank_or_punctuation(query: str) -> None:
    assert query_words(query) == ()


def test_keeps_letters_and_digits_when_query_mixes_scripts() -> None:
    assert query_words("café_2x-ü") == ("café", "2x", "ü")


def test_cuts_snippet_to_one_line_when_text_long() -> None:
    assert snippet_line("  first line\nsecond\r\nthird\u2028fourth \t end ") == (
        "first line second third fourth end"
    )

    cut = snippet_line("x" * 400)

    assert MAX_SNIPPET_CHARS == 160
    assert cut == "x" * 159 + "…"
    assert snippet_line("y" * 160) == "y" * 160
