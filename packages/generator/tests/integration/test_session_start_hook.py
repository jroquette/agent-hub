"""SessionStart through the rendered hook: the cached brief, else the mini brief, and the refresh.

ADR 0055: the hook never waits for the CLI. It injects ``.hub-cache/brief.json`` headed with
its age while the cache is under 12 h old, else the mini brief naming the cause (``brief cache
folder is a link``, ``no brief cache``, ``brief cache stale``, ``brief cache unreadable``, or the
last refresh's cause from ``.hub-cache/refresh.json``). When the cache is missing, unreadable or
at least 5 min old it starts one detached refresh (its own session, none of the hook's stdio, one
at a time per hub through a ``flock`` on ``.hub-cache/refresh.lock``), which runs the pinned
``hub brief --write-cache`` as AC-4.17 and AC-15.7 ran ``hub brief``: the resolve step
(``hub --version``) then the brief on a tag, one call on a lock commit (ADR 0054), within one
``REFRESH_TIMEOUT``, its process group killed past it.

A rendered demo hub at ``ws/demo-hub`` pins ``platform.version`` ``1.2.3``. The hook runs as
Claude Code runs it, a file on ``hook_python`` with the event on stdin, in an environment built
from scratch whose ``PATH`` holds only a test folder: the fake ``uvx`` when a case installs it
(the refresh runs on the hook's own interpreter), so the real ``uv`` (and the network) is never
reached. The fake
records each call's arguments, working directory and ``AGENT_HUB_ROOT`` (and its session, its
parent and its parent's session, for the foreground and refresh checks), then answers the
resolve step as ``FAKE_UVX_RESOLVE`` says (``ok``, ``fail``, ``slow``) and the brief as
``FAKE_UVX_BRIEF`` says (``brief``, ``exit3``, ``empty``, ``slow``, ``sleep``, ``hang``,
``long``). Given
``--write-cache``, a brief it printed is also written to the cache, replaced whole, as the CLI
does. Every process a case leaves behind (a refresh, the fake, its holders) is killed at
teardown.
"""

import contextlib
import fcntl
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterator, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND, pinned_release_command
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.hub_files.release_commit import ReleaseCommit
from agent_hub.core.testing.builders import (
    a_hub_document,
    a_local_environments_document,
    an_environments_document,
)
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    VALUE_PARTS,
    RepositoryCase,
)
from agent_hub.generator.render_hub import render_hub

HOOK = "plugin/hub-workflow/hooks/session_start.py"
VERSION = "1.2.3"
BRIEF = "# Brief\nAll repos green.\n"
# The refresh's limit in the rendered hook (ADR 0055), and the one a timeout run lowers it to (s).
REFRESH_TIMEOUT = 60
TEST_TIMEOUT = 2
# Each of the two calls takes this long: alone it fits the lowered deadline with a margin; both
# together do not, so only one deadline for both ends the run.
SLOW_CALL = 0.7 * TEST_TIMEOUT
# How long a holder waits for the run to reach the point the test is about.
HOLDER_WAIT = 10.0
# The lock probe: how long a killed holder may take to release its lock.
PROBE_DEADLINE = 5.0
# A hanging call's processes: ``hub`` (uvx's child) and its own child (as ``hub brief``'s git or
# gh), in the call's process group, each holding an exclusive lock until it dies.
# The hub holder prints the brief after FAKE_UVX_HOLD seconds (default: never) and exits; the tool
# holder, its stdout not the call's, holds its lock until killed, as an orphaned git or gh would.
HOLDER = """\
import fcntl, os, subprocess, sys, time
lock = open(sys.argv[1], "w")
fcntl.flock(lock, fcntl.LOCK_EX)
with open(sys.argv[1] + ".pid", "w") as fh:
    fh.write(str(os.getpid()))
if len(sys.argv) < 3:
    time.sleep(60)
    sys.exit(0)
tool = [sys.executable, __file__, sys.argv[2]]
subprocess.Popen(tool, start_new_session=False, stdout=subprocess.DEVNULL)
while not os.path.exists(sys.argv[2] + ".pid"):
    time.sleep(0.01)
time.sleep(float(os.environ.get("FAKE_UVX_HOLD", "60")))
sys.stdout.write(BRIEF_TEXT)
""".replace("BRIEF_TEXT", repr(BRIEF))
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
call = {"args": args, "cwd": os.getcwd(), "root": os.environ.get("AGENT_HUB_ROOT"),
        "session": os.getsid(0), "parent": os.getppid(), "parent_session": os.getsid(os.getppid())}
with open(log, "a", encoding="utf-8") as fh:
    fh.write(json.dumps(call) + "\\n")
text = ""
if mode == "slow":  # answers, late
    time.sleep(SLOW_SECONDS)
    text = "1.2.3\\n" if kind == "resolve" else BRIEF_TEXT
elif mode == "sleep":  # answers after FAKE_UVX_SLEEP seconds
    time.sleep(float(os.environ["FAKE_UVX_SLEEP"]))
    text = BRIEF_TEXT
elif mode == "hang":  # like uvx, wait on its child (hub), which has a child of its own
    holder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "holder.py")
    held = [sys.executable, holder, log + ".hub.lock", log + ".tool.lock"]
    text = subprocess.run(held, stdout=subprocess.PIPE).stdout.decode()
elif mode == "fail":  # the release cannot be resolved
    sys.stderr.write("error: cannot fetch the release\\n")
    sys.exit(1)
elif mode == "exit3":  # some output, but a non-zero exit: still a failure
    sys.stdout.write("Usage: hub [OPTIONS] COMMAND\\n")
    sys.exit(3)
elif mode == "ok":
    text = "1.2.3\\n"
elif mode == "brief":
    text = BRIEF_TEXT
