"""AGH-7's characterization cases, run on the rendered hooks and scripts (AC-4.22, erratum E1).

Each ``<file>/<case>`` of ``CASES`` builds its workspace in a fresh ``<ROOT>`` (``char_workspace``),
returns how the file under test is run, and is compared byte for byte with the golden AGH-7 wrote
for the hub's own files (``golden/<file>/<case>.golden``, copied unchanged). The builders and
their data are AGH-7's, case for case. The four ``DIVERGENT`` session start cases embed the output
and ``gh`` calls of the hub's ``scripts/brief.py``, which is not rendered: they are asserted to
differ from their goldens, so the list cannot rot. ``session_start/brief_crash_compact`` matches
vacuously for the same reason (its brief crash adds nothing, and there is no brief).
"""

import json
import re
import shutil
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

type Run = dict[str, Any]
type Builder = Callable[..., Run]

# post_edit (AGH-7's test_post_edit.py). The two lint reports are exactly 1501 chars once ANSI
# codes are removed and the ends stripped: the hook keeps the last 1500.
ESC = "\x1b"
CUT = 1500
NO_COLOR_ENV = {"NO_COLOR": "1", "FORCE_COLOR": "0"}


def lint_report(
    *, first_line: str, line: Callable[[int], str], count: int, summary: str
) -> tuple[str, str]:
    """(stdout, stderr) of a colored lint report whose plain, stripped text is CUT + 1 chars."""
    head = f"{ESC}[1m^{first_line}{ESC}[0m\n"
    lines = "".join(line(i) for i in range(1, count + 1))
    tail = f"{summary}\n\n"
    plain = re.sub(ESC + r"\[[0-9;]*m", "", head + lines + tail).strip()
    pad = CUT + 1 - len(plain) - 1  # one more "\n" ends the padding line
    if pad < 1:
        raise AssertionError(f"report already {len(plain)} chars")
    return head + lines + "=" * pad + "\n", tail


RUFF_OUT, RUFF_ERR = lint_report(
    first_line="ruff (fake) report —",
    line=lambda i: (
        f"{ESC}[1msrc/x.py{ESC}[0m:{i}:1: {ESC}[1;31mF401{ESC}[m `mod{i:02d}` imported but unused\n"
    ),
    count=29,
    summary="Found 29 errors.",
)
ESLINT_OUT, ESLINT_ERR = lint_report(
    first_line="eslint (fake) report —",
    line=lambda i: (
        f"  {i}:1  {ESC}[31merror{ESC}[39m  '{ESC}[4mv{i:02d}{ESC}[24m' is never used"
        "  no-unused-vars\n"
    ),
    count=27,
    summary=f"{ESC}[2K{ESC}[31m{ESC}[1m27 problems (27 errors, 0 warnings){ESC}[22m{ESC}[39m",
)


def rule(argv_has: list[str], **answer: Any) -> dict[str, Any]:
    return dict(answer, argv_has=argv_has, env_has=NO_COLOR_ENV)


RUFF_CLEAN = {
    "ruff": [
        rule(
            ["format", "-q"],
            stdout="1 file reformatted\n",
            write={"x.py": "import os\n\nprint(os.sep)\n"},
        ),
        rule(["check", "--fix", "-q"], stdout="All checks passed!\n"),
    ]
}
RUFF_ERRORS = {
    "ruff": [  # format fails too: its rc and text are ignored
        rule(
            ["format", "-q"],
            stderr="error: format failed\n",
            rc=2,
            write={"src/x.py": "import os  # formatted\n"},
        ),
        rule(["check", "--fix", "-q"], stdout=RUFF_OUT, stderr=RUFF_ERR, rc=1),
    ]
}


def node(*, name: str, formatted: str) -> dict[str, Any]:
    """prettier formats ``name`` (and fails: its rc and text are ignored); eslint reports errors."""
    return {
        "prettier": [
            rule(
                ["--write", "--log-level", "warn"],
                stderr=f"[warn] {name}\n",
                rc=2,
                write={name: formatted},
            )
        ],
        "eslint": [rule(["--fix"], stdout=ESLINT_OUT, stderr=ESLINT_ERR, rc=1)],
    }


def edit_event(path: Path, cwd: Path | None = None) -> bytes:
    data: dict[str, Any] = {"tool_name": "Write", "tool_input": {"file_path": str(path)}}
    if cwd is not None:
        data["cwd"] = str(cwd)
    return json.dumps(data).encode()


def hub_of(ws: Any) -> Path:
    return Path(ws.root, "ws", ws.HUB_DIR)


def post_edit_workspace(ws: Any) -> tuple[Path, Path, Path]:
    """The hub copy (with ``brain/``, so the workspace scan finds it), ``api`` and ``web``."""
    ws.hub_copy(extra_files={"brain/now.md": "# Now\n", "notes/x.py": "x = 1\n"})
    api = ws.make_repo(
        ws.root / "ws" / "api",
        files={"x.py": "import os\nprint( os.sep )\n", "src/x.py": "import os\n"},
    )
    web = ws.make_repo(
        ws.root / "ws" / "web",
        files={"a.ts": "export const a=1\n", "a.js": "export const b=2\n", "package.json": "{}\n"},
    )
    return hub_of(ws), api, web


