"""The session record and the session reminder, run on the rendered hooks of a demo hub.

``pre_compact.py`` adds 1 to ``compactions`` in ``<hub>/.agent-runs/sessions/<session id>.json``
(``{"started": <epoch s>, "compactions": <int>, "reminded": <bool>}``), creating the record when it
is missing. The hook runs as Claude Code runs it: a file of a rendered demo hub on ``hook_python``,
with the event on stdin, in an environment from scratch (``HOME`` and ``TMPDIR`` under
``tmp_path``), from the hub. A session id that does not have the safe shape writes no record; a
record that cannot be read (not JSON, not an object, a link, more than 4 KiB) counts as a fresh one,
a link is never followed, and nothing ever errors the session.

``session_reminder.py`` (UserPromptSubmit) creates the record on the session's first prompt and,
once the session was compacted twice or has been open for 2 days, prints one JSON line with only
``systemMessage`` (compactions win when both hold) and sets ``reminded``, so it reminds once. With
no hub or a bad event it prints nothing; it always exits 0.
"""

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hook_inputs import HOOK_SESSION, a_hook_input

HOOKS = "plugin/hub-workflow/hooks"
EVENT = "PreCompact"
SESSIONS = ".agent-runs/sessions"
SNAPSHOT = "brain/auto/workspace/session-snapshot.md"
RECORD_MAX = 4096
PROMPT_EVENT = "UserPromptSubmit"
DAY = 24 * 60 * 60

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]
type RunCompact = Callable[..., subprocess.CompletedProcess[bytes]]
type RunReminder = Callable[..., subprocess.CompletedProcess[bytes]]

