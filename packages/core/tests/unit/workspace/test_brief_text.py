import pytest
from pydantic import ValidationError

from agent_hub.core.workspace import brief_text
from agent_hub.core.workspace.brief_text import (
    BriefInputs,
    RepoState,
    journal_day,
    now_verified,
    repo_line,
    select_journal,
)
from agent_hub.core.workspace.brief_text import (
    brief_text as render_brief,
)

NOW = "---\nlast_verified: 2026-01-12\n---\n# Now\nShip the collector.\nThen the CLI.\n"
FOOTER = [
    "",
    "Linear: n/a (connector not configured for scripts).",
    "More: brain/index.md (pull only what the task needs).",
]
STALE_TAIL = (
    ": treat it as possibly stale and check git log / Linear before trusting it;"
    " update it with /handoff."
)


def inputs(**changes: object) -> BriefInputs:
    values: dict[str, object] = {
        "now_text": NOW,
        "now_age_days": 3,
        "journal": (),
        "repos": (),
        "network": True,
    }
    return BriefInputs.model_validate(values | changes)


def a_repo(**changes: object) -> RepoState:
    values: dict[str, object] = {
        "name": "api",
        "checkout": True,
        "branch": "trunk",
        "dirty": 2,
        "behind": "1",
        "base": "origin/trunk",
        "prs": "",
        "ci": "",
    }
    return RepoState.model_validate(values | changes)


def test_pins_max_chars_when_module_loaded() -> None:
    assert brief_text.MAX_CHARS == 5500


def test_pins_stale_days_when_module_loaded() -> None:
    assert brief_text.STALE_DAYS == 3


def test_pins_journal_max_age_when_module_loaded() -> None:
    assert brief_text.JOURNAL_MAX_AGE == 7


def test_pins_journal_count_when_module_loaded() -> None:
    assert brief_text.JOURNAL_COUNT == 2


def test_pins_titles_cap_when_module_loaded() -> None:
    assert brief_text.TITLES_CAP == 300


def test_pins_pr_lines_when_module_loaded() -> None:
    assert brief_text.PR_LINES == 4


def test_pins_pr_cap_when_module_loaded() -> None:
    assert brief_text.PR_CAP == 70


def test_refuses_change_when_state_assigned() -> None:
    state = a_repo()

    with pytest.raises(ValidationError):
        state.dirty = 3  # type: ignore[misc]


def test_builds_whole_brief_when_inputs_given() -> None:
    text = render_brief(
        inputs(
            journal=(("brain/journal/2026/01/13.md", "# 2026-01-13\n## Fixed the loader\n"),),
            repos=(a_repo(name="hub", dirty=0, behind="0"),),
        )
    )

    assert text.split("\n") == [
        "# Brief",
        "",
        "## Now",
        "Ship the collector.",
        "Then the CLI.",
        "",
        "## Journal (last 7 days)",
        "- 2026-01-13: Fixed the loader",
        "",
        "## Repos",
        "- hub: trunk, 0 changed file(s), 0 behind origin/trunk",
        *FOOTER,
    ]


def test_warns_stale_when_age_over_three_days() -> None:
    lines = render_brief(inputs(now_age_days=4)).split("\n")

    assert lines[3] == f"> ⚠ now.md is 4 days old{STALE_TAIL}"
    assert "⚠" not in render_brief(inputs(now_age_days=3))


def test_warns_stale_when_undated() -> None:
    lines = render_brief(inputs(now_age_days=None)).split("\n")

    assert lines[3] == f"> ⚠ now.md is undated{STALE_TAIL}"


def test_drops_first_line_when_now_has_body() -> None:
    # Quirk kept (spec Q-5): the first body line is taken for a heading even when it is not one.
    text = "---\nlast_verified: 2026-01-12\n---\nFirst content line.\nSecond content line.\n"

    lines = render_brief(inputs(now_text=text)).split("\n")

    assert lines[3:5] == ["Second content line.", ""]


def test_says_missing_when_now_absent() -> None:
    lines = render_brief(inputs(now_text=None, now_age_days=None)).split("\n")

    assert lines[2:5] == ["## Now", "(brain/now.md missing)", ""]


def test_reads_verified_date_when_front_matter_has_one() -> None:
    assert now_verified(NOW) == "2026-01-12"
    assert now_verified("---\ntype: now\n---\n# Now\n") is None


