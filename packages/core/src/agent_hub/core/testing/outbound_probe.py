"""A probe that catches the outbound network calls of a child process, for no-network tests.

A test makes an empty folder, writes the probe's files there (``write_stubs``), serves its
recording proxy (``recording_proxy``) and runs a child (a rendered hook, a ``hub`` command) in
``outbound_env``: an environment built from scratch that loads ``SITECUSTOMIZE`` in every Python
child, points every proxy variable at the recorder and puts stand-ins for gh, uv, uvx, claude,
curl, wget, ssh and git's proxy command first on ``PATH``. Apart from the ``PATH`` the test
passes, nothing of its own environment reaches the child: no proxy setting, ``NO_PROXY``, git
config or token. A call is logged when it is made, so before the recorder closes the test waits
until nothing the child started still runs, detached processes included (``processes_left``).

Once the recorder has closed, ``outbound_calls`` lists what the child tried, one line each:

- ``<call> <target> by <argv>``: a socket call of a Python child that would leave the machine
  (``connect``, ``connect_ex``, ``sendto``, ``getaddrinfo``, ``gethostbyname``,
  ``gethostbyname_ex``, ``gethostbyaddr``). It is refused with ``ENETUNREACH`` before it runs;
  ``connect_ex`` returns that errno instead of raising, as it does for any failed connect.
- ``<tool> <arguments> by <argv>``: a stand-in, which records the call and exits 1. The line
  names the process that ran it by its marker, or says ``by process <pid>`` when that process
  loaded no probe (a shell, git).
- ``<request line> through the proxy``: a tool that used a proxy variable (git, curl,
  ``urllib``). The proxy cannot tell which process sent it.

A Python process is named by its ``sys.argv`` joined by spaces, as it was when the record was
written: the marker of a ``python -m`` child reads ``-m <arguments>``, because Python puts the
module's path in ``sys.argv`` only once the module starts. Each Python child the probe loads in
appends that marker (``pid``, ``ppid``, ``argv``) to ``<folder>/loaded.jsonl``, so a test can
check that the probe ran in the process it started. Loopback connects and ``localhost`` lookups
pass untouched.

What the probe cannot see: a Python child run with ``-I``, ``-E`` or ``-S``, or in an environment
without the probe's ``PYTHONPATH``, never loads the sitecustomize, so its own socket calls are
neither refused nor recorded, and it leaves no marker. Nor does the probe see a C extension's
socket calls, ``sendmsg`` or ``getnameinfo``, a tool other than the stand-ins that ignores the
proxy variables, or a call made after the logs are read: when a case does not wait, or by a
process the wait cannot find, one whose command line does not name the case's folder and that has
not loaded the probe (a detached shell or git, a Python child still starting). Standard library
only; ``SITECUSTOMIZE`` runs inside the child, so it stays Python 3.9 code.
"""

import contextlib
import json
import os
import shlex
import socket
import socketserver
import subprocess
import threading
import time
from collections.abc import Collection, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# The probe's folder: stand-ins (first on PATH), the sitecustomize (PYTHONPATH), the child's HOME,
# one record file per stand-in process, and the logs. SITECUSTOMIZE names its two logs itself.
STAND_IN_FOLDER = "bin"
SITE_FOLDER = "site"
HOME_FOLDER = "home"
TOOL_CALL_FOLDER = "tool-calls"
SOCKET_CALL_LOG = "calls.jsonl"
LOADED_LOG = "loaded.jsonl"
PROXY_LOG = "proxy.jsonl"

# The tools that reach the network on their own, and the command git runs for a git:// remote.
STAND_INS = ("gh", "uv", "uvx", "claude", "curl", "wget", "ssh")
GIT_PROXY_COMMAND = "git-proxy-command"
# Both spellings of the proxy variables that curl, git and Python's urllib read.
PROXY_VARIABLES = (
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
)
# A stand-in appends one record per call to a file named after its own process id, so stand-ins
# that run at once never share a write, and a reused pid adds a second record. A record is
# NUL-separated, since no argument can hold a NUL: the parent's pid, the tool, the argument
# count, then the arguments.
STAND_IN = """\
#!/bin/sh
printf '%s\\0' "$PPID" {tool} "$#" "$@" >> {records}/"$$"
exit 1
"""
# A proxy client sends its request line as soon as it connects; a connection with nothing by then
# is still recorded.
REQUEST_TIMEOUT = 5.0
REQUEST_LIMIT = 8192
POLL_INTERVAL = 0.05