def post_edit_empty_stdin(*, ws: Any) -> Run:
    _, api, _ = post_edit_workspace(ws)
    ws.install_repo_fakes(api, ["ruff"])
    return {"stdin": b"", "answers": RUFF_ERRORS}


def post_edit_missing_file(*, ws: Any) -> Run:
    # Inside a listed repo that has ruff: only the file check stops the hook.
    hub, api, _ = post_edit_workspace(ws)
    ws.install_repo_fakes(api, ["ruff"])
    return {"stdin": edit_event(api / "gone.py", hub), "answers": RUFF_ERRORS}


def post_edit_no_hub(*, ws: Any) -> Run:
    # No hub above the cwd or the file, and the repo is named like a listed one. AGH-7 pinned
    # "no hub, not linted"; under Q-4 the hub holding the hook is the config, so it is linted.
    post_edit_workspace(ws)
    repo = ws.make_repo(ws.root / "elsewhere" / "api", files={"x.py": "x = 1\n"})
    ws.install_repo_fakes(repo, ["ruff"])
    return {"stdin": edit_event(repo / "x.py", repo), "answers": RUFF_ERRORS, "no_hub": True}


def post_edit_hub_file_not_linted(*, ws: Any) -> Run:
    hub, _, _ = post_edit_workspace(ws)
    ws.install_repo_fakes(hub, ["ruff"])  # .venv/ is ignored: the hub stays clean
    return {"stdin": edit_event(hub / "notes" / "x.py", hub), "answers": RUFF_ERRORS}


def post_edit_py_ruff_clean(*, ws: Any) -> Run:
    hub, api, _ = post_edit_workspace(ws)
    ws.install_repo_fakes(api, ["ruff"])
    return {"stdin": edit_event(api / "x.py", hub), "answers": RUFF_CLEAN}


def post_edit_py_ruff_errors(*, ws: Any) -> Run:
    # In a worktree that has its own ruff, next to the main checkout's: the worktree's runs.
    hub, api, _ = post_edit_workspace(ws)
    wt = ws.add_worktree(api, "e")
    ws.install_repo_fakes(api, ["ruff"])
    ws.install_repo_fakes(wt, ["ruff"])
    return {"stdin": edit_event(wt / "src" / "x.py", hub), "answers": RUFF_ERRORS}


def post_edit_py_worktree_uses_main_ruff(*, ws: Any) -> Run:
    hub, api, _ = post_edit_workspace(ws)
    wt = ws.add_worktree(api, "t")
    ws.install_repo_fakes(api, ["ruff"])
    return {"stdin": edit_event(wt / "x.py", hub), "answers": RUFF_CLEAN}


def post_edit_ts_prettier_eslint_errors(*, ws: Any) -> Run:
    hub, _, web = post_edit_workspace(ws)
    ws.install_repo_fakes(web, ["prettier", "eslint"])
    ws.write_files(web, {"eslint.config.js": "export default [];\n"})
    return {
        "stdin": edit_event(web / "a.ts", hub),
        "answers": node(name="a.ts", formatted="export const a = 1;\n"),
    }


def post_edit_js_prettier_only(*, ws: Any) -> Run:
    # In web's worktree j: prettier and eslint in both checkouts, a listed eslint config only in
    # the main checkout and look-alikes only in the worktree, so the worktree's own tools and top
    # level decide. The event has no cwd and the hook runs from <ROOT>/elsewhere: the hub is found
    # from the file path.
    _, _, web = post_edit_workspace(ws)
    wt = ws.add_worktree(web, "j")
    ws.install_repo_fakes(web, ["prettier", "eslint"])
    ws.install_repo_fakes(wt, ["prettier", "eslint"])
    ws.write_files(web, {"eslint.config.js": "export default [];\n"})
    ws.write_files(
        wt, {"eslint.config.json": "{}\n", "src/eslint.config.js": "export default [];\n"}
    )
    return {
        "stdin": edit_event(wt / "a.js"),
        "answers": node(name="a.js", formatted="export const b = 2;\n"),
        "cwd": ws.root / "elsewhere",
    }


def post_edit_py_stale_ruff_silent(*, ws: Any) -> Run:
    # api's ruff exists but its interpreter is gone: both runs raise OSError, swallowed as rc 0.
    hub, api, _ = post_edit_workspace(ws)
    ws.write_exe(api / ".venv" / "bin" / "ruff", "#!/nonexistent/python3\n")
    return {"stdin": edit_event(api / "x.py", hub), "answers": RUFF_ERRORS}


