"""The link from a hook-observed Session to the agent session driving it (P13).

``AgentSessionLinks`` (LK) implements ``AgentSessionLinkLookup`` from the live index and the
store; the session read models take it to fill ``Session.agent_session_id`` and to show a live
tile ``waiting`` while a permission request is open (AC-165.25).
"""

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
