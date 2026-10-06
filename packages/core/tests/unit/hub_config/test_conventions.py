import re
from dataclasses import dataclass
from pathlib import Path

import pytest
from pydantic import TypeAdapter

from agent_hub.core.hub_config.conventions import (
    DEFAULT_BRANCH,
    DEFAULT_COMMIT_TITLE,
    DEFAULT_PR_TITLE,
    MAX_PATTERN_CHARS,
    EffectiveConventions,
    PatternError,
    PatternPart,
    branch_pattern_problem,
    effective_conventions,
    fill_pattern,
    pattern_parts,
    title_pattern_problem,
)
from agent_hub.core.hub_config.model import BranchName

# The model passes its own BranchName pattern; the tests read the same one through its schema.
BRANCH_NAME = re.compile(TypeAdapter(BranchName).json_schema()["pattern"])

BRANCH_UNKNOWN = "use {prefix}, {ISSUE}, {issue_lower}, {slug}"
TITLE_UNKNOWN = "use {ISSUE}, {type}, {scope}, {summary}"
LONG = "pattern is longer than 120 characters"
BRANCH_LITERAL = "only letters, digits and . _ / - may appear outside a placeholder"
TITLE_LITERAL = "a backtick or a control character may not appear outside a placeholder"
BRACES = "a { or } may appear only as part of a placeholder"
TOUCHING = "placeholders need a literal between them"


@dataclass(frozen=True)
class Layer:
    branch: str | None = None
    commit_title: str | None = None
    pr_title: str | None = None


def branch_problem(pattern: str) -> str | None:
    return branch_pattern_problem(pattern, branch_name=BRANCH_NAME)


def test_splits_pattern_into_literals_and_placeholders_when_parsed() -> None:
    assert pattern_parts("a/{ISSUE}-x{slug}") == (
        PatternPart(text="a/", placeholder=None),
        PatternPart(text="{ISSUE}", placeholder="ISSUE"),
        PatternPart(text="-x", placeholder=None),
        PatternPart(text="{slug}", placeholder="slug"),
    )


@pytest.mark.parametrize("pattern", ["a{b", "a}b", "{ISSUE", "{ISSUE}}"])
def test_refuses_pattern_when_brace_unmatched(pattern: str) -> None:
    with pytest.raises(
        PatternError, match=r"^a \{ or \} may appear only as part of a placeholder$"
    ):
        pattern_parts(pattern)


@pytest.mark.parametrize(
    ("pattern", "slug", "expected"),
    [
        ("{issue_lower}-{slug}", "", "dem-7"),
        ("{issue_lower}_{slug}", "", "dem-7"),
        ("{issue_lower}.{slug}", "", "dem-7"),
        ("feature/{issue_lower}/{slug}", "", "feature/dem-7"),
        ("{issue_lower}--{slug}", "", "dem-7-"),
        ("{issue_lower}{slug}", "", "dem-7"),
        ("{issue_lower}x{slug}", "", "dem-7x"),
        ("{issue_lower}-{slug}", "x", "dem-7-x"),
        ("{issue_lower}/{slug}", "x", "dem-7/x"),
    ],
)
def test_drops_one_separator_before_slug_when_slug_empty(
    pattern: str, slug: str, expected: str
) -> None:
    values = {"issue_lower": "dem-7", "slug": slug}

    assert fill_pattern(pattern_parts(pattern), values) == expected