def post_edit_event_cwd_hub_wins(*, ws: Any) -> Run:
    # A repo outside the workspace, named like a listed one: the hub comes from the event cwd, and
    # repo_of matches by directory name only, so it is linted. No hub is above <ROOT>/elsewhere.
    hub, _, _ = post_edit_workspace(ws)
    repo = ws.make_repo(ws.root / "elsewhere" / "api", files={"x.py": "x = 1\n"})
    ws.install_repo_fakes(repo, ["ruff"])
    return {"stdin": edit_event(repo / "x.py", hub), "answers": RUFF_CLEAN, "no_hub": True}


# session_start (AGH-7's test_session_start.py), on the brief workspace.
SNAPSHOT = "brain/auto/workspace/session-snapshot.md"
LONG_SNAPSHOT = (
    "# Session snapshot (2026-01-15 10:20, before auto)\n"
    + "".join(f"- note {i:03d}: café … résumé; keep going\n" for i in range(1, 80))
)[:2501]
BRIEF_SCRIPT = "scripts/brief.py"


def session_event(source: str, cwd: Path | None = None) -> bytes:
    data = {"session_id": "abcdef123456", "hook_event_name": "SessionStart", "source": source}
    if cwd is not None:
        data["cwd"] = str(cwd)
    return json.dumps(data).encode()


def write_snapshot(ws: Any, text: str = LONG_SNAPSHOT) -> None:
    ws.write_files(hub_of(ws), {SNAPSHOT: text})


def decoy(ws: Any) -> Path:
    """A dir that find_hub accepts (it holds hub.json) but that has no brief and no snapshot."""
    folder = Path(ws.root) / "elsewhere" / "decoy"
    ws.write_files(folder, {"hub.json": "{}\n"})
    return folder


def drop_brief(ws: Any) -> None:
    """AGH-7 deleted the hub's brief script here; no hub copy of the rendered files holds one."""
    assert not (hub_of(ws) / BRIEF_SCRIPT).exists()


def start(
    ws: Any,
    stdin: bytes,
    *,
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    no_hub: bool = False,
) -> Run:
    return {
        "stdin": stdin,
        "cwd": cwd or ws.root / "elsewhere",
        "env": env,
        "answers": ws.BRIEF_GH,
        "no_hub": no_hub,
    }


def session_start_no_hub(*, ws: Any) -> Run:
    ws.brief_workspace()
    # HUB_CONFIG names a dir, so it is ignored. AGH-7 pinned "no snapshot"; under Q-4 the hub
    # holding the hook is found, so its snapshot is appended.
    write_snapshot(ws)
    return start(
        ws,
        session_event("compact", ws.root / "elsewhere"),
        env={"HUB_CONFIG": str(hub_of(ws) / "brain")},
        no_hub=True,
    )


def session_start_startup(*, ws: Any) -> Run:
    ws.brief_workspace()
    write_snapshot(ws)
    folder = decoy(ws)
    return start(
        ws,
        session_event("startup", hub_of(ws)),
        cwd=folder,
        env={"CLAUDE_PROJECT_DIR": str(folder)},
    )


def session_start_sibling_repo_cwd(*, ws: Any) -> Run:
    ws.brief_workspace()
    (ws.root / "ws" / "api" / "src").mkdir()
    return start(ws, session_event("startup", ws.root / "ws" / "api" / "src"))


def session_start_compact_snapshot(*, ws: Any) -> Run:
    ws.brief_workspace()
    write_snapshot(ws)
    return start(
        ws,
        session_event("compact", decoy(ws)),
        env={"HUB_CONFIG": str(hub_of(ws) / "hub.json")},
    )


def session_start_no_brief_compact(*, ws: Any) -> Run:
    ws.brief_workspace()
    drop_brief(ws)
    write_snapshot(ws, LONG_SNAPSHOT[:2500])
    bare = ws.add_worktree(hub_of(ws), "y")  # no brain/, so the walk skips it
    ws.commit_hub({"brain/now.md": None, **dict.fromkeys(ws.JOURNAL)}, repo=bare)
    shutil.rmtree(bare / "brain")
    return start(ws, session_event("compact"), cwd=decoy(ws), env={"CLAUDE_PROJECT_DIR": str(bare)})


def session_start_no_brief_startup(*, ws: Any) -> Run:
    ws.brief_workspace()
    drop_brief(ws)
    write_snapshot(ws)
    return start(ws, session_event("startup", hub_of(ws)), cwd=hub_of(ws))


def session_start_hub_worktree_cwd(*, ws: Any) -> Run:
    ws.brief_workspace()
    # In the main hub only. AGH-7 read the worktree (none, so nothing appended); under Q-4 the
    # hook reads the main hub that holds it, so this snapshot is appended (SNAPSHOT_OF).
    write_snapshot(ws)
    wt = ws.add_worktree(hub_of(ws), "x")
    ws.add_worktree(hub_of(ws), "z")  # also a hub worktree: the scan takes the first sorted
    project = dict(ws.BRIEF_HUB_JSON["project"], hub_repo="acme/demo-hub-wt")
    wt_hub_json = dict(ws.BRIEF_HUB_JSON, project=project)
    wt_now_md = ws.NOW_MD.replace(
        "Ship the collector.\nThen the CLI.", "Worktree focus.\nOnly here."
    )
    ws.commit_hub(
        {"hub.json": json.dumps(wt_hub_json, indent=2) + "\n", "brain/now.md": wt_now_md}, repo=wt
    )
    return start(ws, session_event("compact"), cwd=wt / "brain")


