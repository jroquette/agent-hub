"""The security-sweep pack's ``unseen.py`` (AGH-486), in process: which findings are new against the
hub's store (``select``, which writes nothing), and marking them seen after the report (``mark``).
"""

import importlib.util
import io
import json
import os
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/security-sweep/scripts/unseen.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.security-sweep.scripts.unseen"
TODAY = "2026-10-26"
EMPTY = json.dumps({"findings": [], "listed": 0, "ran": [], "current": []})


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def a_finding(rule: str = "r1", path: str = "a.py", line: int | None = 1, **more: Any) -> Any:
    return {
        "repo": "app",
        "scanner": "semgrep",
        "rule": rule,
        "path": path,
        "line": line,
        "severity": "high",
        "cwe": "",
        "secret": False,
        "package": "",
        "version": "",
        "advisory": "",
        "fixed": "",
        "title": "",
    } | more


def a_scan(*findings: Any, ran: tuple[str, ...] = ("semgrep",), more: int = 0) -> Any:
    scanners = [
        {"name": name, "status": "ran" if name in ran else "missing", "note": "", "count": 0}
        for name in ("semgrep", "bandit", "pip-audit", "npm", "guard")
    ]
    record = {
        "repo": "app",
        "ref": "origin/main",
        "head": "0" * 40,
        "date": "",
        "status": "scanned",
        "note": "",
        "scanners": scanners,
    }
    return {"repos": [record], "findings": list(findings), "more": more, "trimmed": False}


class Store:
    """``unseen.py`` run in process against a store in ``tmp_path``."""

    def __init__(self, tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: Any):
        self.path = tmp_path / ".agent-runs" / "security-sweep" / "seen.json"
        self.capsys = capsys
        self.monkeypatch = monkeypatch

    def call(self, *argv: str, stdin: str) -> tuple[int, str]:
        self.monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
        code = load().main([*argv, "--store", str(self.path), "--today", TODAY])
        captured = self.capsys.readouterr()
        return code, captured.out

    def select(self, scan: Any) -> Any:
        code, out = self.call("select", stdin=json.dumps(scan))
        assert code == 0
        return json.loads(out)

    def mark(self, selected: Any, status: str = "findings", triaged: Any = None) -> Any:
        """``mark`` with ``triaged`` (default: every listed id, as a full triage names them)."""
        named = [finding["id"] for finding in selected["findings"]] if triaged is None else triaged
        argv = ("mark", "--status", status, "--triaged", json.dumps(named))
        code, out = self.call(*argv, stdin=json.dumps(selected))
        assert code == 0
        return json.loads(out)

    def seen(self) -> dict[str, str]:
        found: dict[str, str] = json.loads(self.path.read_text())["seen"]
        return found


@pytest.fixture
def store(tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: Any) -> Store:
    return Store(tmp_path, capsys, monkeypatch)


def test_lists_none_as_new_when_second_run_sees_same_scan(store: Store) -> None:
    scan = a_scan(a_finding("r1"), a_finding("r2"), a_finding("r3", path="b.py"))

    first = store.select(scan)
    marked = store.mark(first)
    second = store.select(scan)

    assert first["listed"] == 3
    assert [finding["id"] for finding in first["findings"]] == ["F1", "F2", "F3"]
    assert first["counts"] == {"new": 3, "seen": 0, "more": 0}
    assert marked == {"status": "findings", "marked": 3, "store_size": 3}
    assert set(store.seen().values()) == {TODAY}
    assert second["listed"] == 0
    assert second["findings"] == []
    assert second["counts"] == {"new": 0, "seen": 3, "more": 0}


def test_lists_finding_again_when_it_was_fixed_and_came_back(store: Store) -> None:
    with_it, without = a_scan(a_finding("r1"), a_finding("r2")), a_scan(a_finding("r2"))
    store.mark(store.select(with_it))

    store.mark(store.select(without), "clean")
    back = store.select(with_it)

    assert [finding["rule"] for finding in back["findings"]] == ["r1"]


