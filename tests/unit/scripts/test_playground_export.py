import hashlib
import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from scripts.playground_export import (
    NO_SESSION,
    SCREEN_ROUTES,
    SHELL_ROUTES,
    Commit,
    RequestsUnavailableError,
    Session,
    Turn,
    area_of,
    build_requests,
    capture_routes,
    commit_patches,
    conductor_logs,
    conductor_token,
    delivering_branches,
    equivalent_on,
    git,
    hub_changes,
    owner_sessions,
    read_session,
    render_brief,
    repeated_changes,
    route_patterns,
    routes_of,
    screens_of,
    slug_of,
    snapshot,
    snapshot_branch,
    uncommitted,
    uncommitted_patch,
)

ROUTES_FILE = Path(__file__).resolve().parents[3] / "apps" / "web" / "src" / "routes.tsx"
SCREENS_DIR = ROUTES_FILE.parent / "screens"
CREATED = datetime(2026, 10, 16, 12, tzinfo=UTC)


def _commit(sha: str, *files: str, subject: str = "feat(web): a step", body: str = "") -> Commit:
    return Commit(sha, subject, body, CREATED, files)


def _bash(command: str) -> dict[str, Any]:
    return {"kind": "tool.call", "body": {"name": "Bash", "input": {"command": command}}}


def _said(text: str, **body: Any) -> dict[str, Any]:
    return {
        "kind": "user.message",
        "at": "2026-10-16T12:08:35.454Z",
        "body": {"text": text, **body},
    }


