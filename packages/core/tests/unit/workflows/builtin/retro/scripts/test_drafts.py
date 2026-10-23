"""The retro pack's ``drafts.py`` (AGH-488), in process: the kept changes as issue drafts."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/retro/scripts/drafts.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.retro.scripts.drafts"


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


TODAY = "2026-10-22"
RUN = "retro-20261022-0a1b"
SUMMARY = "Retro window: 2026-10-15 .. 2026-10-22 (7 days).\nRuns started: 6 workflow runs."


def a_change(n: int, key: str, value: float) -> dict[str, Any]:
    return {
        "n": n,
        "title": f"Change {n}",
        "kind": "workflow",
        "change": f"Do change {n}.",
        "metrics": [{"key": key, "value": value}],
        "links": [f".agent-runs/workflows/deliver-{n}/"],
        "expected_effect": f"Effect {n}.",
        "how_to_tell": f"Tell {n}.",
    }


VETTED = {
    "count": 3,
    "kept": [
        a_change(1, "workflow.deliver.failed", 2),
        a_change(2, "skills.idle", 4),
        a_change(3, "workflow.implement.no_ship_rate", 0.25),
    ],
    "dropped": [],
    "message": "",
}


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "brain" / "_inbox").mkdir(parents=True)
    (tmp_path / "brain" / "_inbox" / "note.md").write_text("an inbox note\n")
    monkeypatch.setenv("AGENT_HUB_RUN_ID", RUN)
    return tmp_path


def run_drafts(
    hub: Path,
    flags: dict[str, str],
    *,
    stdin: str = json.dumps(VETTED),
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[int, dict[str, Any], str]:
    # The script node runs in the hub: the draft goes under the current folder.
    monkeypatch.chdir(hub)
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    given = {"--nothing": "false", "--count": "3", "--decision": "keep", "--note": ""}
    given |= {"--summary": SUMMARY, "--today": TODAY} | flags
    code = load().main([part for flag, value in given.items() for part in (flag, value)])
    captured = capsys.readouterr()
    return code, (json.loads(captured.out) if captured.out else {}), captured.err


def inbox(hub: Path) -> list[str]:
    return sorted(path.name for path in (hub / "brain" / "_inbox").iterdir())


def test_writes_no_file_when_owner_keeps_none(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    flags = {"--decision": "none", "--note": "1,2"}

    code, found, _ = run_drafts(hub, flags, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert (found["outcome"], found["kept"], found["path"]) == ("none kept", 0, "")
    assert "kept none" in found["summary"]
    assert inbox(hub) == ["note.md"]


def test_keeps_none_when_note_names_no_valid_number(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, found, _ = run_drafts(hub, {"--note": "9, x"}, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert (found["outcome"], found["kept"], found["path"]) == ("none kept", 0, "")
    assert "no change number understood" in found["summary"]
    assert inbox(hub) == ["note.md"]


def test_says_nothing_to_change_when_metrics_found_no_runs(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    flags = {"--nothing": "true", "--count": "", "--decision": ""}

    code, found, _ = run_drafts(hub, flags, stdin="", capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert (found["outcome"], found["kept"], found["path"]) == ("nothing to change", 0, "")
    assert "no run in the window" in found["summary"]
    assert inbox(hub) == ["note.md"]


def test_says_nothing_to_change_when_vet_kept_zero(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    stdin = json.dumps(VETTED | {"count": 0, "kept": []})
    flags = {"--count": "0", "--decision": ""}

    code, found, _ = run_drafts(hub, flags, stdin=stdin, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert (found["outcome"], found["path"]) == ("nothing to change", "")
    assert "no change passed the evidence check" in found["summary"]
    assert inbox(hub) == ["note.md"]


def test_writes_kept_changes_with_evidence_when_owner_keeps_some(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, found, _ = run_drafts(hub, {"--note": "1,3"}, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert found["outcome"] == "drafted"
    assert found["kept"] == 2
    assert found["path"] == "brain/_inbox/retro-2026-10-22.md"
    assert "/triage" in found["summary"]
    text = (hub / found["path"]).read_text()
    front = text.split("---\n")[1]
    assert front.splitlines() == [
        "type: issue-drafts",
        "repos: []",
        "status: to-file",
        f"last_verified: {TODAY}",
        f"sources: [.agent-runs/workflows/{RUN}/]",
        "provenance: agent",
        "target: tracker via /triage",
    ]
    assert "## 1. Change 1" in text
    assert "## 3. Change 3" in text
    assert "Change 2" not in text
    assert "- workflow.deliver.failed = 2" in text
    assert "- workflow.implement.no_ship_rate = 0.25" in text
    assert "- .agent-runs/workflows/deliver-3/" in text
    assert "Expected effect: Effect 3." in text
    assert "How the next retro tells: Tell 3." in text
    assert text.index("## 3. Change 3") < text.index(SUMMARY)


def test_keeps_all_when_note_says_all(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    code, found, _ = run_drafts(
        hub, {"--note": "Keep ALL of them."}, capsys=capsys, monkeypatch=monkeypatch
    )

    assert code == 0
    assert (found["outcome"], found["kept"]) == ("drafted", 3)
    text = (hub / found["path"]).read_text()
    assert all(f"## {n}. Change {n}" in text for n in (1, 2, 3))


def test_writes_next_suffix_when_draft_file_exists(
    hub: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    taken = hub / "brain" / "_inbox" / "retro-2026-10-22.md"
    taken.write_text("the owner's earlier draft\n")

    code, found, _ = run_drafts(hub, {"--note": "2"}, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 0
    assert found["path"] == "brain/_inbox/retro-2026-10-22-2.md"
    assert taken.read_text() == "the owner's earlier draft\n"
    for n in range(3, 10):
        (hub / "brain" / "_inbox" / f"retro-2026-10-22-{n}.md").write_text("x\n")

    code, found, err = run_drafts(hub, {"--note": "2"}, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 1
    assert found == {}
    assert err.startswith("drafts.py: ")


def test_refuses_inbox_when_it_is_a_link(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    hub = tmp_path / "hub"
    (hub / "brain").mkdir(parents=True)
    (hub / "brain" / "_inbox").symlink_to(elsewhere)

    code, found, err = run_drafts(hub, {"--note": "1"}, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 1
    assert found == {}
    assert err == "drafts.py: brain/_inbox is a link; no draft written\n"
    assert list(elsewhere.iterdir()) == []


@pytest.mark.parametrize(
    "given",
    [
        ({"--count": "three"}, json.dumps(VETTED)),
        ({"--note": "1"}, "not json"),
        ({"--note": "1"}, json.dumps({"count": 3})),
        ({"--today": "22/10/2026"}, json.dumps(VETTED)),
    ],
)
def test_exits_two_when_input_malformed(
    given: tuple[dict[str, str], str],
    *,
    hub: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    flags, stdin = given
    code, found, err = run_drafts(hub, flags, stdin=stdin, capsys=capsys, monkeypatch=monkeypatch)

    assert code == 2
    assert found == {}
    assert err.startswith("drafts.py: ")
    assert inbox(hub) == ["note.md"]


def test_refuses_root_option_when_given(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as raised:
        load().main(["--root", str(tmp_path), "--nothing", "true"])

    assert raised.value.code == 2