def test_keeps_seen_entries_when_their_scanner_did_not_run(store: Store) -> None:
    store.mark(store.select(a_scan(a_finding("r1"), a_finding("b1", scanner="bandit"))))

    store.mark(store.select(a_scan(ran=("bandit",))), "clean")
    again = store.select(a_scan(a_finding("r1"), a_finding("b1", scanner="bandit")))

    # bandit ran and found nothing: its entry went; semgrep did not run: its entry stays.
    assert [finding["rule"] for finding in again["findings"]] == ["b1"]


def test_keeps_seen_entries_when_scan_was_cut(store: Store) -> None:
    store.mark(store.select(a_scan(a_finding("r1"), a_finding("r2"))))

    # Cut at its cap, the scan's listing does not show every finding the scanners still report.
    store.mark(store.select(a_scan(a_finding("r1"), more=1)), "clean")
    again = store.select(a_scan(a_finding("r1"), a_finding("r2")))

    assert again["listed"] == 0


def test_marks_nothing_when_select_alone_runs(store: Store) -> None:
    store.select(a_scan(a_finding()))
    assert not store.path.exists()

    store.mark(store.select(a_scan(a_finding("r1"))))
    before = store.path.read_bytes()
    store.select(a_scan(a_finding("r9")))

    assert store.path.read_bytes() == before


def test_keeps_fingerprint_when_line_shifts(store: Store) -> None:
    first = store.select(a_scan(a_finding(line=3)))
    store.mark(first)

    shifted = store.select(a_scan(a_finding(line=40)))

    assert shifted["listed"] == 0
    assert shifted["current"] == [first["findings"][0]["fingerprint"]]


def test_tells_two_hits_apart_when_same_rule_and_path(store: Store) -> None:
    store.mark(store.select(a_scan(a_finding(line=3))))

    both = store.select(a_scan(a_finding(line=3), a_finding(line=9)))

    assert len(set(both["current"])) == 2
    # The second hit by line is the new one.
    assert [(finding["line"], finding["id"]) for finding in both["findings"]] == [(9, "F1")]


def test_names_fingerprint_by_repo_and_scanner_when_selected(store: Store) -> None:
    selected = store.select(a_scan(a_finding(secret=True, line=None)))

    (finding,) = selected["findings"]
    repo, scanner, digest = finding["fingerprint"].split("/")
    assert (repo, scanner, len(digest)) == ("app", "semgrep", 16)
    assert selected["ran"] == [{"repo": "app", "scanner": "semgrep"}]


def test_lists_at_most_one_hundred_when_many_are_new(store: Store) -> None:
    many = [a_finding(f"rule-{n:03}", path=f"src/{n}.py") for n in range(150)]

    selected = store.select(a_scan(*many))
    out = json.dumps(selected)
    store.mark(selected)
    after = store.select(a_scan(*many))

    assert selected["listed"] == 100
    assert [finding["id"] for finding in selected["findings"]] == [f"F{n}" for n in range(1, 101)]
    assert selected["counts"] == {"new": 150, "seen": 0, "more": 50}
    assert len(out.encode()) <= 120 * 1024
    # The 50 not listed stay unseen: they come next run.
    assert after["counts"] == {"new": 50, "seen": 100, "more": 0}


