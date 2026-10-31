"""The outbound probe's own checks: what it records, what it refuses and what it lets through.

Each case writes a small hook script and runs it as Claude Code runs a hook (``run_hook_file``:
the file on an interpreter, the event on stdin), on this interpreter and on a real 3.9
(``each_python``), in the probe's environment (``agent_hub.core.testing.outbound_probe``). This
test process keeps a way out of its own (``host_network``): proxy variables at a loopback port,
a ``NO_PROXY`` that exempts every host, a git URL rewrite, GitHub tokens and git limited to
``file`` remotes. A probe that let any of them reach the child would lose the record a case
expects, or hand the child a credential; one case pins the variables the child gets.

The last five pin ``processes_left``. It waits for a detached grandchild the hook leaves running,
and names one that outlives its timeout, through the probe's marker when the grandchild's command
line does not name the case's folder. Run from this process instead of through a hook, a child
is named by its whole command line however narrow ``COLUMNS`` is, and a child that has exited
counts as ended before it is reaped.
"""

import contextlib
import errno
import json
import os
import re
import signal
import socket
import subprocess
import sys
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from agent_hub.core.testing.loopback import closed_url
from agent_hub.core.testing.outbound_probe import (
    LOADED_LOG,
    outbound_calls,
    outbound_env,
    processes_left,
    recording_proxy,
    write_stubs,
)

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]

# Both spellings of the proxy variables that curl, git and Python's urllib read.
PROXY_VARIABLES = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)
# A made-up token in this process's environment, which no probed child may get.
HOST_TOKEN = "host-token-for-no-child"  # noqa: S105 - made up, never a real credential
# An empty event: the scripts below read stdin as a hook does, and ignore it.
NO_EVENT = b"{}"

# Opens a socket to a TEST-NET-1 address (RFC 5737: no host answers there) and, failing open as
# a hook does, prints the errno it got.
BAD_HOOK = """\
import json
import socket
import sys

sys.stdin.read()
attempt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
attempt.settimeout(5)
try:
    attempt.connect(("192.0.2.1", 443))
    print(json.dumps({"errno": None}))
except OSError as error:
    print(json.dumps({"errno": error.errno}))
finally:
    attempt.close()
"""

# Runs git against an https remote whose name never resolves (``.invalid``, RFC 2606), so the
# only way git can try it is through a proxy.
GIT_HOOK = """\
import subprocess
import sys

sys.stdin.read()
subprocess.run(
    ["git", "ls-remote", "https://example.invalid/x.git"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    timeout=30,
)
"""

# Runs gh itself, with no shell between, so gh's parent is this hook.
GH_HOOK = """\
import subprocess
import sys

sys.stdin.read()
subprocess.run(
    ["gh", "pr", "list", "--state", "open"],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    timeout=30,
)
"""

# Connects to the loopback port given on stdin and looks ``localhost`` up twice; then, as the
# control that shows the probe is live in this process, opens a socket to TEST-NET-1. Prints
# what each step gave.
LOOPBACK_HOOK = """\
import json
import socket
import sys

port = json.load(sys.stdin)["port"]
seen = {}
with socket.create_connection(("127.0.0.1", port), timeout=5):
    seen["connect"] = "connected"
socket.getaddrinfo("localhost", port, type=socket.SOCK_STREAM)
seen["lookup"] = socket.gethostbyname("localhost")
attempt = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
attempt.settimeout(5)
try:
    attempt.connect(("192.0.2.1", 443))
    seen["outbound"] = None
except OSError as error:
    seen["outbound"] = error.errno
finally:
    attempt.close()
print(json.dumps(seen))
"""

