"""``/projects/{project}/knowledge/search`` on the composed app over a registered hub checkout and
the web's own database (AGH-393, AC-393.1, AC-393.2, AC-393.5 to AC-393.9, AC-393.17).

Each hub is ``knowledge_world``'s: the git checkout ``demo-hub`` (project ``demo``) with the repo
``demo-api`` beside it, both synthetic, registered in the app as ``hub web`` registers a hub.
"""

import os
import time
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.testing.builders import a_second_repo
from agent_hub.storage import knowledge_index

# The conftest's world and its factory (tests cannot import a conftest in importlib mode).
type KnowledgeWorldFactory = Any

DECISION = b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nCreate worktrees from origin.\n"
PLAYBOOK = b"# Cleanup\n\nRemove old worktrees after the merge.\n"
UNRELATED = b"# Release\n\nTag the release.\n"
GUIDE = b"# Guide\n\nThe api keeps its worktrees small.\n"
MARKER = b"# Note\n\nmarker\n"
MAX_SNIPPET = 160


def ranked_files() -> dict[str, bytes]:
    """AC-393.1's hub: a decision titled after worktrees, notes and a repo doc naming them."""
    return {
        "brain/decisions/0001-worktrees.md": DECISION,
        "brain/playbooks/cleanup.md": PLAYBOOK,
        "brain/playbooks/release.md": UNRELATED,
        "demo-api/docs/guide.md": GUIDE,
    }


def answer(response: Any) -> Any:
    assert response.status_code == 200, response.text
    return response.json()


def paths(found: Any) -> list[str]:
    return [result["path"] for result in found["results"]]


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def database_bytes(database: Path) -> bytes:
    """The database's bytes, with its write-ahead log and shared memory when present."""
    parts = [database, database.with_name(database.name + "-wal")]
    parts.append(database.with_name(database.name + "-shm"))
    return b"".join(part.read_bytes() for part in parts if part.exists())


