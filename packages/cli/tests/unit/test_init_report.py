from dataclasses import replace

import pytest

from agent_hub.cli.init_report import created_lines, next_steps, shown_path
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock
from agent_hub.core.hub_files.plan_init import InitPlan
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document

ROOT = "/work/demo-hub"


def a_plan(**counts: int) -> InitPlan:
    """A plan whose path tuples hold ``counts[name]`` made-up paths each; the rest empty."""
    document = a_hub_document()
    del document["modules"]
    config = HubConfig.model_validate(document)
    plan = InitPlan(
        leftovers=(),
        folders=(),
        writes=(),
        created_managed=(),
        created_seeded=(),
        created_links=(),
        kept_seeded=(),
        kept_equal=(),
        kept_links=(),
        lock=build_hub_lock(rendered=RenderedHub(files=(), links=()), config=config),
    )
    paths = {
        name: tuple(f"{name}/{index}" for index in range(count)) for name, count in counts.items()
    }
    return replace(plan, **paths)


def test_prints_created_line_when_empty_target_written() -> None:
    plan = a_plan(created_managed=38, created_seeded=20, created_links=14)

    assert created_lines(plan, ROOT) == [
        "created 58 files (38 managed, 20 seeded) and 14 links in /work/demo-hub"
    ]


@pytest.mark.parametrize(
    ("counts", "kept_line"),
    [
        ({}, None),
        (
            {"kept_seeded": 3, "kept_equal": 0},
            "kept 3 files already there (3 seeded, 0 equal to the render)",
        ),
        (
            {"kept_seeded": 1, "kept_equal": 2},
            "kept 3 files already there (1 seeded, 2 equal to the render)",
        ),
        (
            {"kept_seeded": 1, "kept_equal": 2, "kept_links": 4},
            "kept 3 files already there (1 seeded, 2 equal to the render) and 4 links",
        ),
        (
            {"kept_links": 2},
            "kept 0 files already there (0 seeded, 0 equal to the render) and 2 links",
        ),
    ],
    ids=["nothing-kept", "seeded-only", "seeded-and-equal", "with-links", "links-only"],
)
def test_prints_kept_line_only_when_files_kept(
    counts: dict[str, int], kept_line: str | None
) -> None:
    plan = a_plan(created_managed=2, created_seeded=1, created_links=1, **counts)

    lines = created_lines(plan, ROOT)

    assert lines[0] == "created 3 files (2 managed, 1 seeded) and 1 links in /work/demo-hub"
    assert lines[1:] == ([] if kept_line is None else [kept_line])


def test_prints_removed_line_when_leftovers_removed() -> None:
    plan = a_plan(created_managed=1, kept_equal=1, leftovers=2)

    assert created_lines(plan, ROOT) == [
        "created 1 files (1 managed, 0 seeded) and 0 links in /work/demo-hub",
        "kept 1 files already there (0 seeded, 1 equal to the render)",
        "removed 2 leftover temporary files",
    ]


@pytest.mark.parametrize(
    ("git_present", "expected"),
    [
        (
            False,
            [
                "Next steps:",
                "  1. cd /work/demo-hub",
                "  2. git init",
                "  3. review hub.json, AGENTS.project.md and README.md",
                '  4. git add -A && git commit -m "Create the hub"',
                "  5. start Claude Code in the hub folder: claude",
            ],
        ),
        (
            True,
            [
                "Next steps:",
                "  1. cd /work/demo-hub",
                "  2. review hub.json, AGENTS.project.md and README.md",
                '  3. git add -A && git commit -m "Create the hub"',
                "  4. start Claude Code in the hub folder: claude",
            ],
        ),
    ],
    ids=["git-absent", "git-present"],
)
def test_adds_git_init_step_only_when_git_absent(*, git_present: bool, expected: list[str]) -> None:
    steps = next_steps(ROOT, git_present=git_present)

    assert steps == expected
    # Only what works in this release (spec Q-2).
    assert not any(name in "\n".join(steps) for name in ("./agent", "make agent", "hub sync"))


def test_quotes_root_when_path_has_spaces() -> None:
    root = "/work/my demo's hub"

    assert next_steps(root, git_present=True)[1] == "  1. cd '/work/my demo'\"'\"'s hub'"
    assert created_lines(a_plan(), root) == [
        "created 0 files (0 managed, 0 seeded) and 0 links in /work/my demo's hub"
    ]


@pytest.mark.parametrize(
    ("path", "shown"),
    [
        ("/work/demo-hub", "/work/demo-hub"),
        ("/work/a b", "/work/a b"),
        ("/work/a\nb", '"/work/a\\nb"'),
        ("/work/a\rcreated 1 files", '"/work/a\\rcreated 1 files"'),
        ('/work/a"b', '"/work/a\\"b"'),
        ("/work/Jos\N{LATIN SMALL LETTER E WITH ACUTE}", '"/work/Jos\\u00e9"'),
        ("/work/a\N{LINE SEPARATOR}b", '"/work/a\\u2028b"'),
    ],
    ids=["plain", "space", "newline", "carriage-return", "quote", "non-ascii", "line-separator"],
)
def test_shows_path_escaped_when_unprintable(path: str, shown: str) -> None:
    assert shown_path(path) == shown


def test_keeps_every_line_whole_when_root_unprintable() -> None:
    root = "/work/a\nkept 9 files already there"

    lines = [*created_lines(a_plan(created_managed=1), root), *next_steps(root, git_present=True)]

    assert all("\n" not in line and "\r" not in line for line in lines)
    shown_root = '"/work/a\\nkept 9 files already there"'
    assert lines[0] == f"created 1 files (1 managed, 0 seeded) and 0 links in {shown_root}"
    assert lines[2] == f"  1. cd {shown_root}"
