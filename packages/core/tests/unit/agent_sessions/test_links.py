from collections.abc import Callable, Collection, Mapping

import pytest

from agent_hub.core.agent_sessions.agent_session import AgentSessionStatus
from agent_hub.core.agent_sessions.driver import PermissionRequest
from agent_hub.core.agent_sessions.links import AgentSessionLink, AgentSessionLinks, prompt_issue
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.testing.agent_session_rig import Rig
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.read_model_builders import a_log_record, an_agent_session

pytestmark = pytest.mark.anyio

CLAUDE_ID = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"


class CountingStore(InMemoryAgentSessionStore):
    """The in-memory store, keeping the ids each batch read of the links asks for."""

    def __init__(self) -> None:
        super().__init__()
        self.links_asked: list[frozenset[str]] = []
        self.records_asked: list[frozenset[str]] = []

    def links_of(self, project: str, claude_session_ids: Collection[str]) -> Mapping[str, str]:
        ids = tuple(claude_session_ids)
        self.links_asked.append(frozenset(ids))
        return super().links_of(project, ids)

    def first_records(
        self, agent_session_ids: Collection[str], *, kinds: Collection[RecordKind]
    ) -> Mapping[str, LogRecord]:
        ids = tuple(agent_session_ids)
        self.records_asked.append(frozenset(ids))
        return super().first_records(ids, kinds=kinds)


def _store_session(
    store: InMemoryAgentSessionStore,
    agent_session_id: str,
    claude_id: str,
    *,
    prompt: str | None = None,
) -> None:
    """An ended agent session driving ``claude_id``, with ``prompt`` as its first message."""
    store.create(
        an_agent_session(
            id=agent_session_id,
            claude_session_id=claude_id,
            status=AgentSessionStatus.ENDED,
            last_seq=0,
        )
    )
    if prompt is not None:
        store.append(agent_session_id, [a_log_record("user.message", seq=1, body={"text": prompt})])


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


@pytest.mark.parametrize(
    ("text", "issue"),
    [
        ("/feature AGH-305\n\nI am the owner…", "AGH-305"),
        # hub web's Start (AGH-579): the one session that conducts the ticket is listed under it.
        ("/implement DEMO-1234\n\nI am the owner of the agent-hub project", "DEMO-1234"),
        ("  /hub:feature agh-7 and more", "AGH-7"),
        ("/feature", None),
        ("Fix AGH-305 please", None),
        ("/feature AGH-0", None),
        (None, None),
    ],
)
def test_reads_issue_when_first_prompt_names_one(text: str | None, issue: str | None) -> None:
    assert prompt_issue(text) == issue


def test_carries_prompt_issue_when_first_prompt_names_ticket() -> None:
    store = InMemoryAgentSessionStore()
    session_id = "01929a4e-0000-7000-8000-00000000a002"
    store.create(an_agent_session(id=session_id, claude_session_id=CLAUDE_ID, last_seq=0))
    links = AgentSessionLinks(lambda project, claude_id: None, store)
    before = links.link_of("demo", CLAUDE_ID)
    store.append(
        session_id,
        [
            a_log_record("user.message", seq=1, body={"text": "/feature DEM-305\n\nContext."}),
            a_log_record("user.message", seq=2, body={"text": "/feature DEM-9"}),
        ],
    )

    assert before == AgentSessionLink(agent_session_id=session_id)
    assert links.link_of("demo", CLAUDE_ID) == AgentSessionLink(
        agent_session_id=session_id, prompt_issue="DEM-305"
    )


