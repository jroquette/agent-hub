"""The golden file harness of the characterization cases (AC-4.22's rules, AGH-7's format).

A golden holds five byte-counted sections; only the exact rendered bytes parse. Output is compared
after two rewrites only (the case root, collapsed tracebacks). A missing or orphan golden fails,
update mode is refused under ``CI``, and no mode variable reaches a child. A case runs in its own
``<ROOT>`` under ``tmp_path``: an environment from scratch, a frozen clock, logging fakes and a
copy of the rendered hooks and scripts.
"""

import contextlib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from pathlib import Path, PurePosixPath
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

ACTUAL = {"rc": b"0\n", "stdout": b"a\nc\n", "stderr": b"", "fs": b"A <ROOT>/x/\n", "calls": b""}
GOLDEN = (
    b"--- rc (2 bytes) ---\n0\n\n"
    b"--- stdout (4 bytes) ---\na\nc\n\n"
    b"--- stderr (0 bytes) ---\n\n"
    b"--- fs (12 bytes) ---\nA <ROOT>/x/\n\n"
    b"--- calls (0 bytes) ---\n\n"
)
TRICKY = (
    b"",
    b"\n",
    b"\n\n",
    b"no final newline",
    b"a\r\nb",
    b"--- stdout (3 bytes) ---\n",
    b"\n--- rc (2 bytes) ---",
    "é ⚠\n".encode(),
    b"\x00\xff\n\x00",
)
CORRUPT = {
    "count too high": GOLDEN.replace(b"(4 bytes)", b"(5 bytes)"),
    "count too low": GOLDEN.replace(b"(4 bytes)", b"(3 bytes)"),
    "count with leading zero": GOLDEN.replace(b"(4 bytes)", b"(04 bytes)"),
    "unknown section": GOLDEN.replace(b"--- calls (", b"--- call ("),
    "sections swapped": GOLDEN.replace(b"--- rc (2 bytes) ---\n0\n\n", b"").replace(
        b"--- stderr (0", b"--- rc (2 bytes) ---\n0\n\n--- stderr (0"
    ),
    "section missing": GOLDEN.replace(b"--- calls (0 bytes) ---\n\n", b""),
    "separator missing": GOLDEN[:-1],
    "trailing bytes": GOLDEN + b"x",
    "truncated": GOLDEN[:30],
    "empty file": b"",
    "CRLF header": GOLDEN.replace(b"--- rc (2 bytes) ---\n", b"--- rc (2 bytes) ---\r\n"),
    "count past int limit": GOLDEN.replace(b"(4 bytes)", b"(" + b"9" * 5000 + b" bytes)"),
    "unpinned section": GOLDEN.replace(
        b"--- stderr (0 bytes) ---\n", b"--- stderr (not pinned: non-empty) ---\n"
    ),
}
TRACEBACK = (
    b"before\nTraceback (most recent call last):\n"
    b'  File "/x/brief.py", line 22, in <module>\n    TEAM = cfg["tracker"]["team"]\n'
    b"           ~~~^^^^^^^^^^^\nKeyError: 'tracker'\nafter\n"
)
COLLAPSED = b"before\nTraceback (most recent call last):\n  ...\nKeyError: 'tracker'\nafter\n"
MODE_AND_MAKE_VARIABLES = (
    "GOLDEN_UPDATE",
    "GOLDEN_KEEP",
    "MAKEFLAGS",
    "MFLAGS",
    "MAKELEVEL",
    "GNUMAKEFLAGS",
    "MAKEFILES",
)
CASE = "demo/c1"
BINARY = b"\x00\x01"


def write(path: Path, content: bytes | str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content if isinstance(content, bytes) else content.encode())


def test_writes_five_counted_sections_when_result_formatted(golden: Any) -> None:
    assert golden.STREAMS == ("rc", "stdout", "stderr", "fs", "calls")
    assert golden.render(ACTUAL) == GOLDEN
    assert golden.parse(GOLDEN) == ACTUAL
    empty = golden.render(ACTUAL | {"stdout": b""})
    assert b"--- stdout (0 bytes) ---\n\n--- stderr (0 bytes) ---\n\n" in empty


@pytest.mark.parametrize("content", TRICKY)
def test_reads_back_stream_when_content_tricky(golden: Any, content: bytes) -> None:
    streams = ACTUAL | {"rc": content, "stdout": content, "calls": content}

    rendered = golden.render(streams)

    assert golden.parse(rendered) == streams
    header = f"--- stdout ({len(content)} bytes) ---\n".encode()
    assert header + content + b"\n--- stderr " in rendered


@pytest.mark.parametrize("why", sorted(CORRUPT))
def test_rejects_golden_when_bytes_not_exactly_rendered(golden: Any, why: str) -> None:
    path = Path("/g/demo/c1.golden")

    with pytest.raises(golden.GoldenFormatError, match=r"^/g/demo/c1\.golden: byte \d+: "):
        golden.parse(CORRUPT[why], path)


def test_replaces_root_when_output_normalized(golden: Any, tmp_path: Path) -> None:
    nested = b"a /private/var/x/r/ws b /var/x/r/home\n"
    assert golden.normalize(nested, root="/private/var/x/r", given="/var/x/r") == (
        b"a <ROOT>/ws b <ROOT>/home\n"
    )
    real = tmp_path / "real" / "r"
    real.mkdir(parents=True)
    given = tmp_path / "given"
    given.symlink_to(real)
    raw = f"{real}/ws {given}/ws\n".encode() + TRACEBACK

    streams = golden.case_streams(
        root=given, returncode=1, stdout=raw, stderr=raw, fs=raw, calls=raw
    )

    replaced = b"<ROOT>/ws <ROOT>/ws\n"
    assert streams == {
        "rc": b"1\n",
        "stdout": replaced + COLLAPSED,
        "stderr": replaced + COLLAPSED,
        "fs": replaced + TRACEBACK,
        "calls": replaced + TRACEBACK,
    }


