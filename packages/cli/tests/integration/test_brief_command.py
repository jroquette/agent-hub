"""``hub brief``: the session brief, against the hub's brief characterization (AC-15.5, AC-15.6).

The ten goldens in ``golden/brief/`` are hub ``tests/characterization/golden/brief/*.golden`` at
hub commit ``8eaebae``, byte for byte; ``brief_workspace`` rebuilds that commit's synthetic
workspace (nothing is copied from the hub's brain).
"""

from typing import Any

# The conftest's workspace (tests cannot import a conftest in importlib mode).
type Workspace = Any


def test_rebuilds_hub_workspace_when_brief_fixture_built(brief_workspace: Workspace) -> None:
    web = brief_workspace.ws / "web"
    api = brief_workspace.ws / "api"

    assert brief_workspace.git("rev-parse", "--short", "HEAD", cwd=web) == "dd68590"
    assert brief_workspace.git("branch", "--show-current", cwd=web) == ""
    assert brief_workspace.git("rev-list", "--count", "HEAD..origin/trunk", cwd=api) == "1"
    status = brief_workspace.git("status", "--porcelain", cwd=api)
    assert [line.split()[-1] for line in status.splitlines()] == ["README.md", "notes.txt"]
    hub = brief_workspace.hub
    assert brief_workspace.git("status", "--porcelain", cwd=hub) == ""
    assert brief_workspace.git("rev-list", "--count", "HEAD..origin/trunk", cwd=hub) == "0"
    assert not (brief_workspace.ws / "ui").exists()
