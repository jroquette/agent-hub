"""The brain-care pack's ``apply.py`` (AGH-487), in process: the owner's decisions written into
the run's hub worktree, and committed."""

import datetime
import importlib.util
import io
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/brain-care/scripts/apply.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.brain-care.scripts.apply"
TODAY = datetime.date(2026, 10, 22)
A = "brain/_inbox/2026-10-01-cache-key.md"
B = "brain/_inbox/2026-10-08-cache-key-again.md"
EXTERNAL = "brain/_inbox/2026-10-09-blog-tip.md"


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


def a_hub(root: Path) -> Path:
    for path, provenance in (
        (A, "agent"),
        (B, "agent-from-code"),
        (EXTERNAL, "agent-from-external"),
    ):
        note = root / path
        note.parent.mkdir(parents=True, exist_ok=True)
        title = note.stem
        note.write_text(
            f"---\ntype: learning\nstatus: proposed\nprovenance: {provenance}\n---\n# {title}\n\n"
            f"Body of {title}.\n"
        )
    return root


def a_decision(
    notes: list[str],
    decision: str,
    *,
    action: str = "promote",
    target: str = "brain/learnings/cache.md",
    text: str = "Key the cache by the lockfile hash.",
    note: str = "",
) -> dict[str, Any]:
    group = {
        "id": 1,
        "notes": notes,
        "external": False,
        "action": action,
        "target": target,
        "reason": "The same lesson twice.",
        "text": text,
    }
    return {"group": group, "decision": decision, "note": note, "approver": "Dana Owner"}


def planned(decisions: list[dict[str, Any]], root: Path) -> Any:
    return load().planned_changes(decisions, root=root, today=TODAY)


def kinds(found: Any) -> list[tuple[str, str]]:
    return [(change.kind, change.path) for change in found.changes]


def test_only_deletes_inbox_notes_when_every_decision_drop(tmp_path: Path) -> None:
    decisions = [
        a_decision([A, B], "drop"),
        a_decision([EXTERNAL], "drop", action="check", target="agent-hub/AGENTS.md"),
    ]

    found = planned(decisions, a_hub(tmp_path))

    assert kinds(found) == [("delete", A), ("delete", B), ("delete", EXTERNAL)]
    assert found.skipped == []


def test_writes_learning_and_deletes_group_when_promote_applied(tmp_path: Path) -> None:
    root = a_hub(tmp_path)
    existing = root / "brain/learnings/cache.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("---\ntype: learning\nlast_verified: 2026-01-01\n---\n# Cache\n\nOld.\n")
    decisions = [
        a_decision([A, B], "apply"),
        a_decision([EXTERNAL], "apply", target="brain/learnings/tips/", text=""),
    ]

    found = planned(decisions, root)
    load().write_changes(root, found.changes)

    assert kinds(found) == [
        ("write", "brain/learnings/cache.md"),
        ("delete", A),
        ("delete", B),
        ("write", "brain/learnings/tips/blog-tip.md"),
        ("delete", EXTERNAL),
    ]
    appended = existing.read_text()
    assert appended.startswith(
        "---\ntype: learning\nlast_verified: 2026-10-22\n---\n# Cache\n\nOld.\n"
    )
    assert "\n## 2026-10-01-cache-key\n\nKey the cache by the lockfile hash.\n" in appended
    created = (root / "brain/learnings/tips/blog-tip.md").read_text()
    assert "status: accepted\n" in created
    assert "last_verified: 2026-10-22\n" in created
    assert "provenance: agent-from-external\n" in created
    assert "Body of 2026-10-09-blog-tip." in created
    assert not (root / A).exists()
    assert not (root / EXTERNAL).exists()


@pytest.mark.parametrize("action", ["route", "check"])
def test_edits_status_in_place_when_route_applied(tmp_path: Path, action: str) -> None:
    root = a_hub(tmp_path)

    found = planned([a_decision([A], "apply", action=action, target="agent-hub/AGENTS.md")], root)
    load().write_changes(root, found.changes)

    assert kinds(found) == [("edit", A)]
    text = (root / A).read_text()
    assert f"status: {'routed' if action == 'route' else 'check'}\n" in text
    assert "routed_to: agent-hub/AGENTS.md\n" in text
    assert "status: proposed" not in text
    assert "Body of 2026-10-01-cache-key." in text


def test_changes_nothing_when_decision_keep(tmp_path: Path) -> None:
    found = planned([a_decision([A, B], "keep")], a_hub(tmp_path))

    assert (found.changes, found.skipped) == ([], [])


@pytest.mark.parametrize(
    "target", ["brain/decisions/0001-cache.md", "brain/_inbox/x.md", "brain/learnings/../x.md"]
)
def test_skips_target_when_under_decisions(tmp_path: Path, target: str) -> None:
    found = planned([a_decision([A], "apply", target=target)], a_hub(tmp_path))

    assert found.changes == []
    assert found.skipped == [
        {"path": target, "reason": "a promote target outside brain/learnings/"}
    ]


def test_skips_external_promote_when_group_holds_other_notes(tmp_path: Path) -> None:
    found = planned([a_decision([A, EXTERNAL], "apply")], a_hub(tmp_path))

    assert found.changes == []
    assert found.skipped == [
        {"path": EXTERNAL, "reason": "an external note is promoted only alone, by its own approval"}
    ]


def test_skips_note_when_absent_from_base(tmp_path: Path) -> None:
    root = a_hub(tmp_path)
    missing = "brain/_inbox/2026-10-21-local-only.md"

    found = planned([a_decision([missing, A], "drop")], root)

    assert kinds(found) == [("delete", A)]
    assert found.skipped == [
        {"path": missing, "reason": "not in the base commit: push it to the default branch first"}
    ]