def test_asks_store_once_when_links_of_many_sessions_read() -> None:
    store = CountingStore()
    claude_ids = [f"aaaaaaaa-bbbb-4ccc-8ddd-{number:012d}" for number in range(50)]
    expected: dict[str, AgentSessionLink] = {}
    for number, claude_id in enumerate(claude_ids):
        agent_session_id = f"01929a4e-0000-7000-8000-{number:012d}"
        issue = f"DEM-{number + 1}" if number % 2 == 0 else None
        prompt = None if issue is None else f"/feature {issue}"
        _store_session(store, agent_session_id, claude_id, prompt=prompt)
        expected[claude_id] = AgentSessionLink(
            agent_session_id=agent_session_id, prompt_issue=issue
        )
    links = AgentSessionLinks(lambda project, claude_id: None, store)

    found = links.links_of("demo", [*claude_ids, "unknown"])

    assert found == expected
    assert store.links_asked == [frozenset({*claude_ids, "unknown"})]
    assert store.records_asked == [frozenset(link.agent_session_id for link in expected.values())]


async def test_prefers_live_link_when_links_of_includes_live_session(
    make_rig: Callable[..., Rig],
) -> None:
    ask = PermissionRequest(request_id="req-1", tool="Bash", input={"command": "ls"})
    rig = make_rig(replies={"Ask.": (ask,)})
    stored_id = "01929a4e-0000-7000-8000-00000000a003"
    _store_session(rig.store, stored_id, CLAUDE_ID)
    created = await rig.create("Ask.")
    links = AgentSessionLinks(rig.control.live_link, rig.store)
    claude_id = created.claude_session_id
    assert claude_id is not None
    assert claude_id != CLAUDE_ID

    await rig.until_status(created.id, "waiting_permission")
    found = links.links_of("demo", [claude_id, CLAUDE_ID, "unknown"])

    assert found == {
        claude_id: AgentSessionLink(agent_session_id=created.id, waiting=True),
        CLAUDE_ID: AgentSessionLink(agent_session_id=stored_id),
    }


def test_asks_again_in_one_batch_when_stored_link_has_no_prompt() -> None:
    store = CountingStore()
    prompted = "01929a4e-0000-7000-8000-00000000a004"
    silent = "01929a4e-0000-7000-8000-00000000a005"
    silent_claude_id = "aaaaaaaa-bbbb-4ccc-8ddd-000000000005"
    _store_session(store, prompted, CLAUDE_ID, prompt="/feature DEM-305")
    _store_session(store, silent, silent_claude_id)
    links = AgentSessionLinks(lambda project, claude_id: None, store)
    first = links.links_of("demo", [CLAUDE_ID, silent_claude_id])
    store.append(silent, [a_log_record("user.message", seq=1, body={"text": "/feature DEM-9"})])

    again = links.links_of("demo", [CLAUDE_ID, silent_claude_id])

    assert store.records_asked == [frozenset({prompted, silent}), frozenset({silent})]
    assert first == {
        CLAUDE_ID: AgentSessionLink(agent_session_id=prompted, prompt_issue="DEM-305"),
        silent_claude_id: AgentSessionLink(agent_session_id=silent),
    }
    assert again == {
        CLAUDE_ID: AgentSessionLink(agent_session_id=prompted, prompt_issue="DEM-305"),
        silent_claude_id: AgentSessionLink(agent_session_id=silent, prompt_issue="DEM-9"),
    }


def test_reads_cached_prompt_issue_when_links_read_again() -> None:
    store = CountingStore()
    named = "01929a4e-0000-7000-8000-00000000a006"
    plain = "01929a4e-0000-7000-8000-00000000a007"
    plain_claude_id = "aaaaaaaa-bbbb-4ccc-8ddd-000000000007"
    _store_session(store, named, CLAUDE_ID, prompt="/feature DEM-305")
    _store_session(store, plain, plain_claude_id, prompt="Look at the export.")
    links = AgentSessionLinks(lambda project, claude_id: None, store)
    first = links.links_of("demo", [CLAUDE_ID, plain_claude_id])

    again = links.links_of("demo", [CLAUDE_ID, plain_claude_id])

    expected = {
        CLAUDE_ID: AgentSessionLink(agent_session_id=named, prompt_issue="DEM-305"),
        plain_claude_id: AgentSessionLink(agent_session_id=plain),
    }
    assert store.records_asked == [frozenset({named, plain})]
    assert first == expected
    assert again == expected
