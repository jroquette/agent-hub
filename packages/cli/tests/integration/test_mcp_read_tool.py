"""``hub mcp``'s ``read`` tool on a real hub: the path rule, git's listing and the index's file
rules (spec D-read, D-hub, Q-3, E-2).

The server is the one ``hub mcp`` builds (``build_server`` over ``hub_context``), driven in
process by ``mcp.Client`` (E-2), on the synthetic ``knowledge_hub`` (project ``demo``, the repo
``demo-api`` beside it, both real git repos under ``tmp_path``).
"""

import faulthandler
import io
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.cli.mcp_command import hub_context
from agent_hub.core.testing.brain_fakes import FakeBrainOrigin, InMemoryBrainChangeRequests
from agent_hub.mcp_server.server import build_server

pytestmark = pytest.mark.disable_socket

# The conftest's hub factory (tests cannot import a conftest in importlib mode).
type KnowledgeHubFactory = Callable[..., Path]

DECISION = (
    b"---\nstatus: accepted\nprovenance: agent\n---\n"
    b"# Worktrees from origin\n\nCreate worktrees from origin.\n"
)
ADR = b"# ADR 1: Use x\n\nWe use x.\n"
SIZE_LIMIT = 262_144
# Every file a refused read names holds this word; no refusal may show it.
CONTENT = "quokkacontent"
NOTE = f"# Note\n\n{CONTENT}\n".encode()
# The FIFO read must answer within this; a read that blocked is stopped (with a traceback) later.
FIFO_SECONDS = 1
FIFO_ALARM_SECONDS = 5


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


def sized(prefix: bytes, size: int) -> bytes:
    """``prefix`` padded with line breaks to exactly ``size`` bytes."""
    return prefix + b"\n" * (size - len(prefix))


def git(folder: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [shutil.which("git") or "git", *args], cwd=folder, check=True, capture_output=True
    )


def test_returns_text_and_metadata_when_path_allowed(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub(
        {"brain/decisions/0001-worktrees.md": DECISION, "demo-api/docs/adr/0001-x.md": ADR}
    )

    decision, adr = served(
        hub_env(hub, tmp_path),
        ("read", {"path": "brain/decisions/0001-worktrees.md"}),
        ("read", {"path": "demo-api/docs/adr/0001-x.md"}),
    )

    assert found_by(decision) == {
        "path": "brain/decisions/0001-worktrees.md",
        "kind": "decision",
        "title": "Worktrees from origin",
        "status": "accepted",
        "provenance": "agent",
        "text": DECISION.decode(),
    }
    assert found_by(adr) == {
        "path": "demo-api/docs/adr/0001-x.md",
        "kind": "adr",
        "title": "ADR 1: Use x",
        "status": None,
        "provenance": None,
        "text": ADR.decode(),
    }


def test_returns_file_when_exactly_at_size_limit(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    exact = sized(NOTE, SIZE_LIMIT)
    hub = knowledge_hub({"brain/exact.md": exact})

    [result] = served(hub_env(hub, tmp_path), ("read", {"path": "brain/exact.md"}))

    text = found_by(result)["text"]
    assert text == exact.decode()
    assert len(text.encode()) == SIZE_LIMIT


def test_returns_main_checkout_text_when_root_is_worktree(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOTE})
    worktree = tmp_path / "hub-task"
    git(hub, "worktree", "add", "-q", "-b", "task", str(worktree))
    (worktree / "brain" / "now.md").write_bytes(b"# Now\n\nOnly in the worktree.\n")

    [result] = served(hub_env(worktree, tmp_path), ("read", {"path": "brain/now.md"}))

    assert found_by(result)["text"] == NOTE.decode()


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def refusing_hub(knowledge_hub: KnowledgeHubFactory, tmp_path: Path) -> Path:
    """A hub holding a file behind every refusal of AC-392.7 (the FIFO has its own test)."""
    hub = knowledge_hub(
        {
            ".gitignore": b"brain/ignored.md\n",
            "brain/now.md": NOTE,
            "brain/auto/workspace/me.md": NOTE,
            "brain/x.txt": NOTE,
            "brain/big.md": sized(NOTE, SIZE_LIMIT + 1),
            "brain/latin.md": f"# Latin\n\n{CONTENT} caf".encode() + b"\xe9\n",
            "brain/_inbox/leak.md": f"# Leak\n\n{CONTENT} {secret_token()}\n".encode(),
            "demo-api/src/notes.md": NOTE,
        }
    )
    brain = hub / "brain"
    (brain / "folder").mkdir()
    (brain / "folder" / "a.md").write_bytes(NOTE)
    (brain / "link.md").symlink_to(brain / "now.md")
    (brain / "linked").symlink_to(brain / "folder")
    (brain / "ignored.md").write_bytes(NOTE)
    return hub


NOT_ALLOWED = "path not allowed"


@pytest.mark.parametrize(
    "refused",
    [
        ("/etc/passwd", NOT_ALLOWED),
        ("brain/../hub.json", NOT_ALLOWED),
        ("brain/./now.md", NOT_ALLOWED),
        ("brain\\now.md", NOT_ALLOWED),
        ("hub.json", NOT_ALLOWED),
        ("brain/auto/workspace/me.md", NOT_ALLOWED),
        ("brain/x.txt", NOT_ALLOWED),
        ("demo-api/src/notes.md", NOT_ALLOWED),
        ("nope/docs/a.md", NOT_ALLOWED),
        ("brain/missing.md", "not found"),
        ("brain/link.md", "reached through a link"),
        ("brain/linked/a.md", "reached through a link"),
        ("brain/big.md", "larger than 256 KiB"),
        ("brain/latin.md", "not UTF-8"),
        ("brain/ignored.md", "not tracked or ignored by git"),
        ("brain/_inbox/leak.md", "matches a secret rule"),
    ],
)
def test_refuses_path_when_rule_breaks(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path, refused: tuple[str, str]
) -> None:
    path, reason = refused
    hub = refusing_hub(knowledge_hub, tmp_path)

    [result] = served(hub_env(hub, tmp_path), ("read", {"path": path}))

    assert result.is_error
    assert text_of(result) == f"read: {reason}"
    assert CONTENT not in result.model_dump_json()
    assert secret_token() not in result.model_dump_json()


def test_refuses_fifo_without_blocking_when_read(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOTE})
    os.mkfifo(hub / "brain" / "pipe.md")

    # A read that blocked on the FIFO would stop the test here, with a traceback.
    faulthandler.dump_traceback_later(FIFO_ALARM_SECONDS, exit=True)
    try:
        started = time.perf_counter()
        [result] = served(hub_env(hub, tmp_path), ("read", {"path": "brain/pipe.md"}))
        elapsed = time.perf_counter() - started
    finally:
        faulthandler.cancel_dump_traceback_later()

    assert result.is_error
    assert text_of(result) == "read: not a regular file"
    assert elapsed < FIFO_SECONDS


def test_refuses_read_when_git_missing(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path, no_git_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOTE})

    [result] = served(
        hub_env(hub, tmp_path, PATH=str(no_git_path)), ("read", {"path": "brain/now.md"})
    )

    assert result.is_error
    assert text_of(result) == "read: git is not on PATH; install git"
    assert CONTENT not in result.model_dump_json()
