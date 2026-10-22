import io
import json
import re
import threading
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import anyio
from mcp import Client
from mcp.types import CallToolResult, TextContent

from agent_hub.core.errors import AgentHubError
from agent_hub.core.knowledge.document_rules import (
    MAX_DOCUMENT_BYTES,
    NOT_REGULAR,
    RULE_MATCH,
    THROUGH_LINK,
    TOO_LARGE,
)
from agent_hub.core.knowledge.knowledge_index import KINDS, KnowledgeIndex
from agent_hub.core.knowledge.sync_plan import ListedFile
from agent_hub.core.learnings.brain_change_requests import (
    BrainProposal,
    ChangeRequestResult,
    ChangeRequestTimeoutError,
    CommitAuthor,
    RefspecRefusedError,
)
from agent_hub.core.testing.brain_fakes import (
    DEMO_HUB_PATH,
    DEMO_HUB_REPO,
    FakeBrainOrigin,
    InMemoryBrainChangeRequests,
)
from agent_hub.core.testing.knowledge_fakes import FakeKnowledgeCheckout, InMemoryKnowledgeIndex
from agent_hub.mcp_server.hub_context import HubCheckout, HubContext, ProposalFacts
from agent_hub.mcp_server.proposal_input import KINDS as PROPOSAL_KINDS
from agent_hub.mcp_server.proposal_input import pull_request_body
from agent_hub.mcp_server.server import build_server

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
AUTHOR = CommitAuthor(name="Demo Owner", email="owner@example.com")


class _Checkout(FakeKnowledgeCheckout):
    """The fake checkout plus the repo folders it says are not checked out, and files it holds
    but leaves out of the listing (as git leaves out an ignored file)."""

    def __init__(
        self,
        *,
        missing: tuple[str, ...] = (),
        before_read: Callable[[str], None] | None = None,
    ) -> None:
        super().__init__(before_read=before_read)
        self.missing = missing
        self.ignored: set[str] = set()
        self.listings = 0

    def not_checked_out(self) -> tuple[str, ...]:
        return self.missing

    def listed(self) -> tuple[ListedFile, ...]:
        self.listings += 1
        return tuple(file for file in super().listed() if file.path not in self.ignored)


class _Hub:
    """What one test's server runs on: the fakes, the factories' call counts and the log."""

    def __init__(self, **overrides: Any) -> None:
        self.checkout = _Checkout()
        self.index = InMemoryKnowledgeIndex()
        self.origin = FakeBrainOrigin()
        self.change_requests = InMemoryBrainChangeRequests(self.origin)
        self.log = io.StringIO()
        self.index_opens = 0
        self.checkout_opens = 0
        self.context = replace(
            HubContext(
                project="demo",
                hub_path=DEMO_HUB_PATH,
                repo_dirs=("demo-api",),
                version="9.8.7",
                proposal=ProposalFacts(
                    hub_repo=DEMO_HUB_REPO,
                    default_branch="main",
                    branch_prefix="demo/",
                    author=AUTHOR,
                ),
                session="s-123",
                checkout=self._open_checkout,
                index=self._open_index,
            ),
            **overrides,
        )

    def _open_checkout(self) -> HubCheckout:
        self.checkout_opens += 1
        return self.checkout

    def _open_index(self) -> KnowledgeIndex:
        self.index_opens += 1
        return self.index

    def run[T](self, calls: Callable[[Client], Awaitable[T]]) -> T:
        server = build_server(
            self.context, change_requests=self.change_requests, clock=lambda: NOW, log=self.log
        )

        async def session() -> T:
            async with Client(server) as client:
                return await calls(client)

        return anyio.run(session)


