import json

import pytest
from pydantic import ValidationError

from agent_hub.core.brain.brain_note import (
    BrainEntry,
    BrainNote,
    BrainNoteNotFoundError,
    BrainNoteTooLargeError,
    BrainTree,
)
from agent_hub.core.errors import AgentHubError


def test_serializes_tree_when_brain_listed() -> None:
    tree = BrainTree(
        project="demo",
        entries=(
            BrainEntry(path="index.md", size=120),
            BrainEntry(path="decisions/index.md", size=80),
        ),
    )

    document = json.loads(tree.model_dump_json())

    assert document["entries"] == [
        {"path": "index.md", "size": 120},
        {"path": "decisions/index.md", "size": 80},
    ]
    assert (document["truncated"], document["skipped"]) == (False, 0)


def test_serializes_note_when_note_read() -> None:
    note = BrainNote(
        project="demo",
        path="now.md",
        frontmatter={"type": "now", "tags": ["a", "b"]},
        markdown="# Now\n",
        size=30,
    )

    document = json.loads(note.model_dump_json())

    assert document == {
        "project": "demo",
        "path": "now.md",
        "frontmatter": {"type": "now", "tags": ["a", "b"]},
        "frontmatter_problem": None,
        "markdown": "# Now\n",
        "size": 30,
        "sha256": None,
    }


def test_rejects_entry_when_size_negative() -> None:
    with pytest.raises(ValidationError, match="size"):
        BrainEntry(path="index.md", size=-1)


def test_names_path_when_note_errors_raised() -> None:
    missing = BrainNoteNotFoundError(project="demo", path="x.md")
    large = BrainNoteTooLargeError(project="demo", path="y.md", size=300_000, limit=262_144)

    assert isinstance(missing, AgentHubError)
    assert (missing.project, missing.path) == ("demo", "x.md")
    assert (large.size, large.limit) == (300_000, 262_144)
    assert "y.md" in str(large)