elif mode == "long":
    text = LONG_TEXT
sys.stdout.write(text)
sys.stdout.flush()
if "--write-cache" in args and text:  # as the CLI does: the printed brief, replaced whole
    folder = os.path.join(os.environ.get("AGENT_HUB_ROOT") or os.getcwd(), ".hub-cache")
    os.makedirs(folder, exist_ok=True)
    written = os.path.join(folder, "brief.json.partial")
    with open(written, "w", encoding="utf-8") as fh:
        json.dump({"made_at": time.time(), "brief": text}, fh)
    os.replace(written, os.path.join(folder, "brief.json"))
""".replace("BRIEF_TEXT", repr(BRIEF))
    .replace("LONG_TEXT", repr(LONG_BRIEF))
    .replace("SLOW_SECONDS", repr(SLOW_CALL))
)
FALLBACK_HEADER = re.compile(
    r"# Brief \(fallback: hub brief (no uv|no version|resolve failed|timed out"
    r"|failed|failed \(exit -?[0-9]+\)|failed \(no output\)|failed \(cannot start\)"
    r"|bad platform\.repository)\)"
)
# AC-49.5's custom source for VERSION, spelled out.
CUSTOM_SOURCE = (
    f"git+https://git.acme.test/tools/agent-hub@v{VERSION}#subdirectory=packages/agent-hub"
)
BAD_REPOSITORIES = [case for case in REPOSITORY_CASES if not case.is_valid]
# Marks a key the document leaves out (``None`` is a value: JSON ``null``).
ABSENT = object()
# The brief cache (ADR 0055, plan Q11): its files, the refresh floor and the shown limit (s).
CACHE_DIR = ".hub-cache"
CACHE = f"{CACHE_DIR}/brief.json"
REFRESH_LOCK = f"{CACHE_DIR}/refresh.lock"
REFRESH_RECORD = f"{CACHE_DIR}/refresh.json"
CACHE_MAX_BYTES = 64 * 1024
CACHED_BRIEF = "# Brief\n\n## Now\nShip the cache.\n"
OLD_BRIEF = "# Brief\n\n## Now\nAn older focus.\n"
FRESH_AGE = 200  # shown as "3 min", whether the age is rounded or cut
FLOOR = 5 * 60
LIMIT = 12 * 60 * 60
# How long a test waits for a refresh to start or end, and for a refresh that must not start.
REFRESH_WAIT = 10.0
NO_REFRESH_GRACE = 2.0
# AC-18: the foreground's budget with no cache (s), while the refresh's brief takes FAKE_UVX_SLEEP.
FOREGROUND_BUDGET = 0.3
REFRESH_SLEEP = 3.0

type RunHook = Callable[..., Any]

pytestmark = pytest.mark.usefixtures("no_process_left")


def expected_mini_brief(cause: str) -> str:
    assert not NOW_MD[NOW_CAP - 1].isspace()  # so the cut shows as it is, whitespace-stripped
    return f"# Brief (fallback: hub brief {cause})\n\n{NOW_MD[:NOW_CAP]}\n\n{LATEST_JOURNAL}"


def cached_context(age: str, brief: str) -> str:
    """The context of a cached brief ``age`` old: one header line naming its age, then the brief."""
    return f"(brief from {age} ago)\n\n{brief.strip()}"


def release_argv(version: str, *arguments: str) -> list[str]:
    """Core's pinned-release command for ``version`` without ``uvx``, then ``arguments``."""
    command = PINNED_RELEASE_COMMAND.format(version=version).split()
    assert command[0] == "uvx"
    return [*command[1:], *(arguments or ("brief",))]


def write_hub_json(hub: Path, *, version: object = VERSION, repository: object = ABSENT) -> None:
    """The builder's document with ``platform.version`` = ``version`` (absent when ``None``) and
    ``platform.repository`` = ``repository`` (absent when ``ABSENT``)."""
    document = a_hub_document()
    if version is None:
        del document["platform"]["version"]
    else:
        document["platform"]["version"] = version
    if repository is not ABSENT:
        document["platform"]["repository"] = repository
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
    assert not (rendered / CACHE_DIR).exists()
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


def raw_calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def calls(log: Path) -> list[dict[str, Any]]:
    """Each call's arguments, working directory and ``AGENT_HUB_ROOT``."""
    return [
        {
            key: value
            for key, value in call.items()
            if key not in ("session", "parent", "parent_session")
        }
        for call in raw_calls(log)
    ]


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


def open_hook(
    hub: Path,
    *,
    python: str,
    bin_dir: Path,
    env: Mapping[str, str] | None = None,
    new_session: bool = False,
) -> subprocess.Popen[bytes]:
    """Start SessionStart at ``hub`` as ``start`` does, without waiting: its event comes from a
    file, its stdout and stderr are pipes."""
    event = bin_dir.parent / "event.json"
    event.write_text(
        json.dumps({"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"}),
        encoding="utf-8",
    )
    full_env = {"PATH": str(bin_dir), "HOME": str(bin_dir.parent / "home")} | dict(env or {})
    with event.open("rb") as stdin:
        return subprocess.Popen(  # noqa: S603 - the hook's interpreter, a rendered hook file
            [python, str(hub / HOOK)],
            stdin=stdin,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=hub.parent,
            env=full_env,
            start_new_session=new_session,
        )