@pytest.mark.parametrize(
    "pattern",
    [
        DEFAULT_BRANCH,
        "{prefix}{ISSUE}-{slug}",
        "feature/{issue_lower}/{slug}",
        "{prefix}{issue_lower}",
        "claude/{issue_lower}",
    ],
)
def test_accepts_branch_pattern_when_shape_valid(pattern: str) -> None:
    assert branch_problem(pattern) is None


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("{prefix}{slug}", "a branch needs {ISSUE} or {issue_lower}"),
        ("{prefix}{type}-{ISSUE}", f"unknown placeholder {{type}}; {BRANCH_UNKNOWN}"),
        ("{prefix}{ISSUE}{foo}", f"unknown placeholder {{foo}}; {BRANCH_UNKNOWN}"),
        ("{ISSUE}-{ISSUE}", "placeholder {ISSUE} appears twice"),
        ("{prefix}{ISSUE} x", "only letters, digits and . _ / - may appear outside a placeholder"),
        ("{prefix}~{ISSUE}", "only letters, digits and . _ / - may appear outside a placeholder"),
        ("{prefix}{ISSUE}..{slug}", "renders to an invalid branch name (me/ABC-1..x)"),
        ("{prefix}@{ISSUE}", "only letters, digits and . _ / - may appear outside a placeholder"),
        ("{prefix}{issue_lower}-{slug}-", "renders to an invalid branch name (me/abc-1-x-)"),
        ("{prefix}{issue_lower}{", "a { or } may appear only as part of a placeholder"),
        ("{prefix}{ISSUE}{foo-bar}", f"unknown placeholder {{foo-bar}}; {BRANCH_UNKNOWN}"),
        ("{prefix}{ISSUE}{}", f"unknown placeholder {{}}; {BRANCH_UNKNOWN}"),
        ("a" * 121 + "{ISSUE}", LONG),
    ],
)
def test_names_problem_when_branch_pattern_invalid(pattern: str, expected: str) -> None:
    assert branch_problem(pattern) == expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("{prefix}{slug}-{issue_lower}", "me/-abc-1"),
        ("{slug}/{issue_lower}", "/abc-1"),
        ("{slug}-{issue_lower}", "-abc-1"),
    ],
)
def test_names_empty_slug_render_when_only_it_is_invalid(pattern: str, expected: str) -> None:
    assert branch_problem(pattern) == f"renders to an invalid branch name ({expected})"


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("{slug} {summary}", f"unknown placeholder {{slug}}; {TITLE_UNKNOWN}"),
        ("{prefix}{summary}", f"unknown placeholder {{prefix}}; {TITLE_UNKNOWN}"),
        ("{foo}{summary}", f"unknown placeholder {{foo}}; {TITLE_UNKNOWN}"),
        ("{summary} {summary}", "placeholder {summary} appears twice"),
        ("{type}: x", "a title needs {summary}"),
        ("{summary} `x`", "a backtick or a control character may not appear outside a placeholder"),
        ("{summary} {", "a { or } may appear only as part of a placeholder"),
        ("{summary}\x07", TITLE_LITERAL),
        ("{summary}\x7f", TITLE_LITERAL),
        ("{summary}\u2028x", TITLE_LITERAL),
        ("{summary}\u2029", TITLE_LITERAL),
        ("{summary}\u202e", TITLE_LITERAL),
        ("{summary2}", f"unknown placeholder {{summary2}}; {TITLE_UNKNOWN}"),
        ("{summary} {foo bar}", f"unknown placeholder {{foo bar}}; {TITLE_UNKNOWN}"),
        ("{summary}" + "a" * 112, LONG),
        ("{type}{scope}: {summary}", TOUCHING),
        ("{type}{summary}", TOUCHING),
        ("{summary}{ISSUE}", TOUCHING),
    ],
)
def test_names_problem_when_title_pattern_invalid(pattern: str, expected: str) -> None:
    assert title_pattern_problem(pattern) == expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("a" * 120 + " {ISSUE}", LONG),
        ("{ISSUE} {", BRANCH_LITERAL),
        ("{ISSUE}{", BRACES),
        ("{foo}{foo}{ISSUE}", f"unknown placeholder {{foo}}; {BRANCH_UNKNOWN}"),
        ("{foo}", f"unknown placeholder {{foo}}; {BRANCH_UNKNOWN}"),
        ("{slug}{slug}", "placeholder {slug} appears twice"),
        ("{prefix}{slug}-", "a branch needs {ISSUE} or {issue_lower}"),
    ],
)
def test_names_first_problem_when_branch_pattern_has_several(pattern: str, expected: str) -> None:
    """Length, characters, braces, unknown, repeated, required, then the sample render."""
    assert branch_problem(pattern) == expected


@pytest.mark.parametrize(
    ("pattern", "expected"),
    [
        ("`" * 121, LONG),
        ("{type}`", TITLE_LITERAL),
        ("{type}\x07{", TITLE_LITERAL),
        ("{type}{", BRACES),
        ("{foo}{foo}", f"unknown placeholder {{foo}}; {TITLE_UNKNOWN}"),
        ("{type}{type}", "placeholder {type} appears twice"),
        ("{type}{foo}: {summary}", f"unknown placeholder {{foo}}; {TITLE_UNKNOWN}"),
        ("{type}{summary} {type}", "placeholder {type} appears twice"),
        ("{type}{scope}: x", TOUCHING),
    ],
)
def test_names_first_problem_when_title_pattern_has_several(pattern: str, expected: str) -> None:
    """Length, characters, braces, unknown, repeated, touching, then required."""
    assert title_pattern_problem(pattern) == expected