def test_keeps_text_when_no_traceback(golden: Any) -> None:
    data = b"  indented\nplain \xe2\x9a\xa0 text\n\nno final newline"

    assert golden.normalize(data, root="/nowhere", given="/nowhere") == data


def test_lists_changes_when_tree_snapshots_differ(golden: Any, tmp_path: Path) -> None:
    for name, content in {"m.txt": "old\n", "gone.txt": "bye\n", "same.txt": "same\n"}.items():
        write(tmp_path / name, content)
    before = golden.snapshot(tmp_path)
    for name, content in {
        "m.txt": "new\n\nend\n",
        "new/a.txt": "x\ny",
        "b.bin": BINARY,
        "new/empty.txt": "",
    }.items():
        write(tmp_path / name, content)
    (tmp_path / "gone.txt").unlink()
    (tmp_path / "link").symlink_to("m.txt")
    (tmp_path / "same.txt").chmod(0o755)

    changes = golden.fs_changes(before, golden.snapshot(tmp_path))

    assert changes.decode() == (
        f"A <ROOT>/b.bin sha256={hashlib.sha256(BINARY).hexdigest()}\n"
        "D <ROOT>/gone.txt\n"
        "A <ROOT>/link -> m.txt\n"
        "M <ROOT>/m.txt\n| new\n|\n| end\n"
        "A <ROOT>/new/\n"
        "A <ROOT>/new/a.txt\n| x\n| y\n\\ no newline at end of file\n"
        "A <ROOT>/new/empty.txt\n"
    )


def test_ignores_harness_paths_when_tree_snapshots_differ(golden: Any, tmp_path: Path) -> None:
    (tmp_path / "sub" / "__pycache__").mkdir(parents=True)
    before = golden.snapshot(tmp_path)
    for name, content in {
        ".git/HEAD": "ref\n",
        "sub/.git": "gitdir: x\n",
        "sub/__pycache__/m.pyc": b"\x00",
        "__pycache__/n.pyc": b"\x00",
        "bin/gh": "#!/bin/sh\n",
        "log/calls.jsonl": "{}\n",
    }.items():
        write(tmp_path / name, content)

    assert golden.fs_changes(before, golden.snapshot(tmp_path)) == b""
    write(tmp_path / "sub" / "bin" / "x", "kept\n")
    assert golden.fs_changes(before, golden.snapshot(tmp_path)) == (
        b"A <ROOT>/sub/bin/\nA <ROOT>/sub/bin/x\n| kept\n"
    )


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="no FIFOs on this platform")
def test_lists_special_file_without_reading_when_tree_holds_fifo(
    golden: Any, tmp_path: Path
) -> None:
    before = golden.snapshot(tmp_path)
    os.mkfifo(tmp_path / "pipe")

    changes = golden.fs_changes(before, golden.snapshot(tmp_path))

    assert changes == b"A <ROOT>/pipe other\n"


