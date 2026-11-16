"""``hub claim take`` and ``hub claim release``: the claim file and the verdict line (AGH-810b).

The hub is ``tmp_path``. ``ps`` is a fake process table that answers each ``ps -o … -p <pid>``
from a dict, and the clock is fixed: no test reads the real process table.
"""

import fcntl
import json
import os
import signal
import stat
from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import claim_command
from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.core.claims.claim import Claim
from agent_hub.core.testing.workflow_fakes import START, FakeClock

TICKET = "DEM-1"
# The pid ``hub claim`` runs under: its parent, where the walk starts.
SHELL_PID = 300
CLAUDE_PID = 100
CLAUDE_START = "Thu Oct 15 08:00:01 2026"
OTHER_START = "Thu Oct 15 08:30:00 2026"
CLAIM_FIELDS = {"ticket", "session", "pid", "started", "hub", "claimed_at", "last_activity"}


@dataclass(frozen=True)
class Process:
    ppid: int
    lstart: str
    args: str


# A local session: Claude Code, then ``uvx`` running ``./hub``, then the sandbox's shell.
SESSION_TREE: dict[int, Process] = {
    SHELL_PID: Process(200, "Thu Oct 15 08:59:58 2026", "/bin/sh -c ./hub claim take DEM-1"),
    200: Process(CLAUDE_PID, "Thu Oct 15 08:59:57 2026", "/usr/local/bin/uvx agent-hub"),
    CLAUDE_PID: Process(1, CLAUDE_START, "node /usr/local/lib/node_modules/.bin/claude --resume"),
}


@dataclass
class FakePs:
    """Answers ``ps -o ppid=,lstart=,args= -p <pid>`` and ``ps -o lstart= -p <pid>`` from
    ``table`` (exit 1 and no output for a pid it does not hold); ``error`` is raised instead
    when set, and ``lstart_reply`` answers every ``ps -o lstart=`` when set. Every argv and its
    options are recorded."""

    table: Mapping[int, Process]
    error: Exception | None = None
    lstart_reply: ChildResult | None = None
    calls: list[dict[str, Any]] = field(default_factory=list)

    def __call__(self, argv: list[str], **options: Any) -> ChildResult:
        self.calls.append({"argv": list(argv), **options})
        assert len(self.calls) < 50, "the walk does not end"
        if self.error is not None:
            raise self.error
        assert argv[0] == "ps" and argv[1] == "-o" and argv[3] == "-p", argv
        if argv[2] == "lstart=" and self.lstart_reply is not None:
            return self.lstart_reply
        process = self.table.get(int(argv[4]))
        if process is None:
            return ChildResult(1, b"", b"")
        if argv[2] == "ppid=,lstart=,args=":
            line = f"{process.ppid:>5} {process.lstart} {process.args}\n"
        elif argv[2] == "lstart=":
            line = f"{process.lstart}\n"
        else:
            raise AssertionError(f"no reply for {argv}")
        return ChildResult(0, line.encode(), b"")


@dataclass
class Hub:
    """A hub folder and the command run in this process against it."""

    root: Path
    monkeypatch: pytest.MonkeyPatch
    clock: FakeClock = field(default_factory=FakeClock)
    ps: FakePs = field(default_factory=lambda: FakePs(SESSION_TREE))
    parent: int = SHELL_PID

    @property
    def claims(self) -> Path:
        return self.root / ".agent-runs" / "claims"

    @property
    def claim_file(self) -> Path:
        return self.claims / f"{TICKET}.json"

    def run(self, *args: str) -> Result:
        self.monkeypatch.setattr(claim_command, "run_child", self.ps)
        self.monkeypatch.setattr(claim_command, "SystemClock", lambda: self.clock)
        self.monkeypatch.setattr(claim_command, "getppid", lambda: self.parent)
        return CliRunner().invoke(claim_command.claim_app, list(args), env={"COLUMNS": "200"})

    def take(self, session: str, ticket: str = TICKET) -> Result:
        return self.run("take", ticket, "--session", session)

    def release(self, session: str, ticket: str = TICKET) -> Result:
        return self.run("release", ticket, "--session", session)

    def write_claim(self, **changed: object) -> bytes:
        """A claim by session ``s-1`` (``changed`` replaces fields), as another session wrote it."""
        claim: dict[str, object] = {
            "ticket": TICKET,
            "session": "s-1",
            "pid": CLAUDE_PID,
            "started": CLAUDE_START,
            "hub": str(self.root),
            "claimed_at": "2026-10-14T09:00:00Z",
            "last_activity": "2026-10-14T10:00:00Z",
            **changed,
        }
        self.claims.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(claim).encode()
        self.claim_file.write_bytes(raw)
        return raw


