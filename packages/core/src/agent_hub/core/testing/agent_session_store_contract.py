"""The ``AgentSessionStore`` contract suite: the in-memory fake and the SQLite store honour it.

An implementation's ``tests/contract/`` provides an ``agent_session_store`` fixture (an empty
store) and declares ``class Test<Implementation>(AgentSessionStoreContract)``. Checks raise
``AssertionError`` by hand: core ships this suite without depending on pytest.
"""

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionStatus,
    EndReason,
)
from agent_hub.core.agent_sessions.errors import AgentSessionNotFoundError, StoreSequenceError
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.agent_sessions.store import AgentSessionStore
from agent_hub.core.sessions.session import TokenUsage
from agent_hub.core.testing.read_model_builders import (
    a_log_record,
    an_agent_session,
    an_open_permission,
)

T0 = datetime(2026, 10, 13, 9, 0, 0, 125000, tzinfo=UTC)
FIRST = "01929a4e-7a11-7c00-8a00-00000000b001"
SECOND = "01929a4e-7a11-7c00-8a00-00000000b002"
THIRD = "01929a4e-7a11-7c00-8a00-00000000b003"
CLAUDE_ID = "5091b986-0000-4000-8000-0000000000b1"


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _session(agent_session_id: str, minutes: int = 0, **fields: object) -> AgentSession:
    at = T0 + timedelta(minutes=minutes)
    base: dict[str, object] = {
        "id": agent_session_id,
        "created_at": at,
        "updated_at": at,
        "last_seq": 0,
        "claude_session_id": None,
        "cost_usd": None,
        "usage": None,
    }
    return an_agent_session(**(base | fields))


def _records(first: int, count: int) -> list[LogRecord]:
    kinds: tuple[RecordKind, ...] = ("user.message", "init", "text", "result")
    return [
        a_log_record(kinds[(seq - 1) % len(kinds)], seq, at=T0 + timedelta(seconds=seq))
        for seq in range(first, first + count)
    ]


def _raises_not_found(action: Callable[[], object]) -> bool:
    try:
        action()
    except AgentSessionNotFoundError:
        return True
    return False


def _ids(sessions: Sequence[AgentSession]) -> list[str]:
    return [session.id for session in sessions]


