"""``hub mcp`` over stdio, as Claude Code runs it: a child speaking JSON-RPC lines on its stdin
and stdout (AGH-392, spec D-transport, D-log, E-1, AM-1).

The child is ``python -m agent_hub.cli mcp`` with ``AGENT_HUB_ROOT`` naming a synthetic hub
(``knowledge_hub``, no origin) and ``AGENT_HUB_DB`` under ``tmp_path``. Requests are written by
hand, one line each, so every byte the server writes on stdout is read and checked.
"""

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import IO, Any, Final

import pytest
from typer.testing import CliRunner

from agent_hub.cli.hub_root import HUB_ROOT_VARIABLE
from agent_hub.cli.main import app
from agent_hub.core.knowledge.document_rules import MAX_DOCUMENT_BYTES

pytestmark = pytest.mark.disable_socket

# The conftest's hub factory (tests cannot import a conftest in importlib mode).
type KnowledgeHubFactory = Callable[..., Path]

# The newest revision reached through the initialize handshake, as Claude Code starts a server.
PROTOCOL: Final = "2025-11-25"
# A reply that does not come in this long fails the test instead of hanging it.
REPLY_SECONDS: Final = 60.0
NOW_TEXT: Final = b"# Now\n\nFocus on worktrees.\n"
CALL_LINE: Final = re.compile(r"^hub mcp: (search|read|propose) (ok|error) \d+ms$")
# /proc/<pid>/net/unix: a listening socket has __SO_ACCEPTCON in its flags.
ACCEPTING: Final = 0x10000
# The inode column of /proc/<pid>/net/{tcp,tcp6,udp,udp6}.
NET_INODE_COLUMN: Final = 9


class Served:
    """A running ``hub mcp`` child: requests written as lines, each stdout line kept."""

    def __init__(self, process: subprocess.Popen[bytes]) -> None:
        self.process = process
        self.lines: list[bytes] = []
        self._replies: queue.Queue[bytes | None] = queue.Queue()
        self._next_id = 0
        assert process.stdout is not None
        self._reader = threading.Thread(target=self._read, args=(process.stdout,), daemon=True)
        self._reader.start()

    def _read(self, stdout: IO[bytes]) -> None:
        for line in stdout:
            self.lines.append(line)
            self._replies.put(line)
        self._replies.put(None)

    def send(self, message: dict[str, Any]) -> None:
        assert self.process.stdin is not None
        self.process.stdin.write(json.dumps(message).encode() + b"\n")
        self.process.stdin.flush()

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        """The reply to one request; notifications the server sends meanwhile are skipped."""
        self._next_id += 1
        self.send({"jsonrpc": "2.0", "id": self._next_id, "method": method, "params": params})
        deadline = time.monotonic() + REPLY_SECONDS
        while True:
            line = self._replies.get(timeout=max(0.0, deadline - time.monotonic()))
            assert line is not None, "hub mcp closed stdout"
            message: dict[str, Any] = json.loads(line)
            if message.get("id") == self._next_id:
                return message

    def initialize(self) -> dict[str, Any]:
        reply = self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL,
                "capabilities": {},
                "clientInfo": {"name": "test-client", "version": "0"},
            },
        )
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return reply

    def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = self.request("tools/call", {"name": name, "arguments": arguments})[
            "result"
        ]
        return result

    def close(self) -> str:
        """Close stdin, wait for the exit and the last stdout line; stderr's text."""
        assert self.process.stdin is not None
        self.process.stdin.close()
        _, stderr = self.process.communicate(timeout=REPLY_SECONDS)
        self._reader.join(timeout=REPLY_SECONDS)
        return stderr.decode()


@contextmanager
def serving(hub: Path, database: Path) -> Iterator[Served]:
    env = dict(os.environ, **{HUB_ROOT_VARIABLE: str(hub), "AGENT_HUB_DB": str(database)})
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        [sys.executable, "-m", "agent_hub.cli", "mcp"],
        cwd=hub.parent,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        yield Served(process)
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate()


def _text(result: dict[str, Any]) -> str:
    [content] = result["content"]
    assert content["type"] == "text"
    text: str = content["text"]
    return text


