"""``ui_path_pattern``: a ``repos[].ui_paths`` glob against a repo-relative path (AGH-474)."""

import pytest

from agent_hub.core.hub_config.ui_paths import ui_path_pattern

HIDDEN_FILE = "apps/web/.storybook/main.ts"


@pytest.mark.parametrize(
    "glob",
    ["apps/web/**", "apps/**/main.ts", "apps/web/*/main.ts", "apps/web/.*/main.ts"],
    ids=["recursive", "recursive middle", "one segment", "dot prefix"],
)
def test_matches_hidden_folder_when_wildcard_crosses_it(glob: str) -> None:
    assert ui_path_pattern(glob).fullmatch(HIDDEN_FILE)


@pytest.mark.parametrize(
    ("glob", "path"),
    [
        ("apps/web/*", "apps/web/src/main.ts"),
        ("*.tsx", "src/main.tsx"),
        ("apps/web/**", "apps/web"),
        ("apps/Web/**", "apps/web/main.ts"),
    ],
    ids=["star stays in folder", "root glob", "folder alone", "case sensitive"],
)
def test_matches_nothing_when_glob_does_not_reach_path(glob: str, path: str) -> None:
    assert ui_path_pattern(glob).fullmatch(path) is None
