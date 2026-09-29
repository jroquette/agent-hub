"""The golden file harness of the characterization cases (AC-4.22's rules, AGH-7's format).

A golden holds five byte-counted sections; only the exact rendered bytes parse. Output is compared
after two rewrites only (the case root, collapsed tracebacks). A missing or orphan golden fails,
update mode is refused under ``CI``, and no mode variable reaches a child.
"""

import hashlib
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

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
