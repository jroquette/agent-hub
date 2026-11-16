"""Fixtures of the agent-session tests."""

from collections.abc import AsyncIterator, Callable

import pytest

from agent_hub.core.testing.agent_session_rig import Rig, build_rig

type MakeRig = Callable[..., Rig]


@pytest.fixture
async def make_rig() -> AsyncIterator[MakeRig]:
    """Build rigs (``build_rig``); each control is shut down after the test."""
    rigs: list[Rig] = []

    def build(**options: object) -> Rig:
        rig = build_rig(**options)  # type: ignore[arg-type]
        rigs.append(rig)
        return rig

    yield build
    for rig in rigs:
        await rig.control.shutdown()
