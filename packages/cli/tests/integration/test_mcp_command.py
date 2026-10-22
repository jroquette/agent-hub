"""``hub mcp``'s start: the hub resolved once before the protocol, the exits, and the lazy import
of the MCP SDK (AGH-392, spec D-start, E-3, D-db).

The exits run ``python -m agent_hub.cli mcp`` as a child with stdin closed; the served tools run
in process (E-2): ``build_server`` over ``hub_context``, driven by ``mcp.Client``.
"""

import io
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from agent_hub.cli import mcp_command
from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.cli.mcp_command import hub_context
from agent_hub.core.json_form import dump_json
from agent_hub.core.knowledge.knowledge_index import KnowledgeIndex
from agent_hub.core.learnings.brain_change_requests import CommitAuthor
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.mcp_server.server import build_server
from agent_hub.storage.knowledge_index import open_knowledge_index

pytestmark = pytest.mark.disable_socket

# The conftest's hub factory (tests cannot import a conftest in importlib mode).
type KnowledgeHubFactory = Callable[..., Path]

NOW_TEXT = b"# Now\n\nFocus on worktrees.\n"
# A child that hangs (it should exit before reading stdin) fails the test instead.
CHILD_SECONDS = 60


def run_mcp(folder: Path, env: Mapping[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """``hub mcp`` started in ``folder`` as Claude Code starts it, with stdin closed."""
    return subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-m", "agent_hub.cli", "mcp"],
        cwd=folder,
        env=dict(os.environ if env is None else env),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        text=True,
        timeout=CHILD_SECONDS,
        check=False,
    )


def test_exits_two_when_folder_not_hub(tmp_path: Path) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    result = run_mcp(elsewhere)

    assert result.returncode == 2
    assert result.stdout == ""
    assert result.stderr == (
        f"{elsewhere}: not a hub: no hub.json in this folder"
        " (hub mcp runs in the hub folder or through ./hub)\n"
    )


@pytest.mark.parametrize("name", ["hub.json", "hub.local.json"])
def test_exits_one_when_hub_config_invalid(knowledge_hub: KnowledgeHubFactory, name: str) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})
    (hub / name).write_bytes(b"{not json")

    result = run_mcp(hub)

    assert result.returncode == 1
    assert result.stdout == ""
    assert result.stderr.startswith(f"{name}: "), result.stderr


def test_imports_mcp_lazily_when_cli_main_loaded() -> None:
    probe = (
        "import sys, agent_hub.cli.main; "
        "print('mcp' in sys.modules, 'agent_hub.mcp_server' in sys.modules)"
    )

    result = subprocess.run(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-I", "-c", probe],
        capture_output=True,
        text=True,
        timeout=CHILD_SECONDS,
        check=True,
    )

    assert result.stdout == "False False\n"


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


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


def test_serves_read_when_database_unwritable(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})
    folder = tmp_path / "db-is-a-folder"
    folder.mkdir()
    env = dict(os.environ, **{HUB_ROOT_VARIABLE: str(hub), "AGENT_HUB_DB": str(folder)})

    searched, again, read = served(
        env,
        ("search", {"query": "worktrees"}),
        ("search", {"query": "worktrees"}),
        ("read", {"path": "brain/now.md"}),
    )

    for failed in (searched, again):
        assert failed.is_error
        assert _text(failed).startswith("search: "), _text(failed)
        assert "\n" not in _text(failed)
    assert not read.is_error, _text(read)
    assert read.structured_content is not None
    assert read.structured_content["text"] == NOW_TEXT.decode()
    assert list(folder.iterdir()) == []


def test_serves_two_searches_when_index_opened_once(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})
    env = dict(os.environ, **{HUB_ROOT_VARIABLE: str(hub), "AGENT_HUB_DB": str(tmp_path / "x.db")})
    opened: list[Path] = []

    def counted(path: Path) -> KnowledgeIndex:
        opened.append(path)
        return open_knowledge_index(path)

    monkeypatch.setattr(mcp_command, "open_knowledge_index", counted)

    first, second = served(
        env, ("search", {"query": "worktrees"}), ("search", {"query": "worktrees"})
    )

    assert opened == [tmp_path / "x.db"]

    for result in (first, second):
        assert not result.is_error, _text(result)
        assert result.structured_content is not None
        assert [hit["path"] for hit in result.structured_content["results"]] == ["brain/now.md"]


def _without_author(hub: Path) -> None:
    document = a_hub_document()
    del document["modules"]
    document["platform"]["version"] = json.loads((hub / "hub.json").read_bytes())["platform"][
        "version"
    ]
    del document["project"]["author_name"], document["project"]["author_email"]
    (hub / "hub.json").write_bytes(dump_json(document))


def test_resolves_proposal_facts_when_hub_local_sets_author(
    knowledge_hub: KnowledgeHubFactory,
) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})
    env = dict(os.environ, **{HUB_ROOT_VARIABLE: str(hub), "CLAUDE_CODE_SESSION_ID": "s-123"})

    from_hub = hub_context(env)
    local = {"project": {"author_name": "Local Dev", "author_email": "local@example.com"}}
    (hub / "hub.local.json").write_bytes(dump_json(local))
    from_local = hub_context(env)
    (hub / "hub.local.json").unlink()
    _without_author(hub)
    from_nowhere = hub_context(env)

    assert from_hub.proposal.author == CommitAuthor(name="Jane Doe", email="jane@example.com")
    assert (from_hub.proposal.hub_repo, from_hub.proposal.default_branch) == (
        "acme/demo-hub",
        "main",
    )
    assert from_hub.proposal.branch_prefix == "jdoe/"
    assert (from_hub.project, from_hub.repo_dirs, from_hub.session) == (
        "demo",
        ("demo-api",),
        "s-123",
    )
    assert from_hub.hub_path == os.path.realpath(hub)
    assert from_local.proposal.author == CommitAuthor(name="Local Dev", email="local@example.com")
    assert from_nowhere.proposal.author is None