# The start of a hook that makes one call of CAUGHT_CALLS, written after it: refused() and
# unreachable() exit 1 unless the probe refused the call with ENETUNREACH (raised, or returned by
# connect_ex); git() runs git ls-remote, which fails once the stand-in it reaches exits 1.
CALL_HOOK = """\
import errno
import socket
import subprocess
import sys

sys.stdin.read()
socket.setdefaulttimeout(5)


def unreachable(code):
    if code != errno.ENETUNREACH:
        sys.exit("not refused: %r" % (code,))


def refused(call, *args):
    try:
        call(*args)
    except OSError as error:
        unreachable(error.errno)
    else:
        sys.exit("not refused: %s" % call.__name__)


def git(url):
    subprocess.run(
        ["git", "ls-remote", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=30,
        check=False,
    )


"""
# The calls the other cases leave out: each socket call the probe refuses beside connect, and git
# over ssh:// and git://, which reach the ssh stand-in and git's proxy command. Each with its line
# in outbound_calls: a socket call names the hook; git loads no probe, so a stand-in it runs is
# named by git's process id, which changes each run (``<pid>``).
CAUGHT_CALLS = [
    pytest.param(
        'refused(socket.getaddrinfo, "example.invalid", 443)',
        "getaddrinfo example.invalid:443 by {hook}",
        id="getaddrinfo",
    ),
    pytest.param(
        'refused(socket.gethostbyname, "example.invalid")',
        "gethostbyname example.invalid by {hook}",
        id="gethostbyname",
    ),
    pytest.param(
        'refused(socket.gethostbyname_ex, "example.invalid")',
        "gethostbyname_ex example.invalid by {hook}",
        id="gethostbyname_ex",
    ),
    pytest.param(
        'refused(socket.gethostbyaddr, "192.0.2.1")',
        "gethostbyaddr 192.0.2.1 by {hook}",
        id="gethostbyaddr",
    ),
    pytest.param(
        'unreachable(socket.socket().connect_ex(("192.0.2.1", 443)))',
        "connect_ex 192.0.2.1:443 by {hook}",
        id="connect_ex",
    ),
    # With flags, the address is the third argument.
    pytest.param(
        'refused(socket.socket(type=socket.SOCK_DGRAM).sendto, b"x", 0, ("192.0.2.1", 53))',
        "sendto 192.0.2.1:53 by {hook}",
        id="sendto",
    ),
    pytest.param(
        'git("ssh://git@example.invalid/x.git")',
        "ssh -o SendEnv=GIT_PROTOCOL git@example.invalid git-upload-pack '/x.git' by process <pid>",
        id="git-ssh",
    ),
    pytest.param(
        'git("git://example.invalid/x.git")',
        "git-proxy-command example.invalid 9418 by process <pid>",
        id="git-protocol",
    ),
]

# Starts a detached grandchild as SessionStart starts its refresh (its own session, none of the
# hook's stdio) and prints its pid: this file again, with ``--linger <seconds>`` from the event,
# so its command line names the case's folder. The grandchild sleeps that long, then looks up a
# host, which the probe records.
LINGERING_HOOK = """\
import json
import socket
import subprocess
import sys
import time

if sys.argv[1:2] == ["--linger"]:
    time.sleep(float(sys.argv[2]))
    try:
        socket.getaddrinfo("example.invalid", 443)
    except OSError:
        pass
    sys.exit(0)
seconds = json.load(sys.stdin)["seconds"]
grandchild = subprocess.Popen(
    [sys.executable, __file__, "--linger", str(seconds)],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
print(grandchild.pid)
"""
# Starts a detached grandchild whose command line does not name the case's folder (``python -c``,
# its code, then the seconds from the event) and prints its pid once the grandchild has said it
# runs: its sitecustomize logged the probe's marker before its code started. It sleeps that long.
MARKED_HOOK = """\
import json
import subprocess
import sys

seconds = json.load(sys.stdin)["seconds"]
grandchild = subprocess.Popen(
    [
        sys.executable,
        "-c",
        "import sys, time; print('runs', flush=True); time.sleep(float(sys.argv[1]))",
        str(seconds),
    ],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.PIPE,
    stderr=subprocess.DEVNULL,
    start_new_session=True,
)
grandchild.stdout.readline()
print(grandchild.pid)
"""
# The grandchild's sleep, in seconds: SHORT_LINGER ends well within LINGER_WAIT, LONG_LINGER
# well past SHORT_WAIT (the case's cleanup kills it).
SHORT_LINGER = 1
LONG_LINGER = 60
LINGER_WAIT = 10.0
SHORT_WAIT = 0.2
# A terminal width that cuts the line ps prints for any child here, unless ps is told to ignore it.
NARROW_COLUMNS = "40"