# The text each Python child imports at start-up. It finds its logs from its own path
# (<folder>/site/sitecustomize.py), so a child that rebuilds its environment but keeps
# PYTHONPATH still records to the same folder. The socket calls are patched before the marker is
# written: a marker that cannot be written leaves the child probed, and its absence fails the test.
SITECUSTOMIZE = """\
# The outbound probe in a test's child: a socket call that would leave the machine is recorded
# to calls.jsonl and refused with ENETUNREACH before it runs; loaded.jsonl gets this process.
import errno
import ipaddress
import json
import os
import socket
import sys

_FOLDER = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _append(name, entry):
    entry.update(pid=os.getpid(), ppid=os.getppid(), argv=list(getattr(sys, "argv", [])))
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    descriptor = os.open(os.path.join(_FOLDER, name), flags, 0o600)
    try:
        os.write(descriptor, (json.dumps(entry) + "\\n").encode("utf-8"))
    finally:
        os.close(descriptor)


def _is_loopback(host):
    if not isinstance(host, str):
        return False
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _outbound(address):
    # "host:port" when a socket address leaves the machine; None for loopback and for the
    # addresses that are no host and port (a Unix socket's path).
    if not isinstance(address, tuple) or not address or _is_loopback(address[0]):
        return None
    return ":".join(str(part) for part in address[:2])


def _record(call, target):
    _append("calls.jsonl", {"call": call, "target": target})


def _refusal(call, target):
    _record(call, target)
    return OSError(errno.ENETUNREACH, "refused by the outbound probe: %s %s" % (call, target))


_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_sendto = socket.socket.sendto
_real_getaddrinfo = socket.getaddrinfo


def _connect(self, address):
    target = _outbound(address)
    if target is not None:
        raise _refusal("connect", target)
    return _real_connect(self, address)


def _connect_ex(self, address):
    target = _outbound(address)
    if target is not None:
        _record("connect_ex", target)
        return errno.ENETUNREACH
    return _real_connect_ex(self, address)


def _sendto(self, data, *args):
    target = _outbound(args[-1] if args else None)
    if target is not None:
        raise _refusal("sendto", target)
    return _real_sendto(self, data, *args)


def _getaddrinfo(host, port, *args, **kwargs):
    # No host means this machine's own addresses: nothing is looked up.
    if host is not None and not _is_loopback(host):
        raise _refusal("getaddrinfo", "%s:%s" % (host, port))
    return _real_getaddrinfo(host, port, *args, **kwargs)


def _lookup(name):
    real = getattr(socket, name)

    def lookup(host):
        if not _is_loopback(host):
            raise _refusal(name, str(host))
        return real(host)

    return lookup


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.socket.sendto = _sendto
socket.getaddrinfo = _getaddrinfo
for _name in ("gethostbyname", "gethostbyname_ex", "gethostbyaddr"):
    setattr(socket, _name, _lookup(_name))
_append("loaded.jsonl", {})
"""


@contextmanager
def recording_proxy(folder: Path) -> Iterator[int]:
    """Serve a loopback listener that logs the request line of each connection under ``folder``
    and closes it; yield its port. Each connection it accepted is logged when the block ends."""
    log = folder.absolute() / PROXY_LOG
    lock = threading.Lock()

    class Recorder(socketserver.BaseRequestHandler):
        def handle(self) -> None:
            line = json.dumps({"request": _request_line(self.request)}) + "\n"
            with lock, log.open("a", encoding="utf-8") as stream:
                stream.write(line)

    # Closing the server waits for the connections it is still logging.
    with socketserver.ThreadingTCPServer(("127.0.0.1", 0), Recorder) as server:
        serving = threading.Thread(
            target=server.serve_forever, kwargs={"poll_interval": POLL_INTERVAL}
        )
        serving.start()
        try:
            yield server.server_address[1]
        finally:
            server.shutdown()
            serving.join()


def _request_line(connection: socket.socket) -> str:
    """The first line a client sent, as text: empty when it sent nothing in time."""
    received = b""
    connection.settimeout(REQUEST_TIMEOUT)
    # A client that connected but sent nothing still tried to go out: its line is empty.
    with contextlib.suppress(OSError):
        received = connection.recv(REQUEST_LIMIT)
    return received.split(b"\n", 1)[0].rstrip(b"\r").decode("ascii", "backslashreplace")


def write_stubs(folder: Path) -> None:
    """Write the probe's files under ``folder`` (an existing, empty folder): the sitecustomize,
    the child's ``HOME`` and stand-ins for gh, uv, uvx, claude, curl, wget, ssh and git's proxy
    command, each recording its arguments and its parent's process id, then exiting 1."""
    folder = folder.absolute()
    for name in (STAND_IN_FOLDER, SITE_FOLDER, HOME_FOLDER, TOOL_CALL_FOLDER):
        (folder / name).mkdir()
    (folder / SITE_FOLDER / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="utf-8")
    records = shlex.quote(str(folder / TOOL_CALL_FOLDER))
    for tool in (*STAND_INS, GIT_PROXY_COMMAND):
        stand_in = folder / STAND_IN_FOLDER / tool
        stand_in.write_text(STAND_IN.format(tool=tool, records=records), encoding="utf-8")
        stand_in.chmod(0o700)


