"""Smoke test of the Linear GraphQL adapter against the real Linear API (Q-6, AC-9.15).

Marked ``live``: ``make check`` never selects it, and ``scripts/pytest_levels.py`` skips every
case, naming the first missing variable, unless ``LINEAR_API_KEY``, ``AGENT_HUB_LIVE_ISSUE`` and
``AGENT_HUB_LIVE_LABEL`` are set and ``AGENT_HUB_LIVE=1`` (Q-7). Run it with
``pytest -m live packages/tracker_linear/tests/integration``.

``AGENT_HUB_LIVE_ISSUE`` names a sandbox issue (``DEM-1``) in a state that is not done
(``list_ready`` leaves done issues out). ``AGENT_HUB_LIVE_LABEL`` is a label of its team or
workspace that is not the runner's ready label (not ``agent-ready``): the round trip adds and
removes it. It writes to that issue only: the label ends as it was found, and one comment is
added. Assertions compare flags, not issue data, so a failure prints none.
"""

import os
from collections.abc import Iterator

import pytest

from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient

pytestmark = pytest.mark.live

_COMMENT = "agent-hub live smoke test (AGH-9): a comment from the Linear GraphQL adapter."


@pytest.fixture
def client() -> LinearGraphqlTrackerClient:
    # The default urllib transport; the key is read from the environment on each call.
    return LinearGraphqlTrackerClient(environ=os.environ)


@pytest.fixture
def issue_id() -> str:
    return os.environ["AGENT_HUB_LIVE_ISSUE"]


@pytest.fixture
def label() -> str:
    return os.environ["AGENT_HUB_LIVE_LABEL"]


@pytest.fixture
def labeled_before(client: LinearGraphqlTrackerClient, issue_id: str, label: str) -> Iterator[bool]:
    """Whether the issue carries the label now; it carries it again, or not, after the test."""
    had_label = label in client.get_issue(issue_id).labels
    yield had_label
    if had_label:
        client.add_label(issue_id, label)
    else:
        client.remove_label(issue_id, label)


def test_reads_issue_when_live(client: LinearGraphqlTrackerClient, issue_id: str) -> None:
    issue = client.get_issue(issue_id)

    same_id = issue.id == issue_id
    assert same_id
    has_text = bool(issue.title) and issue.url.startswith("https://")
    assert has_text


def test_lists_team_ready_issues_when_live(
    client: LinearGraphqlTrackerClient, issue_id: str, label: str
) -> None:
    team = issue_id.partition("-")[0]

    ready = client.list_ready(team, label)

    all_in_team = all(issue.id.startswith(f"{team}-") for issue in ready)
    assert all_in_team
    all_labeled = all(label in issue.labels for issue in ready)
    assert all_labeled


def test_round_trips_label_when_live(
    *, client: LinearGraphqlTrackerClient, issue_id: str, label: str, labeled_before: bool
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


def test_comments_when_live(client: LinearGraphqlTrackerClient, issue_id: str) -> None:
    client.comment(issue_id, _COMMENT)