@pytest.fixture
def hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Hub:
    root = Path(os.path.realpath(tmp_path / "hub"))
    root.mkdir()
    (root / "hub.json").write_text("{}\n")
    monkeypatch.setenv("AGENT_HUB_ROOT", str(root))
    return Hub(root, monkeypatch)


def verdict(result: Result) -> dict[str, Any]:
    """The one JSON line the command printed."""
    assert result.stdout.endswith("\n") and result.stdout.count("\n") == 1, result.output
    line: dict[str, Any] = json.loads(result.stdout)
    return line


def stored(hub: Hub) -> dict[str, Any]:
    claim: dict[str, Any] = json.loads(hub.claim_file.read_bytes())
    return claim


def test_writes_claim_file_with_pid_session_and_activity_when_taken(hub: Hub) -> None:
    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {
        "verdict": "claimed",
        "ticket": TICKET,
        "holder": {"session": "s-1", "pid": CLAUDE_PID, "hub": str(hub.root)},
    }
    assert stored(hub) == {
        "ticket": TICKET,
        "session": "s-1",
        "pid": CLAUDE_PID,
        "started": CLAUDE_START,
        "hub": str(hub.root),
        "claimed_at": "2026-10-15T09:00:00Z",
        "last_activity": "2026-10-15T09:00:00Z",
    }
    assert set(stored(hub)) == CLAIM_FIELDS
    assert hub.claims.stat().st_mode & 0o777 == 0o700
    assert hub.claim_file.stat().st_mode & 0o777 == 0o600
    # Only the claim and its lock: no temp file is left behind.
    assert sorted(path.name for path in hub.claims.iterdir()) == [".lock", f"{TICKET}.json"]
    assert {call["timeout"] for call in hub.ps.calls} == {5.0}


def test_prints_live_holder_and_writes_nothing_when_claim_live(hub: Hub) -> None:
    before = hub.write_claim()

    result = hub.take("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {
        "verdict": "live",
        "ticket": TICKET,
        "holder": {"session": "s-1", "pid": CLAUDE_PID, "hub": str(hub.root)},
    }
    assert hub.claim_file.read_bytes() == before


def test_takes_over_and_names_old_session_when_claim_stale(hub: Hub) -> None:
    hub.write_claim(pid=400, started=OTHER_START)

    result = hub.take("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {
        "verdict": "took_over",
        "ticket": TICKET,
        "holder": {"session": "s-2", "pid": CLAUDE_PID, "hub": str(hub.root)},
        "previous": {"session": "s-1", "pid": 400, "hub": str(hub.root)},
        "reason": "process 400 is not running",
    }
    claim = stored(hub)
    assert (claim["session"], claim["pid"], claim["claimed_at"]) == (
        "s-2",
        CLAUDE_PID,
        "2026-10-15T09:00:00Z",
    )
    # The probe and the walk both read ``lstart`` in the C locale.
    assert {call["argv"][2] for call in hub.ps.calls} == {"lstart=", "ppid=,lstart=,args="}
    assert all(call["env"]["LC_ALL"] == "C" for call in hub.ps.calls)


def test_takes_over_when_pid_reused_by_another_start(hub: Hub) -> None:
    hub.write_claim(started=OTHER_START)

    result = hub.take("s-2")

    assert verdict(result)["verdict"] == "took_over"
    assert verdict(result)["reason"] == (
        f"pid {CLAUDE_PID} now belongs to a process started {CLAUDE_START}, not {OTHER_START}"
    )


