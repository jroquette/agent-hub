"""The MCP server ``hub mcp`` runs: three tools over the hub's knowledge (ADR 0044)."""

import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from functools import partial
from typing import Annotated, Any, Final, NoReturn, TextIO

import anyio
from mcp.server.mcpserver import Context, MCPServer
from mcp.server.mcpserver.exceptions import ToolError, UnexpectedToolError
from mcp.types import CallToolResult, InputRequiredResult, TextContent, ToolAnnotations
from pydantic import Field, ValidationError

from agent_hub.core.json_form import JsonValue, dump_json
from agent_hub.core.knowledge.knowledge_index import Kind
from agent_hub.core.learnings.brain_change_requests import BrainChangeRequests
from agent_hub.hub_git.brain_change_requests import GitBrainChangeRequests
from agent_hub.hub_git.git_runner import GitRunner
from agent_hub.mcp_server.hub_context import HubContext, ToolRefusal
from agent_hub.mcp_server.knowledge_tools import KnowledgeTools
from agent_hub.mcp_server.proposal_input import ProposalKind
from agent_hub.mcp_server.propose_tool import ProposeTool

SERVER_NAME: Final = "hub"
# Every line ``hub mcp`` writes to its log (stderr) starts with this.
LOG_PREFIX: Final = "hub mcp: "
# What the server tells every client in its initialize reply: how to use the three tools. It
# stands alone (no AGENTS.md needed), names no project, repo or path from hub.json, and stays
# within 1,500 characters.
INSTRUCTIONS: Final = "\n".join(
    (
        "This server reads the hub's brain (its team memory: decisions, learnings, playbooks, "
        "feature records and the inbox) and its repos' docs/. Its tools are search, read and "
        "propose (in Claude Code: mcp__hub__search, mcp__hub__read, mcp__hub__propose). Use them "
        "at the start of every task and again before research or planning:",
        "1. search the task's topic with 2 to 4 key words. Every word must appear in a result, so "
        "drop type prefixes such as feat(...):, scopes, tracker ids and filler words. If nothing "
        "comes back, or a hook refuses the call, retry once with fewer words, then go on. limit 5 "
        "is enough to start.",
        "2. read the paths that matter before you plan.",
        "3. Weigh each result by its kind and status: kind inbox is an unreviewed proposal, never "
        "authoritative; of two notes on the same subject, the one with status approved wins over "
        "a draft one.",
        "4. To file a learning, propose opens a hub pull request that adds one note to "
        "brain/_inbox/. When propose is refused (for example where gh is missing, as in a cloud "
        "session), write the learning as a note in brain/_inbox/ or put it in your final message.",
        "Without these tools in the session, run ./hub search <words> from the hub directory (the "
        "one with hub.json), with the same key words, and ./hub brief for the current focus; "
        "brain/index.md says where things are. A missing server never blocks the work: say in "
        "your first message that it was not loaded, and go on.",
    )
)

_SEARCH: Final = (
    "Search the hub's brain and its repos' docs (the hub search index, brought up to date "
    "first). query: 1..500 characters of plain words, every one required in a result; kind: "
    "keep one kind only; limit: 1..50 results, 10 by default."
)
_READ: Final = (
    "Read one Markdown file of the hub's brain/ (not brain/auto/) or of a repo's docs/, by its "
    "hub-relative path (at most 1024 characters, ending in .md). A file reached through a link, "
    "not a regular file, larger than 256 KiB, not UTF-8, ignored by git or matching a secret "
    "rule is refused."
)
_PROPOSE: Final = (
    "Propose a learning: open a hub pull request that adds one note to brain/_inbox/ on a new "
    "branch. title: one line of 1..120 characters; body: 1..65,536 bytes; kind: the brain folder "
    "the note would join; external: true when the knowledge came from outside the hub (web, "
    "issues, fetched docs). Text matching a secret rule or carrying AI attribution is refused."
)

Query = Annotated[str, Field(min_length=1, max_length=500)]
Limit = Annotated[int, Field(ge=1, le=50)]


def build_server(
    hub: HubContext,
    *,
    change_requests: BrainChangeRequests,
    clock: Callable[[], datetime],
    log: TextIO,
) -> MCPServer:
    """The server for ``hub``: ``search``, ``read`` and ``propose``."""
    answer = _Answers(log)
    server = _HubServer(answer, name=SERVER_NAME, version=hub.version, log_level="WARNING")
    knowledge = KnowledgeTools(hub)
    proposals = ProposeTool(hub, change_requests=change_requests, clock=clock)

    def search(query: Query, kind: Kind | None = None, limit: Limit = 10) -> CallToolResult:
        return answer("search", lambda: knowledge.search(query, kind=kind, limit=limit))

    def read(path: str) -> CallToolResult:
        return answer("read", lambda: knowledge.read(path))

    def propose(*, title: str, body: str, kind: ProposalKind, external: bool) -> CallToolResult:
        return answer(
            "propose",
            lambda: proposals.propose(title=title, body=body, kind=kind, external=external),
        )

    reading = ToolAnnotations(read_only_hint=True)
    server.add_tool(
        search, name="search", description=_SEARCH, annotations=reading, structured_output=False
    )
    server.add_tool(
        read, name="read", description=_READ, annotations=reading, structured_output=False
    )
    proposing = ToolAnnotations(read_only_hint=False, destructive_hint=False, open_world_hint=True)
    server.add_tool(
        propose,
        name="propose",
        description=_PROPOSE,
        annotations=proposing,
        structured_output=False,
    )
    return server