def session_start_non_object_stdin(*, ws: Any) -> Run:
    # AGH-7 pinned a crash; hooks fail open (AC-4.11): an empty object, exit 0.
    ws.brief_workspace()
    return start(ws, b"[]", cwd=hub_of(ws))


def session_start_brief_crash_compact(*, ws: Any) -> Run:
    ws.brief_workspace()
    broken = {key: value for key, value in ws.BRIEF_HUB_JSON.items() if key != "tracker"}
    ws.commit_hub({"hub.json": json.dumps(broken, indent=2) + "\n"})  # AGH-7's brief: KeyError
    write_snapshot(ws, "  Snapshot body with surrounding spaces.  \n\n")
    return start(ws, session_event("compact", hub_of(ws)))


# session_end (AGH-7's test_session_end.py).
DAY_FILE = "brain/_inbox/sessions/2026-01-15.md"
OLD_DAY = (
    "---\ntype: session-log\nstatus: proposed\nlast_verified: 2026-01-15\n"
    "provenance: agent-from-code\n---\n"
    "# Sessions 2026-01-15\n\n- 08:00 session `old12345` ended (clear), cwd `/w`\n"
    "  - api [trunk]: 9 changed\n"
)


def fields_event(**fields: Any) -> bytes:
    return json.dumps(fields).encode()


def session_end_workspace(ws: Any) -> None:
    """The hub copy (with a brain/; clean) and ``api`` with 2 dirty entries (one modified file,
    one untracked dir holding two files: porcelain lists the dir once); ``web`` is clean."""
    ws.hub_copy(extra_files={"brain/now.md": "# Now\n"})
    api = ws.make_repo(ws.root / "ws" / "api", files={"README.md": "api\n"})
    ws.write_files(api, {"README.md": "api, edited\n", "notes/a.txt": "a\n", "notes/b.txt": "b\n"})
    ws.make_repo(ws.root / "ws" / "web", files={"index.html": "<p>web</p>\n"})


def session_end_no_hub(*, ws: Any) -> Run:
    # No hub above the event's or the process's cwd. AGH-7 pinned "nothing written"; under Q-4
    # the entry goes to the hub holding the hook.
    session_end_workspace(ws)
    stdin = fields_event(session_id="abcdef123456", reason="logout", cwd=str(ws.root / "elsewhere"))
    return {"stdin": stdin, "no_hub": True}


def session_end_new_day_file(*, ws: Any) -> Run:
    # Three api worktrees created as t, b, c: the listing is sorted, so b (a branch, 3 files), c
    # (a branch, 2 files), then t (detached, 1 file). The sessions dir does not exist yet. The
    # process cwd has no hub above it: the hub comes from the event's cwd.
    session_end_workspace(ws)
    for name, files in (("t", 1), ("b", 3), ("c", 2)):
        wt = ws.add_worktree(
            ws.root / "ws" / "api", name, detach=name == "t", branch=f"dev/tst-{files}-{name}"
        )
        ws.write_files(wt, {f"x{i}.txt": f"{i}\n" for i in range(1, files + 1)})
    stdin = fields_event(
        session_id="abcdef123456", reason="logout", cwd=str(ws.root / "ws" / "api")
    )
    return {"stdin": stdin, "cwd": ws.root / "elsewhere"}


def session_end_append(*, ws: Any) -> Run:
    # An int session id (str() then cut to 8), no reason; web and the hub dirty too.
    session_end_workspace(ws)
    web = ws.root / "ws" / "web"
    ws.write_files(hub_of(ws), {DAY_FILE: OLD_DAY, "scratch.txt": "hub\n"})
    ws.write_files(web, {"index.html": "<p>web, edited</p>\n"})
    return {"stdin": fields_event(session_id=1234567890123, cwd=str(web)), "cwd": web}


def session_end_empty_stdin_in_hub(*, ws: Any) -> Run:
    session_end_workspace(ws)
    return {"stdin": b""}


def session_end_hub_worktree_cwd(*, ws: Any) -> Run:
    # AGH-7's pinned item 1: hooks run from a hub worktree took <hub>/.claude/worktrees as the
    # workspace and wrote into the worktree's brain/. Under Q-4 the worktree's hooks read its
    # hub.json, but the hub and workspace are the main checkout's: the entry goes into the main
    # brain/ and lists api and the worktree. A null session id prints `None`.
    session_end_workspace(ws)
    wt = ws.add_worktree(hub_of(ws), "x", branch="dev/tst-9-x")
    ws.write_files(wt, {"draft.txt": "wt\n"})
    stdin = fields_event(session_id=None, reason="clear", cwd=str(wt / "brain"))
    return {"stdin": stdin, "cwd": wt / "brain", "hub": wt}


