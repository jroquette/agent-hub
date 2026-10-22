"""``repos.ui_paths``: each ``repos[].ui_paths`` glob matches a file of the repo's checkout.

A glob is matched against each listed path, relative to the checkout root: ``*`` stays inside
one folder, ``**`` spans folders, hidden names count. A glob matching no listed file is one
warning; a repo without the key, a missing or unlistable checkout and a failed config give
none. Every text here is synthetic (AGENTS.md rule 4).
"""

from collections.abc import Callable

import pytest

from agent_hub.core.doctor.finding import Finding, Read
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.repo_ui_paths_rule import REPOS_UI_PATHS
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

type SnapshotFactory = Callable[..., DoctorSnapshot]

FIX = "fix the glob or remove it; ui_paths globs match paths from the repo root (docs/design/project-config.md)"


def a_config(*repos: tuple[str, list[str] | None]) -> HubConfig:
    """``a_hub_document`` whose repos are ``(dir, ui_paths)``; ``None`` leaves the key out."""
    document = a_hub_document()
    document["guard"] = {}
    document["repos"] = [
        a_second_repo() | {"dir": repo_dir} | ({} if globs is None else {"ui_paths": globs})
        for repo_dir, globs in repos
    ]
    return HubConfig.model_validate(document)


def found(snapshot: DoctorSnapshot) -> list[Finding]:
    return list(REPOS_UI_PATHS.check(snapshot))


def unmatched(index: int, glob_index: int, glob: str, repo_dir: str) -> Finding:
    return Finding(
        rule="repos.ui_paths",
        severity=Severity.WARNING,
        path="hub.json",
        line=None,
        message=f"repos[{index}].ui_paths[{glob_index}]: {glob} matches no file in ../{repo_dir}",
        fix=FIX,
    )


WEB_FILES = {
    "apps/web/src/main.tsx": b"x",
    "apps/web/.storybook/main.ts": b"x",
    "README.md": b"x",
}


def test_declares_design_fields_when_repo_ui_paths_rule_read() -> None:
    assert REPOS_UI_PATHS.id == "repos.ui_paths"
    assert REPOS_UI_PATHS.severity is Severity.WARNING
    assert REPOS_UI_PATHS.reads == frozenset({Read.REPOS})
    assert REPOS_UI_PATHS.module is None
    assert REPOS_UI_PATHS in REGISTRY


@pytest.mark.parametrize(
    "glob",
    ["apps/web/**", "apps/**/*.tsx", "apps/web/src/main.tsx", "*.md", "apps/web/.storybook/*"],
    ids=["folder", "deep", "exact", "root glob", "hidden folder"],
)
def test_passes_repo_ui_paths_when_glob_matches_listed_file(
    snapshot_of: SnapshotFactory, glob: str
) -> None:
    snapshot = snapshot_of(config=a_config(("web", [glob])), repos={"web": WEB_FILES})

    assert found(snapshot) == []


def test_warns_each_unmatched_glob_when_repo_ui_paths_checked(
    snapshot_of: SnapshotFactory,
) -> None:
    # "*.tsx" stays in the root folder, "apps/we*" names a folder, never a file.
    snapshot = snapshot_of(
        config=a_config(
            ("api", None), ("web", ["apps/web/**", "*.tsx", "apps/we*", "apps/mobile/**"])
        ),
        repos={"api": {"README.md": b"x"}, "web": WEB_FILES},
    )

    assert found(snapshot) == [
        unmatched(1, 1, "*.tsx", "web"),
        unmatched(1, 2, "apps/we*", "web"),
        unmatched(1, 3, "apps/mobile/**", "web"),
    ]


def test_warns_repo_ui_paths_when_file_not_listed(snapshot_of: SnapshotFactory) -> None:
    # Present but not listed (gitignored): only the listing counts, as for the other repo rules.
    snapshot = snapshot_of(
        config=a_config(("web", ["dist/**"])),
        repos={"web": {"dist/app.js": b"x", "README.md": b"x"}},
        repo_listed={"web": ("README.md",)},
    )

    assert found(snapshot) == [unmatched(0, 0, "dist/**", "web")]


def test_cuts_echo_when_repo_ui_paths_glob_long(snapshot_of: SnapshotFactory) -> None:
    glob = "x" * 150 + "/**"
    snapshot = snapshot_of(config=a_config(("web", [glob])), repos={"web": WEB_FILES})

    [finding] = found(snapshot)

    assert finding.message == f"repos[0].ui_paths[0]: {'x' * 79}… matches no file in ../web"


@pytest.mark.parametrize(
    ("files", "problems"),
    [(None, {}), ({}, {"web": "could not list the files: x"})],
    ids=["missing", "unlistable"],
)
def test_skips_repo_ui_paths_checkout_when_missing_or_unlistable(
    snapshot_of: SnapshotFactory, files: dict[str, bytes] | None, problems: dict[str, str]
) -> None:
    snapshot = snapshot_of(
        config=a_config(("web", ["apps/web/**"])), repos={"web": files}, repo_problems=problems
    )

    assert found(snapshot) == []


def test_skips_repo_ui_paths_when_config_failed(snapshot_of: SnapshotFactory) -> None:
    snapshot = snapshot_of(
        config=ConfigFailure(problems=(), pin=None), repos={"demo-api": {"README.md": b"x"}}
    )

    assert found(snapshot) == []