def test_caps_pattern_at_literal_length_when_checked() -> None:
    assert MAX_PATTERN_CHARS == 120
    assert branch_problem("a" * 113 + "{ISSUE}") is None
    assert branch_problem("a" * 114 + "{ISSUE}") == LONG
    assert title_pattern_problem("a" * 111 + "{summary}") is None
    assert title_pattern_problem("a" * 112 + "{summary}") == LONG


@pytest.mark.parametrize(
    "pattern",
    [
        DEFAULT_COMMIT_TITLE,
        "{type}({scope}): {summary}",
        "{ISSUE}: {summary}",
        "{ISSUE}: {type}({scope}): {summary}",
    ],
)
def test_accepts_title_pattern_when_shape_valid(pattern: str) -> None:
    assert title_pattern_problem(pattern) is None


@pytest.mark.parametrize(
    ("project", "repo", "expected"),
    [
        (None, None, (DEFAULT_BRANCH, DEFAULT_COMMIT_TITLE)),
        (Layer(), Layer(), (DEFAULT_BRANCH, DEFAULT_COMMIT_TITLE)),
        (Layer(branch="p/{ISSUE}", commit_title="P {summary}"), None, ("p/{ISSUE}", "P {summary}")),
        (
            Layer(branch="p/{ISSUE}"),
            Layer(commit_title="R {summary}"),
            ("p/{ISSUE}", "R {summary}"),
        ),
        (
            Layer(branch="p/{ISSUE}", commit_title="P {summary}"),
            Layer(branch="r/{ISSUE}", commit_title="R {summary}"),
            ("r/{ISSUE}", "R {summary}"),
        ),
        (None, Layer(branch="r/{ISSUE}"), ("r/{ISSUE}", DEFAULT_COMMIT_TITLE)),
    ],
)
def test_takes_repo_then_project_then_default_when_effective_conventions_built(
    project: Layer | None, repo: Layer | None, expected: tuple[str, str]
) -> None:
    """``expected`` is the effective ``(branch, commit_title)``."""
    effective = effective_conventions(project, repo)

    assert (effective.branch, effective.commit_title) == expected


@pytest.mark.parametrize(
    ("project", "repo", "expected"),
    [
        (None, None, (DEFAULT_COMMIT_TITLE, DEFAULT_COMMIT_TITLE, False)),
        (Layer(commit_title="P {summary}"), None, ("P {summary}", "P {summary}", False)),
        (
            Layer(commit_title="P {summary}"),
            Layer(commit_title="R {summary}"),
            ("R {summary}", "R {summary}", False),
        ),
        (
            Layer(pr_title="PP {summary}"),
            Layer(commit_title="R {summary}"),
            ("R {summary}", "PP {summary}", True),
        ),
        (None, Layer(pr_title="RP {summary}"), (DEFAULT_COMMIT_TITLE, "RP {summary}", True)),
        (
            Layer(pr_title="PP {summary}"),
            Layer(pr_title="RP {summary}"),
            (DEFAULT_COMMIT_TITLE, "RP {summary}", True),
        ),
    ],
    ids=[
        "nothing-set",
        "project-commit-only",
        "repo-commit-over-project-commit",
        "project-pr-over-repo-commit",
        "repo-pr-only",
        "repo-pr-over-project-pr",
    ],
)
def test_layers_pr_title_over_effective_commit_title_when_built(
    project: Layer | None, repo: Layer | None, expected: tuple[str, str, bool]
) -> None:
    """E14 (owner O4 = b): an unset pr_title follows the effective commit_title.

    ``expected`` is the effective ``(commit_title, pr_title, pr_title_explicit)``.
    """
    effective = effective_conventions(project, repo)

    assert (effective.commit_title, effective.pr_title, effective.pr_title_explicit) == expected


def test_equals_default_commit_title_when_default_pr_title_read() -> None:
    assert DEFAULT_COMMIT_TITLE == "{type}({scope}): {summary} ({ISSUE})"
    assert DEFAULT_PR_TITLE == "{type}({scope}): {summary} ({ISSUE})"
    assert DEFAULT_BRANCH == "{prefix}{issue_lower}-{slug}"


@pytest.mark.parametrize(
    ("project", "repo"),
    [
        (Layer(commit_title="{summary}"), None),
        (Layer(pr_title="{summary}"), None),
        (None, Layer(commit_title="{summary}")),
        (None, Layer(pr_title="{summary}")),
    ],
)
def test_flags_titles_configured_when_either_title_key_set(
    project: Layer | None, repo: Layer | None
) -> None:
    assert effective_conventions(project, repo).titles_configured is True


