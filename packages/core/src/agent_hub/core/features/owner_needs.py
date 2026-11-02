"""The features the Features list flags as needing you: the count behind the shell's badge.

RED stub for AGH-623 (plan SHELL-1 commit 30a): the name the tests import, with no logic yet.
"""

from collections.abc import Sequence

from agent_hub.core.features.feature_view import FeatureView
from agent_hub.core.projects.project_views import LiveTile


def features_needing_you(features: Sequence[FeatureView], tiles: Sequence[LiveTile]) -> int:
    """How many of ``features`` the Features list flags as needing you, given the live ``tiles``."""
    raise NotImplementedError
