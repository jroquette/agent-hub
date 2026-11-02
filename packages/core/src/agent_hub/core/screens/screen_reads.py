"""The screen reads (ADR 0056): each screen's first view in one call, over the read ports.

RED stub for AGH-623 (plan SHELL-1 commit 30b): the names the tests import, with no logic yet.
"""

import time
from collections.abc import Callable
from typing import Final

from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.readmodels.read_ports import EventReadModels, HubReadModels
from agent_hub.core.screens.screen_views import ShellView

FEATURES_FRESH_SECONDS: Final = 30.0


class ScreenReads:
    def __init__(
        self,
        events: EventReadModels,
        hubs: HubReadModels,
        agent_sessions: AgentSessionCommands | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        raise NotImplementedError

    def shell(self, scope: str | None) -> ShellView:
        raise NotImplementedError

    def forget_features(self) -> None:
        raise NotImplementedError
