"""An action's script contract (AC-350.7, docs/design/scenarios.md § Actions and the script
contract): one JSON object on stdin, one JSON value out, plan mode without credentials.

Each test writes a synthetic ``actions/demo/`` pack under ``tmp_path``, loads it with the
generator's discovery (which pins the files the process gets, E-4) and runs the real script.
"""

import json
import os
import time
from pathlib import Path

import pytest

from agent_hub.cli.action_process import ActionCall, plan_action, run_action
from agent_hub.core.scenarios.credentials import CredentialNames
from agent_hub.core.workflows.failures import NodeFailedError
from agent_hub.generator.action_discovery import discover_actions

SECRET = "x-" + "secret" + "-y"
ACTION = """\
version: 1
name: send
description: Send one demo message
effect: write
runtime: sh
script: scripts/send.sh
timeout: {timeout}
inputs:
  queue: {{type: service, required: true}}
  message_type: {{type: string, required: true}}
output_format:
  type: object
  required: [message_id]
  properties: {{message_id: {{type: string}}}}
"""
ENDPOINT = {"queue": {"url": "https://queue.staging.example.com/demo", "resource": None}}


def an_action_call(hub: Path, script: str, *, timeout: str = "1m") -> ActionCall:
    pack = hub / "actions" / "demo"
    (pack / "scripts").mkdir(parents=True)
    (pack / "send.yaml").write_text(ACTION.format(timeout=timeout))
    (pack / "scripts" / "send.sh").write_text(script)
    (pack / "scripts" / "lib.sh").write_text("MESSAGE=m-1\n")
    (pack / "scripts" / ".notes").write_text("not pinned\n")
    found = discover_actions(hub)
    assert found.problems == ()
    (entry,) = found.actions
    return ActionCall(
        entry=entry,
        files=found.files[entry.document_path],
        inputs={"queue": "orders-queue", "message_type": "DEMO_FETCH"},
        endpoint=ENDPOINT,
    )


@pytest.fixture
def dump(tmp_path: Path) -> Path:
    folder = tmp_path / "dump"
    folder.mkdir()
    return folder


@pytest.fixture
def environ(dump: Path) -> dict[str, str]:
    return {"PATH": os.environ["PATH"], "DUMP": str(dump), "DEMO_DB_URL": SECRET}


def test_sends_run_stdin_when_action_script_contract_run_mode(
    tmp_path: Path, dump: Path, environ: dict[str, str]
) -> None:
    script = (
        'cat > "$DUMP/stdin.json"\n'
        'ls -a "$(dirname "$0")" > "$DUMP/listing"\n'
        '. "$(dirname "$0")/lib.sh"\n'
        'printf \'{"message_id": "%s"}\' "$MESSAGE"\n'
    )
    call = an_action_call(tmp_path / "hub", script)

    output = run_action(call, environ=environ)

    assert output == {"message_id": "m-1"}
    assert json.loads((dump / "stdin.json").read_text()) == {
        "mode": "run",
        "inputs": {"queue": "orders-queue", "message_type": "DEMO_FETCH"},
        "endpoint": ENDPOINT,
    }
    # Only the pinned files: the script, its helper, never a dot file of the pack's scripts/.
    assert (dump / "listing").read_text().split() == [".", "..", "lib.sh", "send.sh"]


@pytest.mark.parametrize(
    "printed",
    ['{"other": 1}', "not json", '{"message_id": "a"} {"message_id": "b"}', ""],
)
def test_fails_output_contract_when_action_script_contract_output_mismatch(
    tmp_path: Path, environ: dict[str, str], printed: str
) -> None:
    call = an_action_call(tmp_path / "hub", f"printf '%s' '{printed}'\n")

    with pytest.raises(NodeFailedError) as raised:
        run_action(call, environ=environ)

    assert raised.value.kind == "output_contract"