# pre_compact (AGH-7's test_pre_compact.py).
FINAL = "é" + "0123456789" * 80  # 801 chars, 802 UTF-8 bytes: the char cut drops the final 9


def jsonl_bytes(*records: Any) -> bytes:
    """JSON lines as bytes (non-ASCII kept raw); a bytes record is written as is."""
    return b"".join(
        record
        if isinstance(record, bytes)
        else (json.dumps(record, ensure_ascii=False) + "\n").encode("utf-8")
        for record in records
    )


# An invalid first line, a user string holding an invalid UTF-8 byte (read with
# errors="replace"), then the final user string: every later line must be skipped.
TRANSCRIPT = jsonl_bytes(
    b"{not json\n",
    {"type": "user", "message": {"content": "first request"}},
    b'{"type": "user", "message": {"content": "caf\xff"}}\n',
    {"type": "user", "message": {"content": FINAL}},
    {"type": "assistant", "message": {"content": "assistant text is not a request"}},
    {"type": "user", "message": {"content": "<command-name>/compact</command-name>"}},
    {"type": "user", "message": {"content": [{"type": "text", "text": "list content"}]}},
    b"{not json either\n",
    {"type": "user", "message": None},
    {"type": "user", "message": {"content": 42}},
    {"type": "user"},
)


def pre_compact_workspace(ws: Any) -> None:
    """The hub copy (with a brain/; clean), ``api`` with one modified file and 11 untracked
    (12 entries), ``web`` clean."""
    ws.hub_copy(extra_files={"brain/now.md": "# Now\n"})
    api = ws.make_repo(ws.root / "ws" / "api", files={"README.md": "api\n"})
    ws.write_files(
        api,
        dict(
            {"README.md": "api, edited\n"}, **{f"f{i:02d}.txt": f"{i}\n" for i in range(11, 0, -1)}
        ),
    )
    ws.make_repo(ws.root / "ws" / "web", files={"index.html": "<p>web</p>\n"})


def write_transcript(ws: Any) -> Path:
    transcript = Path(ws.root) / "home" / "t.jsonl"
    transcript.write_bytes(TRANSCRIPT)
    return transcript


def pre_compact_no_hub(*, ws: Any) -> Run:
    # As session_end/no_hub: under Q-4 the snapshot goes to the hub holding the hook.
    pre_compact_workspace(ws)
    transcript = write_transcript(ws)
    stdin = fields_event(
        cwd=str(ws.root / "elsewhere"), trigger="manual", transcript_path=str(transcript)
    )
    return {"stdin": stdin, "no_hub": True}


def pre_compact_full(*, ws: Any) -> Run:
    # api: 12 entries, cut to 10. A detached worktree with exactly 10 untracked entries (an
    # untracked dir, listed once as `sub/`, and 9 files) keeps all 10. The process cwd has no hub
    # above it: the hub is found from the event's cwd.
    pre_compact_workspace(ws)
    wt = ws.add_worktree(ws.root / "ws" / "api", "t", detach=True)
    ws.write_files(
        wt,
        dict(
            {"sub/one.txt": "1\n", "sub/two.txt": "2\n"},
            **{f"w{i:02d}.txt": "w\n" for i in range(1, 10)},
        ),
    )
    transcript = write_transcript(ws)
    stdin = fields_event(
        cwd=str(ws.root / "ws" / "api"), trigger="manual", transcript_path=str(transcript)
    )
    return {"stdin": stdin, "cwd": ws.root / "elsewhere"}


def pre_compact_minimal_overwrite(*, ws: Any) -> Run:
    # Clean checkouts, no transcript_path, no trigger; the old snapshot is longer than the new one
    # and is ignored by the hub's .gitignore, so the hub stays clean.
    pre_compact_workspace(ws)
    api, web = ws.root / "ws" / "api", ws.root / "ws" / "web"
    ws.git("checkout", "-q", "--", "README.md", cwd=api)
    ws.git("clean", "-qfd", cwd=api)
    ws.write_files(hub_of(ws), {SNAPSHOT: "# Session snapshot (old)\n" + "- stale\n" * 20})
    return {"stdin": fields_event(cwd=str(web)), "cwd": web}


def pre_compact_missing_transcript(*, ws: Any) -> Run:
    # A transcript_path that does not exist reads as no request: `(n/a)`.
    pre_compact_workspace(ws)
    stdin = fields_event(
        cwd=str(ws.root / "ws" / "api"),
        trigger="auto",
        transcript_path=str(ws.root / "home" / "none.jsonl"),
    )
    return {"stdin": stdin}


# retro_metrics (AGH-7's test_retro_metrics.py). The window of `--days 14` starts on 2026-01-01,
# that of `--days 3` on 2026-01-12; file- and gh-based dates sit on both boundaries.


def commits(*dates: str | None) -> list[dict[str, str]]:
    return [{"committedDate": d} if d else {"oid": "no-date"} for d in dates]