def test_joins_titles_when_journal_read() -> None:
    body = "---\ntype: journal\n---\n# 2026-01-14\n" + "".join(
        f"## Topic {index}: " + "x" * 80 + "\n" for index in range(1, 5)
    )
    body += "### not a title\nbody\n"

    lines = render_brief(inputs(journal=(("brain/journal/2026/01/14.md", body),))).split("\n")

    entry = lines[7]
    titles = "; ".join(f"Topic {index}: " + "x" * 80 for index in range(1, 5))
    assert entry == "- 2026-01-14: " + titles[:300]


def test_says_no_entry_when_journal_empty() -> None:
    lines = render_brief(inputs()).split("\n")

    assert lines[6:8] == ["## Journal (last 7 days)", "- (no entry in the last week)"]


def test_selects_two_newest_when_journal_globbed() -> None:
    paths = [
        "brain/journal/2026/01/07.md",
        "brain/journal/2026/01/08.md",
        "brain/journal/2026/01/10.md",
        "brain/journal/2026/01/14.md",
    ]

    assert select_journal(paths, cutoff="2026-01-08") == (
        "brain/journal/2026/01/14.md",
        "brain/journal/2026/01/10.md",
    )
    # Exactly seven days old is kept; eight is dropped.
    assert select_journal(paths[:2], cutoff="2026-01-08") == ("brain/journal/2026/01/08.md",)


def test_keeps_journal_when_path_date_invalid() -> None:
    # Not a calendar day (February 30) and not a datetime.date year (0): both undated, kept.
    paths = [
        "brain/journal/2026/02/30.md",
        "brain/journal/2026/01/01.md",
        "brain/journal/0000/01/05.md",
    ]

    assert select_journal(paths, cutoff="2026-01-08") == (
        "brain/journal/2026/02/30.md",
        "brain/journal/0000/01/05.md",
    )


def test_keeps_journal_when_path_undated() -> None:
    assert select_journal(["brain/journal/1/2/03.md"], cutoff="2026-01-08") == (
        "brain/journal/1/2/03.md",
    )


def test_names_day_when_path_given() -> None:
    assert journal_day("brain/journal/2026/01/14.md") == "2026-01-14"


@pytest.mark.parametrize(
    ("state", "line"),
    [
        (a_repo(checkout=False), "- api: not found"),
        (
            a_repo(branch="detached@dd68590", dirty=0, behind=""),
            "- api: detached@dd68590, 0 changed file(s), ? behind origin/trunk",
        ),
        (a_repo(), "- api: trunk, 2 changed file(s), 1 behind origin/trunk"),
    ],
    ids=["not-found", "detached", "behind"],
)
def test_formats_repo_line_when_state_given(state: RepoState, line: str) -> None:
    assert repo_line(state, network=True) == line


def test_cuts_prs_when_more_than_four() -> None:
    prs = "#41 Add login\n#40 " + "y" * 80 + "\n#38 Fix\n#37 Bump\n#35 Fifth\n"

    line = repo_line(a_repo(prs=prs), network=True)

    assert (
        line.split("\n")[1]
        == "  open PRs: #41 Add login | #40 " + "y" * 66 + " | #38 Fix | #37 Bump"
    )


def test_sorts_failing_names_when_ci_failed() -> None:
    # Quirk kept (spec Q-5): "main" whatever the default branch is.
    line = repo_line(a_repo(ci="lint\nbuild\nlint\n"), network=True)

    assert line.split("\n")[1] == "  ⚠ failing on main: build, lint"


def test_skips_pr_and_ci_lines_when_network_off() -> None:
    state = a_repo(prs="#1 x\n", ci="lint\n")

    assert (
        repo_line(state, network=False) == "- api: trunk, 2 changed file(s), 1 behind origin/trunk"
    )


def test_truncates_when_over_max_chars() -> None:
    long_now = "---\nlast_verified: 2026-01-14\n---\n# Now\n" + "z" * 6000 + "\n"

    text = render_brief(inputs(now_text=long_now))

    assert len(text) == 5500 - 20 + len("\n…(truncated)")
    assert text.endswith("z\n…(truncated)")
    assert len(render_brief(inputs())) < 5500