@pytest.mark.parametrize(
    ("project", "repo"),
    [(Layer(branch="{ISSUE}"), Layer(branch="{issue_lower}")), (Layer(), Layer()), (None, None)],
)
def test_leaves_titles_unconfigured_when_only_branch_or_nothing_set(
    project: Layer | None, repo: Layer | None
) -> None:
    assert effective_conventions(project, repo).titles_configured is False


def test_builds_frozen_value_when_effective_conventions_built() -> None:
    effective = effective_conventions(None, None)

    assert effective == EffectiveConventions(
        branch=DEFAULT_BRANCH,
        commit_title=DEFAULT_COMMIT_TITLE,
        pr_title=DEFAULT_PR_TITLE,
        titles_configured=False,
        pr_title_explicit=False,
    )
    with pytest.raises(AttributeError):
        effective.branch = "x"  # type: ignore[misc]


# AC-57.14 (plan § Design 6, E2, E10): each repo's conventions have one source, the model's
# conventions_for (and project_conventions, sets_conventions); its branch has one builder,
# worktree_branch over render_branch. A module path ``hub_config.conventions`` is no read.
CONVENTIONS_READ = re.compile(r"(?<!hub_config)\.conventions\b")
BRANCH_BUILD = re.compile(r"\{(?:self\.|cfg\.)?(?:branch_)?prefix\}\{|@@\{project_branch_prefix\}<")

CORE = "core/src/agent_hub/core"
TEMPLATES = "generator/src/agent_hub/generator/templates"

# Lines per file that may name ``.conventions``; every other consumer calls the model's helpers.
CONVENTIONS_READERS = {
    # conventions_for, project_conventions, sets_conventions and the pairing check read the two
    # keys; the repo key's schema description, two docstrings and the pairing message name them
    f"{CORE}/hub_config/model.py": 9,
    # the module docstring names the two keys
    f"{CORE}/hub_config/conventions.py": 2,
    # each repo's own keys, which its Conventions line lists (the one raw read outside the model)
    f"{CORE}/workspace/shown_conventions.py": 1,
    # the module docstring and the Conventions block's lead text name the keys; the values come
    # from shown_conventions only
    "generator/src/agent_hub/generator/placeholders.py": 2,
    # RunChildren.conventions, the repo's effective conventions (conventions_for): its branch
    # and the prompt's commit title
    "cli/src/agent_hub/cli/run_children.py": 2,
    # the PR title step reads RunChildren.conventions
    "cli/src/agent_hub/cli/run_steps.py": 1,
}

# Lines per file that build a branch as the prefix followed by a name.
BRANCH_BUILDERS = {
    # the default branch pattern itself, which render_branch fills
    f"{CORE}/hub_config/conventions.py": 1,
    # the mixed hub's project branch pattern, a test builder's data
    f"{CORE}/testing/builders.py": 1,
    # hint text, unchanged (R-7, AGH-68): doctor branch_shape
    f"{CORE}/doctor/text_rules.py": 1,
    # hint text, unchanged (R-7, AGH-68): the guard's _branch_hint
    f"{TEMPLATES}/plugin/hub-workflow/hooks/guard.py.tmpl": 1,
}


def scan_sources(pattern: re.Pattern[str]) -> tuple[dict[str, int], str]:
    """Hits of ``pattern`` in ``packages/*/src`` (``.py``, ``.tmpl``): counts per file, and
    every hit as ``file:line: text``."""
    packages = Path(__file__).resolve().parents[4]
    sources = [
        source
        for source in sorted(packages.glob("*/src/**/*"))
        if source.is_file() and source.suffix in {".py", ".tmpl"}
    ]
    # an empty scan would pass anywhere
    assert f"{CORE}/hub_config/model.py" in {s.relative_to(packages).as_posix() for s in sources}
    hits = [
        (source.relative_to(packages).as_posix(), number, line.strip())
        for source in sources
        for number, line in enumerate(source.read_text(encoding="utf-8").splitlines(), 1)
        if pattern.search(line)
    ]
    counts: dict[str, int] = {}
    for name, _number, _line in hits:
        counts[name] = counts.get(name, 0) + 1
    return counts, "\n".join(f"{name}:{number}: {line}" for name, number, line in hits)


def test_reads_conventions_only_in_allowed_files_when_sources_scanned() -> None:
    counts, hits = scan_sources(CONVENTIONS_READ)

    assert counts == CONVENTIONS_READERS, hits


def test_builds_branch_only_in_allowed_files_when_sources_scanned() -> None:
    counts, hits = scan_sources(BRANCH_BUILD)

    assert counts == BRANCH_BUILDERS, hits