def test_speaks_only_json_rpc_on_stdout_when_serving(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})
    title, body = "Quokka proposal title", "Wombat proposal body."

    with serving(hub, tmp_path / "knowledge.db") as served:
        initialized = served.initialize()
        tools = served.request("tools/list", {})["result"]["tools"]
        searched = served.call("search", {"query": "worktrees"})
        read = served.call("read", {"path": "brain/now.md"})
        proposed = served.call(
            "propose", {"title": title, "body": body, "kind": "learning", "external": False}
        )
        stderr = served.close()

    assert served.process.returncode == 0, stderr
    assert served.lines
    for line in served.lines:
        assert line.endswith(b"\n")
        assert json.loads(line)["jsonrpc"] == "2.0"
    assert initialized["result"]["serverInfo"]["name"] == "hub"
    assert sorted(tool["name"] for tool in tools) == ["propose", "read", "search"]
    assert [hit["path"] for hit in searched["structuredContent"]["results"]] == ["brain/now.md"]
    assert read["structuredContent"]["text"] == NOW_TEXT.decode()
    assert proposed["isError"] is True
    assert _text(proposed) == "propose: Hub remote is not on GitHub"
    lines = stderr.splitlines()
    assert lines[0] == f"hub mcp: serving demo ({os.path.realpath(hub)})"
    calls = [line for line in lines if CALL_LINE.match(line)]
    assert [line.split()[2:4] for line in calls] == [
        ["search", "ok"],
        ["read", "ok"],
        ["propose", "error"],
    ]
    for value in ("worktrees", "brain/now.md", title, body):
        assert value not in stderr


def _socket_inodes(pid: int) -> set[str]:
    inodes = set()
    for entry in Path(f"/proc/{pid}/fd").iterdir():
        try:
            target = os.readlink(entry)
        except FileNotFoundError:
            continue
        if target.startswith("socket:["):
            inodes.add(target.removeprefix("socket:[").removesuffix("]"))
    return inodes


def _unix_sockets(pid: int) -> dict[str, tuple[int, str]]:
    """Each Unix socket of the process's namespace by inode: its flags and its path."""
    found = {}
    for row in Path(f"/proc/{pid}/net/unix").read_text().splitlines()[1:]:
        fields = row.split()
        path = fields[7] if len(fields) > 7 else ""  # noqa: PLR2004 - the optional Path column
        found[fields[6]] = (int(fields[3], 16), path)
    return found


def _network_inodes(pid: int) -> set[str]:
    """The inodes of every TCP and UDP socket of the process's namespace; a kernel without IPv6
    has no ``tcp6`` or ``udp6`` table."""
    inodes = set()
    for table in ("tcp", "tcp6", "udp", "udp6"):
        listing = Path(f"/proc/{pid}/net/{table}")
        if listing.exists():
            rows = listing.read_text().splitlines()[1:]
            inodes.update(row.split()[NET_INODE_COLUMN] for row in rows)
    return inodes


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="reads /proc")
def test_opens_no_network_socket_when_serving(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    hub = knowledge_hub({"brain/now.md": NOW_TEXT})

    with serving(hub, tmp_path / "knowledge.db") as served:
        served.initialize()
        searched = served.call("search", {"query": "worktrees"})
        pid = served.process.pid
        inodes = _socket_inodes(pid)
        unix = _unix_sockets(pid)
        network = _network_inodes(pid)
        served.close()

    assert not searched.get("isError"), searched
    assert inodes, "the event loop's own socketpair is expected"
    assert not inodes & network
    for inode in inodes:
        assert inode in unix, inode
        flags, path = unix[inode]
        assert path == ""
        assert not flags & ACCEPTING


@pytest.mark.serial
def test_answers_within_budget_when_hub_indexed(
    knowledge_hub: KnowledgeHubFactory, tmp_path: Path
) -> None:
    files = {
        f"brain/features/f{number:03}/note.md": (
            f"# Feature {number}\n\nWorktrees and fetches, note {number}.\n"
        ).encode()
        for number in range(749)
    }
    big = b"# Big\n\n" + b"a" * (MAX_DOCUMENT_BYTES - len(b"# Big\n\n"))
    files["brain/features/big.md"] = big
    hub = knowledge_hub(files)
    database = tmp_path / "knowledge.db"
    env = {HUB_ROOT_VARIABLE: str(hub), "AGENT_HUB_DB": str(database)}
    indexed = CliRunner().invoke(app, ["search", "worktrees", "--json"], env=env)
    assert indexed.exit_code == 0, indexed.output
    assert json.loads(indexed.stdout)["sync"]["indexed"] == 750

    started = time.perf_counter()
    with serving(hub, database) as served:
        served.initialize()
        to_initialize = time.perf_counter() - started
        started = time.perf_counter()
        searched = served.call("search", {"query": "worktrees"})
        to_search = time.perf_counter() - started
        started = time.perf_counter()
        read = served.call("read", {"path": "brain/features/big.md"})
        to_read = time.perf_counter() - started
        served.close()

    assert searched["structuredContent"]["sync"]["read"] == 0
    assert len(read["structuredContent"]["text"]) == MAX_DOCUMENT_BYTES
    assert to_initialize < 5.0, to_initialize  # noqa: PLR2004 - AM-1's budget
    assert to_search < 1.0, to_search
    assert to_read < 0.5, to_read  # noqa: PLR2004 - NFR Latency