def _session(title: str, *turns: Turn, folder: str = "agent-hub", **fields: Any) -> Session:
    return Session(f"id-{title}-{len(turns)}", title, folder, CREATED, list(turns), **fields)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", "-b", "main", cwd=repo)
    git("config", "user.email", "owner@example.com", cwd=repo)
    git("config", "user.name", "Owner", cwd=repo)
    (repo / ".gitattributes").write_text("dist/** linguist-generated\n", "utf-8")
    (repo / "app.py").write_text("one\n", "utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "chore: start", cwd=repo)
    return repo


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


def test_lists_every_area_screen_once_when_screens_read() -> None:
    files = ["apps/web/src/screens/skills/Catalog.tsx", "apps/web/src/screens/skills/a.ts"]

    screens, removed = screens_of([*files, "packages/core/x.py"])

    assert screens == ["skills/skills"]
    assert removed == []


def test_gives_shell_its_representative_routes_when_routes_asked() -> None:
    assert routes_of("shell") == SHELL_ROUTES
    assert routes_of("core") == ()


def test_maps_every_screen_folder_when_routes_listed() -> None:
    folders = {path.name for path in SCREENS_DIR.iterdir() if path.is_dir()} - {"not-found"}
    assert folders <= set(SCREEN_ROUTES)


def test_puts_route_in_removed_screens_when_head_routes_lack_it() -> None:
    routes = 'children: [{ path: "sessions", element: <S /> }, { path: "*", element: <N /> }]'
    files = ["apps/web/src/screens/approvals/index.tsx", "apps/web/src/screens/sessions-list/a.tsx"]

    screens, removed = screens_of(files, route_patterns(routes))

    assert screens == ["sessions-list/sessions"]
    assert removed == ["/approvals"]


def test_matches_param_and_index_routes_when_head_routes_read() -> None:
    patterns = route_patterns('{ path: "projects/:project/skills", element: <K /> }')
    files = ["apps/web/src/screens/skills/a.tsx", "apps/web/src/shell/b.tsx"]

    screens, _ = screens_of(files, patterns)

    assert "skills/skills" in screens
    assert "shell/portfolio" in screens


def test_reads_every_route_of_routes_file_when_patterns_built() -> None:
    patterns = route_patterns(ROUTES_FILE.read_text("utf-8"))
    assert any(pattern.fullmatch("sessions") for pattern in patterns)
    assert not any(pattern.fullmatch("no-such-screen") for pattern in patterns)


def test_captures_shared_screen_once_when_two_requests_show_it() -> None:
    routes = capture_routes(["agent-session/sessions", "skills/skills", "agent-session/sessions"])

    assert [route["file"] for route in routes] == ["agent-session/sessions", "skills/skills"]
    assert routes[0]["follow"] == "/agent-sessions/"


def test_reads_last_token_when_log_holds_several(tmp_path: Path) -> None:
    log = tmp_path / "conductor.log"
    log.write_text(
        "agent-hub at http://127.0.0.1:7420/?token=first_one\nagent-hub at http://127.0.0.1:7420/?token=second-2\n",
        "utf-8",
    )
    assert conductor_token(log) == "second-2"


def test_returns_none_when_log_missing(tmp_path: Path) -> None:
    assert conductor_token(tmp_path / "missing.log") is None


def test_looks_in_playground_folder_under_tmpdir_when_no_log_given(tmp_path: Path) -> None:
    folder = f"agent-hub-playground-{os.getuid()}"

    assert conductor_logs(None, {"TMPDIR": str(tmp_path)})[0] == (
        tmp_path / folder / "agent-hub-conductor.log"
    )
    assert conductor_logs(None, {"TMPDIR": ""})[0] == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
    assert conductor_logs(None, {})[0] == Path("/tmp", folder, "agent-hub-conductor.log")  # noqa: S108
    assert conductor_logs(tmp_path / "x.log", {}) == [tmp_path / "x.log"]


def test_also_looks_in_darwin_user_temp_when_on_macos(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    darwin = tmp_path / "darwin"
    monkeypatch.setattr("scripts.playground_export.sys.platform", "darwin")
    monkeypatch.setattr(
        "scripts.playground_export.subprocess.run",
        lambda *_a, **_k: subprocess.CompletedProcess([], 0, stdout=f"{darwin}/\n"),
    )
    folder = f"agent-hub-playground-{os.getuid()}"

    assert conductor_logs(None, {"TMPDIR": str(tmp_path)}) == [
        tmp_path / folder / "agent-hub-conductor.log",
        darwin / folder / "agent-hub-conductor.log",
    ]


def test_raises_requests_unavailable_when_no_log_has_token(tmp_path: Path) -> None:
    with pytest.raises(RequestsUnavailableError, match="make playground"):
        owner_sessions(CREATED, commits=[], logs=[tmp_path / "missing.log"])


def test_leaves_out_main_and_own_branch_when_delivering_branches_listed() -> None:
    refs = ["origin", "origin/HEAD", "origin/main", "origin/dev", "origin/pr-branch"]
    assert delivering_branches(refs, "dev") == ["origin/pr-branch"]


def test_opens_turn_per_message_and_links_its_own_commits_when_session_read() -> None:
    first = _commit("1" * 40, subject="feat(web): add the tabs")
    second = _commit("2" * 40, subject="feat(web): add the tabs to Brain")
    later = _commit("3" * 40, subject="fix(web): a step")
    events = [
        _said("Put tabs on the page", attachments=[{"kind": "screenshot", "bytes": 10}]),
        _bash("git log --oneline -5"),
        _bash('git add -A && git commit -q -m "feat(web): add the tabs\n\nWhy." && git log -1'),
        {
            "kind": "permission.decision",
            "body": {"decision": "allow", "answers": {"Does it look right?": "Yes, ship it"}},
        },
        _said("Now fix the step"),
        _bash("git commit -F - <<'EOF'\nfix(web): a step\n\nBody.\nEOF"),
    ]

    turns, _, _ = read_session(events, [first, second, later])

    assert [turn.message for turn in turns] == ["Put tabs on the page", "Now fix the step"]
    assert turns[0].screenshot is True
    assert turns[0].commits == [first.sha]
    assert turns[0].answers == ["Does it look right? → Yes, ship it"]
    assert turns[1].commits == [later.sha]


def test_keeps_written_and_published_paths_when_session_read() -> None:
    events = [
        _said("Make a skill"),
        {"kind": "tool.call", "body": {"name": "Write", "input": {"file_path": "/hub/brain/a.md"}}},
        {"kind": "text", "body": {"text": "PUBLISHED plugin/p/skills/x/SKILL.md\nDone."}},
    ]

    _, written, published = read_session(events, [])

    assert written == ["/hub/brain/a.md"]
    assert published == ["plugin/p/skills/x/SKILL.md"]


def test_merges_same_title_sessions_and_keeps_unclaimed_work_when_requests_built(
    tmp_path: Path,
) -> None:
    commits = [
        _commit("4" * 40, "apps/web/src/screens/skills/a.tsx"),
        _commit("5" * 40, "Makefile"),
    ]
    sessions = [
        _session("Skills layout", Turn("t1", "Make it clearer")),
        _session("Skills layout", Turn("t2", "Go on", commits=["4" * 40])),
        _session(
            "Review skill",
            Turn("t3", "Create it"),
            folder="hub",
            published=["plugin/p/skills/x/SKILL.md"],
        ),
        _session(
            "Chat panel",
            Turn("t4", "Add a panel"),
            written=[str(tmp_path / "apps/web/src/screens/agent-session/Files.tsx")],
        ),
    ]

    requests = build_requests(
        sessions,
        commits,
        also_on={"4" * 40: "origin/pr"},
        hub_files=["plugin/p/skills/x/SKILL.md", "notes.md"],
        hub_root=tmp_path / "hub",
        in_progress=["apps/web/src/screens/agent-session/Files.tsx", "loose.txt"],
        checkout=tmp_path,
    )

    titles = [request.title for request in requests]
    assert titles == ["Skills layout", "Review skill", "Chat panel", NO_SESSION]
    skills, review, chat, leftover = requests
    assert [turn.message for turn in skills.turns] == ["Make it clearer", "Go on"]
    assert len(skills.sessions) == 2
    assert skills.commits == ["4" * 40]
    assert skills.screens == ["skills/skills"]
    assert skills.also_on == {"4" * 40: "origin/pr"}
    assert review.hub_files == ["plugin/p/skills/x/SKILL.md"]
    assert chat.in_progress == ["apps/web/src/screens/agent-session/Files.tsx"]
    assert chat.screens == ["agent-session/sessions"]
    assert leftover.commits == ["5" * 40]
    assert leftover.hub_files == ["notes.md"]
    assert leftover.in_progress == ["loose.txt"]


def test_keeps_untitled_sessions_apart_when_requests_built() -> None:
    sessions = [_session("", Turn("t1", "First ask")), _session("", Turn("t2", "Other ask"))]
    sessions[1].id = "other"

    requests = build_requests(sessions, [])

    assert [request.title for request in requests] == ["Untitled session", "Untitled session"]
    assert [request.turns[0].message for request in requests] == ["First ask", "Other ask"]


def test_renders_turns_answers_and_marks_when_brief_rendered() -> None:
    commits = [_commit("6" * 40, "apps/web/src/screens/skills/a.tsx", body="Tabs per kind.")]
    shipped = [_commit("7" * 40, "Makefile", subject="chore: already merged")]
    turn = Turn(
        "2026-10-16T12:08:35.454Z",
        "Make the page clearer",
        screenshot=True,
        answers=["Looks right? → Yes"],
        commits=["6" * 40, "7" * 40],
    )
    requests = build_requests(
        [_session("Skills layout", turn), _session("Just talk", Turn("t", "What if?"))],
        commits,
        also_on={"6" * 40: "origin/pr"},
    )
    requests[0].patch = "requests/01-skills-layout.patch"

    brief = render_brief(
        "a" * 40,
        "6" * 40,
        requests=requests,
        commits=commits,
        shipped=shipped,
        missing=["screens not captured: no Chromium"],
    )

    assert "## 1. Skills layout" in brief
    assert "patch `requests/01-skills-layout.patch`" in brief
    assert "1. 2026-10-16 12:08 UTC (with a screenshot)" in brief
    assert "   > Make the page clearer" in brief
    assert "   - Answered: Looks right? → Yes" in brief
    assert "`66666666` feat(web): a step (also on origin/pr)" in brief
    assert "`77777777` chore: already merged (also on origin/main)" in brief
    assert "  Tabs per kind." in brief
    assert "`screens/skills/skills.png`" in brief
    assert "## 2. Just talk" in brief
    assert "Nothing made yet" in brief
    assert "- screens not captured: no Chromium" in brief
    assert "## Already in origin/main (left out)" in brief


def test_slugs_title_without_accents_when_patch_named() -> None:
    assert slug_of("Revisão de UX: a tela!") == "reviso-de-ux-a-tela"
    assert slug_of("???") == "request"


def test_leaves_generated_files_out_when_patches_written(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "dist").mkdir()
    (repo / "dist" / "bundle.js").write_text("minified\n", "utf-8")
    (repo / "app.py").write_text("two\n", "utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "feat: change the app", cwd=repo)
    (repo / "dist" / "bundle.js").write_text("rebuilt\n", "utf-8")
    git("commit", "-q", "-am", "build: rebuild", cwd=repo)
    shas = git("rev-list", "--reverse", "HEAD~2..HEAD", cwd=repo).split()

    patch = commit_patches(shas, cwd=repo)

    assert "Subject: [PATCH] feat: change the app" in patch
    assert "app.py" in patch
    assert "bundle.js" not in patch
    assert "build: rebuild" not in patch


def test_finds_shared_and_cherry_picked_commits_when_branch_has_them(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo).strip()
    for name in ("a", "b"):
        (repo / f"{name}.py").write_text(f"{name}\n", "utf-8")
        git("add", "-A", cwd=repo)
        git("commit", "-q", "-m", f"feat: {name}", cwd=repo)
    shared, picked = git("rev-list", "--reverse", f"{base}..HEAD", cwd=repo).split()
    git("branch", "other", shared, cwd=repo)
    git("checkout", "-q", "other", cwd=repo)
    git("cherry-pick", "--allow-empty", "--keep-redundant-commits", picked, cwd=repo)
    git("commit", "-q", "--amend", "-m", "feat: b, picked", cwd=repo)
    git("checkout", "-q", "main", cwd=repo)

    assert equivalent_on("other", base, "main", cwd=repo) == {shared, picked}


def test_patches_new_and_changed_files_but_local_ones_when_uncommitted(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    (repo / "app.py").write_text("edited\n", "utf-8")
    (repo / "new.py").write_text("brand new\n", "utf-8")
    (repo / "CLAUDE.local.md").write_text("mine\n", "utf-8")

    paths = uncommitted(cwd=repo)
    patch = uncommitted_patch(paths, cwd=repo)

    assert paths == ["app.py", "new.py"]
    assert "+edited" in patch
    assert "+brand new" in patch
    assert git("diff", "--cached", "--name-only", cwd=repo) == ""


def test_maps_cherry_pick_merged_back_to_first_when_range_repeats_change(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    base = git("rev-parse", "HEAD", cwd=repo).strip()
    git("checkout", "-q", "-b", "other", cwd=repo)
    (repo / "b.py").write_text("b\n", "utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "feat: b", cwd=repo)
    first = git("rev-parse", "HEAD", cwd=repo).strip()
    git("checkout", "-q", "main", cwd=repo)
    (repo / "c.py").write_text("c\n", "utf-8")
    git("add", "-A", cwd=repo)
    git("commit", "-q", "-m", "feat: c", cwd=repo)
    git("cherry-pick", first, cwd=repo)
    git("commit", "-q", "--amend", "-m", "feat: b, picked", cwd=repo)
    picked = git("rev-parse", "HEAD", cwd=repo).strip()
    git("merge", "-q", "--no-edit", "other", cwd=repo)

    # Both were made in the same second: either may be the first in the log.
    [(repeat, kept)] = repeated_changes(base, "HEAD", cwd=repo).items()
    assert {repeat, kept} == {first, picked}


def test_counts_repeat_as_first_commit_when_requests_built() -> None:
    commits = [_commit("8" * 40, "Makefile")]
    turn = Turn("t", "Do it", commits=["9" * 40])

    requests = build_requests([_session("Ask", turn)], commits, same_as={"9" * 40: "8" * 40})

    assert requests[0].commits == ["8" * 40]
    assert requests[0].turns[0].commits == ["8" * 40]


def test_names_snapshot_after_branch_prefix_else_email_when_branch_named() -> None:
    stamp = "20261016T120000Z"
    assert snapshot_branch("roquettejh/agh-live-dev", "x@y.z", stamp) == (
        "roquettejh/playground-snapshot/20261016T120000Z"
    )
    assert snapshot_branch("main", "owner@example.com", stamp) == (
        "owner/playground-snapshot/20261016T120000Z"
    )


def test_commits_uncommitted_work_on_branch_and_leaves_checkout_when_snapshot_taken(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    head = git("rev-parse", "HEAD", cwd=repo).strip()
    (repo / "app.py").write_text("edited\n", "utf-8")
    (repo / "new.py").write_text("brand new\n", "utf-8")
    git("config", "user.email", "someone-else@example.com", cwd=repo)

    commit = snapshot(
        "owner/playground-snapshot/s1",
        message="chore(dev): playground snapshot s1",
        in_progress=uncommitted(cwd=repo),
        cwd=repo,
    )

    branch = "owner/playground-snapshot/s1"
    assert git("rev-parse", branch, cwd=repo).strip() == commit
    assert git("rev-parse", f"{commit}^", cwd=repo).strip() == head
    assert git("show", f"{commit}:app.py", cwd=repo) == "edited\n"
    assert git("show", f"{commit}:new.py", cwd=repo) == "brand new\n"
    assert git("log", "-1", "--format=%ae", commit, cwd=repo).strip() == "owner@example.com"
    assert git("rev-parse", "HEAD", cwd=repo).strip() == head
    assert git("branch", "--show-current", cwd=repo).strip() == "main"
    assert git("status", "--porcelain", cwd=repo).split("\n")[:2] == [" M app.py", "?? new.py"]


def test_says_how_to_go_back_when_brief_has_snapshot() -> None:
    brief = render_brief(
        "a" * 40, "b" * 40, requests=[], commits=[], snapshot="o/playground-snapshot/s"
    )
    assert "`git switch -c <name> o/playground-snapshot/s`" in brief


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
