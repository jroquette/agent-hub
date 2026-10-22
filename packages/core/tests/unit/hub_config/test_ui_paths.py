"""``ui_path_matches``: a ``repos[].ui_paths`` glob against a repo-relative path (AGH-474)."""

import pytest

from agent_hub.core.hub_config import ui_paths
from agent_hub.core.hub_config.ui_paths import ui_path_matches

HIDDEN_FILE = "apps/web/.storybook/main.ts"


@pytest.mark.parametrize(
    "glob",
    ["apps/web/**", "apps/**/main.ts", "apps/web/*/main.ts", "apps/web/.*/main.ts"],
    ids=["recursive", "recursive middle", "one segment", "dot prefix"],
)
def test_matches_hidden_folder_when_wildcard_crosses_it(glob: str) -> None:
    assert ui_path_matches(glob, HIDDEN_FILE)


@pytest.mark.parametrize(
    ("glob", "path"),
    [
        ("apps/web/**", "apps/web/main.ts"),
        ("apps/web/**", "apps/web/a/b/c.ts"),
        ("apps/**/main.ts", "apps/main.ts"),
        ("**/main.ts", "main.ts"),
        ("**/main.ts", "a/b/main.ts"),
        ("a/**/b/**/c.ts", "a/b/c.ts"),
        ("a/**/b/**/c.ts", "a/x/b/y/z/c.ts"),
        ("src/*.ts?", "src/a.tsx"),
        ("*.vue", "App.vue"),
        ("a**b/x", "aZZb/x"),
    ],
    ids=[
        "trailing recursive",
        "trailing recursive deep",
        "middle recursive zero folders",
        "leading recursive zero folders",
        "leading recursive two folders",
        "two recursives zero folders",
        "two recursives many folders",
        "question mark",
        "root glob",
        "double star inside a name",
    ],
)
def test_matches_path_when_glob_reaches_it(glob: str, path: str) -> None:
    assert ui_path_matches(glob, path)


@pytest.mark.parametrize(
    ("glob", "path"),
    [
        ("apps/web/*", "apps/web/src/main.ts"),
        ("*.tsx", "src/main.tsx"),
        ("apps/web/**", "apps/web"),
        ("apps/Web/**", "apps/web/main.ts"),
        ("src/?.ts", "src/ab.ts"),
        ("a**b/x", "a/b/x"),
        ("apps/web", "apps/web/main.ts"),
    ],
    ids=[
        "star stays in folder",
        "root glob",
        "folder alone",
        "case sensitive",
        "question mark is one character",
        "double star inside a name stays in folder",
        "prefix only",
    ],
)
def test_matches_nothing_when_glob_does_not_reach_path(glob: str, path: str) -> None:
    assert not ui_path_matches(glob, path)


NAME_80 = "a" * 79 + "b"
NAME_254 = "a" * 253 + "b"
DEEP_PATH = "/".join(["d"] * 60) + "/x.ts"
EIGHT_RECURSIVE = "/".join(["**", "d"] * 8) + "/y.ts"


@pytest.mark.parametrize(
    ("glob", "path"),
    [
        ("*a*a*a/*a*a*a", f"{NAME_80}/{NAME_80}"),
        ("*a*a*a/*a*a*a", f"{NAME_254}/{NAME_254}"),
        (EIGHT_RECURSIVE, DEEP_PATH),
    ],
    ids=["stars on 80 characters", "stars on 254 characters", "eight recursives 60 deep"],
)
def test_matches_nothing_when_pathological_glob_fails(glob: str, path: str) -> None:
    assert not ui_path_matches(glob, path)


def test_bounds_segment_matches_when_recursive_globs_fail(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, str]] = []
    real = ui_paths.fnmatchcase

    def counted(name: str, pattern: str) -> bool:
        calls.append((name, pattern))
        return real(name, pattern)

    monkeypatch.setattr(ui_paths, "fnmatchcase", counted)

    assert not ui_path_matches(EIGHT_RECURSIVE, DEEP_PATH)
    # At most one segment match per (glob segment, path segment) pair: 8 ``d`` and one ``y.ts``
    # segment against 61 path segments, never a product over the ``**`` segments.
    assert 0 < len(calls) <= 9 * 61
