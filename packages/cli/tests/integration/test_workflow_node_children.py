"""Workflow node children are killed as a group (AGH-221 AC: shell and script nodes run as
children; a timeout leaves nothing behind before a retry starts another copy)."""

import dataclasses
import os
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.cli.child_process import ChildResult, run_child
from agent_hub.cli.workflow_executors import WorkflowExecutors
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.workflow_fakes import a_plan
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.core.workflows.nodes import ShellNode
from agent_hub.core.workflows.ports import NodeCall
from agent_hub.core.workflows.substitution import RefContext


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def runner_in(tmp_path: Path) -> WorkflowExecutors:
    return WorkflowExecutors(
        hub=tmp_path / "hub",
        config=HubConfig.model_validate(a_hub_document()),
        run_id="r1",
        pack_root=tmp_path,
        environ={"PATH": os.environ["PATH"]},
        hub_program=("/bin/false",),
    )


def shell_call(tmp_path: Path, script: str, **keys: object) -> tuple[NodeCall, Path]:
    pidfile = tmp_path / "hub" / "pid"
    pidfile.parent.mkdir(exist_ok=True)
    command = ["sh", "-c", script.replace("PIDFILE", str(pidfile))]
    node = a_plan({"id": "slow", "type": "shell", "command": command, **keys}).document.nodes[0]
    assert isinstance(node, ShellNode)
    return NodeCall(node, 1, RefContext({}, {}), argv=tuple(node.command)), pidfile


def gone(pidfile: Path) -> bool:
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    return not alive(pid)


def test_kills_background_process_when_node_times_out(tmp_path: Path) -> None:
    call, pidfile = shell_call(tmp_path, "sleep 30 & echo $! > PIDFILE; wait", timeout="1s")

    with pytest.raises(NodeFailedError) as raised:
        runner_in(tmp_path).run(call)

    assert raised.value.kind == "timeout"
    assert gone(pidfile)


def test_kills_background_process_when_node_exits_zero(tmp_path: Path) -> None:
    call, pidfile = shell_call(tmp_path, "sleep 30 & echo $! > PIDFILE")

    reply = runner_in(tmp_path).run(call)

    assert reply.text == ""
    assert gone(pidfile)


def test_kills_running_children_when_the_run_is_interrupted(tmp_path: Path) -> None:
    call, pidfile = shell_call(tmp_path, "sleep 30 & echo $! > PIDFILE; wait")
    runner = runner_in(tmp_path)
    failure: list[BaseException] = []

    def attempt() -> None:
        try:
            runner.run(call)
        except NodeFailedError as error:
            failure.append(error)

    worker = threading.Thread(target=attempt)
    worker.start()
    deadline = time.monotonic() + 5
    while not pidfile.exists() and time.monotonic() < deadline:
        time.sleep(0.05)

    runner.stop_children()
    worker.join(timeout=5)

    assert not worker.is_alive()
    assert failure
    assert gone(pidfile)


def test_spawns_nothing_when_the_children_were_stopped(tmp_path: Path) -> None:
    call, pidfile = shell_call(tmp_path, "echo $$ > PIDFILE")
    runner = runner_in(tmp_path)
    runner.stop_children()

    with pytest.raises(NodeFailedError) as raised:
        runner.run(call)

    assert raised.value.kind == "cancelled"
    assert not pidfile.exists()


def test_kills_a_child_when_it_starts_after_the_stop(tmp_path: Path) -> None:
    call, pidfile = shell_call(tmp_path, "sleep 30 & echo $! > PIDFILE; wait")
    runner = runner_in(tmp_path)

    def late(argv: Sequence[str], **options: Any) -> ChildResult:
        # The stop lands between the check before the spawn and the child's start.
        runner.stop_children()
        return run_child(argv, **options)

    started = time.monotonic()
    with pytest.raises(NodeFailedError):
        dataclasses.replace(runner, child=late, stop=runner.stop).run(call)

    assert time.monotonic() - started < 10
