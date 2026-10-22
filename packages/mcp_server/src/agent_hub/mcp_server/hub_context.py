"""What ``hub mcp``'s tools are given about the hub, and how a tool refuses a call.

``cli``'s ``mcp_command`` resolves the hub once, as ``hub search`` does (O-1: nothing moves out
of ``cli``), and hands it here as a ``HubContext``: the hub's facts, and two factories that
build the checkout and open the knowledge index when a tool needs them.
"""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from agent_hub.core.errors import AgentHubError
from agent_hub.core.knowledge.knowledge_index import KnowledgeIndex
from agent_hub.core.knowledge.sync_knowledge import KnowledgeCheckout
from agent_hub.core.learnings.brain_change_requests import CommitAuthor


class ToolRefusal(AgentHubError):  # noqa: N818 - a tool's answer, read as "the tool refused"
    """A tool call refused before or while it ran; ``line`` is the one-line tool error the
    caller sees (``<tool>: <reason>``), never holding the caller's text or a match."""

    def __init__(self, line: str) -> None:
        self.line = line
        super().__init__(line)


class HubCheckout(KnowledgeCheckout, Protocol):
    """The hub's checkout as the index sees it, plus the ``repos[].dir`` folders that are not
    checked out beside the hub (``search`` warns about them)."""

    def not_checked_out(self) -> tuple[str, ...]:
        """The repo folders of ``hub.json`` that do not exist beside the hub, in its order."""
        ...


@dataclass(frozen=True, kw_only=True)
class ProposalFacts:
    """What ``propose`` needs of the hub: its GitHub repo and default branch, the developer's
    branch prefix (``""`` when none) and the effective author (None when no source sets one)."""

    hub_repo: str
    default_branch: str
    branch_prefix: str
    author: CommitAuthor | None


@dataclass(frozen=True, kw_only=True)
class HubContext:
    """The hub ``hub mcp`` serves, resolved once at start.

    ``hub_path`` is the real path of the hub's main checkout: the index's key for the hub and the
    checkout a proposal is made from. ``session`` is ``CLAUDE_CODE_SESSION_ID`` as found (checked
    when a note is written). ``checkout`` builds the checkout for one call (raising
    ``KnowledgeCheckoutError`` when git cannot be found); ``index`` opens the knowledge index
    (raising an ``AgentHubError`` when it cannot), called on the first ``search`` only.
    """

    project: str
    hub_path: str
    repo_dirs: tuple[str, ...]
    version: str
    proposal: ProposalFacts
    session: str | None
    checkout: Callable[[], HubCheckout]
    index: Callable[[], KnowledgeIndex]
