"""SessionStart through the rendered hook: the pinned ``hub brief``, else the mini brief.

AC-4.17 and AC-15.7: the hook resolves the pinned release (``hub --version``), then runs its
``hub brief``, both within one 10 s deadline. A rendered demo hub at ``ws/demo-hub`` pins
``platform.version`` ``1.2.3``. The hook runs as Claude Code runs it, a file on ``hook_python``
with the event on stdin, in an environment built from scratch whose ``PATH`` holds only a test
folder: the fake ``uvx`` when a case installs it, so the real ``uv`` (and the network) is never
reached. The fake records each call's arguments, working directory and ``AGENT_HUB_ROOT``, then
answers the resolve step as ``FAKE_UVX_RESOLVE`` says (``ok``, ``fail``, ``sleep``) and the brief
as ``FAKE_UVX_BRIEF`` says (``brief``, ``exit3``, ``empty``, ``sleep``, ``long``).
"""

import contextlib
import fcntl
import json
import os
import re
import signal
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

HOOK = "plugin/hub-workflow/hooks/session_start.py"
VERSION = "1.2.3"
BRIEF = "# Brief\nAll repos green.\n"
# The deadline of both calls in the rendered hook, and the one a timeout run lowers it to (s).
BRIEF_TIMEOUT = 10
TEST_TIMEOUT = 2
# A slow resolve step fits the lowered deadline with a wide margin; the brief then hangs past it.
RESOLVE_SLEEP = 0.5
# Each of two slow calls fits the lowered deadline with a margin; together they do not.
SLOW_CALL = 0.7 * TEST_TIMEOUT
# The lock probe: how long a killed holder may take to release its lock.
PROBE_DEADLINE = 5.0
# A hanging call's processes: ``hub`` (uvx's child) and its own child (as ``hub brief``'s git or
# gh), in the call's process group, each holding an exclusive lock until it dies.
HOLDER = """\
import fcntl, os, subprocess, sys, time
lock = open(sys.argv[1], "w")
fcntl.flock(lock, fcntl.LOCK_EX)
with open(sys.argv[1] + ".pid", "w") as fh:
    fh.write(str(os.getpid()))
if len(sys.argv) > 2:
    subprocess.Popen([sys.executable, __file__, sys.argv[2]], start_new_session=False)
    while not os.path.exists(sys.argv[2] + ".pid"):
        time.sleep(0.01)
time.sleep(60)
"""
BRIEF_CAP = 8000
# A brief longer than the cap; its cut falls inside a word.
LONG_BRIEF = "# Brief\n" + "".join(
    f"- repo {i:04d} is green today and tomorrow\n" for i in range(1, 400)
)
# AC-4.17's source for VERSION, as the criterion spells it (the platform-source exception).
AC_SOURCE = f"git+https://github.com/jroquette/agent-hub@v{VERSION}#subdirectory=packages/agent-hub"
NOW_CAP = 2500
# now.md: longer than the cap, its cut falls inside a word, so a longer or shorter cut shows.
NOW_MD = "---\nlast_verified: 2026-01-12\n---\n# Now\n" + "".join(
    f"- focus item {i:04d}: keep the hub smaller\n" for i in range(1, 120)
)
# Journal days, plus files the mini brief must skip; the newest three by path, newest first.
JOURNAL = {
    "brain/journal/2025/12/31.md": "# 2025-12-31\n",
    "brain/journal/2026/01/03.md": "# 2026-01-03\n",
    "brain/journal/2026/01/10.md": "# 2026-01-10\n",
    "brain/journal/2026/01/13.md": "# 2026-01-13\n",
    "brain/journal/2026/01/14.txt": "not a journal day\n",
}
LATEST_JOURNAL = (
    "Latest journal: brain/journal/2026/01/13.md, brain/journal/2026/01/10.md, "
    "brain/journal/2026/01/03.md"
)
SNAPSHOT = "brain/auto/workspace/session-snapshot.md"
SNAPSHOT_TEXT = "# Session snapshot\n" + "- snapshot line\n" * 200
SNAPSHOT_HEAD = "\n\n## Snapshot before compaction\n"
# argv: the log file, then uvx's arguments. A POSIX shell wrapper execs it on the interpreter.
FAKE_UVX = (
    """\
import json, os, subprocess, sys, time
log, args = sys.argv[1], sys.argv[2:]
kind = "resolve" if args[-1:] == ["--version"] else "brief"
mode = os.environ.get("FAKE_UVX_" + kind.upper(), "ok" if kind == "resolve" else "brief")
call = {"args": args, "cwd": os.getcwd(), "root": os.environ.get("AGENT_HUB_ROOT")}
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(call) + "\\n")
if mode == "slow":  # answers, late
    time.sleep(float(os.environ.get("FAKE_UVX_SLOW", RESOLVE_SECONDS)))
    sys.stdout.write("1.2.3\\n" if kind == "resolve" else BRIEF_TEXT)
elif mode == "hang":  # like uvx, wait on its child (hub), which has a child of its own
    holder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holder.py")
    subprocess.run([sys.executable, holder, log + ".hub.lock", log + ".tool.lock"])
elif mode == "fail":  # the release cannot be resolved
    sys.stderr.write("error: cannot fetch the release\\n")
    sys.exit(1)
elif mode == "exit3":  # some output, but a non-zero exit: still a failure
    sys.stdout.write("Usage: hub [OPTIONS] COMMAND\\n")
    sys.exit(3)
elif mode == "ok":
    sys.stdout.write("1.2.3\\n")
elif mode == "brief":
    sys.stdout.write(BRIEF_TEXT)
elif mode == "long":
    sys.stdout.write(LONG_TEXT)
""".replace("BRIEF_TEXT", repr(BRIEF))
    .replace("LONG_TEXT", repr(LONG_BRIEF))
    .replace("RESOLVE_SECONDS", repr(RESOLVE_SLEEP))
)
FALLBACK_HEADER = re.compile(
    r"# Brief \(fallback: hub brief (no uv|no version|resolve failed|timed out"
    r"|failed|failed \(exit -?[0-9]+\)|failed \(no output\)|failed \(cannot start\))\)"
)

