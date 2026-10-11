import random
import re

import pytest

from agent_hub.core.workspace.task_slug import (
    MAX_SLUG_CHARS,
    is_task_folder,
    task_name,
    title_slug,
)
from agent_hub.core.workspace.worktree_name import worktree_name_problem

SLUG_SHAPE = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
# Characters the generated titles are drawn from: ASCII, punctuation, spaces and letters that
# lowercase oddly or are not ASCII at all.
TITLE_ALPHABET = (
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    " !\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~\t\n"
    "éKİ\U0001f600"
)


def test_cuts_at_word_end_when_slug_longer_than_forty() -> None:
    title = "hub start ISSUE: ticket to worktrees, In Progress and an agent session"

    assert title_slug(title) == "hub-start-issue-ticket-to-worktrees-in"


def test_collapses_punctuation_when_slug_built() -> None:
    assert title_slug("Fix: CI!!") == "fix-ci"


@pytest.mark.parametrize("title", ["???", "   "])
def test_names_task_by_id_when_slug_empty(title: str) -> None:
    assert title_slug(title) == ""
    assert task_name("DEM-7", title) == "dem-7"


def test_names_task_by_id_and_slug_when_title_has_words() -> None:
    assert task_name("DEM-7", "Add the collector") == "dem-7-add-the-collector"


def test_cuts_first_word_when_word_longer_than_forty() -> None:
    assert title_slug("a" * 45) == "a" * 40
    assert title_slug("a" * 45 + " more") == "a" * 40


def test_keeps_slug_whole_when_slug_is_forty() -> None:
    title = "b" * 30 + " " + "c" * 9

    assert title_slug(title) == "b" * 30 + "-" + "c" * 9
    assert title_slug(title + " d") == "b" * 30 + "-" + "c" * 9


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Café crème", "caf-cr-me"),
        # KELVIN SIGN lowercases to an ASCII ``k`` and DOTTED CAPITAL I to ``i`` + a combining
        # dot: only A-Z are lowercased, so both are dropped (E6).
        ("Kelvin", "elvin"),
        ("İstanbul", "stanbul"),
    ],
)
def test_drops_non_ascii_letters_when_slug_built(title: str, slug: str) -> None:
    assert title_slug(title) == slug


def test_states_forty_as_slug_limit_when_module_read() -> None:
    assert MAX_SLUG_CHARS == 40


def test_passes_worktree_name_rule_when_titles_generated() -> None:
    generator = random.Random(62)  # noqa: S311 - seeded test titles, not cryptography
    titles = [
        "".join(generator.choices(TITLE_ALPHABET, k=generator.randint(0, 120)))
        for _ in range(1_000)
    ]

    for title in titles:
        slug = title_slug(title)
        assert worktree_name_problem(task_name("DEM-7", title), teams=("DEM",)) is None, title
        assert len(slug) <= 40, title
        assert slug == "" or SLUG_SHAPE.fullmatch(slug), title


@pytest.mark.parametrize("folder", ["dem-7", "dem-7-x", "dem-7-old-title"])
def test_matches_task_folder_when_name_is_id_or_id_prefix(folder: str) -> None:
    assert is_task_folder(folder, "DEM-7")


@pytest.mark.parametrize("folder", ["dem-70-x", "dem-7x", "dem-1", "DEM-7", "xdem-7", ""])
def test_skips_folder_when_name_is_other_issue(folder: str) -> None:
    assert not is_task_folder(folder, "DEM-7")
