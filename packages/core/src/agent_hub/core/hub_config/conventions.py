"""Branch and title patterns: their grammar, their checks and a repo's effective conventions.

A pattern is literal text and placeholders ``{name}``. ``project.conventions`` sets the
defaults and ``repos[].conventions`` overrides them key by key; an absent key keeps today's
shape. This module is pure and knows nothing of the model: the model passes its own
``BranchName`` pattern in and gives its layers through ``ConventionsLike``.
"""

import re
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import NamedTuple, Protocol

DEFAULT_BRANCH = "{prefix}{issue_lower}-{slug}"
DEFAULT_COMMIT_TITLE = "{type}({scope}): {summary} ({ISSUE})"
# An unset pr_title follows the effective commit_title (owner decision O4 = b), so an
# unconfigured repo keeps today's title only while the two defaults are equal.
DEFAULT_PR_TITLE = DEFAULT_COMMIT_TITLE
BRANCH_PLACEHOLDERS = ("prefix", "ISSUE", "issue_lower", "slug")
TITLE_PLACEHOLDERS = ("ISSUE", "type", "scope", "summary")
MAX_PATTERN_CHARS = 120
SLUG_SEPARATORS = "-_./"

# Any brace-free name is a token, so a bad name gets the unknown-placeholder message; the class
# excludes both braces, so the match is linear.
_PLACEHOLDER = re.compile(r"\{([^{}]*)\}")
# Control, format (bidi overrides) and line or paragraph separators: none may sit in a title.
_TITLE_REFUSED_CATEGORIES = frozenset({"Cc", "Cf", "Zl", "Zp"})
_BRANCH_LITERAL = re.compile(r"[A-Za-z0-9._/-]")
_BRACES = "{}"
# The sample values the model renders a branch pattern with: prefix, issue and both slugs.
_SAMPLE_PREFIX = "me/"
_SAMPLE_ISSUE = "ABC-1"
_SAMPLE_SLUGS = ("x", "")

LONG_MESSAGE = f"pattern is longer than {MAX_PATTERN_CHARS} characters"
BRANCH_LITERAL_MESSAGE = "only letters, digits and . _ / - may appear outside a placeholder"
TITLE_LITERAL_MESSAGE = "a backtick or a control character may not appear outside a placeholder"
BRACE_MESSAGE = "a { or } may appear only as part of a placeholder"
BRANCH_REQUIRED_MESSAGE = "a branch needs {ISSUE} or {issue_lower}"
TITLE_REQUIRED_MESSAGE = "a title needs {summary}"


class PatternError(ValueError):
    """A pattern holds a ``{`` or ``}`` outside a placeholder."""


class PatternPart(NamedTuple):
    """One piece of a pattern: a literal (``placeholder`` None) or a placeholder token."""

    text: str
    placeholder: str | None


class ConventionsLike(Protocol):
    """One layer of conventions (the project's or a repo's); None means the key is absent."""

    @property
    def branch(self) -> str | None: ...

    @property
    def commit_title(self) -> str | None: ...

    @property
    def pr_title(self) -> str | None: ...


@dataclass(frozen=True)
class EffectiveConventions:
    """A repo's patterns after layering, and whether its titles are configured.

    ``titles_configured``: some layer sets ``commit_title`` or ``pr_title`` (a branch alone
    does not count). ``pr_title_explicit``: some layer sets ``pr_title``; otherwise it is the
    effective ``commit_title``.
    """

    branch: str
    commit_title: str
    pr_title: str
    titles_configured: bool
    pr_title_explicit: bool


def pattern_parts(pattern: str) -> tuple[PatternPart, ...]:
    """Split ``pattern`` into literals and ``{name}`` tokens, in order, with no empty literal.

    Raises ``PatternError`` when a literal holds a ``{`` or ``}``. Placeholder names are not
    checked here.
    """
    parts: list[PatternPart] = []
    start = 0
    for match in _PLACEHOLDER.finditer(pattern):
        _append_literal(parts, pattern[start : match.start()])
        parts.append(PatternPart(text=match.group(0), placeholder=match.group(1)))
        start = match.end()
    _append_literal(parts, pattern[start:])
    return tuple(parts)


def _append_literal(parts: list[PatternPart], text: str) -> None:
    if any(brace in text for brace in _BRACES):
        raise PatternError(BRACE_MESSAGE)
    if text:
        parts.append(PatternPart(text=text, placeholder=None))