# The overrides of each unsafe session id (``...`` drops the key).
UNSAFE_SESSION_IDS: dict[str, Any] = {
    "missing": ...,
    "null": None,
    "number": 7,
    "dots": "../x",
    "slash": "a/b",
    "too_long": "a" * 513,
}
# Were this record read, one more compaction would make 6; a fresh record makes 1.
OLD_RECORD = {"started": 1, "compactions": 5, "reminded": True}
UNREADABLE_RECORDS = {
    "not_json": "{not json",
    "array": json.dumps([OLD_RECORD]),
    "too_big": json.dumps(dict(OLD_RECORD, pad="x" * RECORD_MAX)),
    # Within the size cap, nested deeper than the parser goes: RecursionError, not ValueError.
    "deep": "[" * (RECORD_MAX // 2 - 1) + "]" * (RECORD_MAX // 2 - 1),
}
# 3.9 to 3.11 raise RecursionError on "deep" at the default recursion limit; 3.12 and later
# measure the C stack, so the case runs the hook on a stack this small, where every version
# raises (the case probes it first).
DEEP_STACK_KIB = 256
# stdin: the record. Parses it as the hook does (``json.loads``) and says which.
NESTING_PROBE = """\
import json, sys
try:
    json.loads(sys.stdin.read())
except RecursionError:
    print("raises")
else:
    print("parses")
"""


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub, with the builder's ``hub.json`` (the hooks find the hub by it)."""
    rendered = rendered_hub(demo_config).resolve()
    (rendered / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")
    return rendered


@pytest.fixture
def hook_env(tmp_path: Path) -> dict[str, str]:
    """``HOME`` and ``TMPDIR`` under ``tmp_path``, for an environment from scratch."""
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    return {"HOME": str(home), "TMPDIR": str(temp)}


@pytest.fixture
def run_compact(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, hook_env: dict[str, str]
) -> RunCompact:
    """Run ``pre_compact.py`` from the hub on a PreCompact event (``overrides`` change it)."""

    def run(*, python: str | None = None, **overrides: Any) -> subprocess.CompletedProcess[bytes]:
        event = a_hook_input(EVENT, **dict({"cwd": str(hub)}, **overrides))
        return run_hook_file(
            python or hook_python,
            hub / HOOKS / "pre_compact.py",
            stdin=json.dumps(event).encode(),
            cwd=hub,
            env=hook_env,
        )

    return run


@pytest.fixture
def run_reminder(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, hook_env: dict[str, str]
) -> RunReminder:
    """Run ``session_reminder.py`` on a UserPromptSubmit event, from ``cwd`` (default: the hub);
    ``stdin`` replaces the event, ``overrides`` change it."""
    script = hub / HOOKS / "session_reminder.py"

    def run(
        *, stdin: bytes | None = None, cwd: Path | None = None, **overrides: Any
    ) -> subprocess.CompletedProcess[bytes]:
        assert script.is_file(), f"no reminder hook at {script}"
        start = cwd or hub
        event = a_hook_input(PROMPT_EVENT, **dict({"cwd": str(start)}, **overrides))
        return run_hook_file(
            hook_python,
            script,
            stdin=stdin if stdin is not None else json.dumps(event).encode(),
            cwd=start,
            env=hook_env,
        )

    return run


def record_path(hub: Path) -> Path:
    return hub / SESSIONS / f"{HOOK_SESSION}.json"


def read_record(hub: Path) -> dict[str, Any]:
    path = record_path(hub)
    assert path.is_file(), f"no session record at {path}"
    assert not path.is_symlink()
    record = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(record, dict)
    return record


def write_record(hub: Path, content: str) -> Path:
    path = record_path(hub)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def assert_quiet(completed: subprocess.CompletedProcess[bytes]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == b""


def assert_reminds(completed: subprocess.CompletedProcess[bytes]) -> str:
    """Exit 0, nothing on stderr, exactly one JSON line with only ``systemMessage``; returns it."""
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == b""
    lines = completed.stdout.decode().splitlines()
    assert len(lines) == 1, completed.stdout
    output = json.loads(lines[0])
    assert list(output) == ["systemMessage"]
    message = output["systemMessage"]
    assert isinstance(message, str)
    assert "/handoff" in message
    assert "a new session" in message
    return message


def assert_silent(completed: subprocess.CompletedProcess[bytes]) -> None:
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == b""
    assert b"Traceback" not in completed.stderr


def a_record(*, started_ago: int = 0, compactions: int = 0) -> str:
    """A record started ``started_ago`` seconds back, with ``compactions``, not reminded."""
    started = int(time.time()) - started_ago
    return json.dumps({"started": started, "compactions": compactions, "reminded": False})


def assert_fresh_count(record: dict[str, Any], *, before: int, after: int) -> None:
    """A fresh record after one compaction: ``started`` now, 1 compaction, not reminded."""
    assert record["compactions"] == 1
    assert record["reminded"] is False
    started = record["started"]
    assert isinstance(started, int)
    assert not isinstance(started, bool)
    assert before <= started <= after


def test_counts_compactions_when_pre_compact_runs(hub: Path, run_compact: RunCompact) -> None:
    before = int(time.time())
    assert_quiet(run_compact())
    assert_quiet(run_compact())
    after = int(time.time()) + 1

    record = read_record(hub)
    assert record["compactions"] == 2
    assert record["reminded"] is False
    started = record["started"]
    assert isinstance(started, int)
    assert not isinstance(started, bool)
    assert before <= started <= after


def test_keeps_started_when_record_exists(hub: Path, run_compact: RunCompact) -> None:
    started = int(time.time()) - 100
    write_record(hub, json.dumps({"started": started, "compactions": 0, "reminded": False}))

    assert_quiet(run_compact())

    record = read_record(hub)
    assert record["started"] == started
    assert record["compactions"] == 1
    assert record["reminded"] is False


@pytest.mark.parametrize("session_id", UNSAFE_SESSION_IDS.values(), ids=UNSAFE_SESSION_IDS.keys())
def test_writes_no_record_when_session_id_unsafe(
    session_id: Any, hub: Path, run_compact: RunCompact
) -> None:
    completed = run_compact(session_id=session_id)

    assert completed.returncode == 0, completed.stderr
    assert b"Traceback" not in completed.stderr
    sessions = hub / SESSIONS
    assert not sessions.exists() or list(sessions.iterdir()) == []
    assert not (hub / ".agent-runs" / "x.json").exists()
    assert (hub / SNAPSHOT).is_file()


@pytest.mark.parametrize("kind", ["not_json", "array", "link", "too_big", "deep"])
def test_starts_a_fresh_record_when_record_unreadable(
    kind: str,
    hub: Path,
    *,
    run_compact: RunCompact,
    tmp_path: Path,
    hook_python: str,
    run_hook_file: RunHook,
    small_stack: Callable[[str, int], str],
) -> None:
    target = tmp_path / "elsewhere.json"
    target_text = json.dumps(OLD_RECORD)
    python = None
    if kind == "link":
        target.write_text(target_text, encoding="utf-8")
        record_path(hub).parent.mkdir(parents=True, exist_ok=True)
        record_path(hub).symlink_to(target)
    else:
        write_record(hub, UNREADABLE_RECORDS[kind])
    if kind == "deep":
        assert len(UNREADABLE_RECORDS["deep"].encode()) <= RECORD_MAX
        python = small_stack(hook_python, DEEP_STACK_KIB)
        probe = tmp_path / "nesting_probe.py"
        probe.write_text(NESTING_PROBE, encoding="utf-8")
        probed = run_hook_file(
            python, probe, stdin=UNREADABLE_RECORDS["deep"].encode(), cwd=tmp_path
        )
        assert probed.returncode == 0, probed.stderr
        assert probed.stdout.decode().strip() == "raises"
    before = int(time.time())

    assert_quiet(run_compact(python=python))

    assert_fresh_count(read_record(hub), before=before, after=int(time.time()) + 1)
    if kind == "link":
        assert target.read_text(encoding="utf-8") == target_text


def test_records_start_and_stays_silent_when_first_prompt(
    hub: Path, run_reminder: RunReminder
) -> None:
    before = int(time.time())

    completed = run_reminder()

    assert_quiet(completed)
    assert completed.stdout == b""
    record = read_record(hub)
    assert record["compactions"] == 0
    assert record["reminded"] is False
    started = record["started"]
    assert isinstance(started, int)
    assert not isinstance(started, bool)
    assert before <= started <= int(time.time()) + 1


def test_reminds_once_when_compacted_twice(hub: Path, run_reminder: RunReminder) -> None:
    write_record(hub, a_record(compactions=2))

    message = assert_reminds(run_reminder())

    assert "compacted twice" in message
    assert_silent(run_reminder())
    assert read_record(hub)["reminded"] is True


def test_reminds_once_when_open_two_days(hub: Path, run_reminder: RunReminder) -> None:
    write_record(hub, a_record(started_ago=2 * DAY + 1))

    message = assert_reminds(run_reminder())

    assert "open for 2 days" in message
    assert_silent(run_reminder())
    assert read_record(hub)["reminded"] is True


def test_reminds_when_open_exactly_two_days(hub: Path, run_reminder: RunReminder) -> None:
    # ``started`` is exactly 2 days before now at writing; the hook's now can only be later.
    write_record(hub, a_record(started_ago=2 * DAY))

    message = assert_reminds(run_reminder())

    assert "open for 2 days" in message


def test_stays_silent_when_under_both_limits(hub: Path, run_reminder: RunReminder) -> None:
    write_record(hub, a_record(started_ago=47 * 60 * 60, compactions=1))

    assert_silent(run_reminder())

    assert read_record(hub)["reminded"] is False


def test_names_compactions_when_both_limits_reached(hub: Path, run_reminder: RunReminder) -> None:
    write_record(hub, a_record(started_ago=2 * DAY + 1, compactions=2))

    message = assert_reminds(run_reminder())

    assert "compacted twice" in message
    assert "open for 2 days" not in message


@pytest.mark.parametrize("case", ["no_hub", "not_json", "no_session_id"])
def test_stays_silent_when_no_hub_or_bad_input(
    case: str, hub: Path, *, run_reminder: RunReminder, tmp_path: Path
) -> None:
    if case == "no_hub":
        (hub / "hub.json").unlink()
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        completed = run_reminder(cwd=elsewhere)
    elif case == "not_json":
        completed = run_reminder(stdin=b"not json")
    else:
        completed = run_reminder(session_id=...)

    assert_silent(completed)
    sessions = hub / SESSIONS
    assert not sessions.exists() or list(sessions.iterdir()) == []
