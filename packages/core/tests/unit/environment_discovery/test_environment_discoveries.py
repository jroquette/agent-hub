import json
from collections.abc import AsyncIterator, Callable, Sequence
from datetime import datetime
from itertools import count

import pytest

from agent_hub.core.agent_sessions.driver import StartSpec, TextBlock
from agent_hub.core.environment_discovery.discovery import (
    DiscoveryNotFoundError,
    StartEnvironmentDiscovery,
)
from agent_hub.core.environment_discovery.environment_discoveries import (
    NOT_STARTED,
    SESSION_GONE,
    EnvironmentDiscoveries,
)
from agent_hub.core.environment_discovery.proposal import NO_BLOCK
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.testing.agent_session_rig import Rig, build_rig
from agent_hub.core.testing.discovery_fakes import (
    DEMO_HUB_PATH,
    DemoConfigs,
    InMemoryDiscoveryRecords,
)
from agent_hub.core.testing.session_driver_fakes import Hold, InMemorySessionDriver, Turn

pytestmark = pytest.mark.anyio

PROPOSAL = {
    "environments": [{"name": "staging", "preset": "staging"}],
    "services": [
        {
            "repo": "demo-api",
            "name": "payments",
            "kind": "lambda",
            "addresses": [{"environment": "staging", "address": "demo-payments-staging"}],
        }
    ],
}
FOUND = (TextBlock(block=0, text=f"Done.\n\n```json\n{json.dumps(PROPOSAL)}\n```"),)


class Setup:
    """The use case over a rig's control, the demo config and in-memory records."""

    def __init__(self, rig: Rig) -> None:
        self.rig = rig
        self.records = InMemoryDiscoveryRecords()
        ids = count(1)
        self.discoveries = EnvironmentDiscoveries(
            rig.control,
            DemoConfigs(),
            self.records,
            clock=self._later(rig),
            new_id=lambda: f"{next(ids):012x}",
        )

    @staticmethod
    def _later(rig: Rig) -> Callable[[], datetime]:
        def now() -> datetime:
            rig.clock.advance(1)
            return rig.clock.now

        return now

    def spec(self) -> StartSpec:
        (spec,) = [call.args[0] for call in self.rig.driver.calls if call.method == "start"]
        assert isinstance(spec, StartSpec)
        return spec


type MakeSetup = Callable[[Sequence[Turn]], Setup]


@pytest.fixture
async def make_setup() -> AsyncIterator[MakeSetup]:
    setups: list[Setup] = []

    def build(turns: Sequence[Turn]) -> Setup:
        setup = Setup(build_rig(driver=InMemorySessionDriver(turns=turns)))
        setups.append(setup)
        return setup

    yield build
    for setup in setups:
        await setup.rig.control.shutdown()


def _request(**fields: object) -> StartEnvironmentDiscovery:
    body: dict[str, object] = {"repos": ["demo-api"], "environments": ["Staging"]}
    return StartEnvironmentDiscovery.model_validate(body | fields)


async def test_starts_read_only_session_on_picked_repos_when_started(make_setup: MakeSetup) -> None:
    setup = make_setup([(Hold(),)])

    started = await setup.discoveries.start("demo", _request())

    spec = setup.spec()
    assert (spec.tool_access, spec.add_dirs, spec.cwd) == (
        "read_only",
        ("/hubs/demo-api",),
        DEMO_HUB_PATH,
    )
    assert (started.state, started.environments, started.repos) == (
        "running",
        ("staging",),
        ("demo-api",),
    )
    prompt = setup.rig.records(started.agent_session_id)[0].body["text"]
    assert isinstance(prompt, str)
    assert "- demo-api: /hubs/demo-api" in prompt
    assert "Look for these environments only: staging." in prompt
    assert setup.records.get(DEMO_HUB_PATH, started.id) is not None


async def test_refuses_with_problems_when_repo_or_environment_unknown(
    make_setup: MakeSetup,
) -> None:
    setup = make_setup([])

    with pytest.raises(HubInvalidError) as raised:
        await setup.discoveries.start(
            "demo", _request(repos=["demo-api", "nope"], environments=["qa"])
        )

    assert raised.value.title == NOT_STARTED
    assert [problem.pointer for problem in raised.value.problems] == [
        "/repos/1",
        "/environments/0",
    ]
    assert setup.rig.driver.calls == []


async def test_finishes_with_checked_proposal_when_claude_replies(make_setup: MakeSetup) -> None:
    setup = make_setup([FOUND])
    started = await setup.discoveries.start("demo", _request())
    await setup.rig.until_status(started.agent_session_id, "idle")

    found = await setup.discoveries.get("demo", started.id)

    assert found.state == "finished"
    assert found.proposal is not None
    (environment,) = found.proposal.environments
    assert (environment.status, environment.access) == ("declared", "ask")
    (service,) = found.proposal.services
    assert (service.status, service.addresses[0].status) == ("new", "new")


async def test_fails_with_reason_when_reply_holds_no_proposal(make_setup: MakeSetup) -> None:
    setup = make_setup([(TextBlock(block=0, text="Nothing to see."),)])
    started = await setup.discoveries.start("demo", _request())
    await setup.rig.until_status(started.agent_session_id, "idle")

    found = await setup.discoveries.get("demo", started.id)

    assert (found.state, found.problem, found.proposal) == ("failed", NO_BLOCK, None)


async def test_stops_when_person_interrupts_before_proposal(make_setup: MakeSetup) -> None:
    setup = make_setup([(Hold(),)])
    started = await setup.discoveries.start("demo", _request())

    await setup.rig.control.interrupt(started.agent_session_id)
    await setup.rig.until_status(started.agent_session_id, "idle")
    found = await setup.discoveries.get("demo", started.id)

    assert (found.state, found.problem) == ("stopped", None)


async def test_stops_when_person_closes_session_before_proposal(make_setup: MakeSetup) -> None:
    setup = make_setup([(Hold(),)])
    started = await setup.discoveries.start("demo", _request())

    await setup.rig.control.close(started.agent_session_id)
    found = await setup.discoveries.get("demo", started.id)

    assert found.state == "stopped"


async def test_lists_newest_first_and_hides_discarded_when_listed(make_setup: MakeSetup) -> None:
    setup = make_setup([FOUND, FOUND, FOUND])
    first = await setup.discoveries.start("demo", _request())
    second = await setup.discoveries.start("demo", _request())
    third = await setup.discoveries.start("demo", _request())

    await setup.discoveries.discard("demo", second.id)
    listed = await setup.discoveries.list("demo")

    assert [item.id for item in listed.items] == [third.id, first.id]
    with pytest.raises(DiscoveryNotFoundError):
        await setup.discoveries.get("demo", second.id)
    assert setup.rig.store.get(second.agent_session_id).status == "ended"


async def test_fails_when_session_was_removed(make_setup: MakeSetup) -> None:
    setup = make_setup([FOUND])
    started = await setup.discoveries.start("demo", _request())
    await setup.rig.control.close(started.agent_session_id)
    await setup.rig.control.delete(started.agent_session_id)

    found = await setup.discoveries.get("demo", started.id)

    assert (found.state, found.problem) == ("failed", SESSION_GONE)


async def test_raises_not_found_when_id_unknown(make_setup: MakeSetup) -> None:
    setup = make_setup([])

    with pytest.raises(DiscoveryNotFoundError):
        await setup.discoveries.get("demo", "0123456789ab")