@pytest.fixture(autouse=True)
def host_network(monkeypatch: pytest.MonkeyPatch) -> None:
    """This process's own network settings, which a probed child must never inherit.

    A cloud container's proxy is itself a loopback address, so a child that kept the proxy
    variables would turn a real call into an allowed loopback connect: here they point at a
    loopback port that refuses connections. ``NO_PROXY`` would skip the recorder, the git config
    would send the remote of ``GIT_HOOK`` to that port, ``GIT_ALLOW_PROTOCOL=file`` would stop git
    before it tries, and the tokens are credentials.
    """
    host_proxy = closed_url()
    for name in PROXY_VARIABLES:
        monkeypatch.setenv(name, host_proxy)
    for name in ("NO_PROXY", "no_proxy"):
        monkeypatch.setenv(name, "*")
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{host_proxy}/.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://example.invalid/")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    for name in ("GH_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, HOST_TOKEN)


@pytest.fixture
def no_process_left(tmp_path: Path) -> Iterator[None]:
    """After the case, kill what it left running, as ``processes_left`` finds it, then wait until
    all of it has gone. It replaces conftest's ``pkill -f`` of the case's folder here, which
    misses a grandchild found only by its marker."""
    yield
    folder = tmp_path / "probe"
    for left in processes_left(folder, tmp_path, timeout=0):
        with contextlib.suppress(ProcessLookupError):  # it ended on its own meanwhile
            os.kill(int(left.split(" ", 1)[0]), signal.SIGKILL)
    still = processes_left(folder, tmp_path, timeout=LINGER_WAIT)
    assert still == [], "still running after the kill:\n" + "\n".join(still)


@contextlib.contextmanager
def probed(folder: Path) -> Iterator[dict[str, str]]:
    """The probe's environment for a child, with its recorder serving until the block ends."""
    folder.mkdir()
    write_stubs(folder)
    with recording_proxy(folder) as port:
        yield outbound_env(folder, port, os.environ.get("PATH", os.defpath))


def write_hook(folder: Path, name: str, text: str) -> Path:
    hook = folder / name
    hook.write_text(text, encoding="utf-8")
    return hook


