"""The backlog-care pack's ``read.py`` (AGH-489), in process: the skill's issues file, bounded.

``/triage --backlog`` writes the open issues it read to one JSON file; ``read.py`` checks it, keeps
the oldest ``--limit`` issues, cuts every field, and says how many open issues were left unread.
"""

import importlib.util
import json
import sys
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/backlog-care/scripts/read.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.backlog-care.scripts.read"


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


START = datetime(2026, 1, 1, tzinfo=UTC)
HUB_JSON = {"tracker": {"ready_label": "ready-now"}, "repos": [{"dir": "api"}, {"dir": "web"}]}


def an_issue(n: int, **fields: Any) -> dict[str, Any]:
    issue: dict[str, Any] = {
        "id": f"DEM-{n}",
        "title": f"Issue {n}",
        "url": f"https://linear.app/demo/issue/DEM-{n}",
        "state": {"name": "Todo", "type": "unstarted"},
        "created_at": (START + timedelta(days=n)).isoformat().replace("+00:00", "Z"),
        "updated_at": "2026-10-01T10:00:00+00:00",
        "labels": [],
        "blocked_by": [],
        "blocks": [],
        "links": [],
        "branch_name": "",
        "description": f"Text of issue {n}.",
    }
    return issue | fields


def a_document(issues: list[Any], **top: Any) -> dict[str, Any]:
    document = {
        "version": 1,
        "read_at": "2026-10-26T09:00:00Z",
        "teams": ["DEM"],
        "open_total": len(issues),
        "issues": issues,
    }
    return document | top


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "hub.json").write_text(json.dumps(HUB_JSON), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def write(path: Path, document: object) -> Path:
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def run(capsys: pytest.CaptureFixture[str], path: Path, limit: str = "50") -> dict[str, Any]:
    assert load().main(["--file", str(path), "--limit", limit]) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def test_reads_oldest_first_and_cuts_to_limit_when_file_has_more(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issues = [an_issue(n) for n in range(60, 0, -1)]
    path = write(hub / "issues.json", a_document(issues, open_total=63))

    found = run(capsys, path)

    assert [issue["id"] for issue in found["issues"]] == [f"DEM-{n}" for n in range(1, 51)]
    assert (found["read"], found["open"], found["unread"]) == (50, 63, 13)
    assert found["unread_line"] == ("13 open issues were left unread (50 of 63 read, oldest first)")
    assert found["skipped"] == []
    assert found["descriptions_dropped"] == 0


@pytest.mark.parametrize("open_total", [None, 3, "many"])
def test_counts_entries_past_limit_when_open_total_missing_or_smaller(
    hub: Path, capsys: pytest.CaptureFixture[str], open_total: object
) -> None:
    document = a_document([an_issue(n) for n in range(1, 8)])
    if open_total is None:
        del document["open_total"]
    else:
        document["open_total"] = open_total
    path = write(hub / "issues.json", document)

    found = run(capsys, path, limit="5")

    assert (found["read"], found["open"], found["unread"]) == (5, 7, 2)
    assert found["unread_line"] == "2 open issues were left unread (5 of 7 read, oldest first)"


def test_says_none_left_unread_when_every_issue_read(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(hub / "issues.json", a_document([an_issue(1)]))

    found = run(capsys, path)

    assert found["unread"] == 0
    assert found["unread_line"] == "No open issue was left unread (1 of 1 read)"


def test_prints_ready_label_and_repos_when_hub_json_read(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(hub / "issues.json", a_document([an_issue(1)], teams=["DEM", "OPS"]))

    found = run(capsys, path)

    assert found["ready_label"] == "ready-now"
    assert found["repos"] == ["api", "web"]
    assert found["teams"] == ["DEM", "OPS"]


def test_takes_default_ready_label_when_hub_json_names_none(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (hub / "hub.json").write_text(json.dumps({"repos": [{"dir": "api"}]}), encoding="utf-8")
    path = write(hub / "issues.json", a_document([an_issue(1)]))

    assert run(capsys, path)["ready_label"] == "agent-ready"


@pytest.mark.parametrize(
    "hub_json",
    [
        "not json",
        "[1]",
        json.dumps({"repos": "api"}),
        json.dumps({"repos": [{"dir": "../etc"}]}),
        json.dumps({"tracker": {"ready_label": 3}, "repos": []}),
        None,
    ],
    ids=["text", "array", "repos-not-list", "dir-escapes", "label-not-text", "missing"],
)
def test_exits_two_when_hub_json_unreadable(
    hub: Path, capsys: pytest.CaptureFixture[str], hub_json: str | None
) -> None:
    if hub_json is None:
        (hub / "hub.json").unlink()
    else:
        (hub / "hub.json").write_text(hub_json, encoding="utf-8")
    path = write(hub / "issues.json", a_document([an_issue(1)]))

    assert load().main(["--file", str(path), "--limit", "50"]) == 2
    assert capsys.readouterr().err.startswith("read.py: hub.json: ")


def test_exits_two_when_file_is_link_or_large_or_not_json(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = write(hub / "good.json", a_document([an_issue(1)]))
    link = hub / "link.json"
    link.symlink_to(good)
    large = hub / "large.json"
    large.write_text(json.dumps(a_document([], pad="x" * (1 << 20))), encoding="utf-8")
    text = hub / "text.json"
    text.write_text("not json", encoding="utf-8")
    binary = hub / "binary.json"
    binary.write_bytes(b"\xff\xfe{}")
    cases = {
        "relative": "good.json",
        "link": str(link),
        "folder": str(hub),
        "missing": str(hub / "missing.json"),
        "large": str(large),
        "text": str(text),
        "binary": str(binary),
        "array": str(write(hub / "array.json", [1])),
        "version": str(write(hub / "v2.json", a_document([], version=2))),
        "issues": str(write(hub / "issues.json", a_document([]) | {"issues": {"a": 1}})),
        "entries": str(write(hub / "many.json", a_document([an_issue(1)] * 501))),
    }

    for name, given in cases.items():
        assert load().main(["--file", given, "--limit", "50"]) == 2, name
        assert capsys.readouterr().err.startswith("read.py: "), name
    for limit in ("0", "101", "x"):
        assert load().main(["--file", str(good), "--limit", limit]) == 2, limit
        assert capsys.readouterr().err.startswith("read.py: "), limit


def test_skips_entry_when_id_malformed_or_dates_missing(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    good = an_issue(1)
    bad: list[object] = [
        "not an object",
        an_issue(2, id="dem-2"),
        an_issue(3, id="DEM-03"),
        an_issue(4, title=""),
        an_issue(5, state={"type": "started"}),
        an_issue(6, created_at="yesterday"),
        an_issue(7, updated_at="2026-10-01T10:00:00"),
        {key: value for key, value in an_issue(8).items() if key != "updated_at"},
    ]
    path = write(hub / "issues.json", a_document([good, *bad]))

    found = run(capsys, path)

    assert [issue["id"] for issue in found["issues"]] == ["DEM-1"]
    assert [entry["index"] for entry in found["skipped"]] == list(range(1, 9))
    reasons = [entry["reason"] for entry in found["skipped"]]
    assert reasons[0] == "not an object"
    assert reasons[1] == reasons[2] == "id missing or malformed"
    assert reasons[3] == "title missing"
    assert reasons[4] == "state.name missing"
    assert reasons[5] == "created_at missing or not ISO-8601 with an offset"
    assert reasons[6] == reasons[7] == "updated_at missing or not ISO-8601 with an offset"
    # A skipped entry is still an open issue: it counts toward open, never toward read.
    assert (found["read"], found["open"]) == (1, 9)


def test_cuts_fields_and_drops_control_characters_when_read(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    issue = an_issue(
        1,
        title="T\x1b[31mitle\u0085" + "x" * 600,
        labels=[f"l{n}\x00" for n in range(30)] + [3],
        blocked_by=[f"DEM-{n}" for n in range(100, 140)] + ["bad id", 7],
        blocks="DEM-9",
        links=[f"https://github.com/o/r/pull/{n}" for n in range(15)],
        branch_name="jo/dem-1\x07",
        description="line one\nline\ttwo\x00\x1b" + "d" * 2000,
        state={"name": "In\x7f Progress", "type": "started"},
    )
    path = write(hub / "issues.json", a_document([issue], teams=["DEM\x00"]))

    (found,) = run(capsys, path)["issues"]

    assert found["title"] == "T[31mitle" + "x" * 491
    assert len(found["title"]) == 500
    assert found["labels"] == [f"l{n}" for n in range(20)]
    assert found["blocked_by"] == [f"DEM-{n}" for n in range(100, 125)]
    assert found["blocks"] == []
    assert len(found["links"]) == 10
    assert found["branch_name"] == "jo/dem-1"
    assert found["description"].startswith("line one\nline\ttwod")
    assert len(found["description"]) == 1000
    assert found["state"] == {"name": "In Progress", "type": "started"}
    assert set(found) == set(load().ISSUE_FIELDS)


def test_keeps_links_null_when_skill_could_not_read_them(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = write(hub / "issues.json", a_document([an_issue(1, links=None)]))

    (found,) = run(capsys, path)["issues"]

    assert found["links"] is None


def test_fills_optional_fields_when_entry_has_only_required_ones(
    hub: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    required = {
        "id": "DEM-1",
        "title": "Only required",
        "state": {"name": "Todo"},
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": "2026-01-02T00:00:00Z",
    }
    path = write(hub / "issues.json", a_document([required]))

    (found,) = run(capsys, path)["issues"]

    assert found == required | {
        "url": "",
        "state": {"name": "Todo", "type": ""},
        "labels": [],
        "blocked_by": [],
        "blocks": [],
        "links": [],
        "branch_name": "",
        "description": "",
    }


def test_drops_newest_descriptions_when_output_over_budget(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    issues = [an_issue(n, description="d" * 1000) for n in range(1, 6)]
    path = write(hub / "issues.json", a_document(issues))
    monkeypatch.setattr(module, "OUTPUT_BUDGET", 4000)

    assert module.main(["--file", str(path), "--limit", "50"]) == 0

    found = json.loads(capsys.readouterr().out)
    descriptions = [issue["description"] for issue in found["issues"]]
    assert found["descriptions_dropped"] == 3
    assert descriptions == ["d" * 1000, "d" * 1000, "", "", ""]


def test_exits_two_when_output_over_budget_without_descriptions(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    module = load()
    path = write(hub / "issues.json", a_document([an_issue(n) for n in range(1, 6)]))
    monkeypatch.setattr(module, "OUTPUT_BUDGET", 100)

    assert module.main(["--file", str(path), "--limit", "50"]) == 2
    assert "over" in capsys.readouterr().err
