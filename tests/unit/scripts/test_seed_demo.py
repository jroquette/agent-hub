import json
import subprocess
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path, PurePosixPath
from typing import Any

import httpx
import pytest

from agent_hub.core.features.feature_evals import eval_coverage, eval_records
from agent_hub.core.features.feature_record import FeatureRecordFile
from agent_hub.core.features.feature_reviews import approved_tickets, review_records
from agent_hub.core.features.feature_status import RecordHead
from agent_hub.core.features.ticket_planning import ticket_board
from agent_hub.core.testing.transcript_lines import TRANSCRIPT_MODEL
from scripts.seed_demo import (
    ASK_SESSION,
    BACKFILL_SESSION,
    DEMO_BRANCH,
    DEMO_PROJECT,
    FEATURE,
    INBOX_NOTE,
    ISSUE,
    LIVE_SESSION,
    STUCK_SESSION,
    ComposeTarget,
    LocalTarget,
    choose_target,
    demo_envelopes,
    demo_transcript,
    hub_files,
    main,
)

NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
URL = "http://127.0.0.1:7420"
HUB = PurePosixPath("/data/demo/demo-hub")
FOLDER = HUB / "brain" / "features" / FEATURE


class FakeTarget:
    """Records what the seed writes and the hub commands it runs; answers each command 0."""

    def __init__(self, workdir: str = "/data/demo", *, init_stderr: str = "") -> None:
        self.workdir = PurePosixPath(workdir)
        self.files: dict[str, str] = {}
        self.commands: list[list[str]] = []
        self._init_stderr = init_stderr

    def write(self, path: PurePosixPath, text: str) -> None:
        self.files[str(path)] = text

    def hub(self, arguments: Sequence[str]) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(arguments))
        if arguments[0] == "init" and self._init_stderr:
            return subprocess.CompletedProcess(arguments, 1, "", self._init_stderr)
        return subprocess.CompletedProcess(arguments, 0, "appended 1, duplicates 0\n", "")


