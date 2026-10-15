"""The engine's checkout probe: ``git status`` around a ``mutates_checkout: false`` node, against
real git repositories under ``tmp_path``."""

import os
import subprocess
from pathlib import Path

import pytest

from agent_hub.cli.workflow_checkout import GitCheckoutProbe
from agent_hub.core.testing.workflow_fakes import (
    FakeClock,
    KeysOutputs,
    ListRecorder,
    ScriptedRunner,
    a_plan,
)
from agent_hub.core.workflows.engine import EnginePorts, run_workflow
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.ports import NodeCall, NodeReply


def git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - git with a fixed argv, no shell
        ["git", "-c", "user.name=Test", "-c", "user.email=test@example.com", *args],  # noqa: S607
        cwd=repo,
        check=True,
        capture_output=True,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    folder = tmp_path / "repo"
    folder.mkdir()
    git(folder, "init", "-q")
    (folder / "a.txt").write_text("one\n")
    git(folder, "add", "a.txt")
    git(folder, "commit", "-q", "-m", "start")
    return folder


def probe(*roots: Path) -> GitCheckoutProbe:
    return GitCheckoutProbe(roots=roots, environ=dict(os.environ))


def test_reads_the_same_status_when_nothing_changes(repo: Path, tmp_path: Path) -> None:
    other = tmp_path / "other"
    other.mkdir()
    git(other, "init", "-q")
    checkout = probe(repo, other)

    assert checkout.status() == checkout.status()


@pytest.mark.parametrize("change", ["add", "edit"])
def test_reads_another_status_when_a_file_is_added_or_edited(repo: Path, change: str) -> None:
    checkout = probe(repo)
    before = checkout.status()

    target = repo / ("new.txt" if change == "add" else "a.txt")
    target.write_text("two\n")

    assert checkout.status() != before


def test_fails_config_when_a_root_is_not_a_repository(tmp_path: Path) -> None:
    with pytest.raises(NodeFailedError) as caught:
        probe(tmp_path).status()

    assert caught.value.kind == "config"


class WritingRunner(ScriptedRunner):
    """Writes a file into ``repo`` while running node ``r``."""

    def __init__(self, repo: Path) -> None:
        super().__init__()
        self.repo = repo

    def run(self, call: NodeCall) -> NodeReply:
        (self.repo / f"{call.node.id}.out").write_text("x")
        return super().run(call)


def test_fails_a_read_only_node_config_when_it_writes_into_the_checkout(repo: Path) -> None:
    plan = a_plan({"id": "r", "type": "shell", "command": ["true"], "mutates_checkout": False})
    recorder = ListRecorder()
    ports = EnginePorts(
        WritingRunner(repo), recorder, FakeClock(), KeysOutputs(), lambda: 0.5, probe(repo)
    )

    report = run_workflow(plan, {}, ports)

    assert (recorder.end_of("r").status, recorder.end_of("r").failure_kind) == ("failed", "config")
    assert report.status == "failed"
