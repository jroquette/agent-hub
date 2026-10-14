"""Cloud sessions (D8, L9): start is link-out guidance, a follow-up is behind its flag."""

from datetime import UTC, datetime, timedelta

import pytest

from agent_hub.core.agent_sessions.agent_session import CloudMessage, StartCloud
from agent_hub.core.agent_sessions.cloud import (
    CLAUDE_CODE_URL_PREFIX,
    FOLLOWUP_GUIDANCE,
    NO_CLOUD_GUIDANCE,
    START_GUIDANCE,
    CloudReply,
    CloudSessions,
    claude_code_url,
)
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.errors import (
    AgentSessionNotFoundError,
    CloudFailedError,
    CloudUnavailableError,
)
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.records import LogRecord
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.read_model_builders import WORKDIR_ID, an_agent_session

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 13, 12, 0, tzinfo=UTC)
CLOUD_ID = "cse_01synthetic"
ROW_ID = "01929a4e-7a11-7c00-8a00-00000000c001"
CAPABLE = DriverCapabilities(available=True, cloud=True, cloud_followup=True)


class FakeLauncher:
    """Answers each follow-up with ``reply``; records the calls."""

    def __init__(self, reply: CloudReply | Exception | None = None) -> None:
        self.calls: list[tuple[str, str, int]] = []
        self._reply = reply or CloudReply(
            cloud_id=CLOUD_ID, url=f"{CLAUDE_CODE_URL_PREFIX}{CLOUD_ID}"
        )

    async def follow_up(self, cloud_id: str, text: str, *, timeout_seconds: int) -> CloudReply:
        self.calls.append((cloud_id, text, timeout_seconds))
        if isinstance(self._reply, Exception):
            raise self._reply
        return self._reply


def _cloud(
    capabilities: DriverCapabilities = CAPABLE,
    launcher: FakeLauncher | None = None,
    store: InMemoryAgentSessionStore | None = None,
) -> tuple[CloudSessions, FakeLauncher, InMemoryAgentSessionStore]:
    launcher = launcher or FakeLauncher()
    store = store or InMemoryAgentSessionStore()

    async def capabilities_now() -> DriverCapabilities:
        return capabilities

    cloud = CloudSessions(
        launcher=launcher,
        store=store,
        capabilities=capabilities_now,
        clock=lambda: NOW,
        limits=SessionLimits(cloud_timeout_seconds=30),
    )
    return cloud, launcher, store


def _started(store: InMemoryAgentSessionStore, row_id: str = ROW_ID, **fields: object) -> None:
    defaults: dict[str, object] = {
        "id": row_id,
        "kind": "cloud",
        "cloud_id": CLOUD_ID,
        "url": f"{CLAUDE_CODE_URL_PREFIX}{CLOUD_ID}",
        "claude_session_id": None,
        "last_seq": 0,
        "title": "Upgrade the linter",
    }
    store.create(an_agent_session(**(defaults | fields)))
    record = LogRecord(seq=1, at=NOW, kind="cloud.start", by="web", body={"cloud_id": CLOUD_ID})
    store.append(row_id, [record])


async def test_raises_terminal_guidance_when_started_with_cloud() -> None:
    cloud, launcher, store = _cloud()

    with pytest.raises(CloudUnavailableError) as raised:
        await cloud.start(
            StartCloud(project="demo", workdir_id=WORKDIR_ID, task="Fix the flaky test")
        )

    assert raised.value.guidance == START_GUIDANCE
    assert 'claude --cloud "<task>"' in START_GUIDANCE
    assert "claude --teleport" in START_GUIDANCE
    assert "Fix the flaky test" not in str(raised.value)
    assert launcher.calls == []
    assert store.list(kind="cloud") == ()


async def test_raises_update_guidance_when_cli_lacks_cloud() -> None:
    cloud, _, _ = _cloud(DriverCapabilities(available=True))

    with pytest.raises(CloudUnavailableError) as raised:
        await cloud.start(StartCloud(project="demo", workdir_id=WORKDIR_ID, task="Fix it"))

    assert raised.value.guidance == NO_CLOUD_GUIDANCE


async def test_raises_guidance_when_followup_flag_off() -> None:
    cloud, launcher, store = _cloud(DriverCapabilities(available=True, cloud=True))
    _started(store)

    with pytest.raises(CloudUnavailableError) as raised:
        await cloud.follow_up(CLOUD_ID, CloudMessage(text="And the docs"))

    assert raised.value.guidance == FOLLOWUP_GUIDANCE
    assert launcher.calls == []


async def test_runs_followup_and_records_it_when_capable() -> None:
    cloud, launcher, store = _cloud()
    _started(store)

    followed = await cloud.follow_up(CLOUD_ID, CloudMessage(text="And update the docs"))

    assert launcher.calls == [(CLOUD_ID, "And update the docs", 30)]
    assert (followed.id, followed.cloud_id, followed.followups) == (ROW_ID, CLOUD_ID, 1)
    assert followed.teleport_command == f"claude --teleport {CLOUD_ID}"
    assert followed.url == f"{CLAUDE_CODE_URL_PREFIX}{CLOUD_ID}"
    [record] = store.records(ROW_ID, after=1)
    assert (record.seq, record.kind, record.by, record.body) == (
        2,
        "cloud.followup",
        "web",
        {"cloud_id": CLOUD_ID},
    )
    assert "docs" not in str(record)


async def test_drops_url_when_not_claude_code() -> None:
    reply = CloudReply(cloud_id=CLOUD_ID, url="https://evil.example/code/cse_01synthetic")
    cloud, _, store = _cloud(launcher=FakeLauncher(reply))
    _started(store, url=None)

    followed = await cloud.follow_up(CLOUD_ID, CloudMessage(text="Go on"))

    assert followed.url is None
    assert claude_code_url("https://claude.ai/code/x") == "https://claude.ai/code/x"
    for url in (
        None,
        "",
        "http://claude.ai/code/x",
        "https://claude.ai/codex",
        "https://claude.ai.evil/code/",
    ):
        assert claude_code_url(url) is None


async def test_raises_not_found_when_cloud_id_unknown() -> None:
    cloud, launcher, _ = _cloud()

    with pytest.raises(AgentSessionNotFoundError):
        await cloud.follow_up("cse_unknown", CloudMessage(text="Go on"))
    with pytest.raises(AgentSessionNotFoundError):
        await cloud.follow_up("-p", CloudMessage(text="Go on"))

    assert launcher.calls == []


async def test_keeps_log_when_followup_fails() -> None:
    cloud, _, store = _cloud(launcher=FakeLauncher(CloudFailedError("follow-up exit 1")))
    _started(store)

    with pytest.raises(CloudFailedError):
        await cloud.follow_up(CLOUD_ID, CloudMessage(text="Go on"))

    assert store.get(ROW_ID).last_seq == 1


async def test_lists_cloud_rows_newest_first_when_listed() -> None:
    cloud, _, store = _cloud()
    _started(store, created_at=NOW - timedelta(hours=1))
    _started(
        store,
        row_id="01929a4e-7a11-7c00-8a00-00000000c002",
        cloud_id="cse_02synthetic",
        url="https://evil.example/",
        created_at=NOW,
    )
    store.create(an_agent_session(id="01929a4e-7a11-7c00-8a00-00000000c003", last_seq=0))

    listed = await cloud.list_cloud("demo")

    assert [item.cloud_id for item in listed.items] == ["cse_02synthetic", CLOUD_ID]
    assert listed.items[0].url is None
    assert listed.items[1].followups == 0
    assert (await cloud.list_cloud("other")).items == ()