def test_counts_claim_live_when_process_table_unreadable(hub: Hub) -> None:
    before = hub.write_claim()
    hub.ps.error = OSError("ps cannot start")

    result = hub.take("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result)["verdict"] == "live"
    assert hub.claim_file.read_bytes() == before


@pytest.mark.parametrize(
    "reply",
    [
        ChildResult(1, b"", b"ps: illegal option -- o\nusage: ps [-AaCcEefhjlMmrSTvwXx]\n"),
        ChildResult(1, b"", b"ps: Operation not permitted\n"),
        ChildResult(1, b"usage: ps\n", b""),
    ],
    ids=["ps-rejects-option", "ps-not-permitted", "ps-prints-usage"],
)
def test_counts_claim_live_when_ps_fails_with_message(hub: Hub, reply: ChildResult) -> None:
    before = hub.write_claim(pid=400, started=OTHER_START)
    hub.ps.lstart_reply = reply

    result = hub.take("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result)["verdict"] == "live"
    assert hub.claim_file.read_bytes() == before


def test_refreshes_own_claim_when_same_session_takes_again(hub: Hub) -> None:
    assert hub.take("s-1").exit_code == 0
    hub.clock.current = START.replace(hour=11)

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {
        "verdict": "refreshed",
        "ticket": TICKET,
        "holder": {"session": "s-1", "pid": CLAUDE_PID, "hub": str(hub.root)},
    }
    claim = stored(hub)
    assert (claim["claimed_at"], claim["last_activity"]) == (
        "2026-10-15T09:00:00Z",
        "2026-10-15T11:00:00Z",
    )


def test_removes_file_when_released(hub: Hub) -> None:
    assert hub.take("s-1").exit_code == 0

    result = hub.release("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {"verdict": "released", "ticket": TICKET}
    assert not hub.claim_file.exists()


def test_prints_not_held_when_another_session_releases(hub: Hub) -> None:
    before = hub.write_claim()

    result = hub.release("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {"verdict": "not_held", "ticket": TICKET}
    assert hub.claim_file.read_bytes() == before


def test_prints_not_held_when_no_claim_released(hub: Hub) -> None:
    result = hub.release("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {"verdict": "not_held", "ticket": TICKET}
    assert not hub.claim_file.exists()


def test_takes_released_ticket_when_file_gone(hub: Hub) -> None:
    assert hub.take("s-1").exit_code == 0
    assert hub.release("s-1").exit_code == 0

    result = hub.take("s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result)["verdict"] == "claimed"
    assert stored(hub)["session"] == "s-2"


@pytest.mark.parametrize("ticket", ["../x", "agh-1", "A-", "DEM-1\n", "DEM-1/../../x"])
@pytest.mark.parametrize("action", ["take", "release"])
def test_refuses_ticket_when_id_outside_pattern(hub: Hub, action: str, ticket: str) -> None:
    result = hub.run(action, ticket, "--session", "s-1")

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert not (hub.root / ".agent-runs").exists()
    assert hub.ps.calls == []


@pytest.mark.parametrize("session", ["", "s 1", "s-1\n", "x" * 513])
def test_refuses_session_when_id_outside_shape(hub: Hub, session: str) -> None:
    result = hub.take(session)

    assert result.exit_code == 2, result.output
    assert not (hub.root / ".agent-runs").exists()


@pytest.mark.parametrize("action", ["take", "release"])
def test_refuses_claim_file_when_linked(hub: Hub, tmp_path: Path, action: str) -> None:
    target = tmp_path / "elsewhere.json"
    hub.write_claim()
    target.write_bytes(hub.claim_file.read_bytes())
    before = target.read_bytes()
    hub.claim_file.unlink()
    hub.claim_file.symlink_to(target)

    result = hub.run(action, TICKET, "--session", "s-2")

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert result.stderr.startswith(f"cannot read the claim {hub.claim_file}: ")
    assert result.stderr.count("\n") == 1
    assert hub.claim_file.is_symlink()
    assert target.read_bytes() == before


def _missing_field(hub: Hub) -> bytes:
    claim = json.loads(hub.write_claim())
    del claim["last_activity"]
    return json.dumps(claim).encode()


def _too_large(hub: Hub) -> bytes:
    return hub.write_claim().ljust(4097)


@pytest.mark.parametrize(
    "corrupt",
    [
        lambda hub: b"not json",
        _too_large,
        _missing_field,
        lambda hub: b"[]",
        lambda hub: hub.write_claim(ticket="DEM-2"),
    ],
    ids=["not-json", "over-4-kib", "field-missing", "not-an-object", "another-ticket"],
)
def test_reports_an_unreadable_claim_when_file_corrupt(hub: Hub, corrupt: Any) -> None:
    hub.write_claim()
    raw = corrupt(hub)
    hub.claim_file.write_bytes(raw)

    result = hub.take("s-2")

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert result.stderr.startswith(f"cannot read the claim {hub.claim_file}: ")
    assert result.stderr.count("\n") == 1
    assert hub.claim_file.read_bytes() == raw


def _hung(signum: int, frame: object) -> None:
    raise AssertionError("hub claim hangs on the claim file")


def test_reports_an_unreadable_claim_when_file_is_a_fifo(hub: Hub) -> None:
    hub.claims.mkdir(parents=True)
    os.mkfifo(hub.claim_file)

    # A blocking open of a FIFO with no writer never returns: fail after 5 seconds instead.
    previous = signal.signal(signal.SIGALRM, _hung)
    signal.alarm(5)
    try:
        result = hub.take("s-2")
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous)

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    assert result.stderr == f"cannot read the claim {hub.claim_file}: it is not a regular file\n"
    assert stat.S_ISFIFO(os.lstat(hub.claim_file).st_mode)
    assert sorted(path.name for path in hub.claims.iterdir()) == [".lock", f"{TICKET}.json"]


def test_keeps_old_claim_and_no_temp_file_when_write_fails(
    hub: Hub, monkeypatch: pytest.MonkeyPatch
) -> None:
    before = hub.write_claim(pid=400, started=OTHER_START)

    def replace(source: object, target: object) -> None:
        raise OSError(28, "No space left on device")

    monkeypatch.setattr(claim_command.os, "replace", replace)

    result = hub.take("s-2")

    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert "cannot write the claim" in result.stderr
    assert hub.claim_file.read_bytes() == before
    assert sorted(path.name for path in hub.claims.iterdir()) == [".lock", f"{TICKET}.json"]


@pytest.mark.parametrize(
    "claude_args",
    ["node /usr/local/lib/node_modules/.bin/claude --resume", "/opt/homebrew/bin/claude"],
)
def test_finds_claude_pid_when_walking_ancestors(hub: Hub, claude_args: str) -> None:
    hub.ps = FakePs({**SESSION_TREE, CLAUDE_PID: Process(1, CLAUDE_START, claude_args)})

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert (stored(hub)["pid"], stored(hub)["started"]) == (CLAUDE_PID, CLAUDE_START)
    assert [call["argv"] for call in hub.ps.calls] == [
        ["ps", "-o", "ppid=,lstart=,args=", "-p", str(pid)] for pid in (SHELL_PID, 200, CLAUDE_PID)
    ]


def _chain(length: int) -> dict[int, Process]:
    """``length`` shells, each the parent of the one before, from ``SHELL_PID`` up; Claude Code
    is the parent of the last one."""
    table = {
        SHELL_PID + level: Process(SHELL_PID + level + 1, OTHER_START, "/bin/zsh -l")
        for level in range(length)
    }
    table[SHELL_PID + length] = Process(1, CLAUDE_START, "/opt/homebrew/bin/claude")
    return table


@pytest.mark.parametrize(
    ("ps", "calls"),
    [
        (FakePs({SHELL_PID: Process(1, OTHER_START, "node /srv/app/server.js")}), 2),
        (FakePs(_chain(10)), 10),
        (FakePs({}), 1),
        (FakePs(SESSION_TREE, error=OSError("ps cannot start")), 1),
        (FakePs(SESSION_TREE, error=ChildTimedOutError(program="ps", timeout=5.0)), 1),
    ],
    ids=["no-claude", "claude-past-10-levels", "parent-gone", "ps-cannot-start", "ps-timed-out"],
)
def test_records_no_pid_when_no_claude_ancestor(hub: Hub, ps: FakePs, calls: int) -> None:
    hub.ps = ps

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result)["holder"] == {"session": "s-1", "pid": None, "hub": str(hub.root)}
    assert (stored(hub)["pid"], stored(hub)["started"]) == (None, None)
    assert len(ps.calls) == calls


def test_finds_claude_pid_when_nine_levels_up(hub: Hub) -> None:
    hub.ps = FakePs(_chain(9))

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert stored(hub)["pid"] == SHELL_PID + 9


@pytest.fixture
def held_lock(hub: Hub) -> Iterator[None]:
    hub.claims.mkdir(parents=True)
    handle = os.open(hub.claims / ".lock", os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(handle)


@pytest.mark.usefixtures("held_lock")
@pytest.mark.parametrize("action", ["take", "release"])
def test_refuses_when_claims_lock_held(hub: Hub, action: str) -> None:
    result = hub.run(action, TICKET, "--session", "s-1")

    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert result.stderr.count("\n") == 1
    assert "claim" in result.stderr
    assert sorted(path.name for path in hub.claims.iterdir()) == [".lock"]


QUESTION = "Merge #41?"
SESSION_TITLE = "DEM-1 login"
QUESTION_FIELDS = ("question", "asked_at", "title")


def _wait(hub: Hub, session: str, question: str = QUESTION, *more: str) -> Result:
    return hub.run("wait", TICKET, "--session", session, "--question", question, *more)


def test_records_question_when_holder_waits(hub: Hub) -> None:
    assert hub.take("s-1").exit_code == 0
    before = stored(hub)
    hub.clock.current = START.replace(hour=10)

    result = _wait(hub, "s-1", QUESTION, "--title", SESSION_TITLE)

    assert result.exit_code == 0, result.output
    line = verdict(result)
    assert (line["verdict"], line["ticket"]) == ("waiting", TICKET)
    claim = stored(hub)
    assert (claim["question"], claim["title"], claim["asked_at"]) == (
        QUESTION,
        SESSION_TITLE,
        "2026-10-15T10:00:00Z",
    )
    for name in ("claimed_at", "pid", "started"):
        assert claim[name] == before[name], name
    assert Claim.model_validate_json(hub.claim_file.read_bytes()).question == QUESTION


def test_changes_nothing_when_another_session_waits(hub: Hub) -> None:
    before = hub.write_claim()

    result = _wait(hub, "s-2")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {"verdict": "not_held", "ticket": TICKET}
    assert hub.claim_file.read_bytes() == before


def test_changes_nothing_when_no_claim_waits(hub: Hub) -> None:
    result = _wait(hub, "s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result) == {"verdict": "not_held", "ticket": TICKET}
    assert not hub.claim_file.exists()


def test_clears_question_when_holder_takes_again(hub: Hub) -> None:
    assert hub.take("s-1").exit_code == 0
    assert _wait(hub, "s-1", QUESTION, "--title", SESSION_TITLE).exit_code == 0
    hub.clock.current = START.replace(hour=11)

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    assert verdict(result)["verdict"] == "refreshed"
    claim = stored(hub)
    assert "question" not in claim
    assert "asked_at" not in claim
    assert claim["title"] == SESSION_TITLE
    parsed = Claim.model_validate_json(hub.claim_file.read_bytes())
    assert (parsed.question, parsed.asked_at, parsed.title) == (None, None, SESSION_TITLE)


@pytest.mark.parametrize(
    ("ps", "process"),
    [(FakePs(SESSION_TREE), (CLAUDE_PID, CLAUDE_START)), (FakePs({}), (None, None))],
    ids=["with_pid", "no_pid"],
)
def test_writes_no_question_fields_when_taken_without_wait(
    hub: Hub, ps: FakePs, process: tuple[int | None, str | None]
) -> None:
    hub.ps = ps

    result = hub.take("s-1")

    assert result.exit_code == 0, result.output
    claim = stored(hub)
    assert not set(QUESTION_FIELDS) & set(claim), claim
    assert (claim["pid"], claim["started"]) == process
    assert set(claim) == CLAIM_FIELDS


@pytest.mark.parametrize(
    "question",
    ["Merge #41?\nOr wait?", "Merge\t#41?", "Merge #41?\x07", "x" * 201],
    ids=["newline", "tab_escape", "control", "too_long"],
)
def test_refuses_question_when_not_one_line(hub: Hub, question: str) -> None:
    before = hub.write_claim()

    result = _wait(hub, "s-1", question)

    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    # Refused for the question, not for the command line.
    assert "question" in result.stderr, result.stderr
    assert hub.claim_file.read_bytes() == before
    assert sorted(path.name for path in hub.claims.iterdir()) == [f"{TICKET}.json"]
    assert hub.ps.calls == []


@pytest.mark.usefixtures("held_lock")
def test_exits_one_when_lock_held_during_wait(hub: Hub) -> None:
    result = _wait(hub, "s-1")

    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    assert result.stderr.count("\n") == 1
    assert "claim" in result.stderr
    assert sorted(path.name for path in hub.claims.iterdir()) == [".lock"]
