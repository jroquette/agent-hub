"""The words of a query and their FTS5 form (AGH-391, D-query): no caller text is FTS5 syntax.
The order of results by kind and status (B-11)."""

import pytest

from agent_hub.core.knowledge.knowledge_index import KINDS
from agent_hub.core.knowledge.search_query import (
    KIND_TIERS,
    MAX_SNIPPET_CHARS,
    fts5_match,
    kind_tier,
    query_words,
    snippet_line,
    status_tier,
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


@pytest.mark.parametrize("query", ["", "   ", "!!!"])
def test_finds_no_words_when_query_blank_or_punctuation(query: str) -> None:
    assert query_words(query) == ()


def test_keeps_letters_and_digits_when_query_mixes_scripts() -> None:
    assert query_words("café_2x-ü") == ("café", "2x", "ü")


def test_composes_accents_when_query_decomposed() -> None:
    assert query_words("e\u0301clair") == ("\u00e9clair",)


def test_cuts_snippet_to_one_line_when_text_long() -> None:
    assert snippet_line("  first line\nsecond\r\nthird\u2028fourth \t end ") == (
        "first line second third fourth end"
    )

    cut = snippet_line("x" * 400)

    assert MAX_SNIPPET_CHARS == 160
    assert cut == "x" * 159 + "…"
    assert snippet_line("y" * 160) == "y" * 160


def test_puts_each_kind_in_one_tier_when_tiers_read() -> None:
    tiered = [kind for kinds in KIND_TIERS for kind in kinds]

    assert sorted(tiered) == sorted(KINDS)
    assert [kind_tier(kind) for kind in ("learning", "adr", "doc", "journal", "feature")] == [
        0,
        0,
        1,
        1,
        1,
    ]
    assert kind_tier("inbox") == 1


@pytest.mark.parametrize(
    ("status", "tier"),
    [
        ("approved", 0),
        ("Approved (owner, 2026-10-13)", 0),
        ("ACTIVE", 0),
        (None, 1),
        ("accepted", 1),
        ("", 1),
        ("done", 1),
        ("drafted", 1),
        (" approved", 1),
        ("(draft)", 1),
        ("draft", 2),
        ("draft, proposed extra", 2),
        ("proposed", 2),
        ("drafté", 2),
    ],
)
def test_tiers_status_by_leading_word_when_status_given(status: str | None, tier: int) -> None:
    assert status_tier(status) == tier
