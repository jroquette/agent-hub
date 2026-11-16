"""``make playground`` (``scripts/playground.sh``): the order of its start-up steps.

The script starts real servers and sessions, so it is read, not run: what matters is which Node
the conductor inherits.
"""

from pathlib import Path


def _lines(repo_root: Path) -> list[str]:
    return (repo_root / "scripts" / "playground.sh").read_text().splitlines()


# AGH-431 (AC-431.1): the conductor's sessions inherit its PATH, and their Stop gate runs npm ci,
# which needs the web app's Node; so the Node is selected, and printed, before the conductor starts.
def test_selects_web_app_node_before_conductor_when_playground_starts(repo_root: Path) -> None:
    lines = _lines(repo_root)
    conductor = next(i for i, line in enumerate(lines) if 'step "conductor on 7420"' in line)
    use = [i for i, line in enumerate(lines) if "nvm use" in line and ".node-version" in line]
    printed = [i for i, line in enumerate(lines) if line.strip() == "node --version"]

    assert len(use) == 1
    assert use[0] < conductor
    assert printed
    assert printed[0] < conductor
    assert use[0] < printed[0]
