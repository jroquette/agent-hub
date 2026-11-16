"""The link from a hook-observed Session to the agent session driving it (P13).

``AgentSessionLinks`` (LK) implements ``AgentSessionLinkLookup`` from the live index and the
store; the session read models take its ``links_of``, once per project per read, to fill
``Session.agent_session_id`` and to show a live tile ``waiting`` while a permission request is
open (AC-165.25). The other way round, ``ObservedSessionLookup`` tells the agent-session use
case whether a Claude session has an observed twin, to fill ``AgentSession.observed_session_id``
(D2).
"""

import re
from collections.abc import Callable, Collection, Iterable, Mapping
from typing import Final, Protocol

from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.readmodels.view_types import ViewModel

# The first prompt's slash command and the issue it names: ``/implement AGH-305`` (the Start of a
# ticket, the hub's ``/implement <ISSUE>``; ``/feature <ISSUE>`` too); the issue's team is checked
# later against the hub's.
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
    """The store's half of the links: the newest agent session driving each Claude session,
    and the agent sessions' first prompts."""

    def links_of(self, project: str, claude_session_ids: Collection[str]) -> Mapping[str, str]:
        """The agent session's id of each Claude session that has one."""
        ...

    def first_records(
        self, agent_session_ids: Collection[str], *, kinds: Collection[RecordKind]
    ) -> Mapping[str, LogRecord]:
        """Each session's first record of ``kinds`` (the first prompt, here)."""
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
        # The first prompt never changes once stored, so its issue is read once per session; a
        # session with no prompt stored yet is asked again, in the next read's one batch.
        self._prompt_issues: dict[str, str | None] = {}

    def link_of(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The link of ``claude_session_id`` in ``project``, or None."""
        return self.links_of(project, (claude_session_id,)).get(claude_session_id)

    def links_of(
        self, project: str, claude_session_ids: Collection[str]
    ) -> dict[str, AgentSessionLink]:
        """The link of each of ``claude_session_ids`` in ``project`` that has one: the live
        sessions first, then one store read for the others, then one read of the first prompts
        whose issue is not known yet."""
        links: dict[str, AgentSessionLink] = {}
        rest: list[str] = []
        for claude_session_id in claude_session_ids:
            live = self._live_link(project, claude_session_id)
            if live is None:
                rest.append(claude_session_id)
            else:
                links[claude_session_id] = live
        if rest:
            stored = self._store.links_of(project, rest)
            links |= {
                claude_session_id: AgentSessionLink(agent_session_id=agent_session_id)
                for claude_session_id, agent_session_id in stored.items()
            }
        self._read_prompt_issues(link.agent_session_id for link in links.values())
        return {
            claude_session_id: self._with_issue(link) for claude_session_id, link in links.items()
        }

    def _read_prompt_issues(self, agent_session_ids: Iterable[str]) -> None:
        unread = {
            agent_session_id
            for agent_session_id in agent_session_ids
            if agent_session_id not in self._prompt_issues
        }
        if not unread:
            return
        first = self._store.first_records(unread, kinds=_PROMPT_KINDS)
        for agent_session_id, record in first.items():
            self._prompt_issues[agent_session_id] = prompt_issue(record.body.get("text"))

    def _with_issue(self, link: AgentSessionLink) -> AgentSessionLink:
        issue = self._prompt_issues.get(link.agent_session_id)
        return link if issue is None else link.model_copy(update={"prompt_issue": issue})