type RunHook = Callable[..., Any]


def expected_mini_brief(cause: str) -> str:
    assert not NOW_MD[NOW_CAP - 1].isspace()  # so the cut shows as it is, whitespace-stripped
    return f"# Brief (fallback: hub brief {cause})\n\n{NOW_MD[:NOW_CAP]}\n\n{LATEST_JOURNAL}"


def release_argv(version: str, *arguments: str) -> list[str]:
    """Core's pinned-release command for ``version`` without ``uvx``, then ``arguments``."""
    command = PINNED_RELEASE_COMMAND.format(version=version).split()
    assert command[0] == "uvx"
    return [*command[1:], *(arguments or ("brief",))]


def write_hub_json(hub: Path, *, version: object = VERSION) -> None:
    """The builder's document with ``platform.version`` = ``version`` (absent when ``None``)."""
    document = a_hub_document()
    if version is None:
        del document["platform"]["version"]
    else:
        document["platform"]["version"] = version
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub with ``now.md`` and journal days, pinned to ``VERSION``."""
    rendered = rendered_hub(demo_config).resolve()
    (rendered / "brain" / "now.md").write_text(NOW_MD, encoding="utf-8")
    for rel, text in JOURNAL.items():
        (rendered / rel).parent.mkdir(parents=True, exist_ok=True)
        (rendered / rel).write_text(text, encoding="utf-8")
    assert (rendered / "brain" / "journal" / "_template.md").is_file()  # rendered, never listed
    write_hub_json(rendered)
    return rendered


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    """The only folder on the hook's ``PATH``: empty until a case installs the fake ``uvx``."""
    folder = tmp_path / "bin"
    folder.mkdir()
    return folder


@pytest.fixture
def uvx_log(tmp_path: Path) -> Path:
    return tmp_path / "uvx-calls.jsonl"


def install_uvx(bin_dir: Path, *, python: str, log: Path, interpreter: str = "/bin/sh") -> None:
    """The fake ``uvx`` in ``bin_dir``: a shell wrapper that execs ``FAKE_UVX`` on ``python``."""
    script = bin_dir.parent / "fake_uvx.py"
    script.write_text(FAKE_UVX, encoding="utf-8")
    (bin_dir.parent / "holder.py").write_text(HOLDER, encoding="utf-8")
    wrapper = bin_dir / "uvx"
    wrapper.write_text(
        f'#!{interpreter}\nexec "{python}" "{script}" "{log}" "$@"\n', encoding="utf-8"
    )
    wrapper.chmod(0o755)


def calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def start(
    hub: Path,
    *,
    python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    source: str = "startup",
    env: Mapping[str, str] | None = None,
) -> tuple[Any, float]:
    """Run SessionStart at ``hub``: (the completed process, the seconds it took)."""
    event = {"session_id": "abcdef123456", "cwd": str(hub), "source": source}
    began = time.monotonic()
    completed = run_hook_file(
        python,
        hub / HOOK,
        stdin=json.dumps(event).encode(),
        cwd=hub.parent,  # the workspace: the brief must still run from the hub
        env={"PATH": str(bin_dir), "HOME": str(bin_dir.parent / "home")} | dict(env or {}),
    )
    return completed, time.monotonic() - began