class FakeServer:
    """The control plane's routes the seed calls, recording the posted bodies."""

    def __init__(self, *, hubs_status: int = 201) -> None:
        self.hubs: list[dict[str, Any]] = []
        self.envelopes: list[dict[str, Any]] = []
        self._hubs_status = hubs_status

    def __call__(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.method == "GET" and path == "/api/v1/collector/status":
            return httpx.Response(200, json={"db_path": "/data/agent-hub.db"})
        if request.method == "POST" and path == "/api/v1/hubs":
            self.hubs.append(json.loads(request.content))
            return httpx.Response(self._hubs_status, json={})
        if request.method == "POST" and path == "/api/v1/events/hooks":
            self.envelopes.append(json.loads(request.content))
            return httpx.Response(202, json={})
        return httpx.Response(404, json={})


def test_sends_live_idle_and_waiting_sessions_when_envelopes_built() -> None:
    envelopes = demo_envelopes(NOW)

    by_session: dict[str, list[datetime]] = {}
    for envelope in envelopes:
        sent = datetime.fromisoformat(envelope["sent_at"])
        by_session.setdefault(envelope["hook"]["session_id"], []).append(sent)
    decisions = [envelope.get("decision") for envelope in envelopes]
    suffix = "20261011120000"
    assert set(by_session) == {
        f"{LIVE_SESSION}-{suffix}",
        f"{ASK_SESSION}-{suffix}",
        f"{STUCK_SESSION}-{suffix}",
    }
    assert {"by": "guard", "kind": "deny", "rule": "push-to-main"} in decisions
    assert {"by": "guard", "kind": "ask", "rule": "ask_before_edit"} in decisions
    assert all(envelope["project"] == DEMO_PROJECT for envelope in envelopes)
    # Live and waiting: active in the last 5 minutes; idle: quiet for 5 to 30 minutes.
    for session, times in by_session.items():
        oldest = (
            timedelta(minutes=30) if session.startswith(STUCK_SESSION) else timedelta(minutes=5)
        )
        newest = timedelta(minutes=5) if session.startswith(STUCK_SESSION) else timedelta(0)
        assert all(NOW - oldest < sent <= NOW - newest for sent in times), session


def test_runs_feature_skill_subagent_and_recovered_check_when_live_session_built() -> None:
    live = [
        envelope["hook"]
        for envelope in demo_envelopes(NOW)
        if envelope["hook"]["session_id"].startswith(LIVE_SESSION)
    ]

    names = [hook["hook_event_name"] for hook in live]
    tools = [hook.get("tool_name") for hook in live if hook["hook_event_name"] == "PreToolUse"]
    assert live[1]["prompt"].startswith("/feature ")
    assert tools[:3] == ["Skill", "Agent", "Grep"]
    assert {"SubagentStart", "SubagentStop", "PostToolUseFailure"} <= set(names)
    assert all(hook["cwd"].endswith("/.claude/worktrees/agh-7-demo-feature") for hook in live)
    [failure] = [hook for hook in live if hook["hook_event_name"] == "PostToolUseFailure"]
    retried = [hook for hook in live if hook.get("tool_input") == failure["tool_input"]]
    assert [hook["hook_event_name"] for hook in retried] == [
        "PreToolUse",
        "PostToolUseFailure",
        "PreToolUse",
        "PostToolUse",
    ]


def test_keeps_priced_usage_and_recent_times_when_transcript_built() -> None:
    lines = [json.loads(line) for line in demo_transcript(NOW).splitlines()]

    models = {line["message"]["model"] for line in lines if line["type"] == "assistant"}
    assert models == {TRANSCRIPT_MODEL}
    assert all(
        NOW - timedelta(hours=3) < datetime.fromisoformat(line["timestamp"]) for line in lines
    )
    tools = [
        block["name"]
        for line in lines
        if line["type"] == "assistant"
        for block in line["message"]["content"]
        if block["type"] == "tool_use"
    ]
    assert tools == ["Read", "Edit", "Bash", "Write"]
    assert {line["gitBranch"] for line in lines} == {DEMO_BRANCH}
    assert lines[0]["message"]["content"].startswith("/feature ")


def test_loads_every_screen_input_when_run_against_target(
    capsys: pytest.CaptureFixture[str],
) -> None:
    target = FakeTarget()
    server = FakeServer()

    code = main(["--url", URL], target=target, transport=httpx.MockTransport(server))

    assert code == 0
    hub = "/data/demo/demo-hub"
    assert target.commands[0][:2] == ["init", DEMO_PROJECT]
    assert target.commands[0][-2:] == ["--dir", hub]
    folder = f"{hub}/brain/features/export-button"
    for name in ("features.json", "spec.md", "plan.md", "eval.md", "evals/agh-7.md"):
        assert f"{folder}/{name}" in target.files
    assert f"{folder}/reviews/{ISSUE}.md" in target.files
    assert target.files[f"{hub}/{INBOX_NOTE}"].startswith("---\nkind: team\n")
    assert server.hubs == [{"path": hub}]
    assert len(server.envelopes) == len(demo_envelopes(NOW))
    runs, transcript = target.commands[1], target.commands[2]
    assert runs[:2] == ["collect", "--runs"]
    assert runs[2] in target.files
    assert transcript[:2] == ["collect", "--transcript"]
    assert transcript[2].startswith(f"/data/demo/transcripts/{BACKFILL_SESSION}-")
    for command in (runs, transcript):
        assert command[-4:] == ["--project", DEMO_PROJECT, "--db", "/data/agent-hub.db"]
    assert f"demo data loaded: open {URL}" in capsys.readouterr().out


def _heads(files: dict[PurePosixPath, str], folder: str) -> list[RecordHead]:
    return [
        RecordHead(name=path.name, head=text.encode(), problem=None)
        for path, text in sorted(files.items())
        if path.parent == FOLDER / folder
    ]


def test_plans_blocked_tickets_with_evals_and_reviews_when_feature_files_built() -> None:
    files = hub_files(HUB)
    record = FeatureRecordFile.model_validate_json(files[FOLDER / "features.json"])
    evals = eval_records(_heads(files, "evals"), files[FOLDER / "eval.md"].encode(), slug=FEATURE)
    reviews = review_records(_heads(files, "reviews"), slug=FEATURE)

    board = ticket_board(
        record.tickets, record.acs, None, linear=record.linear, approved=approved_tickets(reviews)
    )
    coverage = eval_coverage(evals, record.acs, tickets=record.tickets)

    assert record.linear == (ISSUE,)
    assert [(t.key, t.id) for t in record.tickets] == [("T1", ISSUE), ("T2", None), ("T3", None)]
    assert [t.blocked_by for t in record.tickets] == [(), ("T1",), ("T2",)]
    assert all(ac.ticket is not None for ac in record.acs)
    assert [row.ref for row in board.rows] == [ISSUE, "T2", "T3"]
    assert board.plan.layers == ((ISSUE,), ("T2",), ("T3",))
    assert board.plan.cycles == ()
    assert [(e.delivery, e.verdict, e.problem) for e in evals] == [
        ("legacy", "SHIP-WITH-OWNER-STEPS", None),
        ("agh-7", "SHIP-WITH-OWNER-STEPS", None),
    ]
    assert coverage.unscoped is False
    assert coverage.covered == ("AC-7.1", "AC-7.2", "AC-7.3")
    assert [(r.ticket, r.outcome, r.problem) for r in reviews] == [(ISSUE, "approved", None)]


def test_keeps_going_when_hub_exists_and_is_registered(capsys: pytest.CaptureFixture[str]) -> None:
    target = FakeTarget(init_stderr="hub.lock: this folder is already a hub; run hub sync\n")
    server = FakeServer(hubs_status=409)

    code = main(["--url", URL], target=target, transport=httpx.MockTransport(server))

    assert code == 0
    assert len(target.commands) == 3


def test_fails_naming_command_when_hub_command_fails(capsys: pytest.CaptureFixture[str]) -> None:
    target = FakeTarget(init_stderr="error: something else\n")

    code = main(["--url", URL], target=target, transport=httpx.MockTransport(FakeServer()))

    assert code == 1
    assert "hub init failed: error: something else" in capsys.readouterr().err


def test_fails_naming_url_when_no_server_answers(capsys: pytest.CaptureFixture[str]) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    code = main(["--url", URL], target=FakeTarget(), transport=httpx.MockTransport(refuse))

    assert code == 1
    assert f"no agent-hub answers at {URL}" in capsys.readouterr().err


def test_picks_compose_when_service_running() -> None:
    assert isinstance(
        choose_target("auto", compose_running=True, db_path="/data/a.db"), ComposeTarget
    )


def test_picks_local_next_to_database_when_service_not_running(tmp_path: Path) -> None:
    target = choose_target("auto", compose_running=False, db_path=str(tmp_path / "agent-hub.db"))

    assert isinstance(target, LocalTarget)
    assert target.workdir == PurePosixPath(tmp_path / "demo")


def test_writes_files_under_workdir_when_local_target_writes(tmp_path: Path) -> None:
    target = LocalTarget(workdir=PurePosixPath(tmp_path / "demo"))

    target.write(target.workdir / "a" / "b.txt", "text")

    assert (tmp_path / "demo" / "a" / "b.txt").read_text(encoding="utf-8") == "text"


def test_runs_hub_in_service_when_compose_target_runs_command() -> None:
    calls: list[tuple[list[str], str | None]] = []

    def runner(command: list[str], stdin: str | None) -> subprocess.CompletedProcess[str]:
        calls.append((command, stdin))
        return subprocess.CompletedProcess(command, 0, "", "")

    target = ComposeTarget(runner=runner)
    target.write(PurePosixPath("/data/demo/x.jsonl"), "line\n")
    target.hub(["collect", "--runs", "/data/demo/x.jsonl"])

    write, hub = calls
    assert write[0][:5] == ["docker", "compose", "exec", "-T", "agent-hub"]
    assert write[0][-1] == "/data/demo/x.jsonl"
    assert write[1] == "line\n"
    assert hub[0] == [
        "docker",
        "compose",
        "exec",
        "-T",
        "agent-hub",
        "hub",
        "collect",
        "--runs",
        "/data/demo/x.jsonl",
    ]