def test_lists_fewer_when_findings_hold_wide_characters(store: Store) -> None:
    wide = "\U0001f512"
    many = [
        a_finding(wide * 200, path=wide * 300, line=n, title=wide * 200, package=wide * 214)
        for n in range(100)
    ]

    selected = store.select(a_scan(*many))

    canonical = json.dumps(
        selected["findings"], sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert 0 < selected["listed"] < 100
    assert len(canonical.encode()) <= 48 * 1024
    assert selected["counts"]["more"] == 100 - selected["listed"]


@pytest.mark.parametrize("problem", ["not json", "version", "link", "big", "folder"])
def test_lists_all_as_new_and_names_problem_when_store_is_corrupt(
    store: Store, tmp_path: Path, problem: str
) -> None:
    store.mark(store.select(a_scan(a_finding())))
    if problem == "not json":
        store.path.write_text("{")
    elif problem == "version":
        store.path.write_text(json.dumps({"version": 2, "seen": {}}))
    elif problem == "link":
        target = tmp_path / "elsewhere.json"
        target.write_bytes(store.path.read_bytes())
        store.path.unlink()
        store.path.symlink_to(target)
    elif problem == "big":
        store.path.write_text(" " * (2 * 1024 * 1024 + 1))
    else:
        store.path.unlink()
        store.path.mkdir()

    selected = store.select(a_scan(a_finding()))

    assert selected["listed"] == 1
    assert selected["store_problem"] == "the seen-findings store could not be read; read as empty"


def test_rewrites_the_store_when_it_was_corrupt(store: Store) -> None:
    store.path.parent.mkdir(parents=True)
    store.path.write_text("{")

    store.mark(store.select(a_scan(a_finding())))

    assert len(store.seen()) == 1
    assert json.loads(store.path.read_text())["version"] == 1


def test_drops_oldest_entries_when_store_is_over_its_cap(store: Store) -> None:
    store.path.parent.mkdir(parents=True)
    old = {f"app/semgrep/{n:016x}": f"2026-01-{n % 28 + 1:02}" for n in range(20_000)}
    store.path.write_text(json.dumps({"version": 1, "seen": old}))

    marked = store.mark(store.select(a_scan(a_finding(), ran=())))

    seen = store.seen()
    assert marked["store_size"] == len(seen) == 20_000
    assert TODAY in seen.values()
    # The oldest date goes first, ties by fingerprint: the first of day 1.
    assert "app/semgrep/0000000000000000" not in seen
    assert "app/semgrep/000000000000001c" in seen


@pytest.mark.parametrize(
    ("argv", "stdin"),
    [
        (("select",), "not json"),
        (("select",), "[]"),
        (("select",), '{"repos": [], "findings": {}}'),
        (("mark", "--status", "findings", "--triaged", "[]"), '{"findings": []}'),
        (("mark", "--status", "maybe", "--triaged", "[]"), json.dumps({"findings": []})),
        (("mark", "--status", "clean"), EMPTY),
        (("mark", "--status", "clean", "--triaged", "x"), EMPTY),
        (("mark", "--status", "clean", "--triaged", '["G1"]'), EMPTY),
    ],
)
def test_exits_two_when_stdin_is_not_scan_json(
    store: Store, argv: tuple[str, ...], stdin: str
) -> None:
    code, out = store.call(*argv, stdin=stdin)

    assert (code, out) == (2, "")
    assert not store.path.exists()


def test_writes_the_store_atomically_when_marked(store: Store) -> None:
    store.mark(store.select(a_scan(a_finding())))

    assert sorted(os.listdir(store.path.parent)) == ["seen.json"]


def test_marks_only_the_ids_triage_named_when_reply_undercounts(store: Store) -> None:
    scan = a_scan(a_finding("r1"), a_finding("r2"), a_finding("r3"))

    first = store.select(scan)
    marked = store.mark(first, triaged=["F2"])
    second = store.select(scan)

    assert marked["marked"] == 1
    # The two triage never named stay unseen: they come back next run.
    assert [finding["rule"] for finding in second["findings"]] == ["r1", "r3"]


def test_lists_the_seen_hit_again_when_a_new_hit_lands_above_it(store: Store) -> None:
    # The known limit of a rank-by-line fingerprint: a new hit of the same rule in the same file,
    # above a seen one, takes the seen hit's rank 0; the seen hit, now rank 1, is listed instead.
    store.mark(store.select(a_scan(a_finding(line=9))))

    both = store.select(a_scan(a_finding(line=3), a_finding(line=9)))

    assert [finding["line"] for finding in both["findings"]] == [9]
