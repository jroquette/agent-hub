"""``hub mcp``'s ``search`` and ``read`` tools (spec D-search, D-search-sync, D-read, D-db).

``search`` runs AGH-391's ``search_knowledge`` on the hub, as ``hub search`` does, and answers
``hub search --json``'s object plus ``warnings``. The knowledge index is opened on the first
``search`` and kept; an open that fails is tried again by the next ``search``, and ``read`` never
opens it. Every failure is a ``ToolRefusal`` with ``<tool>: <reason>``.
"""

from typing import Final

from agent_hub.core.errors import AgentHubError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.knowledge.document_rules import UNREADABLE, document_from
from agent_hub.core.knowledge.knowledge_index import Kind, KnowledgeIndex, SkippedFile
from agent_hub.core.knowledge.search_query import query_words
from agent_hub.core.knowledge.sync_knowledge import SearchOutcome, search_knowledge
from agent_hub.mcp_server.hub_context import HubContext, ToolRefusal
from agent_hub.mcp_server.read_path import refusal

NO_WORDS: Final = "search: the query has no words"
# Why ``read`` refuses a path that is not a file of the listing (D-read).
NOT_FOUND: Final = "not found"
NOT_LISTED: Final = "not tracked or ignored by git"


class KnowledgeTools:
    """The ``search`` and ``read`` tools over ``hub``; one caller at a time (the server's lock)."""

    def __init__(self, hub: HubContext) -> None:
        self._hub = hub
        self._index: KnowledgeIndex | None = None

    def search(self, query: str, *, kind: Kind | None, limit: int) -> dict[str, JsonValue]:
        """The hub's documents holding every word of ``query`` (of ``kind`` when given), at most
        ``limit``, after the index is brought up to date with the checkout."""
        words = query_words(query)
        if not words:
            raise ToolRefusal(NO_WORDS)
        try:
            checkout = self._hub.checkout()
            index = self._opened_index()
            outcome = search_knowledge(
                index,
                checkout,
                self._hub.hub_path,
                words=words,
                kinds=() if kind is None else (kind,),
            )
            missing = checkout.not_checked_out()
        except AgentHubError as error:
            raise ToolRefusal(f"search: {error}") from None
        found = _outcome_json(self._hub.project, query, outcome, limit=limit)
        found["warnings"] = [
            f"{name}: not checked out; its docs are not searched" for name in missing
        ]
        return found

    def read(self, path: str) -> dict[str, JsonValue]:
        """The file at ``path`` with its kind and metadata, under the index's own rules: the path
        is allowed (``read_path``), git lists the file, and it reads as a document the index
        would keep (no link, regular, size, UTF-8, no secret)."""
        refused = refusal(path, self._hub.repo_dirs)
        if refused is not None:
            raise ToolRefusal(f"read: {refused}")
        try:
            checkout = self._hub.checkout()
            listed = {file.path: file for file in checkout.listed()}
        except AgentHubError as error:
            raise ToolRefusal(f"read: {error}") from None
        entry = listed.get(path)
        if entry is None:
            # Not listed: name why when the walk can (a link on a folder, a FIFO), else git's.
            raise ToolRefusal(f"read: {_unlisted_reason(checkout.read(path))}")
        if entry.skip_reason is not None or entry.fingerprint is None:
            raise ToolRefusal(f"read: {entry.skip_reason or UNREADABLE}")
        data = checkout.read(path)
        if not isinstance(data, bytes):
            raise ToolRefusal(f"read: {NOT_FOUND if data is None else data}")
        document = document_from(path, data, entry.fingerprint)
        if isinstance(document, SkippedFile):
            raise ToolRefusal(f"read: {document.reason}")
        return {
            "path": document.path,
            "kind": document.kind,
            "title": document.title,
            "status": document.status,
            "provenance": document.provenance,
            "text": data.decode("utf-8"),
        }

    def _opened_index(self) -> KnowledgeIndex:
        if self._index is None:
            self._index = self._hub.index()
        return self._index


def _unlisted_reason(content: bytes | str | None) -> str:
    if content is None:
        return NOT_FOUND
    if isinstance(content, str):
        return content
    return NOT_LISTED


def _outcome_json(
    project: str, query: str, outcome: SearchOutcome, *, limit: int
) -> dict[str, JsonValue]:
    """``hub search --json``'s object (its ``_outcome_json``), the results cut to ``limit``."""
    report = outcome.report
    return {
        "hub": project,
        "query": query,
        "results": [
            {
                "path": hit.path,
                "kind": hit.kind,
                "title": hit.title,
                "status": hit.status,
                "provenance": hit.provenance,
                "snippet": hit.snippet,
            }
            for hit in outcome.results[:limit]
        ],
        "sync": {
            "listed": report.listed,
            "read": report.read,
            "indexed": report.indexed,
            "dropped": report.dropped,
        },
        "skipped": [{"path": file.path, "reason": file.reason} for file in report.skipped],
    }