def _text(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def _structured(result: CallToolResult) -> dict[str, Any]:
    assert not result.is_error, _text(result)
    assert result.structured_content is not None
    assert json.loads(_text(result)) == result.structured_content
    return result.structured_content


def test_lists_three_tools_with_schemas_when_client_initializes() -> None:
    hub = _Hub()

    async def listing(client: Client) -> tuple[Any, Any]:
        return client.server_info, (await client.list_tools()).tools

    info, tools = hub.run(listing)

    assert (info.name, info.version) == ("hub", "9.8.7")
    by_name = {tool.name: tool for tool in tools}
    assert sorted(by_name) == ["propose", "read", "search"]
    search = by_name["search"].input_schema
    assert search["required"] == ["query"]
    query = search["properties"]["query"]
    assert (query["type"], query["minLength"], query["maxLength"]) == ("string", 1, 500)
    limit = search["properties"]["limit"]
    assert (limit["type"], limit["minimum"], limit["maximum"], limit["default"]) == (
        "integer",
        1,
        50,
        10,
    )
    assert _enum(search, "kind") == sorted(KINDS)
    read = by_name["read"].input_schema
    assert read["required"] == ["path"]
    assert read["properties"]["path"]["type"] == "string"
    propose = by_name["propose"].input_schema
    assert sorted(propose["required"]) == ["body", "external", "kind", "title"]
    assert _enum(propose, "kind") == sorted(PROPOSAL_KINDS)
    assert propose["properties"]["external"]["type"] == "boolean"
    assert by_name["search"].annotations.read_only_hint is True
    assert by_name["read"].annotations.read_only_hint is True
    proposing = by_name["propose"].annotations
    assert (
        proposing.read_only_hint,
        proposing.destructive_hint,
        proposing.open_world_hint,
    ) == (False, False, True)
    assert all(word in by_name["search"].description for word in ("500", "50", "10"))
    assert all(word in by_name["read"].description for word in ("1024", "256 KiB", "brain/"))
    assert all(word in by_name["propose"].description for word in ("120", "65,536", "_inbox"))


def _enum(schema: dict[str, Any], name: str) -> list[str]:
    """The values of the enum property ``name``, nullable or not, inline or a ``$defs`` entry."""
    prop = schema["properties"][name]
    options = [_resolved(schema, option) for option in prop.get("anyOf", [prop])]
    return sorted(value for option in options for value in option.get("enum", []))


def _resolved(schema: dict[str, Any], option: dict[str, Any]) -> dict[str, Any]:
    ref = option.get("$ref")
    if ref is None:
        return option
    found: dict[str, Any] = schema["$defs"][ref.removeprefix("#/$defs/")]
    return found


def _seed(checkout: FakeKnowledgeCheckout, count: int) -> None:
    for number in range(count):
        text = f"---\nstatus: active\n---\n# Note {number:02}\n\nWorktrees need a fresh fetch.\n"
        checkout.write(f"brain/learnings/note-{number:02}.md", text.encode())


def _call(name: str, arguments: dict[str, Any]) -> Callable[[Client], Awaitable[CallToolResult]]:
    async def calling(client: Client) -> CallToolResult:
        return await client.call_tool(name, arguments)

    return calling


def _calls(
    *calls: tuple[str, dict[str, Any]],
) -> Callable[[Client], Awaitable[list[CallToolResult]]]:
    async def calling(client: Client) -> list[CallToolResult]:
        return [await client.call_tool(name, arguments) for name, arguments in calls]

    return calling


def test_cuts_results_to_limit_when_more_match() -> None:
    hub = _Hub()
    _seed(hub.checkout, 60)

    default, widest = hub.run(
        _calls(("search", {"query": "worktrees"}), ("search", {"query": "worktrees", "limit": 50}))
    )

    found = _structured(default)
    assert sorted(found) == ["hub", "query", "results", "skipped", "sync", "warnings"]
    assert (found["hub"], found["query"]) == ("demo", "worktrees")
    assert len(found["results"]) == 10
    assert sorted(found["results"][0]) == [
        "kind",
        "path",
        "provenance",
        "snippet",
        "status",
        "title",
    ]
    assert found["results"][0]["path"] == "brain/learnings/note-00.md"
    assert (found["results"][0]["kind"], found["results"][0]["status"]) == ("learning", "active")
    assert found["sync"] == {"listed": 60, "read": 60, "indexed": 60, "dropped": 0}
    assert (found["skipped"], found["warnings"]) == ([], [])
    assert len(_structured(widest)["results"]) == 50


def test_opens_index_lazily_when_first_search_runs() -> None:
    hub = _Hub()
    _seed(hub.checkout, 1)
    hub.run(_call("read", {"path": "brain/learnings/note-00.md"}))
    assert hub.index_opens == 0

    first, second = hub.run(_calls(("search", {"query": "fetch"}), ("search", {"query": "fetch"})))

    assert [len(_structured(result)["results"]) for result in (first, second)] == [1, 1]
    assert hub.index_opens == 1


def test_opens_index_lazily_again_when_first_open_fails() -> None:
    hub = _Hub()
    _seed(hub.checkout, 1)
    failures = [AgentHubError("database is locked")]

    def flaky() -> KnowledgeIndex:
        if failures:
            raise failures.pop()
        return hub.index

    hub.context = replace(hub.context, index=flaky)

    failed, answered = hub.run(
        _calls(("search", {"query": "fetch"}), ("search", {"query": "fetch"}))
    )

    assert failed.is_error
    assert _text(failed) == "search: database is locked"
    assert len(_structured(answered)["results"]) == 1


def test_warns_when_fake_repo_not_checked_out() -> None:
    hub = _Hub()
    hub.checkout.missing = ("demo-web",)
    _seed(hub.checkout, 1)

    found = _structured(hub.run(_call("search", {"query": "fetch"})))

    assert found["warnings"] == ["demo-web: not checked out; its docs are not searched"]
    assert len(found["results"]) == 1


# A synthetic token the secret rules match, built at run time.
TOKEN = "ghp_" + "abcdefgh12345678" + "ABCDEFGH12345678" + "zz00"
DECISION = "---\nstatus: accepted\nprovenance: human\n---\n# Use worktrees\n\nAlways.\n"


def test_reads_metadata_and_reasons_when_fake_checkout_lists_file() -> None:
    hub = _Hub()
    checkout = hub.checkout
    checkout.write("brain/decisions/0001-worktrees.md", DECISION.encode())
    checkout.write("demo-api/docs/adr/0001-x.md", b"No heading here.\n")
    checkout.skip_when_listed("brain/link.md", THROUGH_LINK)
    checkout.write("brain/ignored.md", b"# Ignored\n")
    checkout.ignored.add("brain/ignored.md")
    checkout.answer_read("brain/linked/a.md", THROUGH_LINK)
    checkout.write("brain/pipe.md", b"")
    checkout.answer_read("brain/pipe.md", NOT_REGULAR)
    checkout.write("brain/big.md", b"a" * (MAX_DOCUMENT_BYTES + 1))
    checkout.write("brain/leak.md", f"# Leak\n\n{TOKEN}\n".encode())
    checkout.write("brain/limit.md", b"b" * MAX_DOCUMENT_BYTES)

    def reading(*paths: str) -> Callable[[Client], Awaitable[list[CallToolResult]]]:
        return _calls(*(("read", {"path": path}) for path in paths))

    refused = hub.run(reading("hub.json", "brain/auto/me.md"))
    assert [_text(result) for result in refused] == ["read: path not allowed"] * 2
    assert all(result.is_error for result in refused)
    assert (hub.checkout_opens, checkout.listings, checkout.reads) == (0, 0, [])

    decision, doc, at_limit = hub.run(
        reading(
            "brain/decisions/0001-worktrees.md", "demo-api/docs/adr/0001-x.md", "brain/limit.md"
        )
    )
    assert _structured(decision) == {
        "path": "brain/decisions/0001-worktrees.md",
        "kind": "decision",
        "title": "Use worktrees",
        "status": "accepted",
        "provenance": "human",
        "text": DECISION,
    }
    assert _structured(doc) == {
        "path": "demo-api/docs/adr/0001-x.md",
        "kind": "adr",
        "title": "0001-x.md",
        "status": None,
        "provenance": None,
        "text": "No heading here.\n",
    }
    assert len(_structured(at_limit)["text"]) == MAX_DOCUMENT_BYTES

    paths = (
        "brain/link.md",
        "brain/ignored.md",
        "brain/linked/a.md",
        "brain/missing.md",
        "brain/pipe.md",
        "brain/big.md",
        "brain/leak.md",
    )
    answers = hub.run(reading(*paths))
    assert all(result.is_error for result in answers)
    assert [_text(result) for result in answers] == [
        f"read: {THROUGH_LINK}",
        "read: not tracked or ignored by git",
        f"read: {THROUGH_LINK}",
        "read: not found",
        f"read: {NOT_REGULAR}",
        f"read: {TOO_LARGE}",
        f"read: {RULE_MATCH}",
    ]
    assert hub.index_opens == 0


BODY = "Fetch origin before creating a worktree.\n\nOtherwise it starts from a stale main."


def _proposal(**overrides: Any) -> dict[str, Any]:
    return {
        "title": "Worktrees need a fresh fetch",
        "body": BODY,
        "kind": "playbook",
        "external": False,
    } | overrides


def test_refuses_secret_before_port_when_text_matches() -> None:
    hub = _Hub()

    in_body, in_title = hub.run(
        _calls(
            ("propose", _proposal(body=f"The key is {TOKEN} for now.")),
            ("propose", _proposal(title=f"Rotate {TOKEN}")),
        )
    )

    for result in (in_body, in_title):
        assert result.is_error
        assert _text(result) == "propose: the text matches a secret rule"
        assert TOKEN not in _text(result)
    assert hub.change_requests.calls == []


def test_returns_pull_request_when_port_accepts() -> None:
    hub = _Hub()

    found = _structured(hub.run(_call("propose", _proposal())))

    note = "_inbox/2026-10-21-worktrees-need-a-fresh-fetch.md"
    branch = "demo/learning-propose-worktrees-need-a-fresh-fetch"
    assert found == {
        "pr_url": f"https://github.com/{DEMO_HUB_REPO}/pull/1",
        "branch": branch,
        "path": f"brain/{note}",
    }
    [proposal] = hub.change_requests.calls
    assert isinstance(proposal, BrainProposal)
    assert (proposal.hub_path, proposal.hub_repo, proposal.default_branch) == (
        DEMO_HUB_PATH,
        DEMO_HUB_REPO,
        "main",
    )
    assert (proposal.branch, proposal.note, proposal.author) == (branch, note, AUTHOR)
    assert proposal.text == (
        "---\ntype: learning-proposal\nstatus: proposed\nprovenance: agent\n"
        "target: brain/playbooks/\ncreated: 2026-10-21\nsession: s-123\n---\n\n"
        f"# Worktrees need a fresh fetch\n\n{BODY}\n"
    )
    assert proposal.title == "Learning proposal: Worktrees need a fresh fetch"
    assert proposal.body == pull_request_body(note=note, body=BODY, external=False, session="s-123")
    assert proposal.commit_message == "docs(brain): propose learning worktrees-need-a-fresh-fetch"
    [pull] = hub.origin.pull_requests()
    assert (pull.head, pull.base) == (branch, "main")


class _TimedOut(InMemoryBrainChangeRequests):
    def propose(self, proposal: BrainProposal) -> ChangeRequestResult:
        self.calls.append(proposal)
        raise ChangeRequestTimeoutError


class _Refused(InMemoryBrainChangeRequests):
    def propose(self, proposal: BrainProposal) -> ChangeRequestResult:
        self.calls.append(proposal)
        raise RefspecRefusedError("Branch outside the learning names: demo/x")


def test_maps_failed_step_when_port_fails() -> None:
    def answer(hub: _Hub) -> str:
        result = hub.run(_call("propose", _proposal()))
        assert result.is_error
        return _text(result)

    failing = _Hub()
    failing.change_requests.fail_step = "push"
    assert answer(failing) == "propose: could not push (step failed)"
    timed_out = _Hub()
    timed_out.change_requests = _TimedOut(timed_out.origin)
    assert answer(timed_out) == "propose: could not open the pull request (timed out)"
    refused = _Hub()
    refused.change_requests = _Refused(refused.origin)
    assert answer(refused) == "propose: Branch outside the learning names: demo/x"
    unavailable = _Hub()
    unavailable.change_requests.unavailable = "Hub is read-only here"
    assert answer(unavailable) == "propose: Hub is read-only here"
    twice = _Hub()
    first = twice.run(_call("propose", _proposal()))
    assert not first.is_error
    assert answer(twice) == (
        "propose: branch exists: demo/learning-propose-worktrees-need-a-fresh-fetch"
    )
    assert len(twice.origin.pull_requests()) == 1
    authorless = _Hub()
    authorless.context = replace(
        authorless.context, proposal=replace(authorless.context.proposal, author=None)
    )
    assert answer(authorless) == "propose: the hub has no author"
    assert authorless.change_requests.calls == []


def test_refuses_input_before_port_when_out_of_bounds() -> None:
    hub = _Hub()

    answers = hub.run(
        _calls(
            ("propose", _proposal(title="  ")),
            ("propose", _proposal(title="a" * 121)),
            ("propose", _proposal(title="one\ntwo")),
            ("propose", _proposal(title="!!!")),
            ("propose", _proposal(body="")),
            ("propose", _proposal(kind="adr")),
        )
    )

    assert all(result.is_error for result in answers)
    texts = [_text(result) for result in answers]
    assert texts[:5] == [
        "propose: the title is empty",
        "propose: the title is longer than 120 characters",
        "propose: the title must be one line with no control characters",
        "propose: the title has no letters or digits for a file name",
        "propose: the body is empty",
    ]
    assert texts[5] == "propose: invalid arguments (kind)"
    assert hub.change_requests.calls == []


def test_answers_field_names_only_when_schema_rejects_arguments() -> None:
    hub = _Hub()
    title, body, query = "Quokkamarker title", "Wombatmarker body", "zebracornmarker" * 34
    no_external = {"title": title, "body": body, "kind": "playbook"}

    answers = hub.run(
        _calls(
            ("propose", no_external),
            ("propose", {"title": title}),
            ("search", {"query": query}),
            ("read", {"path": 42}),
            ("read", {}),
            ("search", {"query": "fetch"}),
        )
    )

    assert [result.is_error for result in answers] == [True] * 5 + [False]
    assert [_text(result) for result in answers[:5]] == [
        "propose: invalid arguments (external)",
        "propose: invalid arguments (body, external, kind)",
        "search: invalid arguments (query)",
        "read: invalid arguments (path)",
        "read: invalid arguments (path)",
    ]
    dumped = "\n".join(result.model_dump_json() for result in answers[:5])
    assert not any(marker in dumped for marker in ("Quokkamarker", "Wombatmarker", "zebracorn"))
    assert "Error executing" not in dumped
    assert hub.change_requests.calls == []


def test_logs_error_line_when_schema_rejects_call() -> None:
    hub = _Hub()

    hub.run(
        _calls(
            ("propose", {"title": "Quokkamarker title", "body": "Wombatmarker body"}),
            ("read", {"path": 42}),
        )
    )

    log = hub.log.getvalue()
    assert [re.sub(r"\d+ms$", "<n>ms", line) for line in log.splitlines()] == [
        "hub mcp: propose error <n>ms",
        "hub mcp: read error <n>ms",
    ]
    assert "marker" not in log


def test_returns_one_line_error_when_tool_refuses() -> None:
    hub = _Hub()

    result = hub.run(_call("search", {"query": "!!!"}))

    assert result.is_error
    assert _text(result) == "search: the query has no words"
    assert hub.checkout_opens == 0


class _Exploding(_Checkout):
    def __init__(self) -> None:
        super().__init__()
        self.explode = True

    def listed(self) -> tuple[ListedFile, ...]:
        if self.explode:
            self.explode = False
            raise RuntimeError("secret-ish")
        return super().listed()


def test_returns_internal_error_when_tool_raises_unexpectedly() -> None:
    hub = _Hub()
    hub.checkout = _Exploding()
    _seed(hub.checkout, 1)

    failed, answered = hub.run(
        _calls(("search", {"query": "fetch"}), ("search", {"query": "fetch"}))
    )

    assert failed.is_error
    assert _text(failed) == "search: internal error (RuntimeError)"
    assert "secret-ish" not in failed.model_dump_json()
    log = hub.log.getvalue()
    assert "Traceback" in log
    assert "RuntimeError: secret-ish" in log
    assert len(_structured(answered)["results"]) == 1


def test_logs_one_line_per_call_when_tools_called() -> None:
    hub = _Hub()
    hub.checkout.write("brain/now.md", b"# Now\n\nFocus on worktrees.\n")
    secret_words = ("zebracorn", "brain/now.md", "Quokka title", "Wombat body")

    hub.run(
        _calls(
            ("search", {"query": "zebracorn"}),
            ("read", {"path": "brain/now.md"}),
            ("read", {"path": "hub.json"}),
            ("propose", _proposal(title="Quokka title", body="Wombat body")),
        )
    )

    lines = hub.log.getvalue().splitlines()
    assert [re.sub(r"\d+ms$", "<n>ms", line) for line in lines] == [
        "hub mcp: search ok <n>ms",
        "hub mcp: read ok <n>ms",
        "hub mcp: read error <n>ms",
        "hub mcp: propose ok <n>ms",
    ]
    assert not any(word in "\n".join(lines) for word in secret_words)


def test_serializes_calls_when_client_sends_them_together() -> None:
    # A handshake, not a timed wait: the first read holds on until another read enters (bounded),
    # and any later read sets ``entered``. With the lock, no read enters while the first is held.
    entered = threading.Event()
    starts: list[str] = []
    overlapped: list[bool] = []
    guard = threading.Lock()

    def before_read(path: str) -> None:
        with guard:
            starts.append(path)
            is_first = len(starts) == 1
        if not is_first:
            entered.set()
            return
        overlapped.append(entered.wait(timeout=2))

    hub = _Hub()
    hub.checkout = _Checkout(before_read=before_read)
    hub.checkout.write("brain/now.md", b"# Now\n")

    async def together(client: Client) -> list[CallToolResult]:
        results: list[CallToolResult] = []

        async def one() -> None:
            results.append(await client.call_tool("read", {"path": "brain/now.md"}))

        async with anyio.create_task_group() as group:
            for _ in range(3):
                group.start_soon(one)
        return results

    results = hub.run(together)

    assert [result.is_error for result in results] == [False] * 3
    assert overlapped == [False]
    assert len(starts) == 3
