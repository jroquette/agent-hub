"""Workflow node children are killed as a group (AGH-221 AC: shell and script nodes run as
children; a timeout leaves nothing behind before a retry starts another copy)."""

import os
import time
from pathlib import Path

import pytest

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


def test_kills_background_process_when_node_times_out(tmp_path: Path) -> None:
    pidfile = tmp_path / "hub" / "pid"
    pidfile.parent.mkdir()
    script = f"sleep 30 & echo $! > {pidfile}; wait"
    spec = {"id": "slow", "type": "shell", "command": ["sh", "-c", script], "timeout": "1s"}
    node = a_plan(spec).document.nodes[0]
    assert isinstance(node, ShellNode)
    runner = WorkflowExecutors(
        hub=tmp_path / "hub",
        config=HubConfig.model_validate(a_hub_document()),
        run_id="r1",
        pack_root=tmp_path,
        environ={"PATH": os.environ["PATH"]},
        hub_program=("/bin/false",),
    )

    with pytest.raises(NodeFailedError) as raised:
        runner.run(NodeCall(node, 1, RefContext({}, {}), argv=tuple(node.command)))

    assert raised.value.kind == "timeout"
    pid = int(pidfile.read_text())
    deadline = time.monotonic() + 5
    while alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not alive(pid)
