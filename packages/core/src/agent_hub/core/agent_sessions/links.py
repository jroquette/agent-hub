"""The link from a hook-observed Session to the agent session driving it (P13).

``AgentSessionLinks`` (LK) implements ``AgentSessionLinkLookup`` from the live index and the
store; the session read models take it to fill ``Session.agent_session_id`` and to show a live
tile ``waiting`` while a permission request is open (AC-165.25).
"""

from collections.abc import Callable
from typing import Protocol

from agent_hub.core.readmodels.view_types import ViewModel


class AgentSessionLink(ViewModel):
    """The agent session driving a Claude session, and whether it waits on a permission."""

    agent_session_id: str
    waiting: bool = False


class AgentSessionLinkLookup(Protocol):
    """Finds the agent session of a Claude session."""

    def link_of(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The link of ``claude_session_id`` in ``project``, or None."""
        ...


class AgentSessionStoreLinks(Protocol):
    """The store's half of a link: the newest agent session driving a Claude session."""

    def link_of(self, project: str, claude_session_id: str) -> str | None:
        """The agent session's id, or None."""
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

    def link_of(self, project: str, claude_session_id: str) -> AgentSessionLink | None:
        """The link of ``claude_session_id`` in ``project``, or None."""
        live = self._live_link(project, claude_session_id)
        if live is not None:
            return live
        found = self._store.link_of(project, claude_session_id)
        return None if found is None else AgentSessionLink(agent_session_id=found)