def context_of(completed: Any) -> str:
    """The ``additionalContext`` of a clean run (exit 0, nothing on stderr, one JSON object)."""
    assert (completed.returncode, completed.stderr) == (0, b"")
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return output["hookSpecificOutput"]["additionalContext"]


def test_resolves_then_briefs_when_uvx_succeeds(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == BRIEF.strip()
    # Both calls from the hub, told where it is, whatever the session's own folder.
    assert calls(uvx_log) == [
        {"args": release_argv(VERSION, "--version"), "cwd": str(hub), "root": str(hub)},
        {"args": release_argv(VERSION), "cwd": str(hub), "root": str(hub)},
    ]
    assert [call["args"] for call in calls(uvx_log)] == [
        ["--from", AC_SOURCE, "hub", "--version"],
        ["--from", AC_SOURCE, "hub", "brief"],
    ]


def test_caps_brief_when_uvx_prints_long_output(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    assert len(LONG_BRIEF) > BRIEF_CAP
    assert not LONG_BRIEF[BRIEF_CAP - 1].isspace()

    completed, _ = start(
        hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        bin_dir=bin_dir,
        env={"FAKE_UVX_BRIEF": "long"},
    )

    assert context_of(completed) == LONG_BRIEF[:BRIEF_CAP]


# (the fake uvx's answers, or None for no uvx; the hub.json version; the cause the header names;
# the number of uvx calls)
CAUSES: dict[str, tuple[dict[str, str] | None, object, str, int]] = {
    "no_uvx": (None, VERSION, "no uv", 0),
    "resolve_fails": ({"FAKE_UVX_RESOLVE": "fail"}, VERSION, "resolve failed", 1),
    "brief_exits_three": ({"FAKE_UVX_BRIEF": "exit3"}, VERSION, "failed (exit 3)", 2),
    "brief_empty": ({"FAKE_UVX_BRIEF": "empty"}, VERSION, "failed (no output)", 2),
    "cannot_start": ({"unstartable": "yes"}, VERSION, "failed (cannot start)", 0),
    "version_absent": ({}, None, "no version", 0),
    "version_malformed": ({}, "1.2", "no version", 0),
}


@pytest.mark.parametrize("case", sorted(CAUSES))
def test_names_cause_when_brief_unavailable(
    case: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    answers, version, cause, called = CAUSES[case]
    env = dict(answers or {})
    if env.pop("unstartable", None):  # found on PATH, but its interpreter does not exist: OSError
        install_uvx(bin_dir, python=hook_python, log=uvx_log, interpreter="/no/such/sh")
    elif answers is not None:
        install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub, version=version)

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
    )

    context = context_of(completed)
    assert context == expected_mini_brief(cause)
    assert FALLBACK_HEADER.fullmatch(context.splitlines()[0])
    assert len(calls(uvx_log)) == called


def is_lock_free_within(lock_path: Path, deadline: float) -> bool:
    """True once an exclusive lock on ``lock_path`` can be taken ("r+": it must exist)."""
    end = time.monotonic() + deadline
    with lock_path.open("r+") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.01)
            else:
                return True