def test_names_script_when_hook_opens_outbound_socket(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "bad_hook.py", BAD_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        completed = run_hook_file(each_python, hook, stdin=NO_EVENT, cwd=tmp_path, env=env)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    # Refused by the probe before any packet leaves, whatever the network would have answered.
    assert json.loads(completed.stdout) == {"errno": errno.ENETUNREACH}
    assert len(calls) == 1, calls
    missing = [
        part for part in ("bad_hook.py", "connect", "192.0.2.1", "443") if part not in calls[0]
    ]
    assert missing == [], calls[0]


@pytest.mark.parametrize(("call", "record"), CAUGHT_CALLS)
def test_records_call_when_hook_calls_out(
    call: str, record: str, *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "call_hook.py", f"{CALL_HOOK}{call}\n")
    folder = tmp_path / "probe"

    with probed(folder) as env:
        completed = run_hook_file(each_python, hook, stdin=NO_EVENT, cwd=tmp_path, env=env)
    calls = [re.sub(r"process \d+$", "process <pid>", line) for line in outbound_calls(folder)]

    assert completed.returncode == 0, completed.stderr
    assert calls == [record.format(hook=hook)]


def test_records_proxy_request_when_child_uses_https(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "git_hook.py", GIT_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        completed = run_hook_file(each_python, hook, stdin=NO_EVENT, cwd=tmp_path, env=env)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert len(calls) == 1, calls
    assert "CONNECT example.invalid:443" in calls[0]


def test_records_tool_when_hook_runs_gh(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "gh_hook.py", GH_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        completed = run_hook_file(each_python, hook, stdin=NO_EVENT, cwd=tmp_path, env=env)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert len(calls) == 1, calls
    # The stand-in's arguments, and the hook named as the process that ran it.
    missing = [part for part in ("gh pr list --state open", "gh_hook.py") if part not in calls[0]]
    assert missing == [], calls[0]
    assert HOST_TOKEN not in env.values()


def test_builds_env_from_scratch_when_host_has_network_settings(tmp_path: Path) -> None:
    folder = tmp_path / "probe"

    env = outbound_env(folder, 0, os.defpath)

    probe_variables = {"PATH", "HOME", "PYTHONPATH", "GIT_PROXY_COMMAND", "GIT_CONFIG_NOSYSTEM"}
    assert set(env) == probe_variables | set(PROXY_VARIABLES)
    assert folder in Path(env["HOME"]).parents


def test_records_nothing_when_connect_is_loopback(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "loopback_hook.py", LOOPBACK_HOOK)
    folder = tmp_path / "probe"

    with socket.create_server(("127.0.0.1", 0)) as listener, probed(folder) as env:
        stdin = json.dumps({"port": listener.getsockname()[1]}).encode()
        completed = run_hook_file(each_python, hook, stdin=stdin, cwd=tmp_path, env=env)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) == {
        "connect": "connected",
        "lookup": "127.0.0.1",
        "outbound": errno.ENETUNREACH,
    }
    # Only the control: the loopback connect and both lookups left no record.
    assert len(calls) == 1, calls
    assert "192.0.2.1" in calls[0]


@pytest.mark.usefixtures("no_process_left")
def test_waits_for_detached_grandchild_when_it_ends_within_timeout(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "lingering_hook.py", LINGERING_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        stdin = json.dumps({"seconds": SHORT_LINGER}).encode()
        completed = run_hook_file(each_python, hook, stdin=stdin, cwd=tmp_path, env=env)
        left = processes_left(folder, tmp_path, timeout=LINGER_WAIT)
    calls = outbound_calls(folder)

    assert completed.returncode == 0, completed.stderr
    assert left == []
    # The grandchild had ended: its lookup, made a second after the hook exited, is logged.
    assert calls == [f"getaddrinfo example.invalid:443 by {hook} --linger {SHORT_LINGER}"]


@pytest.mark.usefixtures("no_process_left")
def test_names_detached_grandchild_when_it_outlives_timeout(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "lingering_hook.py", LINGERING_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        stdin = json.dumps({"seconds": LONG_LINGER}).encode()
        completed = run_hook_file(each_python, hook, stdin=stdin, cwd=tmp_path, env=env)
        left = processes_left(folder, tmp_path, timeout=SHORT_WAIT)

    assert completed.returncode == 0, completed.stderr
    assert len(left) == 1, left
    # Its pid, then its command line: the interpreter, then this file with its arguments.
    pid, command = left[0].split(" ", 1)
    assert pid == completed.stdout.decode().strip()
    assert command.endswith(f" {hook} --linger {LONG_LINGER}"), command


@pytest.mark.usefixtures("no_process_left")
def test_names_grandchild_by_its_marker_when_command_line_omits_case_folder(
    *, each_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    hook = write_hook(tmp_path, "marked_hook.py", MARKED_HOOK)
    folder = tmp_path / "probe"

    with probed(folder) as env:
        stdin = json.dumps({"seconds": LONG_LINGER}).encode()
        completed = run_hook_file(each_python, hook, stdin=stdin, cwd=tmp_path, env=env)
        left = processes_left(folder, tmp_path, timeout=SHORT_WAIT)

    assert completed.returncode == 0, completed.stderr
    assert len(left) == 1, left
    pid, command = left[0].split(" ", 1)
    assert pid == completed.stdout.decode().strip()
    # The interpreter, -c and its code: only the marker can name this process.
    assert " -c " in command, command
    assert str(tmp_path) not in command, command


def test_names_whole_command_line_when_columns_is_narrow(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    script = write_hook(tmp_path, "sleeping.py", f"import time\ntime.sleep({LONG_LINGER})\n")
    argv = [sys.executable, str(script)]
    # Exported, as a developer's shell or a CI runner may: ps reads it even into a pipe.
    monkeypatch.setenv("COLUMNS", NARROW_COLUMNS)

    with subprocess.Popen(argv, stdin=subprocess.DEVNULL) as child:  # noqa: S603 - this interpreter, a script in tmp_path
        try:
            left = processes_left(tmp_path / "probe", tmp_path, timeout=0)
        finally:
            child.kill()

    assert left == [f"{child.pid} {' '.join(argv)}"]


def test_counts_child_as_ended_when_it_has_exited_unreaped(tmp_path: Path) -> None:
    script = write_hook(tmp_path, "quick.py", "")
    argv = [sys.executable, str(script)]
    folder = tmp_path / "probe"

    with (
        probed(folder) as env,
        subprocess.Popen(argv, env=env, stdin=subprocess.DEVNULL) as child,  # noqa: S603 - this interpreter, a script in tmp_path
    ):
        # Its exit, without reaping it: a zombie that ps still lists until the block reaps it.
        # A zombie's command line is empty, so pgrep -f misses it and only its marker names it.
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)
        left = processes_left(folder, tmp_path, timeout=0)
    markers = (folder / LOADED_LOG).read_text(encoding="utf-8").splitlines()

    assert [json.loads(marker)["pid"] for marker in markers] == [child.pid]
    assert left == []
