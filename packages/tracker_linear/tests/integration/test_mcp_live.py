"""Smoke test of the Linear MCP adapter against the real Linear MCP server (AC-27.12, E7).

Marked ``live("mcp")``: ``make check`` never selects it, and ``scripts/pytest_levels.py`` skips
every case, naming the first missing variable, unless ``AGENT_HUB_LIVE_ISSUE``,
``AGENT_HUB_LIVE_LABEL`` and ``AGENT_HUB_LIVE_HUB`` are set and ``AGENT_HUB_LIVE=1``. It needs
no ``LINEAR_API_KEY``: ``claude`` reaches Linear through the user's ``Linear`` MCP server, so
the owner runs it with the key unset, after ``test_linear_live.py`` with the key on the same
issue and label (E23). Run it with
``pytest -m live packages/tracker_linear/tests/integration/test_mcp_live.py``.

``AGENT_HUB_LIVE_ISSUE`` and ``AGENT_HUB_LIVE_LABEL`` are as in ``test_linear_live.py``: a
sandbox issue in a state that is not done, and a label of its team or workspace that is not the
runner's ready label; every case fails at setup when the label is ``agent-ready`` or the hub's
``tracker.ready_label``. The label ends as it was found, and one comment is added.
``AGENT_HUB_LIVE_HUB`` is a hub root: each call runs ``claude -p`` there, the cwd production
uses, so the hub's CLAUDE.md, plugins and settings load as they will for ``hub next``.
Assertions compare flags, not issue data, so a failure prints none.
"""

import contextlib
import json
import os
from collections.abc import Iterator
from pathlib import Path

import pytest

from agent_hub.tracker_linear.mcp import McpTrackerClient

pytestmark = pytest.mark.live("mcp")

_COMMENT = "agent-hub live smoke test (AGH-27): a comment from the Linear MCP adapter."
_READY_LABEL = "agent-ready"


def _hub_root() -> Path:
    return Path(os.environ["AGENT_HUB_LIVE_HUB"])


def _ready_labels(hub_root: Path) -> set[str]:
    """``agent-ready`` and the hub's ``tracker.ready_label``, when its hub.json names one."""
    labels = {_READY_LABEL}
    with contextlib.suppress(OSError, ValueError):
        tracker = json.loads((hub_root / "hub.json").read_text(encoding="utf-8")).get("tracker")
        if isinstance(tracker, dict) and isinstance(tracker.get("ready_label"), str):
            labels.add(tracker["ready_label"])
    return labels


@pytest.fixture(autouse=True)
def _refuse_ready_label() -> None:
    # The round trip adds and removes the label: on the ready label it would hand the issue to
    # the runner.
    label = os.environ["AGENT_HUB_LIVE_LABEL"]
    if label in _ready_labels(_hub_root()):
        pytest.fail(
            "AGENT_HUB_LIVE_LABEL is the runner's ready label; set it to another label of the"
            " issue's team or workspace",
            pytrace=False,
        )


@pytest.fixture
def client() -> McpTrackerClient:
    # The default runner and caps; claude reads the Linear MCP server from the user's config.
    return McpTrackerClient(environ=os.environ, cwd=_hub_root())


@pytest.fixture
def issue_id() -> str:
    return os.environ["AGENT_HUB_LIVE_ISSUE"]


@pytest.fixture
def label() -> str:
    return os.environ["AGENT_HUB_LIVE_LABEL"]


@pytest.fixture
def labeled_before(client: McpTrackerClient, issue_id: str, label: str) -> Iterator[bool]:
    """Whether the issue carries the label now; it carries it again, or not, after the test."""
    had_label = label in client.get_issue(issue_id).labels
    yield had_label
    if had_label:
        client.add_label(issue_id, label)
    else:
        client.remove_label(issue_id, label)


def test_reads_issue_when_live(client: McpTrackerClient, issue_id: str) -> None:
    issue = client.get_issue(issue_id)

    same_id = issue.id == issue_id
    assert same_id
    has_text = bool(issue.title) and issue.url.startswith("https://")
    assert has_text
    has_cost = client.last_cost_usd > 0
    assert has_cost


def test_lists_team_ready_issues_when_live(
    client: McpTrackerClient, issue_id: str, label: str
) -> None:
    team = issue_id.partition("-")[0]

    ready = client.list_ready(team, label)

    all_in_team = all(issue.id.startswith(f"{team}-") for issue in ready)
    assert all_in_team
    all_labeled = all(label in issue.labels for issue in ready)
    assert all_labeled


def test_round_trips_label_when_live(
    *, client: McpTrackerClient, issue_id: str, label: str, labeled_before: bool
) -> None:
    # Flip the label, then flip it back; the fixture restores it even when an assert fails.
    # After each flip, list_ready lists the issue exactly when it carries the label.
    team = issue_id.partition("-")[0]
    for _ in range(2):
        labeled = label in client.get_issue(issue_id).labels
        if labeled:
            client.remove_label(issue_id, label)
        else:
            client.add_label(issue_id, label)
        flipped = (label in client.get_issue(issue_id).labels) is not labeled
        assert flipped
        listed = issue_id in {issue.id for issue in client.list_ready(team, label)}
        listed_when_labeled = listed is not labeled
        assert listed_when_labeled

    restored = (label in client.get_issue(issue_id).labels) is labeled_before
    assert restored


def test_comments_when_live(client: McpTrackerClient, issue_id: str) -> None:
    client.comment(issue_id, _COMMENT)