def context_of(completed: Any) -> str:
    """The ``additionalContext`` of a clean run (exit 0, nothing on stderr, one JSON object)."""
    assert (completed.returncode, completed.stderr) == (0, b"")
    output = json.loads(completed.stdout)
    assert output["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return output["hookSpecificOutput"]["additionalContext"]


def write_cache(hub: Path, *, age: float, brief: str = CACHED_BRIEF) -> None:
    """The cache ``hub brief --write-cache`` leaves, made ``age`` seconds ago."""
    folder = hub / CACHE_DIR
    folder.mkdir(exist_ok=True)
    (folder / ".gitignore").write_text("*\n", encoding="utf-8")
    document = {"made_at": time.time() - age, "brief": brief}
    (hub / CACHE).write_text(json.dumps(document), encoding="utf-8")


def cached_brief(hub: Path) -> str:
    brief: str = json.loads((hub / CACHE).read_bytes())["brief"]
    return brief


def wait_until(condition: Callable[[], object], deadline: float = REFRESH_WAIT) -> bool:
    """True once ``condition()`` is truthy, polled until ``deadline`` seconds have passed."""
    end = time.monotonic() + deadline
    while not condition():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    return True


def refresh_ended(hub: Path, deadline: float = REFRESH_WAIT) -> bool:
    """True once the refresh lock exists and is free: the refresh that held it has ended."""
    end = time.monotonic() + deadline
    lock = hub / REFRESH_LOCK
    if not wait_until(lock.exists, deadline):
        return False
    return is_lock_free_within(lock, max(end - time.monotonic(), 0.0))


def refresh_cause(hub: Path) -> str:
    """The cause the last failed refresh recorded."""
    cause: str = json.loads((hub / REFRESH_RECORD).read_bytes())["cause"]
    return cause


def brief_calls(log: Path) -> list[dict[str, Any]]:
    """The calls of ``hub brief --write-cache`` (the refresh's brief)."""
    return [call for call in raw_calls(log) if call["args"][-2:] == ["brief", "--write-cache"]]


def set_constant(hub: Path, name: str, value: object) -> None:
    """Give the rendered hook's module-level ``name`` the literal ``value``: the hook and the
    refresh it starts run the same file."""
    hook = hub / HOOK
    text, count = re.subn(
        rf"^{name} = .*$", f"{name} = {value!r}", hook.read_text(encoding="utf-8"), flags=re.M
    )
    assert count == 1, f"{name}: {count} module-level assignments in the rendered hook"
    hook.write_text(text, encoding="utf-8")


@pytest.mark.parametrize("source", ["startup", "resume", "clear"])
def test_injects_cached_brief_with_age_when_cache_is_fresh(
    source: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    # AC-17: a cache under the floor is the context, headed with its age; no call in the
    # foreground.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_cache(hub, age=FRESH_AGE)

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source=source
    )

    assert context_of(completed) == cached_context("3 min", CACHED_BRIEF)
    assert calls(uvx_log) == []


def shows_mini_brief_then_refreshes(
    hub: Path, cause: str, *, python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    """AC-18: the mini brief naming ``cause`` within the budget while the refresh's brief takes
    ``REFRESH_SLEEP``; then that refresh runs ``hub brief --write-cache`` and ends."""
    install_uvx(bin_dir, python=python, log=uvx_log)
    env = {"FAKE_UVX_BRIEF": "sleep", "FAKE_UVX_SLEEP": str(REFRESH_SLEEP)}

    completed, took = start(
        hub, python=python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
    )

    assert context_of(completed) == expected_mini_brief(cause)
    assert took < FOREGROUND_BUDGET
    assert wait_until(lambda: brief_calls(uvx_log)), "no refresh started"
    assert refresh_ended(hub, REFRESH_WAIT + REFRESH_SLEEP)
    assert len(brief_calls(uvx_log)) == 1


@pytest.mark.serial
def test_shows_mini_brief_and_starts_refresh_when_cache_is_missing(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    shows_mini_brief_then_refreshes(
        hub,
        "no brief cache",
        python=hook_python,
        run_hook_file=run_hook_file,
        bin_dir=bin_dir,
        uvx_log=uvx_log,
    )


@pytest.mark.serial
def test_shows_mini_brief_and_starts_refresh_when_cache_is_stale(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    write_cache(hub, age=LIMIT + 3600)

    shows_mini_brief_then_refreshes(
        hub,
        "brief cache stale",
        python=hook_python,
        run_hook_file=run_hook_file,
        bin_dir=bin_dir,
        uvx_log=uvx_log,
    )


def test_starts_no_refresh_when_cache_is_younger_than_floor(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # Q11: resume, compact, hub web and claude -p sessions in a row start no refresh each.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_cache(hub, age=FLOOR - 60)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == cached_context("4 min", CACHED_BRIEF)
    assert not wait_until(lambda: raw_calls(uvx_log), NO_REFRESH_GRACE)


def test_writes_cache_when_refresh_ends(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # A cache past the floor but under the limit: shown with its age, then refreshed.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_cache(hub, age=60 * 60, brief=OLD_BRIEF)
    before = time.time()

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    header, _, body = context_of(completed).partition("\n\n")
    assert re.fullmatch(r"\(brief from [^\n]+ ago\)", header), header
    assert body == OLD_BRIEF.strip()
    assert refresh_ended(hub)
    after = time.time()
    document = json.loads((hub / CACHE).read_bytes())
    assert document["brief"] == BRIEF
    assert before <= document["made_at"] <= after


# (what the last failed refresh recorded, what the mini brief names)
RECORDED_CAUSES = {
    "timed_out": ("timed out", "timed out"),
    "long_cause": ("x" * 300, "x" * 200),
}


@pytest.mark.parametrize("case", sorted(RECORDED_CAUSES))
def test_names_last_refresh_cause_when_refresh_failed(
    case: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    recorded, shown = RECORDED_CAUSES[case]
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    (hub / CACHE_DIR).mkdir()
    (hub / REFRESH_RECORD).write_text(
        json.dumps({"made_at": time.time() - 60, "cause": recorded}), encoding="utf-8"
    )
    assert not (hub / CACHE).exists()

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief(shown)
    assert refresh_ended(hub)  # the cache is still missing: a refresh ran


GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_AUTHOR_NAME": "Test User",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "Test User",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_ALLOW_PROTOCOL": "file",
}


def git(hub: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("git")
    assert executable is not None
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(hub.parent)} | GIT_ENV
    return subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        [executable, *args], cwd=hub, env=env, capture_output=True, text=True, check=check
    )


def test_leaves_hub_clean_when_session_start_refreshes(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # The cache folder ignores itself, so no hub's .gitignore needs an edit.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    git(hub, "init", "-q", "-b", "main")
    git(hub, "add", "-A")
    git(hub, "commit", "-q", "-m", "hub")
    assert git(hub, "status", "--porcelain", "--untracked-files=all").stdout == ""
    # Nothing the hub tracks ignores the cache folder already.
    assert git(hub, "check-ignore", "-q", "--no-index", CACHE, check=False).returncode == 1

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert cached_brief(hub) == BRIEF
    assert git(hub, "status", "--porcelain", "--untracked-files=all").stdout == ""


@pytest.mark.serial
def test_releases_hook_output_when_refresh_outlives_hook(
    hub: Path, *, hook_python: str, bin_dir: Path, uvx_log: Path
) -> None:
    # AC-19: the read of the hook's output ends when the hook exits, not when its refresh does.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    env = {"FAKE_UVX_BRIEF": "sleep", "FAKE_UVX_SLEEP": str(REFRESH_SLEEP)}

    hook = open_hook(hub, python=hook_python, bin_dir=bin_dir, env=env)
    try:
        stdout, stderr = hook.communicate(timeout=REFRESH_WAIT + REFRESH_SLEEP)
    finally:
        hook.kill()
        hook.wait()

    # EOF came while the refresh still sleeps: its cache is not written yet.
    assert not (hub / CACHE).exists()
    assert (hook.returncode, stderr) == (0, b"")
    output = json.loads(stdout)["hookSpecificOutput"]
    assert output["additionalContext"] == expected_mini_brief("no brief cache")
    assert refresh_ended(hub, REFRESH_WAIT + REFRESH_SLEEP)
    assert cached_brief(hub) == BRIEF


def test_keeps_refresh_alive_when_hook_group_is_killed(
    hub: Path, *, hook_python: str, bin_dir: Path, uvx_log: Path
) -> None:
    # AC-19: Claude Code kills the hook's process group; the refresh, in its own session, lives.
    # The fake uvx writes the cache itself, so the refresh is checked directly: it is not in the
    # hook's session, and only a refresh that lived to the end removes the recorded cause.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    env = {"FAKE_UVX_BRIEF": "sleep", "FAKE_UVX_SLEEP": str(REFRESH_SLEEP)}
    (hub / CACHE_DIR).mkdir()
    (hub / REFRESH_RECORD).write_text(
        json.dumps({"made_at": time.time() - 60, "cause": "timed out"}), encoding="utf-8"
    )

    hook = open_hook(hub, python=hook_python, bin_dir=bin_dir, env=env, new_session=True)
    try:
        assert wait_until(lambda: brief_calls(uvx_log)), "no refresh started"
        assert not (hub / CACHE).exists()
        # uvx's parent: the refresh that runs the call; the hook leads its own session.
        refresh_pid = brief_calls(uvx_log)[0]["parent"]
        assert refresh_pid not in (hook.pid, os.getpid(), 1)
        assert os.getsid(refresh_pid) == refresh_pid != hook.pid
        with contextlib.suppress(ProcessLookupError):
            os.killpg(hook.pid, signal.SIGKILL)
    finally:
        hook.kill()
        hook.communicate()

    assert refresh_ended(hub, REFRESH_WAIT + REFRESH_SLEEP)
    assert cached_brief(hub) == BRIEF
    assert not (hub / REFRESH_RECORD).exists()


def test_runs_one_refresh_when_two_sessions_start_together(
    hub: Path, *, hook_python: str, bin_dir: Path, uvx_log: Path
) -> None:
    # AC-19: both see no cache; the refresh lock lets one of them refresh.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    env = {"FAKE_UVX_BRIEF": "sleep", "FAKE_UVX_SLEEP": str(REFRESH_SLEEP)}

    hooks = [open_hook(hub, python=hook_python, bin_dir=bin_dir, env=env) for _ in range(2)]
    outputs = []
    try:
        outputs = [hook.communicate(timeout=REFRESH_WAIT) for hook in hooks]
    finally:
        for hook in hooks:
            hook.kill()
            hook.wait()

    assert len(outputs) == 2
    for stdout, stderr in outputs:
        assert stderr == b""
        context = json.loads(stdout)["hookSpecificOutput"]["additionalContext"]
        assert context == expected_mini_brief("no brief cache")
    assert refresh_ended(hub, REFRESH_WAIT + REFRESH_SLEEP)
    assert [call["args"][-1] for call in calls(uvx_log)] == ["--version", "--write-cache"]


def fresh_document(*, brief: str = CACHED_BRIEF) -> bytes:
    return json.dumps({"made_at": time.time() - FRESH_AGE, "brief": brief}).encode()


def planted_link(cache: Path) -> None:
    target = cache.parent.parent.parent / "planted.json"
    target.write_bytes(fresh_document())
    cache.symlink_to(target)


# Each writes a cache file the hook must refuse (AC-21): not a JSON object with a finite,
# not-future made_at and a string brief, a link, a FIFO, a folder, or over 64 KiB.
MALFORMED: dict[str, Callable[[Path], object]] = {
    "not_json": lambda cache: cache.write_bytes(b"{not json"),
    "array": lambda cache: cache.write_bytes(b"[]"),
    "deep_nesting": lambda cache: cache.write_bytes(b"[" * 30_000 + b"]" * 30_000),
    "no_made_at": lambda cache: cache.write_bytes(b'{"brief": "# Brief"}'),
    "made_at_text": lambda cache: cache.write_bytes(b'{"made_at": "now", "brief": "# Brief"}'),
    "made_at_nan": lambda cache: cache.write_bytes(b'{"made_at": NaN, "brief": "# Brief"}'),
    "made_at_future": lambda cache: cache.write_bytes(
        json.dumps({"made_at": time.time() + 3600, "brief": "# Brief"}).encode()
    ),
    "brief_not_text": lambda cache: cache.write_bytes(
        json.dumps({"made_at": time.time() - FRESH_AGE, "brief": 42}).encode()
    ),
    "oversized": lambda cache: cache.write_bytes(fresh_document(brief="x" * CACHE_MAX_BYTES)),
    "link": planted_link,
    "fifo": lambda cache: os.mkfifo(cache),
    "folder": lambda cache: cache.mkdir(),
}


@pytest.mark.parametrize("case", sorted(MALFORMED))
def test_shows_mini_brief_when_cache_is_malformed(
    case: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    (hub / CACHE_DIR).mkdir()
    MALFORMED[case](hub / CACHE)
    assert os.path.lexists(hub / CACHE)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("brief cache unreadable")
    assert refresh_ended(hub)
    assert len(brief_calls(uvx_log)) == 1


def planted_folder_link(folder: Path) -> None:
    target = folder.parent.parent / "planted-cache"
    target.mkdir()
    (target / "brief.json").write_bytes(fresh_document())
    folder.symlink_to(target)


# Each puts something other than a real folder at ``.hub-cache`` (a fresh cache behind the link),
# and the cause the mini brief names.
FOLDER_PROBLEMS: dict[str, tuple[Callable[[Path], object], str]] = {
    "link": (planted_folder_link, "brief cache folder is a link"),
    "file": (lambda folder: folder.write_bytes(b""), "brief cache folder is not a folder"),
}


def contents(folder: Path) -> dict[str, bytes]:
    """Each file of ``folder`` (none when it is absent) and its bytes."""
    return {path.name: path.read_bytes() for path in folder.iterdir()} if folder.is_dir() else {}


@pytest.mark.parametrize("case", sorted(FOLDER_PROBLEMS))
def test_names_cache_folder_when_it_is_not_a_folder(
    case: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    plant, cause = FOLDER_PROBLEMS[case]
    plant(hub / CACHE_DIR)
    planted = hub.parent / "planted-cache"
    before = (stat.S_IFMT((hub / CACHE_DIR).lstat().st_mode), contents(planted))

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief(cause)
    assert not wait_until(lambda: raw_calls(uvx_log), NO_REFRESH_GRACE)
    assert (stat.S_IFMT((hub / CACHE_DIR).lstat().st_mode), contents(planted)) == before


def test_repairs_ignore_rule_when_gitignore_is_empty(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # A hook killed between creating .gitignore and writing it leaves it empty: the next one
    # writes the rule whole, so the cache never shows in git status.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    (hub / CACHE_DIR).mkdir()
    (hub / CACHE_DIR / ".gitignore").write_bytes(b"")
    (hub / CACHE_DIR / ".gitignore.partial-1").write_bytes(b"")  # a killed run's temp
    git(hub, "init", "-q", "-b", "main")
    git(hub, "add", "-A", ":!.hub-cache")
    git(hub, "commit", "-q", "-m", "hub")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert (hub / CACHE_DIR / ".gitignore").read_text(encoding="utf-8").splitlines()[-1] == "*"
    assert cached_brief(hub) == BRIEF
    assert git(hub, "status", "--porcelain", "--untracked-files=all").stdout == ""


def test_shows_cached_brief_when_ignore_rule_cannot_be_written(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # A cache past the floor starts a refresh, but a folder at .gitignore stops the rule's write:
    # the brief already read is still the context, and no refresh starts.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_cache(hub, age=60 * 60, brief=OLD_BRIEF)
    (hub / CACHE_DIR / ".gitignore").unlink()
    (hub / CACHE_DIR / ".gitignore").mkdir()

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == cached_context("1 h", OLD_BRIEF)
    assert not wait_until(lambda: raw_calls(uvx_log), NO_REFRESH_GRACE)
    assert sorted(path.name for path in (hub / CACHE_DIR).iterdir()) == [".gitignore", "brief.json"]


def test_resolves_then_briefs_when_uvx_succeeds(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    # Both calls of the refresh from the hub, told where it is, whatever the session's own folder.
    assert calls(uvx_log) == [
        {"args": release_argv(VERSION, "--version"), "cwd": str(hub), "root": str(hub)},
        {
            "args": release_argv(VERSION, "brief", "--write-cache"),
            "cwd": str(hub),
            "root": str(hub),
        },
    ]
    assert [call["args"] for call in calls(uvx_log)] == [
        ["--from", AC_SOURCE, "hub", "--version"],
        ["--from", AC_SOURCE, "hub", "brief", "--write-cache"],
    ]


def test_caps_brief_when_cache_holds_long_brief(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    assert len(LONG_BRIEF) > BRIEF_CAP
    assert not LONG_BRIEF[BRIEF_CAP - 1].isspace()
    write_cache(hub, age=FRESH_AGE, brief=LONG_BRIEF)
    assert (hub / CACHE).stat().st_size < CACHE_MAX_BYTES  # read, then cut: not refused

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == cached_context("3 min", LONG_BRIEF[:BRIEF_CAP])


# (the fake uvx's answers, or None for no uvx; the hub.json version; the cause the header names;
# the number of uvx calls; whether the cause comes from a failed refresh, named by the next session)
CAUSES: dict[str, tuple[dict[str, str] | None, object, str, int, bool]] = {
    "no_uvx": (None, VERSION, "no uv", 0, False),
    "resolve_fails": ({"FAKE_UVX_RESOLVE": "fail"}, VERSION, "resolve failed", 1, True),
    "brief_exits_three": ({"FAKE_UVX_BRIEF": "exit3"}, VERSION, "failed (exit 3)", 2, True),
    "brief_empty": ({"FAKE_UVX_BRIEF": "empty"}, VERSION, "failed (no output)", 2, True),
    "cannot_start": ({"unstartable": "yes"}, VERSION, "failed (cannot start)", 0, True),
    "version_absent": ({}, None, "no version", 0, False),
    "version_malformed": ({}, "1.2", "no version", 0, False),
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
    answers, version, cause, called, refreshed = CAUSES[case]
    env = dict(answers or {})
    if env.pop("unstartable", None):  # found on PATH, but its interpreter does not exist: OSError
        install_uvx(bin_dir, python=hook_python, log=uvx_log, interpreter="/no/such/sh")
    elif answers is not None:
        install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub, version=version)

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
    )

    if refreshed:
        assert context_of(completed) == expected_mini_brief("no brief cache")
        assert refresh_ended(hub)
        assert len(calls(uvx_log)) == called
        assert refresh_cause(hub) == cause
        completed, _ = start(
            hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
        )
    context = context_of(completed)
    assert context == expected_mini_brief(cause)
    assert FALLBACK_HEADER.fullmatch(context.splitlines()[0])
    if refreshed:
        assert refresh_ended(hub)  # the next session's own refresh
    else:  # found before any cache: nothing written, no refresh
        assert not wait_until(lambda: raw_calls(uvx_log), NO_REFRESH_GRACE)
        assert not (hub / CACHE_DIR).exists()


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


@contextlib.contextmanager
def holders_reaped(uvx_log: Path) -> Iterator[list[Path]]:
    """The hanging call's two locks; after the block, each held once and now free (probe)."""
    locks = [uvx_log.with_name(uvx_log.name + suffix) for suffix in (".hub.lock", ".tool.lock")]
    try:
        yield locks
        for lock in locks:
            assert lock.with_name(lock.name + ".pid").exists(), f"{lock.name}: never held"
            assert is_lock_free_within(lock, PROBE_DEADLINE), f"{lock.name}: still held"
    finally:
        for lock in locks:
            with contextlib.suppress(FileNotFoundError, ProcessLookupError, ValueError):
                os.kill(int(lock.with_name(lock.name + ".pid").read_text()), signal.SIGKILL)


def test_kills_group_when_calls_exceed_deadline(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # The refresh's rendered 60 s is pinned by test_pins_refresh_timeout_when_rendered; this run
    # lowers it in the hook file the refresh runs. Each call takes SLOW_CALL (the brief's hub,
    # holding the locks, would then print the brief): one deadline for both ends the refresh, and
    # the kill of the brief's group frees both locks before any cache is written.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    set_constant(hub, "REFRESH_TIMEOUT", TEST_TIMEOUT)
    env = {"FAKE_UVX_RESOLVE": "slow", "FAKE_UVX_BRIEF": "hang", "FAKE_UVX_HOLD": str(SLOW_CALL)}

    with holders_reaped(uvx_log):
        completed, _ = start(
            hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
        )

        assert context_of(completed) == expected_mini_brief("no brief cache")
        assert refresh_ended(hub)
        assert [call["args"][-1] for call in calls(uvx_log)] == ["--version", "--write-cache"]
        assert refresh_cause(hub) == "timed out"
        assert not (hub / CACHE).exists()


def test_kills_group_when_refresh_interrupted(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # Ctrl-C (SIGINT) to the refresh while its brief hangs: the call's group dies with it.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    env = {"FAKE_UVX_BRIEF": "hang"}

    with holders_reaped(uvx_log) as locks:
        completed, _ = start(
            hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, env=env
        )
        assert context_of(completed) == expected_mini_brief("no brief cache")
        assert wait_until(
            lambda: all(lock.with_name(lock.name + ".pid").exists() for lock in locks),
            HOLDER_WAIT,
        ), "the brief's holders never started"
        # uvx's parent: the refresh that runs the call.
        refreshes = [call["parent"] for call in brief_calls(uvx_log)]
        assert len(refreshes) == 1
        assert refreshes[0] not in (os.getpid(), 1)

        os.kill(refreshes[0], signal.SIGINT)

        assert refresh_ended(hub, HOLDER_WAIT)


def test_pins_refresh_timeout_when_rendered(
    demo_config: HubConfig, pinned_timeout: Callable[..., Any]
) -> None:
    # The hook waits on no call now; its refresh, detached, has its own limit (ADR 0055).
    value, hook_timeouts = pinned_timeout(
        demo_config, hook=HOOK, constant="REFRESH_TIMEOUT", event="SessionStart"
    )

    assert value == REFRESH_TIMEOUT
    assert hook_timeouts == {
        "plugin/hub-workflow/hooks/hooks.json": [20],
        ".claude/settings.json": [20],
    }


def test_lists_what_exists_when_now_and_journal_missing(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    (hub / "brain" / "now.md").unlink()
    for rel in JOURNAL:
        (hub / rel).unlink()

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == "# Brief (fallback: hub brief no uv)"


@pytest.mark.parametrize("mode", ["cache", None])
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
        write_cache(hub, age=FRESH_AGE)
    (hub / SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
    (hub / SNAPSHOT).write_text(SNAPSHOT_TEXT, encoding="utf-8")

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source="compact"
    )

    brief = cached_context("3 min", CACHED_BRIEF) if mode else expected_mini_brief("no uv")
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


def test_keeps_brief_when_snapshot_is_folder(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    # The read raises IsADirectoryError: the brief stays and the snapshot section is skipped.
    (hub / SNAPSHOT).mkdir(parents=True)

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source="compact"
    )

    assert context_of(completed) == expected_mini_brief("no uv")


def test_keeps_brief_when_snapshot_is_fifo(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    # A FIFO with no writer would block the read for good: it is never opened.
    (hub / SNAPSHOT).parent.mkdir(parents=True, exist_ok=True)
    os.mkfifo(hub / SNAPSHOT)

    completed, _ = start(
        hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir, source="compact"
    )

    assert context_of(completed) == expected_mini_brief("no uv")


def test_calls_uvx_only_from_shim_session_start_and_cloud_setup_when_templates_read(
    demo_config: HubConfig,
) -> None:
    texts = {file.path: file.content.decode("utf-8") for file in render_hub(demo_config).files}
    uvx = re.compile(r"\buvx\b")

    # Every rendered file: the shim has no suffix and lives at the root.
    callers = {path for path, text in texts.items() if uvx.search(text)}

    # The demo selects `cloud`: its setup script warms the pinned release (spec D3).
    assert callers == {"hub", HOOK, "scripts/cloud-setup.sh"}
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
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    # A source the version cannot fill: the refresh's resolution raises before any call, and the
    # next session names it.
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    set_constant(hub, "SOURCE", "{unknown}")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert calls(uvx_log) == []
    assert refresh_cause(hub) == "failed"
    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)
    assert context_of(completed) == expected_mini_brief("failed")
    assert refresh_ended(hub)


def test_briefs_from_custom_source_when_hub_sets_repository(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub, repository=CUSTOM_REPOSITORY)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert calls(uvx_log) == [
        {"args": ["--from", CUSTOM_SOURCE, "hub", "--version"], "cwd": str(hub), "root": str(hub)},
        {
            "args": ["--from", CUSTOM_SOURCE, "hub", "brief", "--write-cache"],
            "cwd": str(hub),
            "root": str(hub),
        },
    ]


def test_briefs_from_default_source_when_repository_absent(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert [call["args"] for call in calls(uvx_log)] == [
        release_argv(VERSION, "--version"),
        release_argv(VERSION, "brief", "--write-cache"),
    ]


@pytest.mark.parametrize("case", BAD_REPOSITORIES, ids=[case.name for case in BAD_REPOSITORIES])
def test_names_bad_repository_cause_when_repository_bad(
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
    case: RepositoryCase,
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub, repository=case.value)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    context = context_of(completed)
    assert context == expected_mini_brief("bad platform.repository")
    assert FALLBACK_HEADER.fullmatch(context.splitlines()[0])
    assert calls(uvx_log) == []
    for part in VALUE_PARTS:
        assert part.encode() not in completed.stdout + completed.stderr, part


def test_names_no_version_first_when_version_and_repository_bad(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_hub_json(hub, version=None, repository="git+ssh://git@github.com/acme/agent-hub")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no version")
    assert calls(uvx_log) == []


# argv: the rendered hook, a repository (JSON: a string or null), a version. Prints the hook's
# ``release_source`` for them.
RELEASE_SOURCE_PROBE = """
import importlib.util, json
spec = importlib.util.spec_from_file_location("session_start", sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
print(json.dumps(module.release_source(json.loads(sys.argv[2]), sys.argv[3])))
"""


@pytest.mark.parametrize("repository", [CUSTOM_REPOSITORY, None], ids=["custom", "default"])
def test_ties_custom_source_to_release_command_when_rendered(
    hub: Path, *, hook_python: str, run_python: Callable[..., Any], repository: str | None
) -> None:
    source = run_python(
        hook_python,
        RELEASE_SOURCE_PROBE,
        path=hub / HOOK.rsplit("/", 1)[0],
        args=[str(hub / HOOK), json.dumps(repository), VERSION],
    )

    expected = (
        pinned_release_command(VERSION, repository=repository)
        if repository
        else PINNED_RELEASE_COMMAND.format(version=VERSION)
    )
    assert expected is not None
    assert ["uvx", "--from", source, "hub"] == expected.split()


MINI_ENVIRONMENTS = (
    "## Environments\n- `local` (write)\n- `staging` (ask)\n- `live` (read, PRODUCTION)"
)
UNUSABLE_LOCAL = "hub.local.json is unusable: your own environments are not shown"


def write_environments(hub: Path, *, local: str | None) -> None:
    """``hub.json`` with the spec's ``W`` (pinned to ``VERSION``), and ``local`` as the bytes of
    ``hub.local.json`` in the hub, the hook root's identity home (absent when ``None``)."""
    document = an_environments_document()
    document["platform"]["version"] = VERSION
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    if local is not None:
        (hub / "hub.local.json").write_text(local, encoding="utf-8")


def test_lists_environments_when_brief_fails(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    # AC-277.8: the mini brief lists both files' names, access and PRODUCTION.
    local = a_local_environments_document()
    local["environments"]["staging"] = {"access": "read"}
    write_environments(hub, local=json.dumps(local))

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == (
        expected_mini_brief("no uv") + "\n\n## Environments\n- `local` (write)\n- `staging` (read)"
        "\n- `live` (read, PRODUCTION)\n- `jane-cloud` (write)"
    )


def test_names_unusable_local_file_when_brief_fails(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    # AC-277.34 (AM-11): hub.json's environments, and a line naming the unusable file.
    write_environments(hub, local="{not json")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == (
        f"{expected_mini_brief('no uv')}\n\n{MINI_ENVIRONMENTS}\n{UNUSABLE_LOCAL}"
    )


def test_adds_no_environments_when_none_declared(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no uv")


# An environment name with a secret's shape (assembled at run time, so the repo holds none). The
# CLI refuses it, so `hub brief` fails and the mini brief is what the agent reads.
SECRET_NAME = "AK" + "IA" + "A" * 16


@pytest.mark.parametrize("layer", ["hub.json", "hub.local.json"])
def test_hides_secret_shaped_name_when_brief_fails(
    layer: str, hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    secret = {SECRET_NAME: {"access": "write", "production": True}}
    if layer == "hub.json":
        document = an_environments_document()
        document["platform"]["version"] = VERSION
        document["environments"] |= secret
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    else:
        write_environments(hub, local=json.dumps({"environments": secret}))

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    context = context_of(completed)
    assert context == (
        f"{expected_mini_brief('no uv')}\n\n{MINI_ENVIRONMENTS}\n- `<hidden>` (write, PRODUCTION)"
    )
    assert SECRET_NAME not in completed.stdout.decode()


def test_cuts_environments_when_over_sixty(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path
) -> None:
    document = a_hub_document()
    document["platform"]["version"] = VERSION
    document["environments"] = {f"e{index}": {"access": "read"} for index in range(1, 62)}
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    shown = "\n".join(f"- `e{index}` (read)" for index in range(1, 61))
    assert context_of(completed) == (
        f"{expected_mini_brief('no uv')}\n\n## Environments\n{shown}\n… 1 more: ./hub env list"
    )


# ADR 0054: with a matching commit in hub.lock the refresh's pinned brief is one call from the
# commit, with no resolve step; a lock without one keeps the two tag calls.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
# Written out, as AC_SOURCE is, so a change to how the hook builds it fails here.
COMMIT_SOURCE = (
    "git+https://github.com/jroquette/agent-hub@0123456789abcdef0123456789abcdef01234567"
    "#subdirectory=packages/agent-hub"
)


def write_lock(hub: Path, *, commit: str | None) -> None:
    """The lock ``hub sync`` writes for the demo pinned to ``VERSION``, with ``commit`` read from
    the default repository (None: no commit)."""
    document = a_hub_document()
    document["platform"]["version"] = VERSION
    config = HubConfig.model_validate(document)
    release = (
        None if commit is None else ReleaseCommit(commit=commit, repository=DEFAULT_REPOSITORY)
    )
    content = lock_bytes(
        build_hub_lock(rendered=render_hub(config), config=config, release=release)
    )
    (hub / "hub.lock").write_bytes(content)
    lock = json.loads(content)
    assert (lock["platform_version"], lock.get("platform_commit")) == (VERSION, commit)


NETWORK_LOGGER = '#!/bin/sh\nprintf \'%s\\n\' "{name} $*" >> "{log}"\nexit 0\n'


def test_refreshes_with_commit_source_when_lock_has_commit(
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
    tmp_path: Path,
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_lock(hub, commit=COMMIT)
    # git and gh loggers on PATH: the hook and its refresh read no release from the network.
    network_log = tmp_path / "network-calls.log"
    install_network_loggers(bin_dir, network_log)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    # No --version call: the commit needs no resolve step.
    assert calls(uvx_log) == [
        {
            "args": ["--from", COMMIT_SOURCE, "hub", "brief", "--write-cache"],
            "cwd": str(hub),
            "root": str(hub),
        }
    ]
    assert cached_brief(hub) == BRIEF
    assert not network_log.exists()


def test_refreshes_with_tag_source_when_lock_has_no_commit(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, bin_dir: Path, uvx_log: Path
) -> None:
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    write_lock(hub, commit=None)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    assert context_of(completed) == expected_mini_brief("no brief cache")
    assert refresh_ended(hub)
    assert [call["args"] for call in calls(uvx_log)] == [
        ["--from", AC_SOURCE, "hub", "--version"],
        ["--from", AC_SOURCE, "hub", "brief", "--write-cache"],
    ]


def install_network_loggers(bin_dir: Path, log: Path) -> None:
    """``git`` and ``gh`` on ``PATH`` that only log their arguments to ``log``."""
    for name in ("git", "gh"):
        (bin_dir / name).write_text(NETWORK_LOGGER.format(name=name, log=log), encoding="utf-8")
        (bin_dir / name).chmod(0o755)


@pytest.mark.parametrize("cache", ["fresh", "missing"])
def test_calls_no_network_tool_when_hook_runs_in_foreground(
    cache: str,
    hub: Path,
    *,
    hook_python: str,
    run_hook_file: RunHook,
    bin_dir: Path,
    uvx_log: Path,
    tmp_path: Path,
) -> None:
    # AC-23: the hook's own process calls no gh, no git and no uvx; only its refresh, in another
    # session, calls uvx (here at the tag: the lock holds no commit).
    install_uvx(bin_dir, python=hook_python, log=uvx_log)
    network_log = tmp_path / "network-calls.log"
    install_network_loggers(bin_dir, network_log)
    if cache == "fresh":
        write_cache(hub, age=FRESH_AGE)

    completed, _ = start(hub, python=hook_python, run_hook_file=run_hook_file, bin_dir=bin_dir)

    context = context_of(completed)
    if cache == "fresh":
        assert context == cached_context("3 min", CACHED_BRIEF)
        assert not wait_until(lambda: raw_calls(uvx_log), NO_REFRESH_GRACE)
    else:
        assert context == expected_mini_brief("no brief cache")
        assert refresh_ended(hub)
    # Each call's caller leads a session of its own: the detached refresh. The hook, run as a
    # plain child of this test, is in this test's session.
    callers = [(call["parent"], call["parent_session"]) for call in raw_calls(uvx_log)]
    assert len(callers) == (0 if cache == "fresh" else 2)
    for parent, parent_session in callers:
        assert parent_session == parent != os.getsid(0)
    assert not network_log.exists()