API_PRS = [
    {
        "number": 11,
        "createdAt": "2026-01-09T08:00:00Z",
        "mergedAt": "2026-01-09T09:09:00Z",
        "body": "Refs the Agent run r0 log",
        "commits": commits("2026-01-09T12:00:00Z"),
    },
    {
        "number": 12,
        "createdAt": "2026-01-10T09:00:00Z",
        "mergedAt": "2026-01-10T19:00:00Z",
        "body": "Agent run `r1` for TST-1",
        "commits": commits("2026-01-10T08:30:00Z", "2026-01-10T09:00:00Z", None),
    },
    {
        "number": 13,
        "createdAt": "2026-01-12T10:00:00Z",
        "mergedAt": "2026-01-12T10:30:00Z",
        "body": "Agent run `r2` for TST-2",
        "commits": commits("2026-01-12T09:00:00Z", "2026-01-12T10:00:01Z"),
    },
]
HUB_PRS = [
    {
        "number": 5,
        "createdAt": "2026-01-13T08:00:00Z",
        "mergedAt": "2026-01-13T13:00:00Z",
        "body": None,
        "commits": [],
    },
    {"number": 4, "createdAt": "2026-01-11T10:00:00Z", "mergedAt": "2026-01-11T12:20:00Z"},
    {
        "number": 3,
        "createdAt": "2026-01-08T10:00:00Z",
        "mergedAt": "2026-01-08T11:00:00Z",
        "body": "Agent run `r3` for TST-3",
    },
    {
        "number": 2,
        "createdAt": "2026-01-06T10:00:00Z",
        "mergedAt": "2026-01-06T13:00:00Z",
        "body": "agent run `r4`",
        "commits": [],
    },
]


def ci_run(conclusion: str | None, created: str, name: str | None = None) -> dict[str, Any]:
    run: dict[str, Any] = {"conclusion": conclusion, "createdAt": created}
    if name:
        run["workflowName"] = name
    return run


API_RUNS = [
    ci_run("failure", "2026-01-14T09:00:00Z", "lint"),
    ci_run("failure", "2026-01-13T09:00:00Z", "build"),
    ci_run("success", "2026-01-14T10:00:00Z", "build"),
    ci_run("failure", "2026-01-10T09:00:00Z", "lint"),
    ci_run(None, "2026-01-14T11:00:00Z", "deploy"),
    ci_run("failure", "2025-12-26T09:00:00Z", "e2e"),
    ci_run("failure", "2026-01-01T00:00:00Z", "docs"),
    ci_run("failure", "2026-01-12T00:00:00Z", "security"),
    ci_run("failure", "2026-01-13T12:00:00Z", "lint " + chr(0x2713)),  # the report escapes it
    ci_run("failure", "2025-12-31T23:59:59Z", "release"),
    ci_run("", "2026-01-14T12:00:00Z", "queued"),
    ci_run("cancelled", "2026-01-11T09:00:00Z", "build"),
]
WEB_RUNS = [
    ci_run("failure", "2026-01-14T09:00:00Z"),
    ci_run("success", "2026-01-14T09:30:00Z", "ci"),
]
RETRO_GH = {
    "gh": [
        {"argv_has": ["pr", "acme/api"], "stdout": json.dumps(API_PRS)},
        {"argv_has": ["pr", "acme/web"], "stdout": "[]"},
        {"argv_has": ["pr", "acme/demo-hub"], "stdout": json.dumps(HUB_PRS)},
        {"argv_has": ["run", "acme/api"], "stdout": json.dumps(API_RUNS)},
        {"argv_has": ["run", "acme/web"], "stdout": json.dumps(WEB_RUNS)},
        {"argv_has": ["run", "acme/demo-hub"], "stdout": ""},
    ]
}


def jsonl_text(*records: Any) -> str:
    return "".join(json.dumps(record) + "\n" for record in records)


