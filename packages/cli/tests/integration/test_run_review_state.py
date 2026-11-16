"""``hub run`` moves the issue to ``tracker.states.review`` (AC-63.2), ``In Review`` by default.

Each run is in process, in a copy of the ``DEMO`` workspace (``run_workspace``: team ``DEM``,
repo ``demo-api``, branch prefix ``jdoe/``), with the conftest's recording tracker.
"""

import json
from collections.abc import Callable
from typing import Any

import pytest
from typer.testing import Result

from agent_hub.cli import run_command
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.fakes import TrackerState
from agent_hub.core.tracker.tracker_client import TrackerClient

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

KEY_VARIABLE = "LINEAR_API_KEY"
CODE_REVIEW = "Code Review"
# The team's states with "Code Review" in place of "In Review": moving to "In Review" fails.
CODE_REVIEW_STATES = (
    TrackerState(name="Todo", type="unstarted"),
    TrackerState(name="In Progress", type="started"),
    TrackerState(name=CODE_REVIEW, type="started"),
    TrackerState(name="Done", type="completed"),
)


class Resolve:
    """Replaces ``run_command.resolve_tracker_client``: returns ``client``."""

    def __init__(self, client: object) -> None:
        self.client = client

    def __call__(self, config: HubConfig, environ: object, *, hub_root: object) -> TrackerClient:
        return self.client  # type: ignore[return-value]


@pytest.fixture(autouse=True)
def with_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(KEY_VARIABLE, "lin" + "_api_" + "x" * 40)


@pytest.fixture
def tracker(run_tracker: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """``run_tracker``, the client every ``hub run`` of the test resolves."""
    monkeypatch.setattr(run_command, "resolve_tracker_client", Resolve(run_tracker))
    return run_tracker


def configure_review_state(hub: Any, state: str) -> None:
    """Set ``tracker.states.review`` in the hub's ``hub.json``."""
    path = hub / "hub.json"
    document = json.loads(path.read_text())
    document["tracker"]["states"] = {"review": state}
    path.write_text(json.dumps(document, indent=2) + "\n")


def run_dem_1(run_command: CommandRunner, workspace: Any, *arguments: str) -> Result:
    return run_command(workspace.hub, "run", "DEM-1", "--repo", "demo-api", *arguments)


def moves(tracker: Any) -> list[Any]:
    return [call for call in tracker.calls if call[0] == "move_state"]


class TestRunReviewState:
    def test_prints_configured_state_when_dry_run(
        self, run_workspace: Workspace, run_command: CommandRunner, *, tracker: Any
    ) -> None:
        workspace = run_workspace.workspace
        configure_review_state(workspace.hub, CODE_REVIEW)

        result = run_dem_1(run_command, workspace)

        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert "would call: move_state(DEM-1, Code Review)" in lines
        assert [line for line in lines if "In Review" in line] == []
        assert tracker.calls == [("get_issue", "DEM-1")]

    def test_moves_to_configured_state_when_live(
        self, run_workspace: Workspace, run_command: CommandRunner, *, tracker: Any
    ) -> None:
        workspace = run_workspace.workspace
        configure_review_state(workspace.hub, CODE_REVIEW)
        tracker.backend.states["DEM"] = CODE_REVIEW_STATES

        result = run_dem_1(run_command, workspace, "--live")

        assert result.exit_code == 0, result.output
        assert moves(tracker) == [("move_state", "DEM-1", CODE_REVIEW)]
        assert tracker.backend.issues["DEM-1"].state == CODE_REVIEW

    def test_moves_to_in_review_when_states_absent(
        self, run_workspace: Workspace, run_command: CommandRunner, *, tracker: Any
    ) -> None:
        workspace = run_workspace.workspace
        document = json.loads((workspace.hub / "hub.json").read_text())
        assert "states" not in document["tracker"]

        dry = run_dem_1(run_command, workspace)
        result = run_dem_1(run_command, workspace, "--live")

        assert dry.exit_code == 0, dry.output
        assert "would call: move_state(DEM-1, In Review)" in dry.stdout.splitlines()
        assert result.exit_code == 0, result.output
        assert moves(tracker) == [("move_state", "DEM-1", "In Review")]
        assert tracker.backend.issues["DEM-1"].state == "In Review"
