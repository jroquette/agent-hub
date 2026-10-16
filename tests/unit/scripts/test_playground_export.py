import os
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.playground_export import (
    SCREEN_ROUTES,
    SHELL_ROUTES,
    Commit,
    area_of,
    conductor_log,
    conductor_token,
    group_commits,
    render_brief,
    routes_of,
)

ROUTES_FILE = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "routes.tsx"
SCREENS_DIR = ROUTES_FILE.parent / "screens"


def _commit(sha: str, *files: str, subject: str = "feat(web): a step", body: str = "") -> Commit:
    return Commit(sha, subject, body, datetime(2026, 10, 16, 12, tzinfo=UTC), files)


@pytest.mark.parametrize(
    ("path", "area"),
    [
        ("apps/web/src/screens/skills/Catalog.tsx", "skills"),
        ("apps/web/src/screens/agent-session/model.ts", "agent-session"),
        ("apps/web/src/shell/ShakeToSession.tsx", "shell"),
        ("apps/web/src/components/core.tsx", "shell"),
        ("apps/web/src/lib/devProxy.ts", "shell"),
        ("packages/core/src/agent_hub/core/agent_sessions/driver.py", "core"),
        ("Makefile", "repo"),
        ("docs/adr/0036-live-playground-and-auto-mode.md", "repo"),
    ],
)
def test_places_file_in_first_matching_area_when_grouped(path: str, area: str) -> None:
    assert area_of(path) == area


def test_joins_commit_to_every_group_it_touches_when_grouped() -> None:
    commits = [
        _commit("a" * 40, "apps/web/src/screens/skills/Catalog.tsx", "packages/core/x.py"),
        _commit("b" * 40, "apps/web/src/screens/skills/Catalog.tsx"),
    ]

    groups = group_commits(commits)

    assert [group.name for group in groups] == ["core", "skills"]
    skills = groups[1]
    assert skills.commits == ["a" * 40, "b" * 40]
    assert skills.files == ["apps/web/src/screens/skills/Catalog.tsx"]
    assert skills.screens == ["skills/skills"]
    assert groups[0].screens == []


def test_gives_shell_its_representative_routes_when_routes_asked() -> None:
    assert routes_of("shell") == SHELL_ROUTES
    assert routes_of("core") == ()


def test_maps_every_screen_folder_when_routes_listed() -> None:
    folders = {path.name for path in SCREENS_DIR.iterdir() if path.is_dir()} - {"not-found"}
    assert folders <= set(SCREEN_ROUTES)


def test_lists_requests_then_each_group_when_brief_rendered() -> None:
    commits = [_commit("c" * 40, "apps/web/src/screens/skills/Catalog.tsx", body="Tabs per kind.")]
    groups = group_commits(commits)
    requests = [{"created_at": "2026-10-16T11:00:00+00:00", "title": "Organize the skills page"}]

    brief = render_brief("a" * 40, "c" * 40, groups=groups, commits=commits, requests=requests)

    assert brief.index("Organize the skills page") < brief.index("## skills")
    assert "`cccccccc` feat(web): a step" in brief
    assert "  Tabs per kind." in brief
    assert "`screens/skills/skills.png`" in brief


def test_says_none_found_when_no_request_given() -> None:
    brief = render_brief("a" * 40, "c" * 40, groups=[], commits=[], requests=[])
    assert "- (none found)" in brief


def test_reads_last_token_when_log_holds_several(tmp_path: Path) -> None:
    log = tmp_path / "conductor.log"
    log.write_text(
        "agent-hub at http://127.0.0.1:7420/?token=first_one\nagent-hub at http://127.0.0.1:7420/?token=second-2\n",
        "utf-8",
    )
    assert conductor_token(log) == "second-2"


def test_returns_none_when_log_missing(tmp_path: Path) -> None:
    assert conductor_token(tmp_path / "missing.log") is None


def test_finds_log_in_playground_folder_when_tmpdir_set_or_not() -> None:
    folder = f"agent-hub-playground-{os.getuid()}"

    assert conductor_log({"TMPDIR": "/home/me/tmp"}) == Path(
        "/home/me/tmp", folder, "agent-hub-conductor.log"
    )
    assert conductor_log({"TMPDIR": ""}) == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
    assert conductor_log({}) == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