def fill_pattern(parts: tuple[PatternPart, ...], values: Mapping[str, str]) -> str:
    """Substitute each placeholder with its value.

    When the slug is empty, one separator (``-``, ``_``, ``.`` or ``/``) that ends the literal
    right before ``{slug}`` is dropped too, so ``{issue_lower}-{slug}`` gives ``dem-7``.
    """
    drops_separator = values.get("slug") == ""
    pieces: list[str] = []
    for index, part in enumerate(parts):
        if part.placeholder is not None:
            pieces.append(values[part.placeholder])
            continue
        following = parts[index + 1] if index + 1 < len(parts) else None
        before_slug = following is not None and following.placeholder == "slug"
        if drops_separator and before_slug and part.text[-1] in SLUG_SEPARATORS:
            pieces.append(part.text[:-1])
        else:
            pieces.append(part.text)
    return "".join(pieces)


def branch_pattern_problem(pattern: str, *, branch_name: re.Pattern[str]) -> str | None:
    """The first problem of a branch pattern, or None.

    Checks, in order: length, literal characters, braces, unknown, repeated and required
    placeholders, then a render with sample values matched against ``branch_name``.
    """
    problem = _shape_problem(
        pattern,
        literal_problem=_branch_literal_problem,
        allowed=BRANCH_PLACEHOLDERS,
    )
    if problem is not None:
        return problem
    parts = pattern_parts(pattern)
    names = {part.placeholder for part in parts}
    if not names & {"ISSUE", "issue_lower"}:
        return BRANCH_REQUIRED_MESSAGE
    for slug in _SAMPLE_SLUGS:
        sample = fill_pattern(
            parts,
            {
                "prefix": _SAMPLE_PREFIX,
                "ISSUE": _SAMPLE_ISSUE,
                "issue_lower": _SAMPLE_ISSUE.lower(),
                "slug": slug,
            },
        )
        if branch_name.fullmatch(sample) is None:
            return f"renders to an invalid branch name ({sample})"
    return None


def title_pattern_problem(pattern: str) -> str | None:
    """The first problem of a commit or PR title pattern, or None.

    Checks, in order: length, literal characters, braces, unknown, repeated and required
    placeholders (``{summary}``; ``{ISSUE}`` may be left out).
    """
    problem = _shape_problem(
        pattern,
        literal_problem=_title_literal_problem,
        allowed=TITLE_PLACEHOLDERS,
    )
    if problem is not None:
        return problem
    if all(part.placeholder != "summary" for part in pattern_parts(pattern)):
        return TITLE_REQUIRED_MESSAGE
    return None


def _shape_problem(
    pattern: str,
    *,
    literal_problem: Callable[[str], str | None],
    allowed: tuple[str, ...],
) -> str | None:
    if len(pattern) > MAX_PATTERN_CHARS:
        return LONG_MESSAGE
    literal = literal_problem(_PLACEHOLDER.sub("", pattern))
    if literal is not None:
        return literal
    try:
        parts = pattern_parts(pattern)
    except PatternError as error:
        return str(error)
    names = [part.placeholder for part in parts if part.placeholder is not None]
    unknown = next((name for name in names if name not in allowed), None)
    if unknown is not None:
        known = ", ".join(f"{{{name}}}" for name in allowed)
        return f"unknown placeholder {{{unknown}}}; use {known}"
    repeated = next((name for index, name in enumerate(names) if name in names[:index]), None)
    if repeated is not None:
        return f"placeholder {{{repeated}}} appears twice"
    return None


def _branch_literal_problem(literal: str) -> str | None:
    # Braces get their own message, from the brace check that follows.
    if all(char in _BRACES or _BRANCH_LITERAL.fullmatch(char) for char in literal):
        return None
    return BRANCH_LITERAL_MESSAGE


def _title_literal_problem(literal: str) -> str | None:
    if any(
        char == "`" or unicodedata.category(char) in _TITLE_REFUSED_CATEGORIES for char in literal
    ):
        return TITLE_LITERAL_MESSAGE
    return None


def effective_conventions(
    project: ConventionsLike | None, repo: ConventionsLike | None
) -> EffectiveConventions:
    """Layer a repo's conventions over the project's, key by key, over today's defaults.

    ``branch`` and ``commit_title``: the repo's, else the project's, else the default.
    ``pr_title``: the repo's, else the project's, else the effective ``commit_title``.
    """
    layers = [layer for layer in (repo, project) if layer is not None]
    branch = _first(layer.branch for layer in layers)
    commit_title = _first(layer.commit_title for layer in layers)
    pr_title = _first(layer.pr_title for layer in layers)
    effective_commit_title = DEFAULT_COMMIT_TITLE if commit_title is None else commit_title
    return EffectiveConventions(
        branch=DEFAULT_BRANCH if branch is None else branch,
        commit_title=effective_commit_title,
        pr_title=effective_commit_title if pr_title is None else pr_title,
        titles_configured=commit_title is not None or pr_title is not None,
        pr_title_explicit=pr_title is not None,
    )


def _first(values: Iterable[str | None]) -> str | None:
    return next((value for value in values if value is not None), None)
