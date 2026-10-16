import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.playground_export import (
    SCREEN_ROUTES,
    SHELL_ROUTES,
    Commit,
    area_of,
    attach_requests,
    conductor_log,
    conductor_token,
    delivering_branches,
    git,
    group_commits,
    hub_changes,
    link_session,
    render_brief,
    route_patterns,
    routes_of,
)

ROUTES_FILE = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "routes.tsx"
SCREENS_DIR = ROUTES_FILE.parent / "screens"


def _commit(sha: str, *files: str, subject: str = "feat(web): a step", body: str = "") -> Commit:
    return Commit(sha, subject, body, datetime(2026, 10, 16, 12, tzinfo=UTC), files)


def _bash(command: str) -> dict[str, Any]:
    return {"kind": "tool.call", "body": {"name": "Bash", "input": {"command": command}}}


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


def test_puts_route_in_removed_screens_when_head_routes_lack_it() -> None:
    routes = 'children: [{ path: "sessions", element: <S /> }, { path: "*", element: <N /> }]'
    commits = [
        _commit("d" * 40, "apps/web/src/screens/approvals/index.tsx"),
        _commit("e" * 40, "apps/web/src/screens/sessions-list/index.tsx"),
    ]

    groups = {group.name: group for group in group_commits(commits, route_patterns(routes))}

    assert groups["approvals"].screens == []
    assert groups["approvals"].removed_screens == ["/approvals"]
    assert groups["sessions-list"].screens == ["sessions-list/sessions"]


def test_matches_param_and_index_routes_when_head_routes_read() -> None:
    patterns = route_patterns('{ path: "projects/:project/skills", element: <K /> }')
    commits = [_commit("f" * 40, "apps/web/src/screens/skills/a.tsx", "apps/web/src/shell/b.tsx")]

    groups = {group.name: group for group in group_commits(commits, patterns)}

    assert groups["skills"].screens == ["skills/skills"]
    assert "shell/portfolio" in groups["shell"].screens


def test_reads_every_route_of_routes_file_when_patterns_built() -> None:
    patterns = route_patterns(ROUTES_FILE.read_text("utf-8"))
    assert any(pattern.fullmatch("sessions") for pattern in patterns)
    assert not any(pattern.fullmatch("no-such-screen") for pattern in patterns)


def test_keeps_other_pushed_branches_when_delivering_branches_listed() -> None:
    refs = ["origin", "origin/HEAD", "origin/main", "origin/dev", "origin/pr-branch"]
    assert delivering_branches(refs, "dev") == ["origin/main", "origin/pr-branch"]


def test_links_only_own_commits_when_sessions_ran_together() -> None:
    first = _commit("1" * 40, subject="feat(web): add the tabs")
    second = _commit("2" * 40, subject="feat(web): add the tabs to Brain")
    events = [
        {"kind": "user.message", "body": {"text": "Put tabs on the page"}},
        _bash("git log --oneline -5"),
        _bash('git add -A && git commit -q -m "feat(web): add the tabs\n\nWhy." && git log -1'),
    ]

    prompt, linked = link_session(events, [first, second])

    assert prompt == "Put tabs on the page"
    assert linked == [first.sha]


def test_links_heredoc_commit_when_message_comes_from_stdin() -> None:
    commit = _commit("3" * 40, subject="fix(web): a step")
    events = [_bash("git commit -F - <<'EOF'\nfix(web): a step\n\nBody.\nEOF")]
    assert link_session(events, [commit]) == ("", [commit.sha])


def test_gives_group_its_requests_when_their_commits_are_in_it() -> None:
    commits = [_commit("4" * 40, "apps/web/src/screens/skills/a.tsx")]
    groups = group_commits(commits)
    requests = [
        {"title": "Skills layout", "commits": ["4" * 40]},
        {"title": "Unrelated", "commits": []},
    ]

    attach_requests(groups, requests)

    assert groups[0].requests == ["Skills layout"]


