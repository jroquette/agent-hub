from collections.abc import Callable

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus
from agent_hub.core.agent_sessions.driver import PermissionRequest
from agent_hub.core.agent_sessions.links import AgentSessionLink, AgentSessionLinks
from agent_hub.core.testing.agent_session_rig import Rig
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.read_model_builders import an_agent_session

pytestmark = pytest.mark.anyio

CLAUDE_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


def test_finds_stored_session_when_not_live() -> None:
    store = InMemoryAgentSessionStore()
    store.create(
        an_agent_session(
            id="01929a4e-0000-7000-8000-00000000a001",
            claude_session_id=CLAUDE_ID,
            status=AgentSessionStatus.ENDED,
            last_seq=0,
        )
    )
    links = AgentSessionLinks(lambda project, session_id: None, store)

    assert links.link_of("demo", CLAUDE_ID) == AgentSessionLink(
        agent_session_id="01929a4e-0000-7000-8000-00000000a001"
    )
    assert links.link_of("other", CLAUDE_ID) is None
    assert links.link_of("demo", "unknown") is None


async def test_prefers_live_link_and_shows_waiting_when_permission_pending(
    make_rig: Callable[..., Rig],
) -> None:
    ask = PermissionRequest(request_id="req-1", tool="Bash", input={"command": "ls"})
    rig = make_rig(replies={"Ask.": (ask,)})
    created = await rig.create("Ask.")
    links = AgentSessionLinks(rig.control.live_link, rig.store)
    claude_id = created.claude_session_id
    assert claude_id is not None

    await rig.until_status(created.id, "waiting_permission")
    waiting = links.link_of("demo", claude_id)
    await rig.control.close(created.id)

    assert waiting == AgentSessionLink(agent_session_id=created.id, waiting=True)
    assert links.link_of("demo", claude_id) == AgentSessionLink(agent_session_id=created.id)