def test_skips_path_when_not_an_inbox_note(tmp_path: Path) -> None:
    found = planned([a_decision(["brain/decisions/0001.md", "../x.md"], "drop")], a_hub(tmp_path))

    assert found.changes == []
    assert [item["reason"] for item in found.skipped] == ["not an inbox note"] * 2


def test_names_approvers_and_followups_when_summary_built(tmp_path: Path) -> None:
    root = a_hub(tmp_path)
    decisions = [
        a_decision([A, B], "apply", note="Merge them."),
        a_decision([EXTERNAL], "apply", action="check", target="agent-hub/AGENTS.md"),
        a_decision(["brain/_inbox/2026-10-10-x.md"], "keep"),
    ]
    found = planned(decisions, root)
    unreadable = [{"path": "brain/_inbox/2026-10-11-bad.md", "reason": "not UTF-8"}]

    ignored = [{"notes": ["brain/_inbox/2026-10-12-y.md"], "reason": "not read by this run"}]
    unproposed = ["brain/_inbox/2026-10-13-z.md"]

    summary = load().summary_of(
        decisions, found, unreadable=unreadable, ignored=ignored, unproposed=unproposed
    )

    assert "apply by Dana Owner" in summary
    assert "Merge them." in summary
    assert "keep by Dana Owner" in summary
    assert "Follow-ups" in summary
    assert f"{EXTERNAL}: check -> agent-hub/AGENTS.md" in summary
    assert "brain/_inbox/2026-10-11-bad.md: not UTF-8" in summary
    assert "brain/_inbox/2026-10-12-y.md: not read by this run" in summary
    assert "brain/_inbox/2026-10-13-z.md: in no group" in summary
    assert len(summary) <= 8000


def git(folder: Path, *args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", "-c", "user.name=T", "-c", "user.email=t@example.com", *args],  # noqa: S607
        cwd=folder,
        capture_output=True,
        text=True,
        check=True,
    )
    return done.stdout.strip()


def a_worktree(tmp_path: Path) -> tuple[Path, str]:
    root = a_hub(tmp_path / "wt")
    git(root, "init", "-q", "-b", "trunk")
    git(root, "config", "user.name", "T")
    git(root, "config", "user.email", "t@example.com")
    git(root, "add", ".")
    git(root, "commit", "-qm", "base")
    return root, git(root, "rev-parse", "HEAD")


def test_commits_changes_when_decisions_applied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    stdin = json.dumps([a_decision([A, B], "drop"), a_decision([EXTERNAL], "keep")])
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    assert load().main(["--worktree", str(root), "--base", base, "--today", "2026-10-22"]) == 0

    found = json.loads(capsys.readouterr().out)
    assert (found["changes"], found["deleted"], found["written"]) == (2, [A, B], [])
    assert git(root, "diff", "--name-status", f"{base}..HEAD").splitlines() == [
        f"D\t{A}",
        f"D\t{B}",
    ]
    assert git(root, "log", "-1", "--format=%s") == "docs(brain): weekly inbox review"
    assert git(root, "status", "--porcelain") == ""


def test_commits_nothing_when_every_decision_keep(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root, base = a_worktree(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([a_decision([A], "keep")])))

    assert load().main(["--worktree", str(root), "--base", base]) == 0

    assert json.loads(capsys.readouterr().out)["changes"] == 0
    assert git(root, "rev-parse", "HEAD") == base


def test_exits_one_when_commit_holds_path_outside_brain(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, base = a_worktree(tmp_path)
    (root / "README.md").write_text("x\n")
    git(root, "add", "README.md")
    git(root, "commit", "-qm", "outside")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([a_decision([A], "drop")])))

    assert load().main(["--worktree", str(root), "--base", base]) == 1


@pytest.mark.parametrize("stdin", ["not json", '{"a": 1}', "[1]"])
def test_exits_two_when_decisions_not_a_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stdin: str
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))

    assert load().main(["--worktree", str(tmp_path), "--base", "HEAD"]) == 2


def test_makes_one_commit_when_run_again_after_failed_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """``hub workflow resume`` runs a failed node again in the same worktree."""
    root, base = a_worktree(tmp_path)
    decisions = json.dumps([a_decision([A, B], "apply"), a_decision([EXTERNAL], "drop")])
    argv = ["--worktree", str(root), "--base", base, "--today", "2026-10-22"]
    failing = load()
    real = failing._git

    def no_commit(folder: Path, *args: str) -> str:
        if args[0] == "commit":
            raise failing.GitFailedError("git commit: no identity")
        return str(real(folder, *args))

    monkeypatch.setattr(failing, "_git", no_commit)
    monkeypatch.setattr(sys, "stdin", io.StringIO(decisions))
    assert failing.main(argv) == 1
    capsys.readouterr()

    outputs = []
    for _ in range(2):
        monkeypatch.setattr(sys, "stdin", io.StringIO(decisions))
        assert load().main(argv) == 0
        outputs.append(json.loads(capsys.readouterr().out))

    assert outputs[0] == outputs[1]
    assert outputs[0]["skipped"] == []
    assert outputs[0]["deleted"] == [A, B, EXTERNAL]
    assert git(root, "rev-list", "--count", f"{base}..HEAD") == "1"
    learning = (root / "brain/learnings/cache.md").read_text()
    assert learning.count("Key the cache by the lockfile hash.") == 1
    assert git(root, "status", "--porcelain") == ""


def test_exits_one_when_head_holds_another_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, base = a_worktree(tmp_path)
    (root / A).unlink()
    git(root, "commit", "-qam", "docs(brain): someone else")
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps([a_decision([A], "drop")])))

    assert load().main(["--worktree", str(root), "--base", base]) == 1
