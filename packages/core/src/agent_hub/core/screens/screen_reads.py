"""The screen reads (ADR 0056): each screen's first view in one call, over the read ports.

Each read composes the existing read use cases: it adds no data source, writes nothing and never
calls the tracker. The shell read keeps each scope's feature list for ``FEATURES_FRESH_SECONDS``
(the Features list's own refresh), so the shell's 5 s poll reads the live tiles again but not every
feature folder; the routes that write feature records call ``forget_features()``.
"""

import threading
import time
from collections import OrderedDict
from collections.abc import Callable
from typing import Final

from agent_hub.core.agent_sessions.control import AgentSessionCommands
from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.features.owner_needs import features_needing_you
from agent_hub.core.readmodels.filters import RunFilter, Scope
from agent_hub.core.readmodels.read_ports import EventReadModels, HubReadModels
from agent_hub.core.screens.screen_views import PortfolioView, ShellProject, ShellView

FEATURES_FRESH_SECONDS: Final = 30.0
# The scopes whose feature list is kept: All projects and a few projects at once.
FEATURE_SCOPES_KEPT: Final = 8


class ScreenReads:
    """The screen reads over the event and hub read models."""

    def __init__(
        self,
        events: EventReadModels,
        hubs: HubReadModels,
        agent_sessions: AgentSessionCommands | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._events = events
        self._hubs = hubs
        self._agent_sessions = agent_sessions
        self._monotonic = monotonic
        self._features: OrderedDict[str | None, tuple[float, tuple[FeatureView, ...]]] = (
            OrderedDict()
        )
        # Bumped by forget_features(), so a list read before a write is never kept after it.
        self._generation = 0
        self._guard = threading.Lock()

    def shell(self, scope: str | None) -> ShellView:
        """The app shell's facts: the registered hubs, every project for the switcher, the
        features of ``scope`` that need you, and whether any project has a workflow run."""
        features = self._scope_features(scope)
        tiles = self._events.list_live_sessions(Scope(project=scope)).items if features else ()
        runs = self._events.list_runs(RunFilter(kind="workflow", limit=1))
        return ShellView(
            hub_count=len(self._hubs.list_hubs().items),
            projects=tuple(
                ShellProject(name=project.name, live_sessions=project.live_sessions)
                for project in self._hubs.list_projects().items
            ),
            features_needing_you=features_needing_you(features, tiles),
            has_workflow_runs=bool(runs.items),
        )

    def portfolio(self, scope: str | None) -> PortfolioView:
        """Home's first view: every project's card, what needs you in ``scope`` and its newest
        activity page.

        RED stub for AGH-623 (plan SCREEN-1 commit 34): the name the tests call, no logic yet.
        """
        raise NotImplementedError

    def forget_features(self) -> None:
        """Drop every kept feature list, after a write of a feature record."""
        with self._guard:
            self._features.clear()
            self._generation += 1

    def _scope_features(self, scope: str | None) -> tuple[FeatureView, ...]:
        now = self._monotonic()
        with self._guard:
            kept = self._features.get(scope)
            if kept is not None and now - kept[0] < FEATURES_FRESH_SECONDS:
                return kept[1]
            generation = self._generation
        features = self._hubs.list_features(Scope(project=scope)).items
        with self._guard:
            if generation == self._generation:
                self._features[scope] = (now, features)
                self._features.move_to_end(scope)
                while len(self._features) > FEATURE_SCOPES_KEPT:
                    self._features.popitem(last=False)
        return features