class AgentSessionStoreContract:
    """Gap-free logs in order, filters, links, restart, retention and delete."""

    def test_gets_session_when_created(self, agent_session_store: AgentSessionStore) -> None:
        session = _session(FIRST, open_permission=an_open_permission())

        agent_session_store.create(session)

        stored = agent_session_store.get(FIRST)
        expected = session.model_copy(update={"open_permission": None})
        _check(stored == expected, f"the session reads back as created: {stored}")

    def test_appends_records_in_order_when_seq_gap_free(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST))
        records = _records(1, 4)

        agent_session_store.append(FIRST, records[:1])
        agent_session_store.append(FIRST, records[1:])

        _check(list(agent_session_store.records(FIRST)) == records, "records read back in order")
        _check(agent_session_store.get(FIRST).last_seq == 4, "last_seq follows the log")

    def test_refuses_append_when_seq_skips_or_repeats(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST))
        agent_session_store.append(FIRST, _records(1, 2))

        for batch in (_records(2, 1), _records(4, 1), [*_records(3, 1), *_records(5, 1)]):
            try:
                agent_session_store.append(FIRST, batch)
            except StoreSequenceError:
                continue
            raise AssertionError(f"a batch from seq {batch[0].seq} must be refused")

        _check(len(agent_session_store.records(FIRST)) == 2, "a refused batch writes nothing")
        _check(agent_session_store.get(FIRST).last_seq == 2, "last_seq does not move")

    def test_pages_records_when_after_and_limit_given(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST))
        agent_session_store.append(FIRST, _records(1, 6))

        page = agent_session_store.records(FIRST, after=2, limit=3)

        _check([record.seq for record in page] == [3, 4, 5], f"a page after 2: {page}")

    def test_updates_fields_when_changed(self, agent_session_store: AgentSessionStore) -> None:
        agent_session_store.create(_session(FIRST))
        ended = T0 + timedelta(hours=1)
        usage = TokenUsage(input=40, output=9, cache_read=3, cache_write=1)

        updated = agent_session_store.update(
            FIRST,
            claude_session_id=CLAUDE_ID,
            status=AgentSessionStatus.ENDED,
            end_reason=EndReason.CLOSED,
            ended_at=ended,
            updated_at=ended,
            mode="plan",
            model="opus",
            cost_usd=Decimal("0.0123"),
            usage=usage,
            title="Fix the flaky test",
        )

        _check(updated == agent_session_store.get(FIRST), "update answers the stored session")
        _check(
            (updated.status, updated.end_reason, updated.ended_at)
            == (AgentSessionStatus.ENDED, EndReason.CLOSED, ended),
            "status, reason and end time change",
        )
        _check((updated.mode, updated.model) == ("plan", "opus"), "mode and model change")
        _check((updated.cost_usd, updated.usage) == (Decimal("0.0123"), usage), "cost kept")
        _check(updated.claude_session_id == CLAUDE_ID, "the Claude session id is linked")

    def test_lists_newest_first_when_filtered(self, agent_session_store: AgentSessionStore) -> None:
        agent_session_store.create(_session(FIRST, 0))
        agent_session_store.create(_session(SECOND, 1, project="other"))
        agent_session_store.create(
            _session(THIRD, 2, kind="cloud", cloud_id="cse_01x", status=AgentSessionStatus.ENDED)
        )

        store = agent_session_store
        _check(_ids(store.list()) == [THIRD, SECOND, FIRST], "newest first")
        _check(_ids(store.list(project="demo")) == [THIRD, FIRST], "filtered by project")
        idle = store.list(status=AgentSessionStatus.IDLE)
        _check(_ids(idle) == [SECOND, FIRST], "filtered by status")
        _check(_ids(store.list(kind="cloud")) == [THIRD], "filtered by kind")
        _check(_ids(store.list(limit=1)) == [THIRD], "at most limit")

    def test_finds_link_when_claude_session_id_known(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST, 0, claude_session_id=CLAUDE_ID))
        agent_session_store.create(_session(SECOND, 1, claude_session_id=CLAUDE_ID))

        _check(agent_session_store.link_of("demo", CLAUDE_ID) == SECOND, "the newest links")
        _check(agent_session_store.link_of("other", CLAUDE_ID) is None, "per project")
        _check(agent_session_store.link_of("demo", "unknown") is None, "unknown: no link")

    def test_ends_unfinished_when_server_restarts(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST, 0, status=AgentSessionStatus.RUNNING))
        agent_session_store.create(
            _session(SECOND, 1, status=AgentSessionStatus.WAITING_PERMISSION)
        )
        failed_at = T0 + timedelta(minutes=5)
        agent_session_store.create(
            _session(
                THIRD,
                2,
                status=AgentSessionStatus.FAILED,
                end_reason=EndReason.FAILED,
                ended_at=failed_at,
            )
        )
        at = T0 + timedelta(hours=2)

        count = agent_session_store.end_unfinished(at, EndReason.SERVER_STOPPED)

        _check(count == 2, f"two sessions were unfinished, got {count}")
        for agent_session_id in (FIRST, SECOND):
            session = agent_session_store.get(agent_session_id)
            _check(
                (session.status, session.end_reason, session.ended_at)
                == (AgentSessionStatus.ENDED, EndReason.SERVER_STOPPED, at),
                f"{agent_session_id} ends server_stopped",
            )
        third = agent_session_store.get(THIRD)
        _check((third.status, third.ended_at) == (AgentSessionStatus.FAILED, failed_at), "kept")

    def test_purges_only_ended_before_cutoff_when_swept(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        cutoff = T0 + timedelta(days=1)
        old = {"status": AgentSessionStatus.ENDED, "end_reason": EndReason.CLOSED}
        agent_session_store.create(_session(FIRST, 0, **old, ended_at=T0))
        agent_session_store.create(_session(SECOND, 1, **old, ended_at=cutoff + timedelta(1)))
        agent_session_store.create(_session(THIRD, 2))
        agent_session_store.append(FIRST, _records(1, 2))

        count = agent_session_store.purge_ended_before(cutoff)

        _check(count == 1, f"only the old ended session goes, got {count}")
        _check(_raises_not_found(lambda: agent_session_store.get(FIRST)), "it is gone")
        _check(_raises_not_found(lambda: agent_session_store.records(FIRST)), "its records too")
        kept = {session.id for session in agent_session_store.list()}
        _check(kept == {SECOND, THIRD}, f"recent and live sessions stay: {kept}")

    def test_deletes_records_when_session_deleted(
        self, agent_session_store: AgentSessionStore
    ) -> None:
        agent_session_store.create(_session(FIRST))
        agent_session_store.create(_session(SECOND, 1))
        agent_session_store.append(FIRST, _records(1, 3))
        agent_session_store.append(SECOND, _records(1, 1))

        agent_session_store.delete(FIRST)

        _check(_raises_not_found(lambda: agent_session_store.get(FIRST)), "the session is gone")
        _check(_raises_not_found(lambda: agent_session_store.records(FIRST)), "records too")
        _check(len(agent_session_store.records(SECOND)) == 1, "other logs stay")

    def test_raises_not_found_when_id_unknown(self, agent_session_store: AgentSessionStore) -> None:
        unknown = "01929a4e-7a11-7c00-8a00-0000000000ff"

        for action in (
            lambda: agent_session_store.get(unknown),
            lambda: agent_session_store.records(unknown),
            lambda: agent_session_store.append(unknown, _records(1, 1)),
            lambda: agent_session_store.update(unknown, title="x"),
            lambda: agent_session_store.delete(unknown),
        ):
            _check(_raises_not_found(action), "an unknown id raises AgentSessionNotFoundError")