def test_kills_group_when_calls_exceed_deadline(
    hub: Path,
    *,
    hook_python: str,
    run_hook_with_constant: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    # The rendered 10 s is pinned by test_keeps_brief_timeout_inside_hook_timeout_when_rendered;
    # this run lowers it to TEST_TIMEOUT. The resolve step fits it; the brief then hangs.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    event = {"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"}
    env = {"FAKE_UVX_RESOLVE": "slow", "FAKE_UVX_BRIEF": "hang"}
    locks = [uvx_log.with_name(uvx_log.name + suffix) for suffix in (".hub.lock", ".tool.lock")]

    try:
        completed = run_hook_with_constant(
            hook_python,
            hub / HOOK,
            constant=("BRIEF_TIMEOUT", TEST_TIMEOUT),
            stdin=json.dumps(event).encode(),
            cwd=hub.parent,
            env={"PATH": str(bin_dir), "HOME": str(bin_dir.parent / "home")} | env,
        )

        assert context_of(completed) == expected_mini_brief("timed out")
        assert [call["args"][-1] for call in calls(uvx_log)] == ["--version", "brief"]
        for lock in locks:
            assert lock.with_name(lock.name + ".pid").exists(), f"{lock.name}: never held"
            assert is_lock_free_within(lock, PROBE_DEADLINE), f"{lock.name}: still held"
    finally:
        for lock in locks:
            with contextlib.suppress(FileNotFoundError, ProcessLookupError, ValueError):
                os.kill(int(lock.with_name(lock.name + ".pid").read_text()), signal.SIGKILL)


def test_times_out_when_calls_together_exceed_deadline(
    hub: Path,
    *,
    hook_python: str,
    run_hook_with_constant: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    # One deadline for both calls: each alone would fit it.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    event = {"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"}
    env = {"FAKE_UVX_RESOLVE": "slow", "FAKE_UVX_BRIEF": "slow", "FAKE_UVX_SLOW": str(SLOW_CALL)}

    completed = run_hook_with_constant(
        hook_python,
        hub / HOOK,
        constant=("BRIEF_TIMEOUT", TEST_TIMEOUT),
        stdin=json.dumps(event).encode(),
        cwd=hub.parent,
        env={"PATH": str(bin_dir), "HOME": str(bin_dir.parent / "home")} | env,
    )

    assert context_of(completed) == expected_mini_brief("timed out")
    assert [call["args"][-1] for call in calls(uvx_log)] == ["--version", "brief"]


def test_keeps_brief_timeout_inside_hook_timeout_when_rendered(
    demo_config: HubConfig, pinned_timeout: Callable[..., Any]
) -> None:
    value, hook_timeouts = pinned_timeout(
        demo_config, hook=HOOK, constant="BRIEF_TIMEOUT", event="SessionStart"
    )

    assert value == BRIEF_TIMEOUT
    assert hook_timeouts == {
        "plugin/hub-workflow/hooks/hooks.json": [20],
        ".claude/settings.json": [20],
    }
    assert all(timeout > BRIEF_TIMEOUT for found in hook_timeouts.values() for timeout in found)


def test_lists_what_exists_when_now_and_journal_missing(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    (hub / "brain" / "now.md").unlink()
    for rel in JOURNAL:
        (hub / rel).unlink()

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == "# Brief (fallback: hub brief no uv)"


@pytest.mark.parametrize("mode", ["brief", None])
def test_appends_snapshot_when_source_compact(
    mode: str | None,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    if mode is not None:
        install_uvx(bin_dir, python=hook_python, log=uvx_log)
    (hub / SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
    (hub / SNAPSHOT).write_text(SNAPSHOT_TEXT, encoding="utf-8")

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source="compact"
    )

    brief = BRIEF.strip() if mode else expected_mini_brief("no uv")
    assert context_of(completed) == brief + SNAPSHOT_HEAD + SNAPSHOT_TEXT[:NOW_CAP]


def test_keeps_brief_when_snapshot_not_utf8(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    (hub / SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
    (hub / SNAPSHOT).write_bytes(b"# Snapshot\ncaf\xe9 notes\n")

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source="compact"
    )

    expected = expected_mini_brief("no uv") + SNAPSHOT_HEAD + "# Snapshot\ncaf\ufffd notes\n"
    assert context_of(completed) == expected


def test_calls_uvx_only_from_session_start_when_templates_read(demo_config: HubConfig) -> None:
    texts = {file.path: file.content.decode("utf-8") for file in render_hub(demo_config).files}
    uvx = re.compile(r"\buvx\b")

    callers = {
        path
        for path, text in texts.items()
        if uvx.search(text) and (path.startswith("plugin/") or path.endswith(".py"))
    }

    assert callers == {HOOK}
    assert [path for path, text in texts.items() if "scripts/brief.py" in text] == []


# Prints the rendered hook's source, formatted for a version given as argv[1] (as the hook does).
SOURCE_PROBE = """
import importlib.util, json
spec = importlib.util.spec_from_file_location("session_start", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.SOURCE.format(version=sys.argv[2])))
"""


def test_ties_brief_source_to_release_command_when_rendered(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any]
) -> None:
    source = run_python(
        hook_python,
        SOURCE_PROBE,
        path=hub / HOOK.rsplit("/", 1)[0],
        args=[str(hub / HOOK), VERSION],
    )

    assert release_argv(VERSION) == ["--from", source, "hub", "brief"]


def test_skips_now_when_not_regular_file(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    # A FIFO with no writer would block the read for good: it is never opened.
    (hub / "brain" / "now.md").unlink()
    os.mkfifo(hub / "brain" / "now.md")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == f"# Brief (fallback: hub brief no uv)\n\n{LATEST_JOURNAL}"


def test_names_failed_when_pinned_brief_raises(
    hub: Path,
    *,
    hook_python: str,
    run_hook_with_constant: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    # A source the version cannot fill: the resolution raises before any call.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    event = {"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"}

    completed = run_hook_with_constant(
        hook_python,
        hub / HOOK,
        constant=("SOURCE", "{unknown}"),
        stdin=json.dumps(event).encode(),
        cwd=hub.parent,
        env={"PATH": str(bin_dir), "HOME": str(bin_dir.parent / "home")},
    )

    assert context_of(completed) == expected_mini_brief("failed")
    assert calls(uvx_log) == []