def serve(hub: HubContext, *, environ: Mapping[str, str]) -> None:
    """Serve ``hub`` over stdio until the client closes stdin. ``propose``'s ``git`` and ``gh``
    run with ``environ``; the log is stderr, and stdout carries the protocol only."""
    change_requests = GitBrainChangeRequests(GitRunner(environ=environ))
    log = sys.stderr
    log.write(f"{LOG_PREFIX}serving {hub.project} ({_shown(hub.hub_path)})\n")
    log.flush()
    server = build_server(
        hub, change_requests=change_requests, clock=lambda: datetime.now(UTC), log=log
    )
    server.run("stdio")


def _shown(text: str) -> str:
    """``text`` on one line: each character that is not printable as its ``\\x``/``\\u`` escape."""
    return "".join(c if c.isprintable() else c.encode("unicode_escape").decode() for c in text)


class _HubServer(MCPServer):
    """The SDK's server, except that a call whose arguments fail the tool's input schema is
    answered like a refusal: ``<tool>: invalid arguments (<fields>)``, the field names only
    (the SDK's own text is pydantic's, which quotes the caller's values), through ``_Answers``
    so it takes the lock and writes its log line as every other call does."""

    def __init__(self, answer: _Answers, **settings: Any) -> None:
        super().__init__(**settings)
        self._answer = answer

    async def call_tool(
        self, name: str, arguments: dict[str, Any], context: Context[Any, Any] | None = None
    ) -> CallToolResult | InputRequiredResult:
        try:
            return await super().call_tool(name, arguments, context)
        except ToolError as error:
            # ``Tool.run`` raises a ``ToolError`` caused by the ``ValidationError`` when the
            # arguments fail its model; anything else keeps the SDK's handling.
            rejected = error.__cause__
            if isinstance(error, UnexpectedToolError) or not isinstance(rejected, ValidationError):
                raise
        line = f"{name}: invalid arguments ({', '.join(_fields(rejected))})"
        # In a worker thread, as the SDK runs the sync tools, so the lock never blocks the loop.
        return await anyio.to_thread.run_sync(self._answer, name, partial(_refuse, line))


def _fields(rejected: ValidationError) -> list[str]:
    """The top-level fields ``rejected`` names: the SDK's argument model ignores unknown keys,
    so each is one of the tool's own parameters, never a caller's key or value."""
    return sorted({str(error["loc"][0]) for error in rejected.errors() if error["loc"]})


def _refuse(line: str) -> NoReturn:
    raise ToolRefusal(line)


class _Answers:
    """Runs each tool call alone (the SDK runs sync tools in worker threads, and the checkout
    and the index serve one caller at a time) and turns its outcome into the result: the
    tool's object as structured content and as JSON text, or one error line with no SDK prefix
    (a refusal's own line; ``<tool>: internal error (<Type>)`` for anything else, its traceback
    on the log). Each call writes one log line, tool, outcome and time, never an argument."""

    def __init__(self, log: TextIO) -> None:
        self._log = log
        self._lock = threading.Lock()

    def __call__(self, tool: str, run: Callable[[], dict[str, JsonValue]]) -> CallToolResult:
        started = time.perf_counter()
        with self._lock:
            result = self._result(tool, run)
            elapsed = round((time.perf_counter() - started) * 1000)
            outcome = "error" if result.is_error else "ok"
            self._write(f"{LOG_PREFIX}{tool} {outcome} {elapsed}ms\n")
        return result

    def _result(self, tool: str, run: Callable[[], dict[str, JsonValue]]) -> CallToolResult:
        try:
            found = run()
        except ToolRefusal as refused:
            return _error(refused.line)
        except Exception as error:  # noqa: BLE001 - every failure is the caller's one line
            self._write("".join(traceback.format_exception(error)))
            return _error(f"{tool}: internal error ({type(error).__name__})")
        text = dump_json(found).decode("utf-8")
        return CallToolResult(
            content=[TextContent(type="text", text=text)], structured_content=found
        )

    def _write(self, text: str) -> None:
        self._log.write(text)
        self._log.flush()


def _error(line: str) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=line)], is_error=True)
