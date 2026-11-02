"""The features the Features list flags as needing you: the count behind the shell's badge.

The shell read (ADR 0056) counts them on the server, so the shell no longer loads every feature and
live session on every screen. The predicate mirrors ``reasonOf(...).needs !== null`` in
``apps/web/src/screens/features/groups.ts``, which the Features list draws its warnings from;
nothing checks the two stay equal, so a change to one changes the other.
"""

import re
from collections.abc import Iterable, Sequence
from typing import Final

from agent_hub.core.features.feature_view import FeatureView, OwnerWaitKind
from agent_hub.core.projects.project_views import LiveTile

# The issue id at the head of a feature's entry ("AGH-200 (provisional …)" → "AGH-200").
_ISSUE_ID: Final = re.compile(r"[A-Z][A-Z0-9]*-\d+")
_OWNER_WAITS: Final[frozenset[OwnerWaitKind]] = frozenset(
    {"change_request", "owner_signoff", "owner_signoff_manual"}
)


def features_needing_you(features: Sequence[FeatureView], tiles: Sequence[LiveTile]) -> int:
    """How many of ``features`` the Features list flags as needing you, given the live ``tiles``."""
    return sum(1 for feature in features if _needs_you(feature, tiles))


def _needs_you(feature: FeatureView, tiles: Iterable[LiveTile]) -> bool:
    if feature.problem:
        return True
    if feature.phase == "shipped":
        return False
    waits_on_owner = (
        feature.waiting_on_owner is not None and feature.waiting_on_owner.kind in _OWNER_WAITS
    )
    return feature.verdict == "NO-SHIP" or waits_on_owner or _a_session_waits(feature, tiles)


def _a_session_waits(feature: FeatureView, tiles: Iterable[LiveTile]) -> bool:
    """A main-session tile waiting on you or idle whose issue is one of the feature's, or whose
    title names the feature (``sessionWaitOf`` in the web)."""
    ids = {_issue_id(issue).upper() for issue in feature.issues}
    return any(
        tile.group in {"waiting", "idle"} and _works_on(tile, ids, feature.slug) for tile in tiles
    )


def _works_on(tile: LiveTile, ids: set[str], slug: str) -> bool:
    if tile.is_subagent:
        return False
    label = tile.label
    issue = (label.issue if label is not None and label.issue is not None else tile.issue) or ""
    title = (label.title if label is not None else None) or ""
    return (issue != "" and issue.upper() in ids) or slug in title


def _issue_id(raw: str) -> str:
    entry = raw.strip()
    found = _ISSUE_ID.match(entry)
    return found.group(0) if found else entry
