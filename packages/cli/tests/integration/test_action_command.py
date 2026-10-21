"""``hub action list|plan|run`` (AC-350.11, .12, .28, .46; docs/design/scenarios.md).

Each test builds a workspace under ``tmp_path``: a hub (``hub.json`` with the environments of
``an_environments_document``) holding the ``demo`` action pack, a git checkout with its own
identity, and runs the command in process with ``AGENT_HUB_ROOT`` naming the hub. Every script
appends its stdin to the file ``MARKER`` names, so a test sees which mode ran, if any.
"""

import json
import os
import pty
import re
import select
import shutil
import subprocess
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.testing.builders import an_environments_document
from agent_hub.storage.event_store import open_event_store

SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
case "$stdin" in
  *'"mode": "plan"'*) printf '{"summary": "would act"}' ;;
  *) printf '{"order": "o-1"}' ;;
esac
"""
ACTION = """\
version: 1
name: {name}
description: A demo {effect}
effect: {effect}
runtime: sh
script: scripts/{name}.sh
inputs:
  target: {{type: service, required: true}}
  count: {{type: integer, default: 1}}
output_format:
  type: object
  required: [order]
  properties: {{order: {{type: string}}}}
"""


def git(hub: Path, *args: str) -> None:
    found = shutil.which("git")
    assert found is not None
    identity = ("-c", "user.name=Demo Dev", "-c", "user.email=dev@example.com")
    command = [found, *identity, *args]
    subprocess.run(command, cwd=hub, check=True, capture_output=True)  # noqa: S603 - absolute git, fixed arguments


def write_action(hub: Path, name: str, effect: str) -> None:
    pack = hub / "actions" / "demo"
    (pack / "scripts").mkdir(parents=True, exist_ok=True)
    (pack / f"{name}.yaml").write_text(ACTION.format(name=name, effect=effect))
    (pack / "scripts" / f"{name}.sh").write_text(SCRIPT)


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """A committed hub with the read action ``get-order`` and the write ``send-order``."""
    root = tmp_path / "workspace" / "hub"
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (root / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    write_action(root, "get-order", "read")
    write_action(root, "send-order", "write")
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "demo hub")
    return root


@pytest.fixture
def marker(tmp_path: Path) -> Path:
    return tmp_path / "marker"


def run_action_command(hub: Path, marker: Path, *args: str, **env: str) -> Result:
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **env,
    }
    return CliRunner().invoke(app, ["action", *args], env=environ, input="")


def modes(marker: Path) -> list[str]:
    if not marker.exists():
        return []
    return [json.loads(line)["mode"] for line in marker.read_text().splitlines()]


def stored(hub: Path) -> list[tuple[str, dict[str, object]]]:
    database = hub.parent.parent / "events.db"
    if not database.exists():
        return []
    return [(event.type, event.payload) for event in open_event_store(database).read_all()]


def test_lists_actions_with_draft_when_list_runs(hub: Path, marker: Path) -> None:
    write_action(hub, "fix-order", "destroy")
    (hub / "actions" / "demo" / "scripts" / "get-order.sh").write_text(SCRIPT + "\n")

    result = run_action_command(hub, marker, "list")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "demo/fix-order  destroy  target (service), count (integer)  draft",
        "demo/get-order  read  target (service), count (integer)  draft",
        "demo/send-order  write  target (service), count (integer)",
    ]
    listed = json.loads(run_action_command(hub, marker, "list", "--json").stdout)
    assert [(item["action"], item["draft"]) for item in listed["actions"]] == [
        ("demo/fix-order", True),
        ("demo/get-order", True),
        ("demo/send-order", False),
    ]
    assert listed["actions"][2]["inputs"] == {"target": "service", "count": "integer"}
    assert modes(marker) == []


def test_prints_no_actions_yet_when_empty_hub(tmp_path: Path, marker: Path) -> None:
    root = tmp_path / "workspace" / "hub"
    root.mkdir(parents=True)
    document = an_environments_document()
    document["platform"]["version"] = version("agent-hub-cli")
    (root / "hub.json").write_text(json.dumps(document) + "\n")

    result = run_action_command(root, marker, "list")

    assert (result.exit_code, result.stdout) == (0, "no actions yet\n")


@pytest.mark.parametrize(
    "args",
    [
        ("plan", "demo/get-order"),
        ("plan", "demo/get-order", "--env", "staging", "--input", "no-equals"),
        ("run", "demo/get-order", "--env"),
        ("unknown",),
        ("list", "--yes"),
        ("run", "demo/send-order", "--env", "staging", "--yes"),
    ],
)
def test_exits_two_when_action_usage_wrong(hub: Path, marker: Path, args: tuple[str, ...]) -> None:
    result = run_action_command(hub, marker, *args)

    assert result.exit_code == 2, result.output
    assert modes(marker) == []


def test_starts_no_run_process_when_standalone_plan(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "plan", "demo/send-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 0, result.output
    assert result.stdout.splitlines() == [
        "action: demo/send-order (write)",
        "environment: staging (access ask)",
        "inputs: target=api, count=1",
        "endpoints: target → demo-api/api https://api.staging.example.com",
        f"content hash: {content_hash(hub, 'send-order')}",
        "draft: no",
        "plan: would act",
        "decision: ask",
    ]
    assert modes(marker) == ["plan"]
    assert stored(hub) == []


def test_exits_one_naming_reason_when_standalone_plan_denies(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "plan", "send-order", "--env", "live", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stdout.splitlines()[-1] == (
        "decision: deny (live is a production environment: writes and destroys are denied)"
    )


@pytest.mark.parametrize(
    "case",
    [
        (("--env", "qa", "--input", "target=api"), "environment qa is not declared"),
        (("--env", "live", "--input", "target=orders"), "has no endpoint in environment live"),
        (
            ("--env", "staging", "--input", "target=api", "--input", "count=two"),
            "input count must be of type integer",
        ),
        (
            (
                "--env",
                "staging",
            ),
            "input target is required",
        ),
    ],
)
def test_exits_one_naming_problem_when_standalone_plan_cannot_resolve(
    hub: Path, marker: Path, case: tuple[tuple[str, ...], str]
) -> None:
    given, line = case

    result = run_action_command(hub, marker, "plan", "demo/get-order", *given)

    assert result.exit_code == 1, result.output
    assert line in result.stderr
    assert modes(marker) == []


def content_hash(hub: Path, name: str) -> str:
    listed = json.loads(
        CliRunner()
        .invoke(app, ["action", "list", "--json"], env={"AGENT_HUB_ROOT": str(hub)})
        .stdout
    )
    return next(item["content_hash"] for item in listed["actions"] if item["name"] == name)


def run_in_terminal(hub: Path, marker: Path, *args: str, answer: str) -> tuple[int, str]:
    """``hub action run`` in a pseudo-terminal: ``answer`` is typed once a ``[y/N]`` prompt
    shows; the exit code and everything the terminal showed."""
    environ = {
        **os.environ,
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
    }
    main, child = pty.openpty()
    argv = [sys.executable, "-m", "agent_hub.cli", "action", "run", *args]
    process = subprocess.Popen(  # noqa: S603 - this interpreter, fixed arguments
        argv, stdin=child, stdout=child, stderr=child, env=environ, close_fds=True
    )
    os.close(child)
    shown, answered = b"", False
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        ready, _, _ = select.select([main], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(main, 4096)
            except OSError:
                break
            if not chunk:
                break
            shown += chunk
        if not answered and b"[y/N]" in shown:
            os.write(main, answer.encode() + b"\n")
            answered = True
        if process.poll() is not None and not ready:
            break
    os.close(main)
    return process.wait(timeout=30), shown.decode(errors="replace")


def test_lists_three_subcommands_when_action_help(hub: Path, marker: Path) -> None:
    result = run_action_command(hub, marker, "--help")

    assert result.exit_code == 0, result.output
    # Rich colours the panel when CI forces a terminal; match the words only.
    help_text = re.sub(r"\x1b\[[0-9;]*m", "", result.stdout)
    for command in ("list", "plan", "run"):
        # A line of the commands panel: the name, then its help after two or more spaces.
        assert re.search(rf"^\W+{command}\s{{2,}}\S", help_text, re.MULTILINE), command


def test_runs_read_when_standalone_without_terminal(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "run", "demo/get-order", "--env", "staging", "--input", "target=orders"
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"order": "o-1"}
    assert modes(marker) == ["run"]
    events = stored(hub)
    assert [kind for kind, _ in events] == ["policy.decision", "action.start", "action.end"]
    decided, _, ended = (payload for _, payload in events)
    assert (decided["decision"], decided["origin"], decided["reason_kind"]) == (
        "allow",
        "human",
        "table",
    )
    assert (ended["status"], ended["service"]) == ("ok", ["demo-api/orders"])
    sessions = {
        event.session for event in open_event_store(hub.parent.parent / "events.db").read_all()
    }
    assert len(sessions) == 1
    assert next(iter(sessions)).startswith("action:")


def test_refuses_write_when_standalone_without_terminal(hub: Path, marker: Path) -> None:
    result = run_action_command(
        hub, marker, "run", "demo/send-order", "--env", "local", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        "hub action run: write and destroy actions need a terminal or a scenario run\n"
    )
    assert modes(marker) == []
    assert stored(hub) == [
        (
            "policy.decision",
            {
                "attempt": 1,
                "action": "demo/send-order",
                "environment": "local",
                "effect": "write",
                "origin": "human",
                "decision": "deny",
                "reason_kind": "read_only",
            },
        )
    ]


def test_prompts_and_runs_nothing_when_standalone_terminal_answers_n(
    hub: Path, marker: Path
) -> None:
    code, shown = run_in_terminal(
        hub, marker, "demo/send-order", "--env", "staging", "--input", "target=api", answer="n"
    )

    assert code == 1, shown
    assert "run demo/send-order (write) in staging? [y/N]" in shown
    assert modes(marker) == []
    assert [(kind, payload["decision"]) for kind, payload in stored(hub)] == [
        ("policy.decision", "ask")
    ]


def test_runs_with_approver_when_standalone_terminal_answers_y(hub: Path, marker: Path) -> None:
    code, shown = run_in_terminal(
        hub, marker, "demo/send-order", "--env", "staging", "--input", "target=api", answer="y"
    )

    assert code == 0, shown
    assert modes(marker) == ["run"]
    ended = stored(hub)[-1]
    assert ended[0] == "action.end"
    assert ended[1]["approver"]


def test_denies_before_prompt_when_standalone_deny(hub: Path, marker: Path) -> None:
    code, shown = run_in_terminal(
        hub, marker, "demo/send-order", "--env", "live", "--input", "target=api", answer="y"
    )

    assert code == 1, shown
    assert "[y/N]" not in shown
    assert "live is a production environment: writes and destroys are denied" in shown
    assert modes(marker) == []
    assert [(kind, payload["reason_kind"]) for kind, payload in stored(hub)] == [
        ("policy.decision", "production")
    ]


def test_refuses_draft_when_action_uncommitted(hub: Path, marker: Path) -> None:
    (hub / "actions" / "demo" / "scripts" / "get-order.sh").write_text(SCRIPT + "# edited\n")

    result = run_action_command(
        hub, marker, "run", "get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert "deny (draft action: commit it to run)" in result.stderr
    assert modes(marker) == []
    assert [(kind, payload["reason_kind"]) for kind, payload in stored(hub)] == [
        ("policy.decision", "draft")
    ]


def test_runs_when_draft_committed(hub: Path, marker: Path) -> None:
    (hub / "actions" / "demo" / "scripts" / "get-order.sh").write_text(SCRIPT + "# edited\n")
    git(hub, "commit", "-q", "-am", "edit get-order")

    result = run_action_command(
        hub, marker, "run", "get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 0, result.output
    assert modes(marker) == ["run"]


ENV_FILE = "demo-api/environment/.env.staging"
ENV_FILE_CAUSES = (
    "missing",
    "unreadable",
    "too large",
    "not a regular file",
    "outside the workspace",
    "not a dotenv file (line 2)",
)


def declare_env_file(hub: Path) -> Path:
    """``staging`` names ``ENV_FILE``; the path it stands at, in the workspace."""
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env_file": ENV_FILE,
    }
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    git(hub, "commit", "-q", "-am", "staging reads an env file")
    path = hub.parent / ENV_FILE
    path.parent.mkdir(parents=True)
    return path


ENV_SECRET = "x-" + "secret" + "-y"


@pytest.fixture(params=ENV_FILE_CAUSES)
def env_file_cause(
    hub: Path, monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> str:
    """``staging``'s env file made unusable for one cause; the cause's words."""
    cause: str = request.param
    path = declare_env_file(hub)
    good = f"DEMO_DB_URL={ENV_SECRET}\n"
    if cause == "unreadable":
        path.write_text(good)
        path.chmod(0)
        if os.geteuid() == 0:
            refuse_open(monkeypatch, path)
    elif cause == "too large":
        path.write_text(good + "#" * (64 * 1024))
    elif cause == "not a regular file":
        os.mkfifo(path)
    elif cause == "outside the workspace":
        outside = hub.parent.parent / "outside.env"
        outside.write_text(good)
        path.symlink_to(outside)
    elif cause.startswith("not a dotenv"):
        path.write_text(f"{good}not a line {ENV_SECRET}\n")
    return cause


def refuse_open(monkeypatch: pytest.MonkeyPatch, path: Path) -> None:
    """Root reads a mode-0 file: the refusal the kernel gives others is played here."""
    real_open = os.open

    def refusing(file: Any, *args: Any, **kwargs: Any) -> int:
        # The loader opens the file by its name in its folder (``dir_fd``).
        if os.fspath(file) in (str(path), path.name):
            raise PermissionError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(os, "open", refusing)


def test_fails_plainly_when_env_file_missing_for_action(
    hub: Path, marker: Path, env_file_cause: str
) -> None:
    cause, secret = env_file_cause, ENV_SECRET
    result = run_action_command(
        hub, marker, "run", "demo/get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        f"hub action run: demo/get-order: config: environment staging: env file {ENV_FILE}"
        f" is {cause}\n"
    )
    assert modes(marker) == []
    assert secret not in result.output
    events = stored(hub)
    assert [kind for kind, _ in events] == ["policy.decision", "action.start", "action.end"]
    assert events[-1][1]["failure_kind"] == "config"
    assert secret not in json.dumps([payload for _, payload in events])


def declare_env_file_at(hub: Path, relative: str) -> Path:
    """``staging`` names the env file ``relative``; its path in the workspace, holding a value."""
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["staging"]["credentials"] = {"env_file": relative}
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    git(hub, "commit", "-q", "-am", "staging reads an env file")
    path = hub.parent / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"DEMO_DB_URL={ENV_SECRET}\n")
    return path


def test_fails_plainly_when_env_file_outside_hub_and_repos(hub: Path, marker: Path) -> None:
    declare_env_file_at(hub, "elsewhere/.env.staging")

    result = run_action_command(
        hub, marker, "run", "demo/get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        "hub action run: demo/get-order: config: environment staging: env file"
        " elsewhere/.env.staging is outside the hub and its repos\n"
    )
    assert modes(marker) == []
    assert ENV_SECRET not in result.output


def test_runs_when_env_file_in_hub(hub: Path, marker: Path) -> None:
    declare_env_file_at(hub, f"{hub.name}/environment/.env.staging")

    result = run_action_command(
        hub, marker, "run", "demo/get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 0, result.output
    assert modes(marker) == ["run"]


def test_fails_plainly_when_env_file_folder_is_a_link(hub: Path, marker: Path) -> None:
    # Real path in the repo, but reached through a linked folder: a link could be swapped
    # between the check and the read, so no link is followed on the way to the file.
    real = hub.parent / "demo-api" / "real-env"
    real.mkdir(parents=True)
    (hub.parent / "demo-api" / "environment").symlink_to(real)
    (real / ".env.staging").write_text(f"DEMO_DB_URL={ENV_SECRET}\n")
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["staging"]["credentials"] = {"env_file": ENV_FILE}
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")

    result = run_action_command(
        hub, marker, "run", "demo/get-order", "--env", "staging", "--input", "target=api"
    )

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        f"hub action run: demo/get-order: config: environment staging: env file {ENV_FILE}"
        " is reached through a link\n"
    )
    assert modes(marker) == []
    assert ENV_SECRET not in result.output


def test_runs_nothing_when_standalone_terminal_ends_input_at_prompt(
    hub: Path, marker: Path
) -> None:
    # Ctrl-D at the start of a line ends the terminal's input: the prompt reads end of file.
    code, shown = run_in_terminal(
        hub, marker, "demo/send-order", "--env", "staging", "--input", "target=api", answer="\x04"
    )

    assert code == 1, shown
    assert "hub action run: demo/send-order: not run" in shown
    assert modes(marker) == []
    assert [(kind, payload["decision"]) for kind, payload in stored(hub)] == [
        ("policy.decision", "ask")
    ]


# AGH-360 (AC-350.20, AC-350.41): an investigation's reads, ``hub action run --run``.
# ``hold-walk`` runs its one read step in staging, which fails until the file ``HELD`` names
# exists, so the scenario run pauses at an investigation.

HELD_SCRIPT = """\
stdin=$(cat)
if [ ! -e "$HELD" ]; then
  exit 3