def test_sends_plan_stdin_without_credentials_when_action_script_contract_plan_mode(
    tmp_path: Path, dump: Path, environ: dict[str, str]
) -> None:
    script = (
        'cat > "$DUMP/stdin.json"\n'
        'env > "$DUMP/env"\n'
        'printf \'{"summary": "would send DEMO_FETCH"}\'\n'
    )
    call = an_action_call(tmp_path / "hub", script)
    names = CredentialNames(env=frozenset({"DEMO_DB_URL"}))

    row = plan_action(call, environ={**environ, "LINEAR_API_KEY": "k" * 8}, hidden=names)

    assert row == "would send DEMO_FETCH"
    assert json.loads((dump / "stdin.json").read_text())["mode"] == "plan"
    seen = (dump / "env").read_text()
    assert "DEMO_DB_URL" not in seen
    assert SECRET not in seen
    assert "LINEAR_API_KEY" not in seen


def test_fails_when_stdout_over_cap(tmp_path: Path, environ: dict[str, str]) -> None:
    script = "head -c 524289 /dev/zero | tr '\\0' 'a'\n"
    call = an_action_call(tmp_path / "hub", script)

    with pytest.raises(NodeFailedError) as raised:
        run_action(call, environ=environ)

    assert raised.value.kind == "output_contract"
    assert "larger than 524288 bytes" in str(raised.value)


def test_kills_group_when_action_times_out(
    tmp_path: Path, dump: Path, environ: dict[str, str]
) -> None:
    script = 'sleep 30 & echo $! > "$DUMP/pid"; wait\n'
    call = an_action_call(tmp_path / "hub", script, timeout="1s")

    with pytest.raises(NodeFailedError) as raised:
        run_action(call, environ=environ)

    assert raised.value.kind == "timeout"
    pid = int((dump / "pid").read_text())
    deadline = time.monotonic() + 5
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not _alive(pid)


@pytest.mark.parametrize(
    "case",
    [
        ("printf '{\"nope\": 1}'\n", "plan failed: output_contract"),
        (f'printf \'{{"summary": "{"a" * 201}"}}\'\n', "plan failed: output_contract"),
        ("printf '[\"summary\"]'\n", "plan failed: output_contract"),
        ("exit 3\n", "plan failed: exec_failed"),
    ],
)
def test_marks_row_when_plan_mode_output_invalid(
    tmp_path: Path, environ: dict[str, str], case: tuple[str, str]
) -> None:
    script, row = case
    call = an_action_call(tmp_path / "hub", script)

    assert plan_action(call, environ=environ) == row


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def test_redacts_credentials_when_action_script_contract_fails(
    tmp_path: Path, environ: dict[str, str]
) -> None:
    script = 'echo "cannot reach $DEMO_TOKEN with key $DEMO_KEY" >&2\nexit 3\n'
    call = an_action_call(tmp_path / "hub", script)
    injected = {"DEMO_TOKEN": SECRET, "DEMO_KEY": "abc"}

    with pytest.raises(NodeFailedError) as raised:
        run_action(call, environ=environ, credentials=injected)

    assert raised.value.kind == "exec_failed"
    assert "cannot reach <credential DEMO_TOKEN> with key abc" in str(raised.value)
    assert SECRET not in str(raised.value)


def test_redacts_credential_cut_by_tail_when_action_script_contract_fails(
    tmp_path: Path, environ: dict[str, str]
) -> None:
    # The detail keeps stderr's last 1500 characters: that tail starts 20 characters into the
    # value, so cutting before redacting would leave the value's last 20 characters.
    value = SECRET + "-" + "q7w8e9r0t1" * 3
    script = (
        "printf '%s' \"$DEMO_TOKEN\" >&2\n"
        f"head -c {1500 - 20} /dev/zero | tr '\\0' 'z' >&2\n"
        "exit 3\n"
    )
    call = an_action_call(tmp_path / "hub", script)

    with pytest.raises(NodeFailedError) as raised:
        run_action(call, environ=environ, credentials={"DEMO_TOKEN": value})

    detail = str(raised.value)
    leaked = [value[i : i + 4] for i in range(len(value) - 3) if value[i : i + 4] in detail]
    assert leaked == []