def reported(issue: str, cost: float | None, stage: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {"event": "reported", "issue": issue, "total_cost_usd": cost}
    if stage is not None:
        record["failed_stage"] = stage
    return record


AGENT_RUNS = {
    ".agent-runs/2025-12-31.jsonl": jsonl_text(reported("TST-9", 9)),
    ".agent-runs/2026-01-01.jsonl": jsonl_text(
        {"event": "started", "issue": "TST-3"}, reported("TST-3", 0.1, "verify")
    ),
    ".agent-runs/2026-01-10.jsonl": jsonl_text(
        {"event": "started", "issue": "TST-1"},
        reported("TST-1", 1.25),
        reported("TST-2", 0.165, "verify"),
        reported("TST-1", 0.2),
        reported("TST-2", None, "check"),
        {"event": "stage", "issue": "TST-2", "failed_stage": "lint"},
        reported("TST-4", None),
        reported("TST-5", 2),
    ),
    ".agent-runs/2026-01-12.jsonl": jsonl_text(reported("TST-3", 0.2, "")),
    ".agent-runs/README.md": "not a run log\n",
}
INBOX = {
    "brain/_inbox/a.md": "a\n",
    "brain/_inbox/b.md": "b\n",
    "brain/_inbox/notes.txt": "n\n",
    "brain/_inbox/sessions/x.md": "x\n",
}
# brain/learnings on trunk, never on T-14 or T-3; b.md renamed to b2.md at T-1 (an R entry).
LEARNINGS: list[tuple[int, dict[str, str | None]]] = [
    (20, {"brain/learnings/old.md": "old\n"}),
    (10, {"brain/learnings/a.md": "a\n", "brain/learnings.md": "index\n"}),
    (5, {"brain/learnings/a.md": "a, again\n", "brain/learnings/b.md": "b\n"}),
    (4, {"brain/learnings/old.md": None}),
    (2, {"brain/learnings/c.md": "c\n"}),
    (1, {"brain/learnings/b.md": None, "brain/learnings/b2.md": "b\n"}),
]


def retro_workspace(ws: Any) -> Path:
    """The hub copy with the learnings history and its origin, then the untracked run logs and
    inbox."""
    hub = ws.hub_copy()
    for days_before, files in LEARNINGS:
        for rel, text in files.items():
            if text is None:
                (hub / rel).unlink()
            else:
                ws.write_files(hub, {rel: text})
        ws.git("add", "-A", cwd=hub)
        ws.git("commit", "-q", "-m", "learnings", cwd=hub, date=ws.at(days_before, "11:00"))
    ws.bare_origin(hub)
    ws.write_files(hub, dict(AGENT_RUNS, **INBOX))
    return Path(hub)


def retro_metrics_full(*, ws: Any) -> Run:
    retro_workspace(ws)
    return {"answers": RETRO_GH}


def retro_metrics_days_3(*, ws: Any) -> Run:
    retro_workspace(ws)
    return {"argv": ["--days", "3"], "answers": RETRO_GH}


def retro_metrics_gh_failing(*, ws: Any) -> Run:
    # The message is 201 chars once stripped: the warning keeps the first 200 (drops the final X).
    retro_workspace(ws)
    message = "HTTP 503: " + "-" * 189 + "|X"
    return {"answers": {"gh": [{"stderr": "  " + message + "\n\n", "rc": 1}]}}


def retro_metrics_gh_bad_json_no_data(*, ws: Any) -> Run:
    hub = retro_workspace(ws)
    shutil.rmtree(hub / ".agent-runs")
    shutil.rmtree(hub / "brain" / "_inbox")
    ws.git("remote", "remove", "origin", cwd=hub)  # the learnings stay on local trunk
    answers = {
        "gh": [{"argv_has": ["pr"], "stdout": "oops\n"}, {"argv_has": ["run"], "stdout": ""}]
    }
    return {"answers": answers}


def retro_metrics_from_hub_worktree(*, ws: Any) -> Run:
    # The worktree has its own run log and inbox, and the only hub.json listing api (the main
    # checkout's is changed after): the report takes the worktree's repos, the main one's data.
    hub = retro_workspace(ws)
    wt = ws.add_worktree(hub, "x")
    ws.write_files(
        wt,
        {
            ".agent-runs/2026-01-14.jsonl": jsonl_text(reported("TST-7", 7.0)),
            "brain/_inbox/w1.md": "w\n",
            "brain/_inbox/w2.md": "w\n",
            "brain/_inbox/w3.md": "w\n",
        },
    )
    main_json = dict(ws.HUB_JSON, repos=[{"dir": "web", "github": "acme/web"}])
    ws.commit_hub({"hub.json": json.dumps(main_json, indent=2) + "\n"})
    return {"answers": RETRO_GH, "hub": wt}


def retro_metrics_bad_run_file(*, ws: Any) -> Run:
    hub = retro_workspace(ws)
    ws.write_files(hub, {".agent-runs/notes.jsonl": jsonl_text(reported("TST-8", 8.0))})
    return {"answers": RETRO_GH}


CASES: dict[str, Builder] = {
    "post_edit/empty_stdin": post_edit_empty_stdin,
    "post_edit/missing_file": post_edit_missing_file,
    "post_edit/no_hub": post_edit_no_hub,
    "post_edit/hub_file_not_linted": post_edit_hub_file_not_linted,
    "post_edit/py_ruff_clean": post_edit_py_ruff_clean,
    "post_edit/py_ruff_errors": post_edit_py_ruff_errors,
    "post_edit/py_worktree_uses_main_ruff": post_edit_py_worktree_uses_main_ruff,
    "post_edit/ts_prettier_eslint_errors": post_edit_ts_prettier_eslint_errors,
    "post_edit/js_prettier_only": post_edit_js_prettier_only,
    "post_edit/py_stale_ruff_silent": post_edit_py_stale_ruff_silent,
    "post_edit/event_cwd_hub_wins": post_edit_event_cwd_hub_wins,
    "session_start/no_hub": session_start_no_hub,
    "session_start/startup": session_start_startup,
    "session_start/sibling_repo_cwd": session_start_sibling_repo_cwd,
    "session_start/compact_snapshot": session_start_compact_snapshot,
    "session_start/no_brief_compact": session_start_no_brief_compact,
    "session_start/no_brief_startup": session_start_no_brief_startup,
    "session_start/hub_worktree_cwd": session_start_hub_worktree_cwd,
    "session_start/non_object_stdin": session_start_non_object_stdin,
    "session_start/brief_crash_compact": session_start_brief_crash_compact,
    "session_end/no_hub": session_end_no_hub,
    "session_end/new_day_file": session_end_new_day_file,
    "session_end/append": session_end_append,
    "session_end/empty_stdin_in_hub": session_end_empty_stdin_in_hub,
    "session_end/hub_worktree_cwd": session_end_hub_worktree_cwd,
    "pre_compact/no_hub": pre_compact_no_hub,
    "pre_compact/full": pre_compact_full,
    "pre_compact/minimal_overwrite": pre_compact_minimal_overwrite,
    "pre_compact/missing_transcript": pre_compact_missing_transcript,
    "retro_metrics/full": retro_metrics_full,
    "retro_metrics/days_3": retro_metrics_days_3,
    "retro_metrics/gh_failing": retro_metrics_gh_failing,
    "retro_metrics/gh_bad_json_no_data": retro_metrics_gh_bad_json_no_data,
    "retro_metrics/from_hub_worktree": retro_metrics_from_hub_worktree,
    "retro_metrics/bad_run_file": retro_metrics_bad_run_file,
}
# AGH-7's case count per file under test.
CASES_PER_FILE = {
    "post_edit": 11,
    "session_start": 9,
    "session_end": 5,
    "pre_compact": 4,
    "retro_metrics": 6,
}
# Erratum E1 (a): their goldens hold the hub brief script's output and gh calls.
DIVERGENT = frozenset(
    {
        "session_start/startup",
        "session_start/sibling_repo_cwd",
        "session_start/compact_snapshot",
        "session_start/hub_worktree_cwd",
    }
)
# What the missing brief script changes in them: its text and its gh calls, nothing else.
BRIEF_STREAMS = frozenset({"stdout", "calls"})
SNAPSHOT_MARKER = "\n\n## Snapshot before compaction\n"
# Q-4: the hook reads the hub that holds it, not the hub worktree of the event's cwd, so this case
# now appends the hub's snapshot: the one compact_snapshot's golden holds (slice 20 regenerates
# both).
SNAPSHOT_OF = {"session_start/hub_worktree_cwd": "session_start/compact_snapshot"}
MATCHING = sorted(CASES.keys() - DIVERGENT)


@pytest.mark.parametrize("case", MATCHING)
def test_matches_golden_when_case_run(
    case: str, char_workspace: Callable[..., Any], hook_python: str
) -> None:
    ws = char_workspace(python=hook_python)
    ws.run_case(case, **CASES[case](ws=ws))


def test_lists_every_golden_when_cases_collected(golden: Any) -> None:
    files = [case.split("/", 1)[0] for case in CASES]
    assert {name: files.count(name) for name in files} == CASES_PER_FILE
    assert CASES.keys() > DIVERGENT
    assert SNAPSHOT_OF.keys() <= DIVERGENT
    assert set(SNAPSHOT_OF.values()) <= CASES.keys()
    assert golden.orphans(golden.GOLDEN_ROOT, CASES) == []
    if not golden.update_mode():  # in update mode the cases write what is missing
        assert golden.missing(golden.GOLDEN_ROOT, CASES) == []


def brief_free_stdout(golden_stdout: bytes) -> bytes:
    """The golden's stdout without the brief: only the snapshot part of the context is left,
    in the hook's JSON form; nothing when the context held no snapshot."""
    output = json.loads(golden_stdout)
    assert json.dumps(output).encode() + b"\n" == golden_stdout, "not the hook's JSON form"
    context = output["hookSpecificOutput"]["additionalContext"]
    if SNAPSHOT_MARKER not in context:
        return b""
    output["hookSpecificOutput"]["additionalContext"] = context[context.index(SNAPSHOT_MARKER) :]
    return json.dumps(output).encode() + b"\n"


@pytest.mark.parametrize("case", sorted(DIVERGENT))
def test_differs_from_golden_when_case_needs_hub_brief_script(
    case: str, *, char_workspace: Callable[..., Any], hook_python: str, golden: Any
) -> None:
    ws = char_workspace(python=hook_python)
    actual = ws.run_named(case, **CASES[case](ws=ws))
    path = golden.GOLDEN_ROOT / f"{case}.golden"
    expected = golden.parse(path.read_bytes(), path)
    differing = {stream for stream in golden.STREAMS if actual[stream] != expected[stream]}
    assert "stdout" in differing, f"{case} now matches the brief's output: drop it from DIVERGENT"
    assert differing <= BRIEF_STREAMS, f"{case}: {sorted(differing)} differ"
    assert actual["calls"] == b""
    snapshot_path = golden.GOLDEN_ROOT / f"{SNAPSHOT_OF.get(case, case)}.golden"
    snapshot_stdout = golden.parse(snapshot_path.read_bytes(), snapshot_path)["stdout"]
    assert actual["stdout"] == brief_free_stdout(snapshot_stdout)
