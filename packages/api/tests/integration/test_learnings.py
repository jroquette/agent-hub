"""``/learnings`` on the composed app over a registered hub checkout (AC-201.20 to AC-201.22):
the note is read from ``brain/_inbox/`` on request, summarized in the list, and never stored."""

import sqlite3
from pathlib import Path
from typing import Any

import pytest

BODY_SENTINEL = "NOTEBODY-x8r2-read-on-demand-only"
OUTSIDE_SENTINEL = "OUTSIDE-q2w4-never-served"
SUMMARY = "The fast gate catches format drift before review, so run it before every push."
NOTE = f"""---
type: learning
target: brain/playbooks/testing.md
provenance: agent
---
# Run the gate before the PR

{SUMMARY}

{BODY_SENTINEL} and more detail below the summary.
"""
MAX_SUMMARY = 200
NOTE_LIMIT = 256 * 1024


def _stored_text(db_path: Path) -> str:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute("SELECT * FROM events").fetchall()
    assert rows
    return "\n".join(repr(row) for row in rows)


def test_returns_note_when_inbox_note_exists(world_app: Any, propose: Any) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE)

    response = world_app.client.get(f"/api/v1/learnings/{learning_id}")

    assert response.status_code == 200, response.text
    detail = response.json()
    assert detail["note"]["frontmatter"] == {
        "type": "learning",
        "target": "brain/playbooks/testing.md",
        "provenance": "agent",
    }
    assert detail["note"]["markdown"].startswith("# Run the gate before the PR\n")
    assert BODY_SENTINEL in detail["note"]["markdown"]
    assert detail["note"]["size"] == len(NOTE.encode())
    assert detail["project"] == "demo"
    assert detail["source_session_id"] == "session-learn"
    assert detail["source_event_id"]
    assert (detail["state"], detail["note_unavailable"], detail["actions_unavailable"]) == (
        "proposed",
        None,
        None,
    )
    assert detail["suggested_target"] == "playbooks/testing.md"
    assert "learnings/" in detail["target_choices"]
    assert not {"_inbox/", "auto/", "decisions/"} & set(detail["target_choices"])
    assert BODY_SENTINEL not in _stored_text(world_app.settings.db_path)


def test_links_source_event_when_note_read(world_app: Any, propose: Any) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE)
    detail = world_app.client.get(f"/api/v1/learnings/{learning_id}").json()

    events = world_app.client.get("/api/v1/sessions/session-learn/events?limit=200").json()

    assert detail["source_event_id"] in {event["event_id"] for event in events["items"]}


def test_summarizes_first_paragraph_when_listed(world_app: Any, propose: Any) -> None:
    long_paragraph = " ".join(["word"] * 120)
    propose(world_app, "gate-first.md", NOTE)
    propose(world_app, "long.md", f"# Long\n\n{long_paragraph}\n")

    response = world_app.client.get("/api/v1/learnings")

    assert response.status_code == 200, response.text
    items = {item["note_path"]: item for item in response.json()["items"]}
    assert items["brain/_inbox/gate-first.md"]["summary"] == SUMMARY
    long_summary = items["brain/_inbox/long.md"]["summary"]
    assert long_summary.startswith("word word")
    assert len(long_summary) <= MAX_SUMMARY
    assert all(item["note_unavailable"] is None for item in items.values())
    assert BODY_SENTINEL not in response.text
    assert BODY_SENTINEL not in _stored_text(world_app.settings.db_path)


def _symlink_outside(world: Any, name: str) -> None:
    outside = world.hub.parent / "outside.md"
    outside.write_text(f"# Outside\n\n{OUTSIDE_SENTINEL}\n", encoding="utf-8")
    (world.hub / "brain" / "_inbox" / name).symlink_to(outside)


@pytest.mark.parametrize(
    ("case", "name", "reason"),
    [
        ("missing", "gone.md", "Note not in the hub checkout"),
        ("too_large", "huge.md", "Note too large"),
        ("symlink", "linked.md", "Not a regular file"),
        ("not_markdown", "plain.txt", None),
        ("archived_path", "_archive/old.md", "Note outside brain/_inbox/"),
        ("unregistered", "elsewhere.md", "Hub not registered"),
    ],
)
def test_reports_unavailable_when_note_unreadable(
    world_app: Any, propose: Any, hub_world: Any, *, case: str, name: str, reason: str | None
) -> None:
    text = "# Note\n\nSome text.\n"
    if case == "missing":
        learning_id = propose(world_app, name, text, on_disk=False)
    elif case == "too_large":
        learning_id = propose(world_app, name, "# Huge\n\n" + "x" * (NOTE_LIMIT + 10) + "\n")
    elif case == "symlink":
        _symlink_outside(hub_world, name)
        learning_id = propose(world_app, name, text, on_disk=False)
    elif case == "unregistered":
        learning_id = propose(world_app, name, text, project="other")
    else:
        learning_id = propose(world_app, name, text)

    detail = world_app.client.get(f"/api/v1/learnings/{learning_id}")
    listed = world_app.client.get("/api/v1/learnings")

    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["note"] is None
    assert body["note_unavailable"] is not None
    if reason is not None:
        assert body["note_unavailable"] == reason
    assert body["actions_unavailable"] is not None
    (item,) = [item for item in listed.json()["items"] if item["id"] == learning_id]
    assert (item["summary"], item["note_unavailable"]) == (None, body["note_unavailable"])
    assert OUTSIDE_SENTINEL not in detail.text + listed.text
