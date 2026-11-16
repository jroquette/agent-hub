"""The example action's script, run as ``hub init`` writes it (AGH-365 review round 1, Q1, Q2, Q8).

Each test writes the script to a temp folder and runs it with this interpreter, isolated, on the
JSON object an action reads. Servers listen on the loopback interface, reached as ``localhost``.
"""

import json
import subprocess
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlunsplit

import pytest

from agent_hub.core.testing.loopback import closed_port
from agent_hub.generator.scenario_examples import EXAMPLE_FILES

SCRIPT = next(example for example in EXAMPLE_FILES if example.path.endswith(".py"))
CHILD_TIMEOUT = 30


def run_script(
    tmp_path: Path, *, mode: str, url: str, path: str
) -> subprocess.CompletedProcess[str]:
    script = tmp_path / "demo_get_status.py"
    script.write_bytes(SCRIPT.content)
    call = {
        "mode": mode,
        "inputs": {"target": "api", "path": path},
        "endpoint": {"target": {"url": url, "resource": None}},
    }
    return subprocess.run(  # noqa: S603 - this interpreter, a script the test wrote
        [sys.executable, "-I", str(script)],
        input=json.dumps(call),
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT,
    )


class Served:
    """A loopback server's port and the paths it was asked for."""

    def __init__(self, port: int) -> None:
        self.port = port
        self.paths: list[str] = []


@pytest.fixture
def server() -> Iterator[Served]:
    """``/redirect`` answers 302 to ``/target``; every other path answers 200."""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    served = Served(httpd.server_address[1])

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - http.server's method name
            served.paths.append(self.path)
            if self.path == "/drop":
                # Close without an answer: the client sees the connection reset.
                self.close_connection = True
                return
            if self.path == "/redirect":
                self.send_response(302)
                self.send_header("Location", "/target")
            else:
                self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *_args: Any) -> None:
            pass

    httpd.RequestHandlerClass = Handler
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield served
    finally:
        httpd.shutdown()
        httpd.server_close()


@pytest.mark.parametrize("mode", ["plan", "run"])
@pytest.mark.parametrize(
    "path", ["@169.254.169.254/latest", "health", ".evil.example.com/x", ":8080/x"]
)
def test_refuses_path_when_path_would_change_the_host(
    tmp_path: Path, server: Served, *, mode: str, path: str
) -> None:
    completed = run_script(tmp_path, mode=mode, url=f"http://localhost:{server.port}", path=path)

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "path must start with /" in completed.stderr
    assert server.paths == []


def test_prints_status_when_path_reads_the_endpoint(tmp_path: Path, server: Served) -> None:
    url = f"http://localhost:{server.port}"

    planned = run_script(tmp_path, mode="plan", url=url, path="/health")
    ran = run_script(tmp_path, mode="run", url=url, path="/health")

    assert (planned.returncode, json.loads(planned.stdout)) == (0, {"summary": f"GET {url}/health"})
    assert (ran.returncode, json.loads(ran.stdout)) == (0, {"status": 200})
    assert server.paths == ["/health"]


def test_prints_status_zero_when_service_refuses_connection(tmp_path: Path) -> None:
    # The expect keeps polling a service that is not up yet: 0 fits output_format, never 200.
    completed = run_script(
        tmp_path, mode="run", url=f"http://localhost:{closed_port()}", path="/health"
    )

    assert (completed.returncode, completed.stderr) == (0, "")
    assert json.loads(completed.stdout) == {"status": 0}


def test_prints_redirect_status_when_endpoint_redirects(tmp_path: Path, server: Served) -> None:
    completed = run_script(
        tmp_path, mode="run", url=f"http://localhost:{server.port}", path="/redirect"
    )

    assert (completed.returncode, completed.stderr) == (0, "")
    assert json.loads(completed.stdout) == {"status": 302}
    assert server.paths == ["/redirect"]


# Review round 2: Q9 (each refusal), Q11 (malformed paths, errors other than unreachable), Q12
# (userinfo never printed).
@pytest.mark.parametrize("mode", ["plan", "run"])
@pytest.mark.parametrize(
    "path",
    ["?x=1", "/a b", "/a\tb", "/a\r\nHost: evil.example.com", "/caf\u00e9", "/a\x7f"],
    ids=["query-only", "space", "tab", "crlf", "non-ascii", "delete"],
)
def test_refuses_path_when_path_malformed(
    tmp_path: Path, server: Served, *, mode: str, path: str
) -> None:
    completed = run_script(tmp_path, mode=mode, url=f"http://localhost:{server.port}", path=path)

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert "path must start with /" in completed.stderr
    assert server.paths == []


def test_stays_on_endpoint_when_path_starts_with_two_slashes(
    tmp_path: Path, server: Served
) -> None:
    # A path starting with / follows the endpoint's host, so it cannot change it: no host check.
    url = f"http://localhost:{server.port}"

    planned = run_script(tmp_path, mode="plan", url=url, path="//evil.example.com/x")
    ran = run_script(tmp_path, mode="run", url=url, path="//evil.example.com/x")

    assert json.loads(planned.stdout) == {"summary": f"GET {url}//evil.example.com/x"}
    assert json.loads(ran.stdout) == {"status": 200}
    # The request reaches the endpoint's own server (urllib folds the leading //).
    assert server.paths == ["/evil.example.com/x"]


def test_prints_status_zero_when_connection_reset(tmp_path: Path, server: Served) -> None:
    completed = run_script(
        tmp_path, mode="run", url=f"http://localhost:{server.port}", path="/drop"
    )

    assert (completed.returncode, completed.stderr) == (0, "")
    assert json.loads(completed.stdout) == {"status": 0}


@pytest.mark.parametrize(
    ("url", "shown"),
    [
        ("https://localhost:{port}", "GET https://localhost:{port}/health: "),
        ("http://localhost:not-a-port", "GET http://localhost:not-a-port/health: "),
    ],
    ids=["tls-to-plain-http", "invalid-url"],
)
def test_exits_with_reason_when_error_is_not_unreachable(
    tmp_path: Path, server: Served, *, url: str, shown: str
) -> None:
    completed = run_script(tmp_path, mode="run", url=url.format(port=server.port), path="/health")

    assert completed.returncode != 0
    assert completed.stdout == ""
    assert completed.stderr.startswith(f"demo-get-status: {shown.format(port=server.port)}")


@pytest.mark.parametrize("mode", ["plan", "run"])
def test_never_prints_userinfo_when_endpoint_holds_it(
    tmp_path: Path, server: Served, *, mode: str
) -> None:
    # Built from parts: the host is localhost, behind a user and password.
    url = urlunsplit(("http", f"u:secret@localhost:{server.port}", "", "", ""))

    completed = run_script(tmp_path, mode=mode, url=url, path="/health")

    assert completed.returncode == 0, completed.stderr
    assert "secret" not in completed.stdout + completed.stderr
    expected = (
        {"summary": f"GET http://localhost:{server.port}/health"}
        if mode == "plan"
        else {"status": 200}
    )
    assert json.loads(completed.stdout) == expected
