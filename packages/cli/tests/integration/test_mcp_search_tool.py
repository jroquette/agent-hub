"""``hub mcp``'s ``search`` tool on a real hub: git, the SQLite index and ``hub search``'s answer
(spec D-search, D-search-sync, D-errors, E-2, E-5).

The server is the one ``hub mcp`` builds (``build_server`` over ``hub_context``), driven in
process by ``mcp.Client`` (E-2), on the synthetic ``knowledge_hub`` (project ``demo``, the repo
``demo-api`` beside it, both real git repos under ``tmp_path``) with its database under
``tmp_path``.
"""

import io
import json
import os
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent
from typer.testing import Result

from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.cli.mcp_command import hub_context
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests
from agent_hub.core.testing.builders import a_second_repo
from agent_hub.mcp_server.server import build_server
from agent_hub.storage import knowledge_index

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run and hub factory (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type KnowledgeHubFactory = Callable[..., Path]

DECISION = b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nCreate worktrees from origin.\n"
PLAYBOOK = b"# Cleanup\n\nRemove old worktrees after the merge.\n"
UNRELATED = b"# Release\n\nTag the release.\n"
MARKER = b"# Note\n\nmarker\n"
NO_WORDS = "search: the query has no words"
SIZE_LIMIT = 262_144
SNIPPET_CHARS = 160


def ranked_hub(knowledge_hub: KnowledgeHubFactory) -> Path:
    """AGH-391's criterion 1 hub: a decision titled after worktrees, a playbook naming them."""
    return knowledge_hub(
        {
            "brain/decisions/0001-worktrees.md": DECISION,
            "brain/playbooks/cleanup.md": PLAYBOOK,
            "brain/playbooks/release.md": UNRELATED,
        }
    )


def hub_env(hub: Path, tmp_path: Path, **extra: str) -> dict[str, str]:
    """The environment ``hub mcp`` gets: the hub named, the database under ``tmp_path``."""
    return dict(
        os.environ,
        **{HUB_ROOT_VARIABLE: str(hub), "AGENT_HUB_DB": str(tmp_path / "index.db")},
        **extra,
    )


def served(environ: Mapping[str, str], *calls: tuple[str, dict[str, Any]]) -> list[CallToolResult]:
    """The results of ``calls``, one session of the server ``hub mcp`` builds for ``environ``."""
    server = build_server(
        hub_context(environ),
        change_requests=InMemoryBrainChangeRequests(FakeBrainOrigin()),
        clock=lambda: datetime(2026, 10, 21, tzinfo=UTC),
        log=io.StringIO(),
    )

    async def session() -> list[CallToolResult]:
        async with Client(server) as client:
            return [await client.call_tool(name, arguments) for name, arguments in calls]

    return anyio.run(session)


def text_of(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def found_by(result: CallToolResult) -> dict[str, Any]:
    """The answer of a successful call, the same object as structured content and as text."""
    assert not result.is_error, text_of(result)
    assert result.structured_content is not None
    assert json.loads(text_of(result)) == result.structured_content
    return result.structured_content


def paths_of(found: Mapping[str, Any]) -> list[str]:
    return [hit["path"] for hit in found["results"]]


def test_matches_hub_search_results_when_query_given(
    knowledge_hub: KnowledgeHubFactory, run_command: CommandRunner, tmp_path: Path
) -> None:
    hub = ranked_hub(knowledge_hub)
    env = hub_env(hub, tmp_path)

    command = run_command(
        hub, "search", "worktrees", "--json", env={"AGENT_HUB_DB": env["AGENT_HUB_DB"]}
    )
    [result] = served(env, ("search", {"query": "worktrees"}))

    assert command.exit_code == 0, command.output
    expected = json.loads(command.stdout)
    found = found_by(result)
    assert set(found) == {"hub", "query", "results", "sync", "skipped", "warnings"}
    assert (
        paths_of(found)
        == paths_of(expected)
        == [
            "brain/decisions/0001-worktrees.md",
            "brain/playbooks/cleanup.md",
        ]
    )
    assert found["results"] == expected["results"]
    assert (found["hub"], found["query"], found["skipped"], found["warnings"]) == (
        "demo",
        "worktrees",
        [],
        [],
    )
    for hit in found["results"]:
        assert hit["path"]
        assert hit["snippet"]
        assert "\n" not in hit["snippet"]
        assert len(hit["snippet"]) <= SNIPPET_CHARS


def test_caps_results_at_limit_when_sixty_match(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({f"brain/notes/{number:02}.md": MARKER for number in range(60)})

    default, fifty = served(
        hub_env(hub, tmp_path),
        ("search", {"query": "marker"}),
        ("search", {"query": "marker", "limit": 50}),
    )

    assert paths_of(found_by(default)) == [f"brain/notes/{number:02}.md" for number in range(10)]
    assert paths_of(found_by(fifty)) == [f"brain/notes/{number:02}.md" for number in range(50)]


def test_keeps_only_kind_when_kind_given(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = ranked_hub(knowledge_hub)

    [result] = served(
        hub_env(hub, tmp_path), ("search", {"query": "worktrees", "kind": "decision"})
    )

    found = found_by(result)
    assert paths_of(found) == ["brain/decisions/0001-worktrees.md"]
    assert {hit["kind"] for hit in found["results"]} == {"decision"}


def test_returns_no_results_when_nothing_matches(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = ranked_hub(knowledge_hub)

    [result] = served(hub_env(hub, tmp_path), ("search", {"query": "zebra"}))

    found = found_by(result)
    assert found["results"] == []
    assert found["sync"] == {"listed": 3, "read": 3, "indexed": 3, "dropped": 0}


def test_refuses_query_when_out_of_bounds(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    refused = {
        "": "search: invalid arguments (query)",
        "!!!": NO_WORDS,
        "(": NO_WORDS,
        "m" * 501: "search: invalid arguments (query)",
    }
    out_of_bounds = [
        ({"query": "marker", "limit": 0}, "search: invalid arguments (limit)"),
        ({"query": "marker", "limit": 51}, "search: invalid arguments (limit)"),
        ({"query": "marker", "kind": "nope"}, "search: invalid arguments (kind)"),
    ]
    calls = [({"query": query}, line) for query, line in refused.items()] + out_of_bounds

    *failed, valid = served(
        hub_env(hub, tmp_path),
        *[("search", arguments) for arguments, _ in calls],
        ("search", {"query": "marker"}),
    )

    assert [(result.is_error, text_of(result)) for result in failed] == [
        (True, line) for _, line in calls
    ]
    assert paths_of(found_by(valid)) == ["brain/a.md"]


def test_searches_words_when_query_has_fts_syntax(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub(
        {
            "brain/both.md": b"# Both\n\na b or near and unclosed title foo\n",
            "brain/only-a.md": b"# Only\n\na\n",
        }
    )
    queries = ("a OR b", "NEAR(a b)", "title:foo", '"unclosed')

    results = served(hub_env(hub, tmp_path), *[("search", {"query": query}) for query in queries])

    for query, result in zip(queries, results, strict=True):
        assert paths_of(found_by(result)) == ["brain/both.md"], query


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def test_lists_skipped_files_when_sync_skips_them(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub(
        {
            "brain/a.md": MARKER,
            "brain/big.md": MARKER + b"\n" * (SIZE_LIMIT + 1 - len(MARKER)),
            "brain/_inbox/leak.md": f"# Leak\n\nmarker {secret_token()}\n".encode(),
        }
    )

    [result] = served(hub_env(hub, tmp_path), ("search", {"query": "marker"}))

    found = found_by(result)
    assert paths_of(found) == ["brain/a.md"]
    assert found["skipped"] == [
        {"path": "brain/_inbox/leak.md", "reason": "matches a secret rule"},
        {"path": "brain/big.md", "reason": "larger than 256 KiB"},
    ]
    assert secret_token() not in text_of(result)


def test_warns_when_repo_not_checked_out(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"demo-api/docs/guide.md": MARKER})
    document = json.loads((hub / "hub.json").read_bytes())
    document["repos"].append(a_second_repo())
    (hub / "hub.json").write_bytes(dump_json(document))

    [result] = served(hub_env(hub, tmp_path), ("search", {"query": "marker"}))

    found = found_by(result)
    assert found["warnings"] == ["demo-web: not checked out; its docs are not searched"]
    assert paths_of(found) == ["demo-api/docs/guide.md"]


def test_returns_error_when_git_missing(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path, no_git_path: Path
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})

    searched, read = served(
        hub_env(hub, tmp_path, PATH=str(no_git_path)),
        ("search", {"query": "marker"}),
        ("read", {"path": "brain/a.md"}),
    )

    assert searched.is_error
    assert text_of(searched) == "search: git is not on PATH; install git"
    assert read.is_error
    assert text_of(read) == "read: git is not on PATH; install git"
    assert not (tmp_path / "index.db").exists()


def test_returns_error_when_sqlite_lacks_fts5(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/a.md": MARKER})
    monkeypatch.setattr(knowledge_index, "fts5_available", lambda *_: False)

    searched, read = served(
        hub_env(hub, tmp_path),
        ("search", {"query": "marker"}),
        ("read", {"path": "brain/a.md"}),
    )

    assert searched.is_error
    assert text_of(searched) == (
        "search: this Python's SQLite has no FTS5 module; the knowledge index needs it"
    )
    assert found_by(read)["text"] == MARKER.decode()
    assert not (tmp_path / "index.db").exists()