fi
printf '{"order": "o-1"}'
"""
ENV_SCRIPT = """\
stdin=$(cat)
printf '%s\\n' "$stdin" >> "$MARKER"
printf '%s %s\\n' "$AWS_PROFILE" "$DEMO_DB_URL" >> "$ENV_MARKER"
printf '{"order": "%s"}' "$DEMO_DB_URL"
"""
HOLD_WALK = """\
version: 1
kind: scenario
name: hold-walk
revision: 1
nodes:
  - id: order-held
    type: action
    action: held-order
    with: {target: api}
"""
RUN = "walk-1"


def investigation_env(hub: Path, marker: Path) -> dict[str, str]:
    return {
        "HELD": str(hub.parent.parent / "released"),
        "ENV_MARKER": str(marker.parent / "env-marker"),
    }


def paused_walk(hub: Path, marker: Path) -> None:
    """Commit ``hold-walk`` and its action, then run it to its first investigation."""
    write_action(hub, "held-order", "read")
    (hub / "actions" / "demo" / "scripts" / "held-order.sh").write_text(HELD_SCRIPT)
    write_action(hub, "env-check", "read")
    (hub / "actions" / "demo" / "scripts" / "env-check.sh").write_text(ENV_SCRIPT)
    scenario = hub / "scenarios" / "demo" / "hold-walk.yaml"
    scenario.parent.mkdir(parents=True)
    scenario.write_text(HOLD_WALK)
    git(hub, "add", "-A")
    git(hub, "commit", "-q", "-m", "hold walk")
    environ = {
        "AGENT_HUB_ROOT": str(hub),
        "MARKER": str(marker),
        "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
        **investigation_env(hub, marker),
    }
    args = ["scenario", "run", "hold-walk", "--env", "staging", "--run-id", RUN]
    started = CliRunner().invoke(app, args, env=environ, input="")
    assert started.exit_code == 0, started.output
    assert "paused at order-held (investigation)" in started.stdout


def run_records(hub: Path) -> list[dict[str, Any]]:
    path = hub / ".agent-runs" / "workflows" / RUN / "records.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()]


def agent_read(hub: Path, marker: Path, action: str, *extra: str) -> Result:
    return run_action_command(
        hub,
        marker,
        "run",
        action,
        "--run",
        RUN,
        "--input",
        "target=api",
        *extra,
        **investigation_env(hub, marker),
    )


def run_events(hub: Path) -> list[tuple[str, dict[str, object]]]:
    database = hub.parent.parent / "events.db"
    return [
        (event.type, event.payload)
        for event in open_event_store(database).read_all()
        if event.session == f"run:{RUN}" and event.type in ("policy.decision", "action.start")
    ]


def test_refuses_write_and_records_deny_when_investigation_read_only_run(
    hub: Path, marker: Path
) -> None:
    paused_walk(hub, marker)

    result = agent_read(hub, marker, "demo/send-order")

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        "hub action run: demo/send-order in staging: an investigation runs read actions only\n"
    )
    assert modes(marker) == []
    decided = [payload for kind, payload in run_events(hub) if kind == "policy.decision"]
    assert [
        (item["action"], item["origin"], item["decision"], item["reason_kind"]) for item in decided
    ][-1] == ("demo/send-order", "agent", "deny", "read_only")
    (line,) = [line for line in run_records(hub) if line["event"] == "agent_action"]
    assert (line["action"], line["origin"], line["status"], line["reason_kind"]) == (
        "demo/send-order",
        "agent",
        "refused",
        "read_only",
    )


def test_records_read_with_agent_origin_when_investigation_read_only_run(
    hub: Path, marker: Path
) -> None:
    paused_walk(hub, marker)

    result = agent_read(hub, marker, "demo/get-order")

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {"order": "o-1"}
    assert modes(marker) == ["run"]
    (line,) = [line for line in run_records(hub) if line["event"] == "agent_action"]
    assert (line["gate"], line["origin"], line["decision"], line["status"]) == (
        "order-held__investigation",
        "agent",
        "allow",
        "ok",
    )
    agent = [payload for _, payload in run_events(hub) if payload.get("origin") == "agent"]
    assert [(item["action"], item["decision"]) for item in agent] == [
        ("demo/get-order", "allow"),
        ("demo/get-order", "allow"),
    ]


def test_refuses_when_run_not_paused_at_investigation(hub: Path, marker: Path) -> None:
    missing = agent_read(hub, marker, "demo/get-order")
    paused_walk(hub, marker)
    (hub.parent.parent / "released").touch()
    answered = CliRunner().invoke(
        app,
        ["workflow", "respond", RUN, "--node", "order-held__investigation", "--choice", "retry"],
        env={
            "AGENT_HUB_ROOT": str(hub),
            "MARKER": str(marker),
            "AGENT_HUB_DB": str(hub.parent.parent / "events.db"),
            **investigation_env(hub, marker),
        },
        input="",
    )

    done = agent_read(hub, marker, "demo/get-order")
    elsewhere = agent_read(hub, marker, "demo/get-order", "--env", "local")

    assert missing.exit_code == 1, missing.output
    assert missing.stderr == f"hub action run: no scenario run {RUN}\n"
    assert answered.exit_code == 0, answered.output
    assert done.exit_code == 1, done.output
    assert (
        done.stderr
        == f"hub action run: scenario run {RUN} is not paused at an open investigation\n"
    )
    assert elsewhere.exit_code == 1, elsewhere.output
    assert modes(marker) == []
    assert [line for line in run_records(hub) if line["event"] == "agent_action"] == []


def test_injects_env_file_when_investigation_credentials_read(hub: Path, marker: Path) -> None:
    path = declare_env_file(hub)
    path.write_text(f"DEMO_DB_URL={ENV_SECRET}\n")
    paused_walk(hub, marker)

    # The caller's environment (an agent session's) has no DEMO_DB_URL and no AWS_PROFILE.
    result = run_action_command(
        hub,
        marker,
        "run",
        "demo/env-check",
        "--run",
        RUN,
        "--input",
        "target=api",
        **investigation_env(hub, marker),
    )

    assert result.exit_code == 0, result.output
    assert "DEMO_DB_URL" not in os.environ
    seen = (marker.parent / "env-marker").read_text()
    assert seen == f"demo-staging {ENV_SECRET}\n"
    assert json.loads(result.stdout) == {"order": "<credential DEMO_DB_URL>"}
    assert ENV_SECRET not in result.output
    (line,) = [line for line in run_records(hub) if line["event"] == "agent_action"]
    assert (line["origin"], line["status"]) == ("agent", "ok")
    folder = hub / ".agent-runs" / "workflows" / RUN
    for item in folder.rglob("*"):
        if item.is_file():
            assert ENV_SECRET.encode() not in item.read_bytes(), item
    assert ENV_SECRET not in json.dumps([payload for _, payload in stored(hub)])
    assert ENV_SECRET.encode() not in (hub.parent.parent / "events.db").read_bytes()


# AGH-360 review round 1: another environment, a draft and an always read-only --run.


def test_refuses_other_environment_when_investigation_read_only_run_paused(
    hub: Path, marker: Path
) -> None:
    paused_walk(hub, marker)

    result = agent_read(hub, marker, "demo/get-order", "--env", "local")

    assert result.exit_code == 1, result.output
    assert result.stderr == f"hub action run: scenario run {RUN} runs in staging, not local\n"
    assert modes(marker) == []
    assert [line for line in run_records(hub) if line["event"] == "agent_action"] == []


def test_denies_draft_when_investigation_read_only_run_reads_draft(hub: Path, marker: Path) -> None:
    paused_walk(hub, marker)
    write_action(hub, "peek-order", "read")

    result = agent_read(hub, marker, "demo/peek-order")

    assert result.exit_code == 1, result.output
    assert "draft action: commit it to run" in result.stderr
    assert modes(marker) == []
    (line,) = [line for line in run_records(hub) if line["event"] == "agent_action"]
    assert (line["decision"], line["reason_kind"], line["status"]) == ("deny", "draft", "refused")
    decided = [payload for kind, payload in run_events(hub) if kind == "policy.decision"]
    assert (decided[-1]["origin"], decided[-1]["reason_kind"]) == ("agent", "draft")


def test_records_read_only_when_investigation_read_only_run_writes_where_table_denies(
    hub: Path, marker: Path
) -> None:
    document = json.loads((hub / "hub.json").read_text())
    document["environments"]["staging"]["access"] = "read"
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    paused_walk(hub, marker)

    result = agent_read(hub, marker, "demo/send-order")

    assert result.exit_code == 1, result.output
    assert result.stderr == (
        "hub action run: demo/send-order in staging: an investigation runs read actions only\n"
    )
    (line,) = [line for line in run_records(hub) if line["event"] == "agent_action"]
    assert (line["decision"], line["reason_kind"]) == ("deny", "read_only")
    decided = [payload for kind, payload in run_events(hub) if kind == "policy.decision"]
    assert (decided[-1]["decision"], decided[-1]["reason_kind"]) == ("deny", "read_only")