def test_matches_note_when_query_names_word(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(ranked_files())

    found = answer(world.search("worktrees"))

    first = found["results"][0]
    assert (first["path"], first["kind"], first["title"], first["status"]) == (
        "brain/decisions/0001-worktrees.md",
        "decision",
        "Worktrees from origin",
        "accepted",
    )
    assert "worktrees" in first["snippet"]
    assert "\n" not in first["snippet"]
    assert len(first["snippet"]) <= MAX_SNIPPET
    assert set(paths(found)) == {
        "brain/decisions/0001-worktrees.md",
        "brain/playbooks/cleanup.md",
        "demo-api/docs/guide.md",
    }
    assert (found["project"], found["query"], found["skipped"], found["warnings"]) == (
        "demo",
        "worktrees",
        [],
        [],
    )


def test_answers_same_paths_as_cli_when_same_hub_and_database(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world(ranked_files())

    routed = answer(world.search("worktrees"))
    printed = world.hub_search("worktrees")

    assert paths(routed) == paths(printed)
    assert len(paths(routed)) == 3


def test_answers_no_results_when_nothing_matches(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(ranked_files())

    found = answer(world.search("zebra"))

    assert found["results"] == []
    assert found["sync"]["indexed"] == len(ranked_files())


def test_keeps_only_kind_when_kind_given(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(ranked_files())

    decisions = answer(world.search("worktrees", kind="decision"))
    two_kinds = answer(world.search("worktrees", kind=["decision", "playbook"]))

    assert paths(decisions) == ["brain/decisions/0001-worktrees.md"]
    assert sorted(paths(two_kinds)) == [
        "brain/decisions/0001-worktrees.md",
        "brain/playbooks/cleanup.md",
    ]


def test_caps_results_at_limit_when_sixty_match(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world({f"brain/notes/{number:02}.md": MARKER for number in range(60)})

    unbounded = answer(world.search("marker"))
    eight = answer(world.search("marker", limit=8))

    every = [f"brain/notes/{number:02}.md" for number in range(60)]
    assert paths(unbounded) == every[:50]
    assert paths(eight) == every[:8]


@pytest.mark.parametrize(
    ("params", "parameter"),
    [
        ({"q": "!!!"}, "q"),
        ({"q": "("}, "q"),
        ({"q": "zanzibarquery" + "x" * 488}, "q"),
        ({"q": "zanzibarquery", "limit": 0}, "limit"),
        ({"q": "zanzibarquery", "limit": 51}, "limit"),
        ({"q": "zanzibarquery", "kind": "nope"}, "kind"),
        ({"q": "zanzibarquery", "kind": ["doc"] * 11}, "kind"),
    ],
)
def test_refuses_query_when_out_of_bounds_or_wordless(
    knowledge_world: KnowledgeWorldFactory, params: dict[str, Any], parameter: str
) -> None:
    world = knowledge_world({"brain/a.md": MARKER})

    response = world.app.client.get("/api/v1/projects/demo/knowledge/search", params=params)

    assert response.status_code == 400
    assert response.headers["content-type"] == "application/problem+json"
    errors = response.json()["errors"]
    assert [error["parameter"] for error in errors] == [parameter]
    assert "zanzibarquery" not in response.text
    if params["q"] in {"!!!", "("}:
        assert errors[0]["message"] == "the query has no words"
        assert f'"{params["q"]}"' not in response.text
    assert world.rows("SELECT count(*) FROM knowledge_documents") == [(0,)]


def test_searches_words_when_query_has_fts_syntax(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(
        {
            "brain/both.md": b"# Both\n\na b or near and unclosed title foo\n",
            "brain/only-a.md": b"# Only\n\na\n",
        }
    )

    for query in ("a OR b", "NEAR(a b)", "title:foo", '"unclosed'):
        found = answer(world.search(query))
        assert paths(found) == ["brain/both.md"], query
        assert found["query"] == query


def test_answers_not_found_when_unknown_project(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world({"brain/a.md": MARKER})

    response = world.app.client.get(
        "/api/v1/projects/nobody/knowledge/search", params={"q": "marker"}
    )

    assert response.status_code == 404
    assert response.headers["content-type"] == "application/problem+json"
    assert world.rows("SELECT count(*) FROM knowledge_documents") == [(0,)]


def test_finds_new_word_when_note_edited(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world({"brain/a.md": b"# A\n\nalpha\n", "brain/b.md": b"# B\n\nbeta\n"})
    assert paths(answer(world.search("alpha"))) == ["brain/a.md"]

    note = world.write("brain/a.md", b"# A\n\nomega\n")
    # Same size: the edit is seen through the mtime, moved on so a coarse clock cannot hide it.
    stat = note.stat()
    os.utime(note, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000_000))

    assert paths(answer(world.search("omega"))) == ["brain/a.md"]
    assert answer(world.search("alpha"))["results"] == []


def test_drops_note_when_deleted(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world({"brain/a.md": MARKER, "brain/b.md": MARKER})
    assert paths(answer(world.search("marker"))) == ["brain/a.md", "brain/b.md"]

    (world.hub / "brain" / "a.md").unlink()
    found = answer(world.search("marker"))

    assert paths(found) == ["brain/b.md"]
    assert found["sync"]["dropped"] == 1


def test_reads_nothing_when_unchanged(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(ranked_files())
    first = answer(world.search("worktrees"))

    again = answer(world.search("worktrees"))

    assert first["sync"]["read"] == len(ranked_files())
    assert again["sync"] == {"listed": len(ranked_files()), "read": 0, "indexed": 0, "dropped": 0}
    assert again["results"] == first["results"]


@pytest.mark.usefixtures("offline")
def test_indexes_offline_when_database_fresh(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(ranked_files() | {"brain/session.jsonl": b'{"worktrees": 1}\n'})
    assert world.rows("SELECT count(*) FROM knowledge_documents") == [(0,)]

    found = answer(world.search("worktrees"))

    assert found["sync"]["indexed"] == len(ranked_files())
    assert set(paths(found)) == {
        "brain/decisions/0001-worktrees.md",
        "brain/playbooks/cleanup.md",
        "demo-api/docs/guide.md",
    }


def test_answers_same_results_when_rows_deleted_and_rebuilt(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world(ranked_files())
    first = answer(world.search("worktrees"))

    for table in ("knowledge_links", "knowledge_text", "knowledge_documents"):
        world.rows(f"DELETE FROM {table}")  # noqa: S608 - fixed table names
    rebuilt = answer(world.search("worktrees"))

    assert rebuilt["results"] == first["results"]
    assert rebuilt["sync"]["read"] == len(ranked_files())


def test_shares_rows_when_cli_and_route_search_same_hub(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world({"brain/a.md": MARKER, "demo-api/docs/b.md": MARKER})

    printed = world.hub_search("marker")
    routed = answer(world.search("marker"))
    world.write("brain/c.md", MARKER)
    routed_after_edit = answer(world.search("marker"))
    printed_after_route = world.hub_search("marker")

    assert printed["sync"]["read"] == 2
    assert routed["sync"]["read"] == 0
    assert routed_after_edit["sync"]["read"] == 1
    assert printed_after_route["sync"]["read"] == 0
    assert paths(printed_after_route) == paths(routed_after_edit)
    assert world.rows("SELECT DISTINCT hub FROM knowledge_documents") == [
        (os.path.realpath(world.hub),)
    ]


def test_never_shows_auto_transcript_or_secret_when_searched(
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

    response = world.search("marker")

    found = answer(response)
    assert paths(found) == ["brain/index.md"]
    assert found["skipped"] == [{"path": "brain/_inbox/leak.md", "reason": "matches a secret rule"}]
    assert token not in response.text
    assert token.encode() not in database_bytes(world.app.settings.db_path)


def test_warns_when_repo_not_checked_out(knowledge_world: KnowledgeWorldFactory) -> None:
    world = knowledge_world(
        {"demo-api/docs/guide.md": MARKER},
        change=lambda document: document["repos"].append(a_second_repo()),
    )

    found = answer(world.search("marker"))

    assert found["warnings"] == ["demo-web: not checked out; its docs are not searched"]
    assert paths(found) == ["demo-api/docs/guide.md"]


def test_answers_problem_when_git_missing(
    knowledge_world: KnowledgeWorldFactory, tmp_path: Path
) -> None:
    world = knowledge_world({"brain/a.md": b"# A\n\nmarker [b](b.md)\n", "brain/b.md": MARKER})
    with_git = world.environ["PATH"]
    no_git = tmp_path / "no-git-bin"
    no_git.mkdir()
    world.environ["PATH"] = str(no_git)

    refused = [world.search("marker"), world.backlinks("b.md")]
    world.environ["PATH"] = with_git
    searched, linked = world.search("marker"), world.backlinks("b.md")

    for response in refused:
        assert response.status_code == 502, response.text
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["title"] == "Could not read the hub's files"
        assert problem["detail"] == "git is not on PATH; install git"
    assert sorted(paths(answer(searched))) == ["brain/a.md", "brain/b.md"]
    assert answer(linked)["items"] == [{"path": "brain/a.md", "kind": "doc", "title": "A"}]


def test_answers_problem_when_sqlite_lacks_fts5(
    knowledge_world: KnowledgeWorldFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = knowledge_world({"brain/a.md": b"# A\n\nmarker [b](b.md)\n", "brain/b.md": MARKER})
    with monkeypatch.context() as patch:
        patch.setattr(knowledge_index, "fts5_available", lambda *_: False)
        refused = [world.search("marker"), world.backlinks("b.md")]
    searched, linked = world.search("marker"), world.backlinks("b.md")

    for response in refused:
        assert response.status_code == 503, response.text
        assert response.headers["content-type"] == "application/problem+json"
        problem = response.json()
        assert problem["title"] == "Search unavailable"
        assert problem["detail"] == (
            "this Python's SQLite has no FTS5 module; the knowledge index needs it"
        )
    assert sorted(paths(answer(searched))) == ["brain/a.md", "brain/b.md"]
    assert answer(linked)["total"] == 1


def test_serves_local_only_when_host_or_origin_foreign(
    knowledge_world: KnowledgeWorldFactory,
) -> None:
    world = knowledge_world({"brain/a.md": MARKER})
    client = world.app.client
    search = "/api/v1/projects/demo/knowledge/search"

    foreign_host = client.get(search, params={"q": "marker"}, headers={"Host": "evil.example:7420"})
    rows_after_refusal = world.rows("SELECT count(*) FROM knowledge_documents")
    foreign_origin = client.get(
        search, params={"q": "marker"}, headers={"Origin": "https://evil.example"}
    )

    assert foreign_host.status_code == 403
    assert rows_after_refusal == [(0,)]
    assert paths(answer(foreign_origin)) == ["brain/a.md"]
    for response in (foreign_host, foreign_origin):
        assert not [name for name in response.headers if name.lower().startswith("access-control")]


def test_indexes_registered_folder_when_hub_registered_as_worktree(
    knowledge_world: KnowledgeWorldFactory, tmp_path: Path
) -> None:
    world = knowledge_world({"brain/a.md": MARKER})
    worktree = tmp_path / "demo-hub-wt"
    world.git("worktree", "add", "--quiet", "-b", "wt", str(worktree))
    (worktree / "brain" / "only-here.md").write_bytes(MARKER)
    (main,) = world.app.client.get("/api/v1/hubs").json()["items"]
    forgotten = world.app.client.delete(
        f"/api/v1/hubs/{main['id']}", headers={"Origin": world.origin}
    )
    assert forgotten.status_code == 204, forgotten.text
    registered = world.app.client.post(
        "/api/v1/hubs", json={"path": str(worktree)}, headers={"Origin": world.origin}
    )
    assert registered.status_code == 201, registered.text

    found = answer(world.search("marker"))

    assert paths(found) == ["brain/a.md", "brain/only-here.md"]
    assert world.rows("SELECT DISTINCT hub FROM knowledge_documents") == [
        (os.path.realpath(worktree),)
    ]


# AC-393.20 (NFR Latency): a hub the size of this project's own, 750 notes (21 MB, none over
# 256 KiB) holding 345 links, as AGH-391's budget hub.
BUDGET_FILES = 750
BUDGET_LINKS = 345
BUDGET_FILE_BYTES = 28_000


def budget_note(number: int) -> bytes:
    """Note ``number``: ``marker``, a link to ``brain/now.md`` for the first ``BUDGET_LINKS``,
    and varied synthetic words, in lines, exactly ``BUDGET_FILE_BYTES`` long."""
    link = "See [now](../../now.md).\n" if number < BUDGET_LINKS else ""
    lines = [f"# Note {number}\n\nmarker: the focus moves.\n{link}"]
    size = len(lines[0])
    line = 0
    while size < BUDGET_FILE_BYTES - 100:
        words = " ".join(f"term{(number * 31 + line * 7 + word) % 4000}" for word in range(10))
        lines.append(words + "\n")
        size += len(words) + 1
        line += 1
    text = "".join(lines).encode()
    return text + b"\n" * (BUDGET_FILE_BYTES - len(text))


@pytest.mark.serial
def test_answers_within_budget_when_hub_unchanged(knowledge_world: KnowledgeWorldFactory) -> None:
    files = {
        f"brain/features/f{number // 10:03}/note-{number:03}.md": budget_note(number)
        for number in range(BUDGET_FILES - 1)
    }
    world = knowledge_world(files | {"brain/now.md": b"# Now\n\nThe focus.\n"}, commit=False)

    started = time.perf_counter()
    first = answer(world.search("marker"))
    first_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    again = answer(world.search("marker"))
    search_elapsed = time.perf_counter() - started
    started = time.perf_counter()
    linked = answer(world.backlinks("now.md"))
    backlinks_elapsed = time.perf_counter() - started

    assert first["sync"]["indexed"] == BUDGET_FILES
    assert again["sync"] == {"listed": BUDGET_FILES, "read": 0, "indexed": 0, "dropped": 0}
    assert len(again["results"]) == 50
    assert (len(linked["items"]), linked["total"]) == (100, BUDGET_LINKS)
    assert world.rows("SELECT count(*) FROM knowledge_links") == [(BUDGET_LINKS,)]
    # Targets about 3 s and 0.3 s; the bounds leave room for a slow machine.
    assert first_elapsed < 10.0
    assert search_elapsed < 1.0
    assert backlinks_elapsed < 1.0