def outbound_env(folder: Path, port: int, path: str) -> dict[str, str]:
    """A child's environment from scratch: the stand-ins, then ``path``, on ``PATH``; ``HOME``
    under ``folder``; ``SITECUSTOMIZE`` on ``PYTHONPATH``; the six proxy variables at
    ``port``; git's proxy command at its stand-in and git's system config off; nothing of this
    process's environment."""
    folder = folder.absolute()
    proxy = f"http://127.0.0.1:{port}"
    return {
        "PATH": os.pathsep.join((str(folder / STAND_IN_FOLDER), path)),
        "HOME": str(folder / HOME_FOLDER),
        "PYTHONPATH": str(folder / SITE_FOLDER),
        "GIT_PROXY_COMMAND": str(folder / STAND_IN_FOLDER / GIT_PROXY_COMMAND),
        # The system git config could hold a proxy or a URL rewrite that takes git around the
        # recorder; the user's is under HOME, which is the probe's.
        "GIT_CONFIG_NOSYSTEM": "1",
    } | dict.fromkeys(PROXY_VARIABLES, proxy)


def processes_left(folder: Path, case: Path, *, timeout: float) -> list[str]:
    """Wait, at most ``timeout`` seconds, until nothing a case started still runs; return what
    still runs then, ``<pid> <command line>`` each (empty once all have ended).

    A case's processes: each one whose command line names ``case``, the case's own folder
    (``pgrep -f``), and each Python child the probe at ``folder`` loaded in, whatever its command
    line. A zombie has ended.
    """
    end = time.monotonic() + timeout
    while True:
        loaded = [marker["pid"] for marker in _json_lines(folder.absolute() / LOADED_LOG)]
        left = _running({*_named(case), *loaded})
        if not left or time.monotonic() > end:
            return left
        time.sleep(POLL_INTERVAL)


def _named(case: Path) -> list[int]:
    """The process ids whose command line names ``case`` (``pgrep -f``)."""
    found = subprocess.run(  # noqa: S603 - pgrep with a fixed option and a path
        ["pgrep", "-f", str(case)],  # noqa: S607 - pgrep from PATH
        capture_output=True,
        text=True,
        check=False,
    )
    if found.returncode > 1:  # 1: no process matched
        raise RuntimeError(f"pgrep -f {case} failed: {found.stderr.strip()}")
    return [int(pid) for pid in found.stdout.split()]


def _running(pids: Collection[int]) -> list[str]:
    """``<pid> <command line>`` of each of ``pids`` that ``ps`` lists and is no zombie."""
    if not pids:
        return []
    ids = ",".join(str(pid) for pid in sorted(pids))
    # -ww: whole lines. Without it, ps cuts each one at an exported COLUMNS, even into a pipe.
    listed = subprocess.run(  # noqa: S603 - ps with fixed options and process ids
        ["ps", "-ww", "-o", "pid=,stat=,args=", "-p", ids],  # noqa: S607 - ps from PATH
        capture_output=True,
        text=True,
        errors="replace",
        check=False,
    )
    if listed.returncode and listed.stderr:  # exit 1 with no message: none of them runs
        raise RuntimeError(f"ps failed: {listed.stderr.strip()}")
    rows = [line.split(None, 2) for line in listed.stdout.splitlines()]
    return [" ".join([row[0], *row[2:]]) for row in rows if not row[1].startswith("Z")]


def outbound_calls(folder: Path) -> list[str]:
    """Every call recorded under ``folder``, one line each, naming the call (its target, request
    line or arguments) and the process that made it; empty when nothing called out. The socket
    calls come first, then the stand-ins, then the proxy's requests."""
    folder = folder.absolute()
    processes = {marker["pid"]: _process(marker) for marker in _json_lines(folder / LOADED_LOG)}
    socket_calls = [
        f"{call['call']} {call['target']} by {_process(call)}"
        for call in _json_lines(folder / SOCKET_CALL_LOG)
    ]
    tool_calls = [
        f"{' '.join(argv)} by {processes.get(parent, f'process {parent}')}"
        for parent, argv in _tool_calls(folder / TOOL_CALL_FOLDER)
    ]
    proxy_requests = [
        f"{entry['request'] or 'a connection with no request line'} through the proxy"
        for entry in _json_lines(folder / PROXY_LOG)
    ]
    return socket_calls + tool_calls + proxy_requests


def _json_lines(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def _process(entry: dict[str, Any]) -> str:
    """A Python child's name in a line: its argv, else its process id."""
    return " ".join(entry["argv"]) or f"process {entry['pid']}"


def _tool_calls(records: Path) -> Iterator[tuple[int, list[str]]]:
    """Each stand-in call: the process id of its parent, and the tool with its arguments."""
    for record in sorted(records.iterdir()):
        raw_fields = record.read_bytes().split(b"\0")
        fields = [field.decode("utf-8", "backslashreplace") for field in raw_fields]
        # The text after the last NUL is empty: one field left means every record is read.
        while len(fields) > 1:
            parent, tool, count = int(fields[0]), fields[1], int(fields[2])
            yield parent, [tool, *fields[3 : 3 + count]]
            del fields[: 3 + count]
