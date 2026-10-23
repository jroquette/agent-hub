"""The brain-care pack's ``groups.py`` (AGH-487), in process: the groups the owner decides one by
one (``plan``), the next gate's group (``next``) and the decisions so far (``record``)."""

import importlib.util
import io
import json
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/groups.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.groups"

PAIR = ["brain/_inbox/2026-10-01-cache-key.md", "brain/_inbox/2026-10-08-cache-key-again.md"]
EXTERNAL = "brain/_inbox/2026-10-09-blog-tip.md"
READ = [*PAIR, EXTERNAL]


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


def a_group(notes: list[str], *, action: str = "promote", target: str = "") -> dict[str, Any]:
    return {
        "notes": notes,
        "action": action,
        "target": target or "brain/learnings/cache.md",
        "reason": "The same lesson twice.",
        "text": "Key the cache by the lockfile hash.",
    }


def run(
    argv: list[str],
    stdin: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    assert load().main(argv) == 0
    found: dict[str, Any] = json.loads(capsys.readouterr().out)
    return found


def plan(
    groups: list[dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    argv = ["plan", "--paths", json.dumps(READ), "--external", json.dumps([EXTERNAL])]
    return run(argv, json.dumps({"groups": groups}), monkeypatch=monkeypatch, capsys=capsys)


def test_keeps_two_groups_when_agent_grouped_pair_and_external(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    proposed = [a_group(PAIR), a_group([EXTERNAL], action="check", target="agent-hub/AGENTS.md")]

    found = plan(proposed, monkeypatch, capsys)

    assert found["count"] == 2
    assert [(g["id"], g["notes"], g["external"]) for g in found["groups"]] == [
        (1, PAIR, False),
        (2, [EXTERNAL], True),
    ]
    assert (found["ignored"], found["unproposed"]) == ([], [])


def test_splits_external_note_into_own_group_when_agent_merged_it(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = plan([a_group(READ)], monkeypatch, capsys)

    assert found["count"] == 2
    first, second = found["groups"]
    # The merged text may hold the external note's content: it goes, and apply uses the notes'
    # own bodies.
    assert (first["notes"], first["external"], first["text"]) == (PAIR, False, "")
    assert "merged with an external note" in first["reason"]
    # Alone, and without the merged text: the owner reads the note itself.
    assert (second["notes"], second["external"], second["text"]) == ([EXTERNAL], True, "")
    assert "its own approval" in second["reason"]


def next_group(
    planned: dict[str, Any],
    after: str,
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> dict[str, Any]:
    return run(
        ["next", "--after", after], json.dumps(planned), monkeypatch=monkeypatch, capsys=capsys
    )


def test_opens_two_gates_when_three_notes_hold_pair_and_external(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = plan([a_group(READ)], monkeypatch, capsys)
    gates: list[dict[str, Any]] = []
    decisions = ""
    after = ""

    # The loop group: next, the gate, record, until next says it was the last.
    for _ in range(50):
        found = next_group(planned, after, monkeypatch=monkeypatch, capsys=capsys)
        gates.append(found)
        argv = ["record", "--group", json.dumps(found["group"]), "--decision", "apply"]
        recorded = run(
            [*argv, "--note", "", "--approver", "Dana"],
            decisions,
            monkeypatch=monkeypatch,
            capsys=capsys,
        )
        decisions, after = json.dumps(recorded["decisions"]), str(found["index"])
        if found["last"]:
            break

    assert len(gates) == 2
    assert gates[0]["group"]["notes"] == PAIR
    assert gates[1]["group"]["notes"] == [EXTERNAL]
    assert "explicit approval" in gates[1]["message"]
    assert "explicit approval" not in gates[0]["message"]
    assert recorded["acted"] == 2


def test_names_action_target_and_choices_when_gate_message_built(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = plan([a_group(PAIR)], monkeypatch, capsys)

    message = next_group(planned, "", monkeypatch=monkeypatch, capsys=capsys)["message"]

    assert "Group 1 of 1" in message
    assert "promote" in message
    assert "brain/learnings/cache.md" in message
    assert all(path in message for path in PAIR)
    assert all(choice in message for choice in ("apply", "drop", "keep"))


def test_ignores_paths_not_read_when_agent_names_unknown_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = "brain/_inbox/2026-10-02-not-read.md"
    proposed = [a_group([*PAIR, unknown]), a_group([PAIR[0], EXTERNAL], action="drop")]

    found = plan(proposed, monkeypatch, capsys)

    assert [g["notes"] for g in found["groups"]] == [PAIR, [EXTERNAL]]
    assert found["ignored"] == [
        {"notes": [unknown], "reason": "not read by this run"},
        {"notes": [PAIR[0]], "reason": "already in an earlier group"},
    ]


@pytest.mark.parametrize(
    "target",
    [
        "brain/decisions/0001-cache.md",
        "brain/_inbox/cache.md",
        "brain/learnings/../decisions/x.md",
        "/brain/learnings/x.md",
        "agent-hub/AGENTS.md",
    ],
)
def test_ignores_promote_when_target_outside_learnings(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], target: str
) -> None:
    found = plan([a_group(PAIR, target=target)], monkeypatch, capsys)

    assert found["count"] == 0
    assert found["ignored"] == [
        {"notes": PAIR, "reason": "a promote target outside brain/learnings/"}
    ]
    assert found["unproposed"] == READ


def test_lists_unproposed_when_agent_skips_a_note(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = plan([a_group(PAIR)], monkeypatch, capsys)

    assert found["unproposed"] == [EXTERNAL]


def record(
    decision: str,
    previous: list[dict[str, Any]],
    *,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    note: str = "",
) -> dict[str, Any]:
    group = {"id": len(previous) + 1, **a_group(PAIR), "external": False}
    argv = ["record", "--group", json.dumps(group), "--decision", decision]
    stdin = json.dumps(previous) if previous else ""
    return run(
        [*argv, "--note", note, "--approver", "Dana"], stdin, monkeypatch=monkeypatch, capsys=capsys
    )


def test_counts_acted_when_decisions_recorded(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    decisions: list[dict[str, Any]] = []
    for decision in ("apply", "keep", "drop"):
        found = record(decision, decisions, monkeypatch=monkeypatch, capsys=capsys)
        decisions = found["decisions"]

    assert [d["decision"] for d in decisions] == ["apply", "keep", "drop"]
    assert decisions[0]["approver"] == "Dana"
    assert decisions[0]["group"]["notes"] == PAIR
    assert found["acted"] == 2


def test_cuts_owner_note_when_longer_than_limit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = record("apply", [], monkeypatch=monkeypatch, capsys=capsys, note="n" * 2500)

    assert found["decisions"][0]["note"] == "n" * 2000


def test_exits_two_when_after_past_last_group(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = plan([a_group(PAIR)], monkeypatch, capsys)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(planned)))

    assert load().main(["next", "--after", "0"]) == 2


@pytest.mark.parametrize(
    ("argv", "stdin"),
    [
        (["plan", "--paths", "[", "--external", "[]"], '{"groups": []}'),
        (["plan", "--paths", "[]", "--external", "[]"], "not json"),
        (["next", "--after", "x"], '{"groups": []}'),
        (["record", "--group", "{}", "--decision", "merge", "--note", "", "--approver", "D"], ""),
        (["record", "--group", "[]", "--decision", "keep", "--note", "", "--approver", "D"], ""),
    ],
)
def test_exits_two_when_input_not_json_or_choice_unknown(
    monkeypatch: pytest.MonkeyPatch, argv: list[str], stdin: str
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    assert load().main(argv) == 2


@pytest.mark.parametrize("note", ["- keep the first line", "-x", "--decision"])
def test_reads_note_when_it_starts_with_a_dash(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], note: str
) -> None:
    found = record("apply", [], monkeypatch=monkeypatch, capsys=capsys, note=note)

    assert (found["decisions"][0]["note"], found["decisions"][0]["decision"]) == (note, "apply")


def test_keeps_merged_text_when_no_external_note_split(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    found = plan([a_group(PAIR)], monkeypatch, capsys)

    assert found["groups"][0]["text"] == "Key the cache by the lockfile hash."
    assert found["groups"][0]["reason"] == "The same lesson twice."


def test_names_undecided_notes_in_first_gate_when_plan_ignored_some(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    unknown = "brain/_inbox/2026-10-02-not-read.md"
    planned = plan([a_group([*PAIR, unknown])], monkeypatch, capsys)
    first = next_group(planned, "", monkeypatch=monkeypatch, capsys=capsys)
    planned_two = plan([a_group(PAIR), a_group([EXTERNAL], action="drop")], monkeypatch, capsys)
    second = next_group(planned_two, "0", monkeypatch=monkeypatch, capsys=capsys)

    assert f"{unknown}: not read by this run" in first["message"]
    assert f"{EXTERNAL}: in no group" in first["message"]
    assert "in no group" not in second["message"]


def test_names_every_trusted_provenance_when_external_warned(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    planned = plan([a_group([EXTERNAL], action="drop")], monkeypatch, capsys)

    message = next_group(planned, "", monkeypatch=monkeypatch, capsys=capsys)["message"]

    assert "not agent, agent-from-code or human" in message