def test_shows_diff_per_section_when_golden_differs(
    golden: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / f"{CASE}.golden"
    write(path, golden.render(ACTUAL | {"stdout": b"a\nb\n", "rc": b"0", "calls": b"x\n"}))

    problems = golden.compare(tmp_path, CASE, ACTUAL, update=False)

    text = "\n".join(problems)
    for part in (
        f"--- {path} [stdout]",
        "+++ actual",
        "-b\n",
        "+c\n",
        f"--- {path} [rc]",
        "\\ no newline at end of file",
        f"--- {path} [calls]",
        "-x\n",
        "Update: GOLDEN_UPDATE=1 ",
    ):
        assert part in text
    for section in ("stderr", "fs"):
        assert f"[{section}]" not in text
    assert capsys.readouterr().err == ""


def test_fails_when_golden_missing(golden: Any, tmp_path: Path) -> None:
    problems = golden.compare(tmp_path, CASE, ACTUAL, update=False)

    assert len(problems) == 1
    assert problems[0].startswith(
        f"missing golden {tmp_path / CASE}.golden\nUpdate: GOLDEN_UPDATE=1"
    )
    assert not (tmp_path / "demo").exists()
    assert golden.missing(tmp_path, [CASE, "demo/c2"]) == [
        f"demo/c1: missing golden {tmp_path / 'demo' / 'c1.golden'}",
        f"demo/c2: missing golden {tmp_path / 'demo' / 'c2.golden'}",
    ]
    write(tmp_path / f"{CASE}.golden", GOLDEN)
    assert golden.missing(tmp_path, [CASE]) == []
    assert golden.compare(tmp_path, CASE, ACTUAL, update=False) == []


def test_fails_when_golden_corrupt(golden: Any, tmp_path: Path) -> None:
    path = tmp_path / f"{CASE}.golden"
    write(path, CORRUPT["count too high"])

    problems = golden.compare(tmp_path, CASE, ACTUAL, update=False)

    assert len(problems) == 1
    assert problems[0].startswith(f"corrupt golden {path}: byte ")
    assert "(wrong byte count?)\nUpdate: GOLDEN_UPDATE=1 " in problems[0]
    assert golden.compare(tmp_path, CASE, ACTUAL, update=True) == []
    assert path.read_bytes() == GOLDEN


@pytest.mark.parametrize("case", ["../escape", "demo/../../escape"])
def test_refuses_golden_path_when_case_leaves_golden_root(
    golden: Any, tmp_path: Path, *, capsys: pytest.CaptureFixture[str], case: str
) -> None:
    root = tmp_path / "golden"
    root.mkdir()
    outside = tmp_path / "escape.golden"
    message = f"{case}: golden path {outside} is outside {root}"

    for update in (False, True):
        assert golden.compare(root, case, ACTUAL, update=update) == [message]
    assert not outside.exists()
    assert capsys.readouterr().err == ""


def test_fails_when_golden_orphaned(golden: Any, tmp_path: Path) -> None:
    demo = tmp_path / "demo"
    for name, content in {
        "c1.golden": GOLDEN,
        "gone.golden": GOLDEN,
        "c1.stdout": "",
        ".golden": GOLDEN,
        "c2.golden": GOLDEN[:-1],
        "dir.golden/x": "",
    }.items():
        write(demo / name, content)
    write(tmp_path / "loose.golden", GOLDEN)
    write(tmp_path / "other" / "c1.golden", GOLDEN)
    cases = ("demo/c1", "demo/c2", "demo/dir")

    assert golden.orphans(tmp_path, cases) == [
        f"{demo / '.golden'}: not a <case>.golden file",
        f"{demo / 'c1.stdout'}: not a <case>.golden file",
        f"corrupt golden {demo / 'c2.golden'}: byte 139: section calls: its 0 bytes are not "
        "followed by the \\n separator (wrong byte count?)",
        f"{demo / 'dir.golden'}: not a <case>.golden file",
        f"{demo / 'gone.golden'}: no case demo/gone",
        f"{tmp_path / 'loose.golden'}: not a <file> directory",
        f"{tmp_path / 'other' / 'c1.golden'}: no case other/c1",
    ]
    assert golden.orphans(tmp_path / "nope", cases) == []


def test_rewrites_golden_only_when_changed_under_update(
    golden: Any, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / f"{CASE}.golden"

    assert golden.compare(tmp_path, CASE, ACTUAL, update=True) == []
    assert capsys.readouterr().err == f"wrote {path}\n"
    assert path.read_bytes() == GOLDEN
    os.utime(path, ns=(10**18, 10**18))
    assert golden.compare(tmp_path, CASE, ACTUAL, update=True) == []
    assert capsys.readouterr().err == ""
    assert path.stat().st_mtime_ns == 10**18
    write(path, golden.render(ACTUAL | {"stdout": b"a\n"}))
    assert golden.compare(tmp_path, CASE, ACTUAL, update=True) == []
    assert path.read_bytes() == GOLDEN
    assert [p.name for p in path.parent.iterdir()] == ["c1.golden"]


def test_fails_case_when_streams_differ_from_golden(
    golden: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GOLDEN_UPDATE", "CI"):
        monkeypatch.delenv(name, raising=False)
    write(tmp_path / f"{CASE}.golden", GOLDEN)
    golden.assert_matches(tmp_path, CASE, ACTUAL)

    with pytest.raises(pytest.fail.Exception, match=r"(?s)^demo/c1:\n--- .*\[stderr\]"):
        golden.assert_matches(tmp_path, CASE, ACTUAL | {"stderr": b"oops\n"})

    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    golden.assert_matches(tmp_path, CASE, ACTUAL | {"stderr": b"oops\n"})
    assert golden.parse((tmp_path / f"{CASE}.golden").read_bytes())["stderr"] == b"oops\n"


@pytest.mark.parametrize(
    ("environ", "expected"),
    [({}, False), ({"GOLDEN_UPDATE": "1"}, True), ({"GOLDEN_UPDATE": "yes"}, False)],
)
def test_reads_update_mode_when_ci_unset(
    golden: Any, monkeypatch: pytest.MonkeyPatch, environ: dict[str, str], *, expected: bool
) -> None:
    for name in ("GOLDEN_UPDATE", "CI"):
        monkeypatch.delenv(name, raising=False)
    for name, value in environ.items():
        monkeypatch.setenv(name, value)

    assert golden.update_mode() is expected


def test_refuses_update_when_ci_set(
    golden: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    monkeypatch.setenv("CI", "true")

    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        golden.update_mode()
    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        golden.assert_matches(tmp_path, CASE, ACTUAL)
    assert not (tmp_path / "demo").exists()
    monkeypatch.delenv("GOLDEN_UPDATE")
    assert golden.update_mode() is False


def test_drops_mode_variables_when_child_env_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, run_python: Callable[..., Any]
) -> None:
    for name in MODE_AND_MAKE_VARIABLES:
        monkeypatch.setenv(name, "1")
    passed = dict.fromkeys(MODE_AND_MAKE_VARIABLES, "2") | {"CASE_VALUE": "kept"}

    seen = run_python(
        sys.executable,
        "import json, os\nprint(json.dumps(dict(os.environ)))",
        path=tmp_path,
        env=passed,
    )

    assert set(seen) & set(MODE_AND_MAKE_VARIABLES) == set()
    assert seen["CASE_VALUE"] == "kept"


# The characterization workspace (AGH-7's ``support/workspace.py``, ``fixtures.py`` and
# ``commands.py``).

FIXED = 1768473000  # 2026-01-15T10:30:00Z
FROZEN = {
    "time": 1768473000.0,
    "time_ns": 1768473000 * 10**9,
    "strftime": "2026-01-15 10:30:00",
    "localtime": [2026, 1, 15, 10, 30, 0],
    "gmtime": [2026, 1, 15, 10, 30, 0],
    "ctime": "Thu Jan 15 10:30:00 2026",
    "asctime": "Thu Jan 15 10:30:00 2026",
    "date_today": "2026-01-15",
    "datetime_now": "2026-01-15T10:30:00",
    "datetime_now_utc": "2026-01-15T10:30:00+00:00",
    "datetime_today": "2026-01-15T10:30:00",
}
CLOCK_PROBE = """
import datetime, json, subprocess, sys, time
seen = {
    "time": time.time(), "time_ns": time.time_ns(), "strftime": time.strftime("%Y-%m-%d %H:%M:%S"),
    "localtime": list(time.localtime())[:6], "gmtime": list(time.gmtime())[:6],
    "ctime": time.ctime(), "asctime": time.asctime(),
    "date_today": datetime.date.today().isoformat(),
    "datetime_now": datetime.datetime.now().isoformat(),
    "datetime_now_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "datetime_today": datetime.datetime.today().isoformat(),
    "zone_offset": time.timezone, "version": list(sys.version_info[:2]),
}
if len(sys.argv) > 1:
    out = subprocess.run([sys.executable, "-c", sys.argv[1]], capture_output=True, text=True)
    seen["grandchild"] = json.loads(out.stdout)
print(json.dumps(seen))
"""
# A POSIX zone 5:30 east of UTC (no tz database needed): the frozen clock must ignore it.
EAST_ZONE = "XST-5:30"
ROOT_LAYOUT = ["bin", "bin/python3", "elsewhere", "home", "home/.config", "log", "origins", "ws"]
CASE_ENV_KEYS = {
    "PATH",
    "HOME",
    "XDG_CONFIG_HOME",
    "TZ",
    "PYTHONUTF8",
    "PYTHONHASHSEED",
    "PYTHONDONTWRITEBYTECODE",
    "PYTHONPATH",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_AUTHOR_NAME",
    "GIT_AUTHOR_EMAIL",
    "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME",
    "GIT_COMMITTER_EMAIL",
    "GIT_COMMITTER_DATE",
    "GIT_ALLOW_PROTOCOL",
    "GIT_TERMINAL_PROMPT",
    "GIT_CEILING_DIRECTORIES",
    "GIT_CONFIG_COUNT",
}
# AGH-7's ``HUB_JSON`` exactly as its hub copy writes it: ``json.dumps(..., indent=2) + "\n"``.
AGH7_HUB_JSON = (
    b'{\n  "project": {\n    "name": "demo",\n    "hub_repo": "acme/demo-hub",\n'
    b'    "branch_prefix": "dev/",\n    "default_branch": "trunk",\n'
    b'    "author_name": "Test User",\n    "author_email": "t@example.com"\n  },\n'
    b'  "tracker": {\n    "kind": "linear",\n    "team": "TST"\n  },\n'
    b'  "repos": [\n    {\n      "dir": "api",\n      "github": "acme/api"\n    },\n'
    b'    {\n      "dir": "web",\n      "github": "acme/web"\n    }\n  ]\n}\n'
)
HUB_GITIGNORE = (
    ".claude/worktrees/\n.venv/\nnode_modules/\n__pycache__/\n.agent-runs/\n"
    "brain/_inbox/sessions/\nbrain/auto/workspace/session-snapshot.md\n"
)
# What ``/bin/sh``, the locale coercion or macOS may add to any child: never a harness value.
SHELL_AND_PLATFORM_VARIABLES = {"LC_CTYPE", "PWD", "SHLVL", "_", "__CF_USER_TEXT_ENCODING"}
# A child that starts a grandchild sharing its stdout, then both sleep: only killing the whole
# process group ends the run.
SLEEPING_FAMILY = """
import subprocess, sys, time
grandchild = subprocess.Popen(["sleep", "30"])
with open(sys.argv[1], "w") as f:
    f.write(str(grandchild.pid))
time.sleep(30)
"""
INSTEAD_OF_PROBE = (
    "import json, os\n"
    "urls = sorted(v for k, v in os.environ.items() if v.endswith('.git.insteadOf'))\n"
    "print(json.dumps([os.getcwd(), urls]))\n"
)
COPIED_GLOBS = ("scripts/*.py", "plugin/hub-workflow/hooks/*.py")
CASE_FILES = ("retro_metrics", "post_edit", "session_start", "session_end", "pre_compact")


def git_out(ws: Any, *args: str, cwd: Path) -> str:
    return str(ws.git(*args, cwd=cwd).stdout)


def test_builds_root_layout_when_workspace_created(
    char_workspace: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LEAK_PROBE", "leaked")
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    ws = char_workspace()

    root = ws.root
    assert root == tmp_path / "root"
    assert sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) == ROOT_LAYOUT
    assert sorted(p.name for p in (tmp_path / "support" / "clock").iterdir()) == [
        "sitecustomize.py"
    ]
    assert (tmp_path / "support" / "fake_tool.py").is_file()
    shim = root / "bin" / "python3"
    assert os.access(shim, os.X_OK)
    env = ws.env({"repos": [{"dir": "api", "github": "acme/api"}]})
    assert set(env) == CASE_ENV_KEYS | {
        f"GIT_CONFIG_{kind}_{i}" for kind in ("KEY", "VALUE") for i in range(5)
    }
    assert env["PATH"] == f"{root}/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    assert env["HOME"] == str(root / "home")
    assert (env["TZ"], env["PYTHONHASHSEED"], env["GIT_ALLOW_PROTOCOL"]) == ("UTC", "0", "file")
    assert env["PYTHONPATH"] == str(tmp_path / "support" / "clock")
    assert env["GIT_AUTHOR_DATE"] == env["GIT_COMMITTER_DATE"] == "2026-01-15T10:30:00Z"
    assert env["GIT_CEILING_DIRECTORIES"] == str(root)
    pairs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"] for i in range(5)}
    assert pairs[f"url.{root}/origins/api.git.insteadOf"] == "https://github.com/acme/api.git"
    assert pairs["maintenance.auto"] == "false"
    seen = subprocess.run(  # noqa: S603 - the workspace's own python3 shim, fixed script
        [
            str(shim),
            "-c",
            "import json, os, sys; print(json.dumps([sys.executable, dict(os.environ)]))",
        ],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    executable, child_env = json.loads(seen.stdout)
    assert executable == sys.executable
    assert {key: child_env.get(key) for key in env} == env
    assert set(child_env) - set(env) <= SHELL_AND_PLATFORM_VARIABLES
    assert {"LEAK_PROBE", "GOLDEN_UPDATE"} & set(child_env) == set()


def test_uses_given_python_when_workspace_created(
    char_workspace: Callable[..., Any], tmp_path: Path
) -> None:
    ws = char_workspace(python="/opt/py/bin/python3.9")

    assert ws.python == "/opt/py/bin/python3.9"
    assert (
        ws.root / "bin" / "python3"
    ).read_text() == '#!/bin/sh\nexec "/opt/py/bin/python3.9" "$@"\n'
    assert ws.command("post_edit", hub=tmp_path / "h") == [
        "/opt/py/bin/python3.9",
        f"{tmp_path}/h/plugin/hub-workflow/hooks/post_edit.py",
    ]


def test_names_one_file_per_case_folder_when_commands_listed(
    char_workspace: Callable[..., Any],
) -> None:
    ws = char_workspace()
    hub = ws.root / "ws" / "demo-hub"

    assert sorted(ws.COMMANDS) == sorted(CASE_FILES)
    assert {name: ws.command(name, hub=hub)[1:] for name in CASE_FILES} == {
        "retro_metrics": [f"{hub}/scripts/retro_metrics.py"],
        "post_edit": [f"{hub}/plugin/hub-workflow/hooks/post_edit.py"],
        "session_start": [f"{hub}/plugin/hub-workflow/hooks/session_start.py"],
        "session_end": [f"{hub}/plugin/hub-workflow/hooks/session_end.py"],
        "pre_compact": [f"{hub}/plugin/hub-workflow/hooks/pre_compact.py"],
    }


def test_freezes_clock_when_child_imports_sitecustomize(
    char_workspace: Callable[..., Any], hook_python: str
) -> None:
    ws = char_workspace(python=hook_python)
    env = ws.env() | {"TZ": EAST_ZONE}

    seen = subprocess.run(  # noqa: S603 - an interpreter from hook_python, fixed script
        [hook_python, "-c", CLOCK_PROBE, CLOCK_PROBE],
        capture_output=True,
        text=True,
        check=True,
        env=env,
        cwd=ws.root / "elsewhere",
    )

    child = json.loads(seen.stdout)
    grandchild = child.pop("grandchild")
    for values in (child, grandchild):
        assert values.pop("zone_offset") == -19800  # the zone is really in effect
        assert values.pop("version") == child_version(hook_python)
        assert values == FROZEN
    assert ws.FIXED == FIXED
    assert ws.at() == "2026-01-15T10:30:00Z"
    assert ws.at(3, "09:05") == "2026-01-12T09:05:00Z"


def child_version(python: str) -> list[int]:
    out = subprocess.run(  # noqa: S603 - an interpreter from hook_python, fixed script
        [python, "-I", "-c", "import sys; print(list(sys.version_info[:2]))"],
        capture_output=True,
        text=True,
        check=True,
    )
    return list(json.loads(out.stdout))


def test_patches_nothing_when_clock_imported_under_other_name(
    char_workspace: Callable[..., Any], tmp_path: Path
) -> None:
    char_workspace()
    clock = tmp_path / "support" / "clock" / "sitecustomize.py"
    code = (
        "import datetime, importlib.util, json, sys, time\n"
        f"spec = importlib.util.spec_from_file_location('clock_probe', {str(clock)!r})\n"
        "module = importlib.util.module_from_spec(spec)\n"
        "spec.loader.exec_module(module)\n"
        "print(json.dumps([module.FIXED, time.time(), datetime.date.today().year]))\n"
    )

    seen = subprocess.run(  # noqa: S603 - this interpreter, fixed script
        [sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True
    )

    fixed, now, year = json.loads(seen.stdout)
    assert fixed == FIXED
    assert now > FIXED + 86400
    assert year >= 2026


def test_logs_call_when_fake_tool_runs(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()
    root = ws.root
    repo = root / "ws" / "api"
    ws.install_fakes(
        {
            "gh": [
                {
                    "argv_has": ["pr", "--repo"],
                    "env_has": {"FAKE_PROBE": "ba"},
                    "stdout": "out é\n",
                    "stderr": "err\n",
                    "rc": 3,
                    "write": {"made/w.txt": "written"},
                },
                {"argv_has": ["pr"], "stdout": "fallback\n"},
            ]
        }
    )
    ws.install_repo_fakes(repo, ["ruff", "eslint"])
    env = ws.env()
    cwd = root / "elsewhere"

    def call(tool: Path, *args: str, **extra: str) -> tuple[int, str, str]:
        done = subprocess.run(  # noqa: S603 - a fake tool of the workspace, fixed arguments
            [str(tool), *args],
            capture_output=True,
            text=True,
            check=False,
            cwd=cwd,
            env=env | extra,
        )
        return done.returncode, done.stdout, done.stderr

    gh = root / "bin" / "gh"
    assert call(gh, "pr", "list", "--repo", "acme/api", FAKE_PROBE="bar") == (3, "out é\n", "err\n")
    assert (cwd / "made" / "w.txt").read_text() == "written"
    assert call(gh, "pr", "--repo", "acme/api", FAKE_PROBE="other") == (0, "fallback\n", "")
    assert call(gh, "issue", "list") == (1, "", "")
    assert call(root / "bin" / "claude", "-p", "x") == (1, "", "")
    ruff = repo / ".venv" / "bin" / "ruff"
    assert call(ruff, "check", "a.py") == (1, "", "")
    assert (repo / "node_modules" / ".bin" / "eslint").is_file()
    assert not (repo / "node_modules" / ".bin" / "ruff").exists()
    logged = (root / "log" / "calls.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in logged] == [
        {"tool": "gh", "cwd": str(cwd), "argv": [str(gh), "pr", "list", "--repo", "acme/api"]},
        {"tool": "gh", "cwd": str(cwd), "argv": [str(gh), "pr", "--repo", "acme/api"]},
        {"tool": "gh", "cwd": str(cwd), "argv": [str(gh), "issue", "list"]},
        {"tool": "claude", "cwd": str(cwd), "argv": [str(root / "bin" / "claude"), "-p", "x"]},
        {"tool": "ruff", "cwd": str(cwd), "argv": [str(ruff), "check", "a.py"]},
    ]


def test_accepts_config_when_characterization_rendered(char_config: HubConfig) -> None:
    assert char_config.project.name == "demo"
    assert char_config.project.hub_repo == "acme/demo-hub"
    assert char_config.project.default_branch == "trunk"
    assert [repo.dir for repo in char_config.repos] == ["api", "web"]


def test_copies_rendered_hooks_and_scripts_when_hub_copied(
    char_workspace: Callable[..., Any], char_config: HubConfig
) -> None:
    rendered = {
        file.path: file
        for file in render_hub(char_config).files
        if any(PurePosixPath(file.path).full_match(glob) for glob in COPIED_GLOBS)
    }
    ws = char_workspace()

    hub = ws.hub_copy()

    assert hub == ws.root / "ws" / "demo-hub"
    assert "plugin/hub-workflow/hooks/stdlib_reader.py" in rendered
    on_disk = sorted(
        p.relative_to(hub).as_posix()
        for p in hub.rglob("*")
        if ".git" not in p.relative_to(hub).parts and not p.is_dir()
    )
    assert on_disk == sorted([*rendered, ".gitignore", "hub.json"])
    assert git_out(ws, "ls-files", cwd=hub).splitlines() == on_disk
    for path, file in rendered.items():
        copy = hub / path
        assert not copy.is_symlink()
        assert copy.read_bytes() == file.content
        assert os.access(copy, os.X_OK) is file.executable
    assert (hub / "hub.json").read_bytes() == AGH7_HUB_JSON
    assert (hub / ".gitignore").read_text() == HUB_GITIGNORE
    assert git_out(ws, "status", "--porcelain", cwd=hub) == ""
    assert git_out(ws, "log", "--format=%s %aI %cI %an", cwd=hub) == (
        "init 2025-12-16T09:00:00+00:00 2025-12-16T09:00:00+00:00 Test User\n"
    )
    assert git_out(ws, "branch", "--show-current", cwd=hub) == "trunk\n"


def test_reaches_bare_origin_when_github_url_used(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()
    hub = ws.hub_copy(origin=True)
    head = git_out(ws, "rev-parse", "HEAD", cwd=hub)

    git = shutil.which("git")
    assert git is not None

    remote = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        [git, "ls-remote", "https://github.com/acme/demo-hub.git", "trunk"],
        capture_output=True,
        text=True,
        check=True,
        cwd=hub,
        env=ws.env(ws.HUB_JSON),
    )

    assert remote.stdout == f"{head.strip()}\trefs/heads/trunk\n"
    assert git_out(ws, "remote", "get-url", "origin", cwd=hub) == (
        f"{ws.root}/origins/demo-hub.git\n"
    )


def test_finds_no_hub_when_started_elsewhere(
    char_workspace: Callable[..., Any], tmp_path: Path
) -> None:
    ws = char_workspace()
    ws.hub_copy(extra_files={"brain/now.md": "# Now\n"})
    elsewhere = ws.root / "elsewhere"

    assert ws.hubs_above(elsewhere) == []

    decoy = tmp_path / "decoy"
    (decoy / "brain").mkdir(parents=True)
    (decoy / "hub.json").write_text("{}\n")
    assert ws.hubs_above(elsewhere) == [decoy]
    (ws.root / "hub.json").write_text("{}\n")
    assert ws.hubs_above(elsewhere) == [ws.root, decoy]
    assert ws.hubs_above(ws.root / "missing" / "deeper") == [ws.root, decoy]


def test_refuses_fixture_paths_when_they_differ_only_by_case(
    char_workspace: Callable[..., Any],
) -> None:
    ws = char_workspace()
    base = ws.root / "ws" / "x"
    ws.write_files(base, {"Docs/a.md": "a\n"})

    with pytest.raises(ValueError, match=r"differ only by case \(docs vs existing Docs\)"):
        ws.write_files(base, {"docs/b.md": "b\n", "c.md": "c\n"})
    with pytest.raises(ValueError, match=r"A\.md vs a\.md"):
        ws.write_files(base, {"a.md": "", "A.md": ""})
    assert sorted(p.name for p in base.iterdir()) == ["Docs"]


def test_records_five_streams_when_case_run(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()
    ws.hub_copy()
    code = (
        "import os, subprocess, sys\n"
        "print(os.getcwd())\n"
        "open(os.path.join(os.environ['HOME'], 'made.txt'), 'w').write('hi\\n')\n"
        "subprocess.run(['gh', 'pr', 'view'])\n"
        "sys.stderr.write(sys.stdin.read())\n"
        "raise SystemExit(4)\n"
    )

    streams = ws.run([sys.executable, "-c", code], stdin=b"in\n", answers={"gh": []})

    hub = "<ROOT>/ws/demo-hub"
    assert streams == {
        "rc": b"4\n",
        "stdout": f"{hub}\n".encode(),
        "stderr": b"in\n",
        "fs": b"A <ROOT>/home/made.txt\n| hi\n",
        "calls": (
            json.dumps({"tool": "gh", "cwd": hub, "argv": ["<ROOT>/bin/gh", "pr", "view"]}) + "\n"
        ).encode(),
    }
    assert (ws.root / "bin" / "answers.json").read_text() == '{\n  "gh": []\n}\n'


def test_starts_in_elsewhere_when_case_expects_no_hub(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()
    ws.hub_copy()
    (ws.root / "hub.json").write_text("{}\n")
    probe = [sys.executable, "-c", "import os; print(os.getcwd())"]

    with pytest.raises(pytest.fail.Exception, match="a hub above <ROOT>/elsewhere"):
        ws.run(probe, no_hub=True)
    (ws.root / "hub.json").unlink()
    assert ws.run(probe, no_hub=True)["stdout"] == b"<ROOT>/elsewhere\n"


def process_gone(pid: int) -> bool:
    """Whether ``pid`` has exited (a zombie waiting for its reaper counts as gone)."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    ps = shutil.which("ps")
    assert ps is not None
    state = subprocess.run(  # noqa: S603 - ps from PATH, fixed arguments
        [ps, "-o", "stat=", "-p", str(pid)], capture_output=True, text=True, check=False
    )
    return state.stdout.strip() in {"", "Z"} or state.stdout.strip().startswith("Z")


def test_kills_process_group_when_time_cap_exceeded(
    char_workspace: Callable[..., Any], tmp_path: Path
) -> None:
    ws = char_workspace()
    ws.hub_copy()
    pid_file = tmp_path / "grandchild.pid"
    ws.started = time.monotonic() - (ws.time_cap - 1.0)  # 1 s of the budget left
    start = time.monotonic()

    try:
        with pytest.raises(pytest.fail.Exception, match=r"exceeded the case time cap of 10\.0 s"):
            ws.run([sys.executable, "-c", SLEEPING_FAMILY, str(pid_file)])
        assert time.monotonic() - start < 4
        pid = int(pid_file.read_text())
        deadline = time.monotonic() + 3
        while not process_gone(pid) and time.monotonic() < deadline:
            time.sleep(0.05)
        assert process_gone(pid)
    finally:
        if pid_file.is_file():
            with contextlib.suppress(ProcessLookupError):
                os.kill(int(pid_file.read_text()), signal.SIGKILL)


def test_counts_setup_in_time_cap_when_case_runs(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()
    ws.hub_copy()
    assert ws.time_cap == 10.0
    assert 0 <= time.monotonic() - ws.started < ws.time_cap  # the budget started with the root
    ws.started = time.monotonic() - (ws.time_cap - 0.3)  # setup spent all but 0.3 s
    start = time.monotonic()

    with pytest.raises(pytest.fail.Exception, match="exceeded the case time cap"):
        ws.run([sys.executable, "-c", "import time; time.sleep(5)"])
    assert time.monotonic() - start < 3  # the child got the rest (floor 0.5 s), not 10 s


def test_fails_after_compare_when_budget_spent(
    char_workspace: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GOLDEN_UPDATE", "CI"):
        monkeypatch.delenv(name, raising=False)
    ws = char_workspace()
    hub = ws.hub_copy()
    (hub / "plugin" / "hub-workflow" / "hooks" / "post_edit.py").write_text("print('ok')\n")
    golden_root = tmp_path / "g"
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    ws.run_case("post_edit/demo", golden_root=golden_root)
    monkeypatch.delenv("GOLDEN_UPDATE")
    ws.started = time.monotonic() - ws.time_cap - 1  # over budget before the run: floor 0.5 s

    with pytest.raises(pytest.fail.Exception) as failure:
        ws.run_case("post_edit/demo", golden_root=golden_root)

    message = str(failure.value)
    assert re.fullmatch(
        r"post_edit/demo:\npost_edit/demo exceeded the case time cap of 10\.0 s after "
        r"\d+\.\d s \(setup, run and compare\)",
        message,
    ), message


def test_reads_worktree_hub_json_when_case_runs_against_hub_worktree(
    char_workspace: Callable[..., Any],
    golden: Any,
    tmp_path: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for name in ("GOLDEN_UPDATE", "CI"):
        monkeypatch.delenv(name, raising=False)
    ws = char_workspace()
    hub = ws.hub_copy()
    wt = ws.add_worktree(hub, "t1")
    (wt / "hub.json").write_text('{"repos": [{"dir": "wtonly", "github": "acme/wtonly"}]}\n')
    probe = [sys.executable, "-c", INSTEAD_OF_PROBE]

    from_worktree = json.loads(ws.run(probe, hub=wt)["stdout"])
    from_hub = json.loads(ws.run(probe)["stdout"])
    no_hub_json = json.loads(ws.run(probe, hub=ws.root / "elsewhere")["stdout"])

    assert from_worktree == [
        "<ROOT>/ws/demo-hub/.claude/worktrees/t1",
        ["url.<ROOT>/origins/wtonly.git.insteadOf"],
    ]
    demo_urls = [f"url.<ROOT>/origins/{name}.git.insteadOf" for name in ("api", "demo-hub", "web")]
    assert from_hub == ["<ROOT>/ws/demo-hub", demo_urls]
    assert no_hub_json == ["<ROOT>/elsewhere", demo_urls]
    (wt / "plugin" / "hub-workflow" / "hooks" / "post_edit.py").write_text(INSTEAD_OF_PROBE)
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    ws.run_case("post_edit/wt", hub=wt, golden_root=tmp_path / "g")
    written = (tmp_path / "g" / "post_edit" / "wt.golden").read_bytes()
    assert json.loads(golden.parse(written)["stdout"]) == from_worktree


def test_gives_each_workspace_its_own_root_when_factory_called_twice(
    char_workspace: Callable[..., Any], tmp_path: Path
) -> None:
    first, second = char_workspace(), char_workspace()

    assert (first.root, second.root) == (tmp_path / "root", tmp_path / "root-2")
    assert sorted(p.relative_to(second.root).as_posix() for p in second.root.rglob("*")) == (
        ROOT_LAYOUT
    )
    second.hub_copy()
    assert not (first.root / "ws" / "demo-hub").exists()
    assert second.env()["HOME"] == str(tmp_path / "root-2" / "home")


def test_refuses_update_before_case_runs_when_ci_set(
    char_workspace: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    monkeypatch.setenv("CI", "true")
    ws = char_workspace()
    ws.hub_copy()

    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        ws.run_case("post_edit/empty_stdin", answers={"gh": []}, golden_root=tmp_path / "g")
    assert not (ws.root / "bin" / "answers.json").exists()
    assert not (tmp_path / "g").exists()


def test_compares_case_with_its_golden_when_case_run(
    char_workspace: Callable[..., Any], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("GOLDEN_UPDATE", "CI"):
        monkeypatch.delenv(name, raising=False)
    ws = char_workspace()
    hub = ws.hub_copy()
    hook = hub / "plugin" / "hub-workflow" / "hooks" / "post_edit.py"
    hook.write_text("print('edited')\n")
    golden_root = tmp_path / "g"

    with pytest.raises(pytest.fail.Exception, match="missing golden"):
        ws.run_case("post_edit/demo", golden_root=golden_root)
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    ws.run_case("post_edit/demo", golden_root=golden_root)
    monkeypatch.delenv("GOLDEN_UPDATE")
    ws.run_case("post_edit/demo", golden_root=golden_root)
    assert (golden_root / "post_edit" / "demo.golden").read_bytes() == (
        b"--- rc (2 bytes) ---\n0\n\n--- stdout (7 bytes) ---\nedited\n\n"
        b"--- stderr (0 bytes) ---\n\n--- fs (0 bytes) ---\n\n--- calls (0 bytes) ---\n\n"
    )


@pytest.mark.parametrize(("keep", "kept"), [(True, True), (False, False)])
def test_keeps_root_only_when_keep_mode_set(
    char_workspace: Callable[..., Any], *, keep: bool, kept: bool
) -> None:
    ws = char_workspace()
    said: list[str] = []

    ws.release(keep=keep, say=said.append)

    assert ws.root.exists() is kept
    assert said == ([f"GOLDEN_KEEP {ws.root}"] if kept else [])


@pytest.fixture
def after_teardown() -> Iterator[dict[str, Any]]:
    """Checks, after ``char_workspace`` is torn down (it is set up later), what became of roots."""
    expected: dict[str, Any] = {}
    yield expected
    try:
        for root in expected.get("roots", []):
            assert root.exists() is expected["kept"]
    finally:
        for root in expected.get("roots", []):
            shutil.rmtree(root, ignore_errors=True)


@pytest.mark.parametrize("keep", [True, False])
def test_releases_roots_when_fixture_torn_down(
    after_teardown: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    char_workspace: Callable[..., Any],
    *,
    keep: bool,
) -> None:
    if keep:
        monkeypatch.setenv("GOLDEN_KEEP", "1")
    else:
        monkeypatch.delenv("GOLDEN_KEEP", raising=False)

    roots = [char_workspace().root, char_workspace().root]

    after_teardown |= {"roots": roots, "kept": keep}
    assert all(root.is_dir() for root in roots)


def test_builds_brief_workspace_when_fixture_built(char_workspace: Callable[..., Any]) -> None:
    ws = char_workspace()

    ws.brief_workspace()

    root = ws.root
    hub, api, web = (root / "ws" / name for name in ("demo-hub", "api", "web"))
    assert json.loads((hub / "hub.json").read_text())["repos"][-1] == {
        "dir": "ui",
        "github": "acme/ui",
    }
    assert not (root / "ws" / "ui").exists()
    assert (hub / "brain" / "now.md").read_text().startswith("---\nlast_verified: 2026-01-12\n")
    assert git_out(ws, "status", "--porcelain", cwd=hub) == ""
    assert git_out(ws, "rev-list", "--count", "trunk...origin/trunk", cwd=hub) == "0\n"
    assert git_out(ws, "status", "--porcelain", cwd=api) == " M README.md\n?? notes.txt\n"
    assert git_out(ws, "rev-list", "--count", "trunk..origin/trunk", cwd=api) == "1\n"
    assert git_out(ws, "rev-list", "--count", "origin/trunk..trunk", cwd=api) == "0\n"
    assert git_out(ws, "branch", "--show-current", cwd=web) == ""
    assert ws.BRIEF_GH["gh"][0]["argv_has"] == ["pr", "acme/api"]
    ws.commit_hub({"brain/now.md": None, "brain/x.md": "x\n"})
    assert git_out(ws, "log", "-1", "--format=%s %aI", "--name-status", cwd=hub) == (
        "case change 2026-01-15T09:30:00+00:00\n\nD\tbrain/now.md\nA\tbrain/x.md\n"
    )
