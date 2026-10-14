"""A rig for tests of ``AgentSessionControl``: the control over the in-memory driver and store,
a demo project with one workdir (its hub) and a clock the test moves by hand."""

import asyncio
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from agent_hub.core.agent_sessions.agent_session import AgentSession, CreateAgentSession
from agent_hub.core.agent_sessions.control import AgentSessionControl
from agent_hub.core.agent_sessions.driver import DriverHandle, PastSession
from agent_hub.core.agent_sessions.limits import SessionLimits
from agent_hub.core.agent_sessions.records import LogRecord
from agent_hub.core.agent_sessions.workdirs import ResolvedWorkdir, WorkdirListing
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.agent_session_store_fakes import InMemoryAgentSessionStore
from agent_hub.core.testing.read_model_builders import WORKDIR_ID, a_workdir
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver, Turn

START = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
HUB_PATH = "/hubs/demo-hub"
WEB_URL = "http://127.0.0.1:7420"
WAIT_SECONDS = 5.0


class Clock:
    """A clock the test moves by hand."""

    def __init__(self, now: datetime = START) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> datetime:
        self.now += timedelta(seconds=seconds)
        return self.now


def demo_workdirs(project: str) -> WorkdirListing:
    """The demo project's one workdir, its hub."""
    if project != "demo":
        raise EntityNotFoundError(entity="project", entity_id=project)
    return WorkdirListing(entries=(ResolvedWorkdir(workdir=a_workdir(), path=HUB_PATH),))


@dataclass
class Rig:
    """The control, its fakes and its clock."""

    control: AgentSessionControl
    driver: InMemorySessionDriver
    store: InMemoryAgentSessionStore
    clock: Clock
    created: list[AgentSession] = field(default_factory=list)

    async def create(self, prompt: str | None = None, **fields: object) -> AgentSession:
        body: dict[str, object] = {"project": "demo", "workdir_id": WORKDIR_ID}
        if prompt is not None:
            body["prompt"] = prompt
        session = await self.control.create(CreateAgentSession.model_validate(body | fields))
        self.created.append(session)
        return session

    def handle(self, number: int = 1) -> DriverHandle:
        return DriverHandle(f"fake-{number}")

    def records(self, agent_session_id: str) -> tuple[LogRecord, ...]:
        return self.store.records(agent_session_id, limit=100_000)

    def kinds(self, agent_session_id: str) -> list[str]:
        return [record.kind for record in self.records(agent_session_id)]

    async def until(self, check: Callable[[], bool]) -> None:
        async with asyncio.timeout(WAIT_SECONDS):
            while not check():
                await asyncio.sleep(0.002)

    async def until_status(self, agent_session_id: str, *statuses: str) -> AgentSession:
        await self.until(lambda: self.store.get(agent_session_id).status in statuses)
        return self.store.get(agent_session_id)


def build_rig(
    *,
    replies: Mapping[str, Turn] | None = None,
    limits: SessionLimits | None = None,
    past_sessions: Sequence[PastSession] = (),
    driver: InMemorySessionDriver | None = None,
    store: InMemoryAgentSessionStore | None = None,
) -> Rig:
    """A rig; ``replies`` script the fake driver per user message."""
    fake = driver or InMemorySessionDriver(replies=replies, past_sessions=past_sessions)
    store = store or InMemoryAgentSessionStore()
    clock = Clock()
    control = AgentSessionControl(
        fake,
        store,
        workdirs=demo_workdirs,
        limits=limits or SessionLimits(),
        clock=clock,
        environment_extra={"AGENT_HUB_WEB_URL": WEB_URL},
    )
    return Rig(control=control, driver=fake, store=store, clock=clock)
