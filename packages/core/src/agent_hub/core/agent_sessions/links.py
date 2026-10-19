"""The link from a hook-observed Session to the agent session driving it (P13).

``AgentSessionLinks`` (LK) implements ``AgentSessionLinkLookup`` from the live index and the
store; the session read models take it to fill ``Session.agent_session_id`` and to show a live
tile ``waiting`` while a permission request is open (AC-165.25). The other way round,
``ObservedSessionLookup`` tells the agent-session use case whether a Claude session has an
observed twin, to fill ``AgentSession.observed_session_id`` (D2).
"""

import re
from collections.abc import Callable, Collection, Iterable
from typing import Final, Protocol

from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.readmodels.view_types import ViewModel

# The first prompt's slash command and the issue it names: ``/feature AGH-305`` (the Start of a
# ticket, the hub's ``/feature <ISSUE>``); the issue's team is checked later against the hub's.
_PROMPT_ISSUE: Final = re.compile(r"\s*/[\w:-]+\s+([A-Za-z][A-Za-z0-9]{0,9}-[1-9][0-9]{0,8})\b")
_PROMPT_KINDS: Final[frozenset[RecordKind]] = frozenset({"user.message"})


def prompt_issue(text: object) -> str | None:
    """The issue id (uppercased) a prompt opening with ``/<command> <ISSUE>`` names, or None."""
    if not isinstance(text, str):
        return None
    found = _PROMPT_ISSUE.match(text)
    return None if found is None else found.group(1).upper()


class AgentSessionLink(ViewModel):
    """The agent session driving a Claude session, and whether it waits on a permission."""

    agent_session_id: str
    waiting: bool = False
    # The issue the session's first prompt names (``/feature AGH-305``), not yet checked
    # against the hub's tracker teams: what a session started from a ticket is about, over
    # what its branch or worktree names.
    prompt_issue: str | None = None


class AgentSessionLinkLookup(Protocol):
    """Finds the agent session of a Claude session."""

    def link_of(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The link of ``claude_session_id`` in ``project``, or None."""
        ...


class ObservedSessionLookup(Protocol):
    """Which Claude sessions the hooks or transcripts observed (the session read models)."""

    def observed(self, pairs: Iterable[tuple[str, str]]) -> frozenset[tuple[str, str]]:
        """The ``(project, session_id)`` pairs of ``pairs`` that are observed sessions, all
        answered from one snapshot of the events."""
        ...


class AgentSessionStoreLinks(Protocol):
    """The store's half of a link: the newest agent session driving a Claude session."""

    def link_of(self, project: str, claude_session_id: str) -> str | None:
        """The agent session's id, or None."""
        ...

    def records(
        self,
        agent_session_id: str,
        *,
        after: int = 0,
        limit: int = 200,
        kinds: Collection[RecordKind] | None = None,
    ) -> tuple[LogRecord, ...]:
        """The session's records after ``after``, in order (the first prompt, here)."""
        ...


class AgentSessionLinks:
    """``AgentSessionLinkLookup`` over the live sessions first (they know whether a
    permission request is open), then the store (an ended session still links, never
    waiting). ``live_link`` is ``AgentSessionControl.live_link``."""

    def __init__(
        self,
        live_link: Callable[[str, str], AgentSessionLink | None],
        store: AgentSessionStoreLinks,
    ) -> None:
        self._live_link = live_link
        self._store = store
        # The first prompt never changes once stored, so its issue is read once per session.
        self._prompt_issues: dict[str, str | None] = {}

    def link_of(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The link of ``claude_session_id`` in ``project``, or None."""
        live = self._live_link(project, claude_session_id)
        if live is None:
            found = self._store.link_of(project, claude_session_id)
            if found is None:
                return None
            live = AgentSessionLink(agent_session_id=found)
        issue = self._prompt_issue(live.agent_session_id)
        return live if issue is None else live.model_copy(update={"prompt_issue": issue})

    def _prompt_issue(self, agent_session_id: str) -> str | None:
        if agent_session_id in self._prompt_issues:
            return self._prompt_issues[agent_session_id]
        first = self._store.records(agent_session_id, limit=1, kinds=_PROMPT_KINDS)
        if not first:
            return None  # no prompt stored yet: asked again on the next read
        issue = prompt_issue(first[0].body.get("text"))
        self._prompt_issues[agent_session_id] = issue
        return issue