def test_lists_only_owner_files_when_hub_changes_read(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    (hub / "plugin" / "p" / "skills" / "mine").mkdir(parents=True)
    (hub / "hub.json").write_text("{}", "utf-8")
    (hub / "AGENTS.md").write_text("synced", "utf-8")
    (hub / "Makefile").write_text("edited after sync", "utf-8")
    (hub / "AGENTS.project.md").write_text("", "utf-8")
    (hub / ".gitignore").write_text("cache/\n", "utf-8")
    (hub / "cache").mkdir()
    (hub / "cache" / "x.pyc").write_text("", "utf-8")
    (hub / "plugin" / "p" / "skills" / "mine" / "SKILL.md").write_text("mine", "utf-8")
    lock = {
        "files": {
            "AGENTS.md": {"ownership": "managed", "sha256": hashlib.sha256(b"synced").hexdigest()},
            "Makefile": {"ownership": "managed", "sha256": hashlib.sha256(b"old").hexdigest()},
            "AGENTS.project.md": {"ownership": "seeded"},
            ".gitignore": {"ownership": "seeded"},
            "hub.json": {"ownership": "seeded"},
        }
    }
    (hub / "hub.lock").write_text(json.dumps(lock), "utf-8")
    git("init", "-q", cwd=hub)

    files = hub_changes(hub, datetime(2026, 10, 16, tzinfo=UTC))

    assert files == ["Makefile", "plugin/p/skills/mine/SKILL.md"]


def test_skips_deleted_file_when_hub_changes_read(tmp_path: Path) -> None:
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "hub.json").write_text("{}", "utf-8")
    (hub / "Makefile").write_text("synced", "utf-8")
    managed = {"ownership": "managed", "sha256": hashlib.sha256(b"synced").hexdigest()}
    (hub / "hub.lock").write_text(json.dumps({"files": {"Makefile": managed}}), "utf-8")
    git("init", "-q", cwd=hub)
    git("add", ".", cwd=hub)
    git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "sync", cwd=hub)
    (hub / "Makefile").unlink()

    assert hub_changes(hub, datetime.now(UTC) + timedelta(days=1)) == []


def test_returns_nothing_when_folder_is_no_hub(tmp_path: Path) -> None:
    assert hub_changes(tmp_path, datetime(2026, 10, 16, tzinfo=UTC)) == []


def test_marks_delivered_and_lists_hub_and_in_progress_when_brief_rendered() -> None:
    commits = [_commit("5" * 40, "apps/web/src/screens/skills/a.tsx")]
    groups = group_commits(commits)
    requests = [
        {
            "created_at": "2026-10-16T11:00:00+00:00",
            "title": "Skills layout",
            "folder": "agent-hub",
            "prompt": "Make the page clearer",
            "commits": ["5" * 40, "6" * 40],
        }
    ]
    attach_requests(groups, requests)

    brief = render_brief(
        "a" * 40,
        "5" * 40,
        groups=groups,
        commits=commits,
        requests=requests,
        left_out=[{"sha": "6" * 40, "subject": "feat(dev): tooling", "branch": "origin/pr"}],
        in_progress=["packages/core/x.py"],
        hub="agent-hub-hub",
        hub_files=["plugin/p/skills/mine/SKILL.md"],
    )

    assert "Skills layout (in agent-hub): `55555555` `66666666` (delivered elsewhere)" in brief
    assert "  > Make the page clearer" in brief
    assert "Requests:\n\n- Skills layout" in brief
    assert "## hub: agent-hub-hub" in brief
    assert "`66666666` feat(dev): tooling (origin/pr)" in brief
    assert "- `packages/core/x.py`" in brief


def test_finds_log_in_playground_folder_when_tmpdir_set_or_not() -> None:
    folder = f"agent-hub-playground-{os.getuid()}"

    assert conductor_log({"TMPDIR": "/home/me/tmp"}) == Path(
        "/home/me/tmp", folder, "agent-hub-conductor.log"
    )
    assert conductor_log({"TMPDIR": ""}) == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
    assert conductor_log({}) == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
