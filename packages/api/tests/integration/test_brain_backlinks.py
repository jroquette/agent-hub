"""``/projects/{project}/brain/backlinks`` on the composed app over a registered hub checkout and
the web's own database (AGH-393, AC-393.6, AC-393.8, AC-393.11, AC-393.17, AM-3).

Each hub is ``knowledge_world``'s: the git checkout ``demo-hub`` (project ``demo``) with the repo
``demo-api`` beside it, both synthetic, registered in the app as ``hub web`` registers a hub.
"""

from typing import Any

import pytest

# The conftest's world factory (tests cannot import a conftest in importlib mode).
type KnowledgeWorldFactory = Any

DECISION = b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nCreate worktrees from origin.\n"
CLEANUP = b"# Cleanup\n\nSee [the decision](../decisions/0001-worktrees.md#why).\n"
GUIDE = (
    b"# Guide\n\nThe hub decided [worktrees](../../demo-hub/brain/decisions/0001-worktrees.md).\n"
)
TARGET = "decisions/0001-worktrees.md"
CLEANUP_ITEM = {"path": "brain/playbooks/cleanup.md", "kind": "playbook", "title": "Cleanup"}
GUIDE_ITEM = {"path": "demo-api/docs/guide.md", "kind": "doc", "title": "Guide"}


def linked_files() -> dict[str, bytes]:
    """AC-393.11's hub: the decision, linked from a playbook and from a repo doc."""
    return {
        "brain/decisions/0001-worktrees.md": DECISION,
        "brain/playbooks/cleanup.md": CLEANUP,
        "brain/playbooks/release.md": b"# Release\n\nTag the release.\n",
        "demo-api/docs/guide.md": GUIDE,
    }


def answer(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def test_lists_sources_sorted_when_note_linked(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(linked_files())

    found = answer(world.backlinks(TARGET))

    assert found == {
        "project": "demo",
        "path": TARGET,
        "items": [CLEANUP_ITEM, GUIDE_ITEM],
        "total": 2,
    }


def test_drops_source_when_link_removed_and_committed(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world(linked_files())
    assert answer(world.backlinks(TARGET))["total"] == 2

    world.write("brain/playbooks/cleanup.md", b"# Cleanup\n\nNo link any more.\n")
    world.git("commit", "--quiet", "-am", "docs: unlink the decision")
    found = answer(world.backlinks(TARGET))

    assert (found["items"], found["total"]) == ([GUIDE_ITEM], 1)


def test_answers_no_items_when_source_deleted(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(linked_files())
    world.write("brain/playbooks/cleanup.md", b"# Cleanup\n\nNo link any more.\n")
    assert answer(world.backlinks(TARGET))["items"] == [GUIDE_ITEM]

    (world.hub.parent / "demo-api" / "docs" / "guide.md").unlink()
    found = answer(world.backlinks(TARGET))

    assert (found["items"], found["total"]) == ([], 0)


@pytest.mark.parametrize(
    ("path", "status", "title"),
    [
        ("auto/x.md", 404, "Brain note not found"),
        ("../hub.json", 400, "Invalid brain path"),
    ],
)
def test_refuses_path_when_note_route_would(
    knowledge_world: KnowledgeWorldFactory, *, path: str, status: int, title: str
) -> None:
    world = knowledge_world(
        linked_files() | {"brain/auto/x.md": b"# X\n\n[d](../decisions/0001-worktrees.md)\n"}
    )

    refused = world.backlinks(path)
    note = world.app.client.get("/api/v1/projects/demo/brain/note", params={"path": path})

    assert (refused.status_code, refused.json()["title"]) == (status, title)
    assert refused.headers["content-type"] == "application/problem+json"
    assert (note.status_code, note.json()["title"]) == (status, title)
    assert world.rows("SELECT count(*) FROM knowledge_documents") == [(0,)]


@pytest.mark.usefixtures("offline")
def test_answers_items_when_empty_index(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(linked_files())
    assert world.rows("SELECT count(*) FROM knowledge_links") == [(0,)]

    found = answer(world.backlinks(TARGET))

    assert (found["items"], found["total"]) == ([CLEANUP_ITEM, GUIDE_ITEM], 2)


def test_never_shows_auto_transcript_or_secret_when_backlinks_read(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    token = secret_token()
    world = knowledge_world(
        {
            "brain/now.md": b"# Now\n\nThe focus.\n",
            "brain/index.md": b"# Index\n\nmarker [now](now.md)\n",
            "brain/auto/workspace/me.md": b"# Me\n\nmarker [now](../../now.md)\n",
            "brain/session.jsonl": b'{"type": "user", "message": "marker [now](now.md)"}\n',
            "brain/_inbox/leak.md": f"# Leak\n\nmarker {token} [now](../now.md)\n".encode(),
        }
    )

    response = world.backlinks("now.md")

    found = answer(response)
    assert found["items"] == [{"path": "brain/index.md", "kind": "doc", "title": "Index"}]
    assert found["total"] == 1
    assert token not in response.text
    assert world.rows("SELECT source FROM knowledge_links") == [("brain/index.md",)]


def test_serves_local_only_when_host_or_origin_foreign(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world(linked_files())

    foreign_host = world.backlinks(TARGET, Host="evil.example:7420")
    rows_after_refusal = world.rows("SELECT count(*) FROM knowledge_documents")
    foreign_origin = world.backlinks(TARGET, Origin="https://evil.example")

    assert foreign_host.status_code == 403
    assert rows_after_refusal == [(0,)]
    assert answer(foreign_origin)["total"] == 2
    for response in (foreign_host, foreign_origin):
        assert not [name for name in response.headers if name.lower().startswith("access-control")]
