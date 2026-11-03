"""The shell's badge count (ADR 0056): the features the Features list flags as needing you.

The predicate mirrors the web's ``reasonOf(...).needs !== null``: a non-shipped feature with a
main-session tile waiting on you or idle on its issue (or titled with its slug), any feature with a
problem, a non-shipped NO-SHIP, and a non-shipped feature waiting on an owner decision. The first
row is the case the web's badge test held before the shell read (plain, asked, broken, refused).
"""

from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_view import FeatureView, WaitingOnOwner
from agent_hub.core.features.owner_needs import features_needing_you
from agent_hub.core.projects.project_views import LiveTile
from agent_hub.core.testing.read_model_builders import a_feature_view, a_session_label

AT = datetime(2026, 10, 9, 14, 0, tzinfo=UTC)


def a_tile(**overrides: object) -> LiveTile:
    """A main-session tile of project ``demo`` with no label, working (``live``)."""
    fields: dict[str, object] = {
        "id": "session-1",
        "project": "demo",
        "repo": "demo-api",
        "agent": "main",
        "status": "live",
        "group": "live",
        "last_action": "Bash make check",
        "last_tool": "Bash",
        "last_activity_at": AT,
        "started_at": AT,
        "turns": 2,
        "tokens_total": 100,
        "files_touched": 1,
        "errors": 0,
        "guard_denials": 0,
        "cost_usd": None,
    }
    return LiveTile.model_validate(fields | overrides)


def on_issue(issue: str, group: str = "waiting", **overrides: object) -> LiveTile:
    """A tile in ``group`` whose label names ``issue``."""
    return a_tile(group=group, label=a_session_label(issue=issue), **overrides)


def feature(slug: str = "search-index", **overrides: object) -> FeatureView:
    """A feature in Build on ``AGH-5``, with nothing that needs the owner."""
    fields: dict[str, object] = {"slug": slug, "issues": ("AGH-5",), "verdict": None}
    return a_feature_view(**(fields | overrides))


def waits_on(kind: str, **overrides: object) -> FeatureView:
    """A feature that waits on the owner's decision of ``kind``."""
    return feature(waiting_on_owner=WaitingOnOwner.model_validate({"kind": kind}), **overrides)


BROKEN = "features.json could not be parsed"
CASES = [
    pytest.param(
        [
            feature("plain", issues=("AGH-1",)),
            feature("asked", issues=("AGH-2",)),
            feature("broken", issues=(), problem=BROKEN),
            feature("refused", issues=(), verdict="NO-SHIP"),
        ],
        [on_issue("AGH-2"), on_issue("AGH-1", "live", id="session-2")],
        3,
        id="list-cases",
    ),
    pytest.param([feature("refused", verdict="NO-SHIP")], [], 1, id="no-tiles"),
    pytest.param([feature()], [on_issue("AGH-5")], 1, id="waiting-tile"),
    pytest.param([feature()], [on_issue("AGH-5", "idle")], 1, id="idle-tile"),
    pytest.param([feature()], [a_tile(group="waiting", issue="AGH-5")], 1, id="tile-issue"),
    pytest.param(
        [feature()],
        [a_tile(group="waiting", issue="AGH-5", label=a_session_label(issue="AGH-9"))],
        0,
        id="label-issue-first",
    ),
    pytest.param(
        [feature()],
        [a_tile(group="idle", label=a_session_label(issue=None, title="Cache search-index"))],
        1,
        id="title-names-slug",
    ),
    pytest.param(
        [feature(issues=("AGH-12 search box",))], [on_issue("agh-12")], 1, id="issue-id-any-case"
    ),
    pytest.param([feature(problem=BROKEN)], [], 1, id="problem"),
    pytest.param([feature(phase="shipped", problem=BROKEN)], [], 1, id="shipped-problem"),
    pytest.param([feature(verdict="NO-SHIP")], [], 1, id="no-ship"),
    pytest.param([waits_on("change_request")], [], 1, id="change-request"),
    pytest.param([waits_on("owner_signoff")], [], 1, id="owner-signoff"),
    pytest.param([waits_on("owner_signoff_manual")], [], 1, id="owner-signoff-manual"),
    pytest.param(
        [feature(problem=BROKEN, verdict="NO-SHIP")], [on_issue("AGH-5")], 1, id="counted-once"
    ),
    pytest.param([feature(phase="shipped")], [on_issue("AGH-5")], 0, id="shipped-waiting"),
    pytest.param([feature()], [on_issue("AGH-5", is_subagent=True)], 0, id="subagent-tile"),
    pytest.param([feature()], [on_issue("AGH-6")], 0, id="tile-on-another-issue"),
    pytest.param([feature()], [on_issue("AGH-5", "ended_recently")], 0, id="ended-tile"),
    pytest.param([feature(phase="shipped", verdict="NO-SHIP")], [], 0, id="shipped-no-ship"),
    pytest.param([waits_on("owner_signoff", phase="shipped")], [], 0, id="shipped-owner-signoff"),
]


@pytest.mark.parametrize(("features", "tiles", "expected"), CASES)
def test_counts_features_the_list_flags_when_tiles_and_records_vary(
    features: Sequence[FeatureView], tiles: Sequence[LiveTile], expected: int
) -> None:
    assert features_needing_you(features, tiles) == expected
