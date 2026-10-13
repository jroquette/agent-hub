import logging
import re
import socket
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from agent_hub.api.session_token import cookie_name
from agent_hub.cli import web_command
from agent_hub.cli.main import app
from agent_hub.core.agent_sessions.limits import SessionLimits

TOKEN_URL = re.compile(r"agent-hub at http://(?P<host>[^/]+)/\?token=(?P<token>[A-Za-z0-9_-]{43,})")


def _web(args: list[str], env: Mapping[str, str | None] | None = None) -> Result:
    return CliRunner().invoke(app, ["web", *args], env=env)


@pytest.fixture
def busy_port() -> Iterator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        yield listener.getsockname()[1]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]
        return port


class ServedApp:
    def __init__(self) -> None:
        self.app: FastAPI | None = None
        self.address: tuple[str, int] | None = None

    def __call__(self, served: FastAPI, sock: socket.socket) -> None:
        self.app = served
        self.address = sock.getsockname()
        sock.close()


@pytest.fixture
def served(monkeypatch: pytest.MonkeyPatch) -> ServedApp:
    recorder = ServedApp()
    monkeypatch.setattr(web_command, "serve_on", recorder)
    return recorder


def test_exits_one_naming_port_when_port_in_use_by_another_process(busy_port: int) -> None:
    result = _web(["--port", str(busy_port)])

    assert result.exit_code == 1
    assert result.stderr == f"error: port {busy_port} is in use\n"
    assert result.stdout == ""


@pytest.mark.parametrize(
    "args", [["--port", "0"], ["--port", "65536"], ["--port", "web"], ["--host", "example.org"]]
)
def test_exits_two_when_invalid_option_given(args: list[str]) -> None:
    assert _web(args).exit_code == 2


@pytest.mark.parametrize("host", ["0.0.0.0", "::", "192.168.1.20"])  # noqa: S104 -- refused here
def test_refuses_address_outside_loopback_when_not_in_container(
    served: ServedApp, tmp_path: Path, host: str
) -> None:
    env = _scratch_env(tmp_path) | {"AGENT_HUB_IN_CONTAINER": None}

    result = _web(["--host", host, "--port", str(_free_port())], env=env)

    assert result.exit_code == 2
    assert result.stderr == "error: binding outside loopback needs AGENT_HUB_IN_CONTAINER=1\n"
    assert served.app is None


def test_refuses_address_outside_loopback_when_container_variable_not_one(
    served: ServedApp, tmp_path: Path
) -> None:
    env = _scratch_env(tmp_path) | {"AGENT_HUB_IN_CONTAINER": "true"}

    result = _web(["--host", "0.0.0.0", "--port", str(_free_port())], env=env)  # noqa: S104

    assert result.exit_code == 2
    assert served.app is None


def test_binds_other_loopback_address_when_host_is_loopback(
    served: ServedApp, tmp_path: Path
) -> None:
    port = _free_port()

    result = _web(["--host", "127.0.0.2", "--port", str(port)], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    assert served.address == ("127.0.0.2", port)
    url_line, listening = result.stdout.splitlines()
    assert _token_of(url_line, f"127.0.0.1:{port}")
    assert listening == f"listening on 127.0.0.2:{port}"


def test_binds_loopback_when_host_is_localhost(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()

    result = _web(["--host", "localhost", "--port", str(port)], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    assert served.address == ("127.0.0.1", port)
    assert _token_of(result.stdout.rstrip("\n"), f"127.0.0.1:{port}")


def test_binds_every_address_and_prints_it_when_in_container(
    served: ServedApp, tmp_path: Path
) -> None:
    port = _free_port()
    env = _scratch_env(tmp_path) | {"AGENT_HUB_IN_CONTAINER": "1"}

    result = _web(["--host", "0.0.0.0", "--port", str(port)], env=env)  # noqa: S104

    assert result.exit_code == 0, result.output
    assert served.address == ("0.0.0.0", port)  # noqa: S104 -- the container's bind
    assert result.stdout == f"agent-hub at http://127.0.0.1:{port}\nlistening on 0.0.0.0:{port}\n"


def test_answers_extra_host_when_allowed_hosts_variable_set(
    served: ServedApp, tmp_path: Path
) -> None:
    env = _scratch_env(tmp_path) | {"AGENT_HUB_ALLOWED_HOSTS": "127.0.0.1:8000,agent-hub.test"}

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 0, result.output
    assert served.app is not None
    settings = served.app.state.settings
    expected = {"127.0.0.1:8000", f"agent-hub.test:{settings.port}"}
    assert settings.allowed_hosts == expected
    with TestClient(served.app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/api/v1/collector/status").status_code == 200


def test_exits_two_naming_variable_when_allowed_hosts_has_wildcard(
    served: ServedApp, tmp_path: Path
) -> None:
    env = _scratch_env(tmp_path) | {"AGENT_HUB_ALLOWED_HOSTS": "*"}

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 2
    assert result.stderr == "error: AGENT_HUB_ALLOWED_HOSTS: '*' is not host[:port]\n"
    assert served.app is None


def test_tails_transcripts_under_variable_when_projects_variable_set(
    served: ServedApp, tmp_path: Path
) -> None:
    projects = tmp_path / "claude" / "projects"
    env = _scratch_env(tmp_path) | {"AGENT_HUB_CLAUDE_PROJECTS": str(projects)}

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 0, result.output
    assert web_command.claude_projects_root(env | {"HOME": "/nowhere"}) == projects


def test_uses_home_projects_when_projects_variable_empty(tmp_path: Path) -> None:
    env = {"HOME": str(tmp_path), "AGENT_HUB_CLAUDE_PROJECTS": ""}

    assert web_command.claude_projects_root(env) == tmp_path / ".claude" / "projects"


def test_exits_one_when_projects_variable_relative(served: ServedApp, tmp_path: Path) -> None:
    env = _scratch_env(tmp_path) | {"AGENT_HUB_CLAUDE_PROJECTS": "claude/projects"}

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 1
    assert result.stderr == "error: AGENT_HUB_CLAUDE_PROJECTS must be an absolute path\n"
    assert served.app is None


def test_prints_url_and_serves_on_loopback_when_started(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()
    db_path = tmp_path / "events.db"

    result = _web(["--port", str(port), "--db", str(db_path)])

    assert result.exit_code == 0, result.output
    assert _token_of(result.stdout.rstrip("\n"), f"127.0.0.1:{port}")
    assert served.address == ("127.0.0.1", port)
    assert served.app is not None
    settings = served.app.state.settings
    assert (settings.db_path, settings.port) == (db_path, port)


def _token_of(line: str, host: str) -> str:
    """The token of a startup URL line naming ``host``; fails the test when it is not one."""
    matched = TOKEN_URL.fullmatch(line)
    assert matched is not None, line
    assert matched["host"] == host
    return matched["token"]


def _scratch_env(tmp_path: Path) -> dict[str, str | None]:
    """HOME and the XDG folders under ``tmp_path``: the database is never the developer's."""
    return {
        "HOME": str(tmp_path / "home"),
        "XDG_DATA_HOME": str(tmp_path / "data"),
        "XDG_CONFIG_HOME": str(tmp_path / "config"),
        "AGENT_HUB_DB": None,
    }


def test_uses_default_port_when_no_port_given(served: ServedApp, tmp_path: Path) -> None:
    result = _web([], env=_scratch_env(tmp_path))

    # 7420 may be taken on the machine running the tests; either way the line names it.
    if result.stderr:
        assert (result.stdout, result.stderr) == ("", "error: port 7420 is in use\n")
    else:
        assert _token_of(result.stdout.rstrip("\n"), "127.0.0.1:7420")


def test_resolves_database_and_registry_like_collect_when_no_path_given(
    served: ServedApp, tmp_path: Path
) -> None:
    env = {"XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CONFIG_HOME": str(tmp_path / "config")}

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 0, result.output
    assert served.app is not None
    settings = served.app.state.settings
    assert settings.db_path == tmp_path / "data" / "agent-hub" / "agent-hub.db"
    assert settings.registry_path == tmp_path / "config" / "agent-hub" / "hubs.json"


def test_reads_database_from_environment_when_variable_set(
    served: ServedApp, tmp_path: Path
) -> None:
    env = {"AGENT_HUB_DB": str(tmp_path / "env.db")}

    _web(["--port", str(_free_port())], env=env)

    assert served.app is not None
    assert served.app.state.settings.db_path == tmp_path / "env.db"


def test_uses_home_config_when_config_home_relative(served: ServedApp, tmp_path: Path) -> None:
    env = _scratch_env(tmp_path) | {"XDG_CONFIG_HOME": "relative/config"}

    _web(["--port", str(_free_port())], env=env)

    assert served.app is not None
    expected = tmp_path / "home" / ".config" / "agent-hub" / "hubs.json"
    assert served.app.state.settings.registry_path == expected


def test_exits_one_when_no_home_directory_found(
    served: ServedApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(web_command, "account_home_directory", lambda: None)

    result = _web(["--port", str(_free_port())], env={"HOME": "", "XDG_DATA_HOME": ""})

    assert result.exit_code == 1
    assert result.stderr.startswith("error: ")
    assert served.app is None


def test_serves_wired_routes_on_its_database_when_started(
    served: ServedApp, tmp_path: Path
) -> None:
    db_path = tmp_path / "events.db"

    result = _web(["--port", str(_free_port()), "--db", str(db_path)], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    assert served.app is not None
    port = served.app.state.settings.port
    with TestClient(served.app, base_url=f"http://127.0.0.1:{port}") as client:
        status = client.get("/api/v1/collector/status")
        hubs = client.get("/api/v1/hubs")
    assert status.status_code == 200, status.text
    assert status.json()["db_path"] == str(db_path)
    assert hubs.json()["items"] == []
    assert db_path.is_file()


def test_exits_one_naming_database_when_it_cannot_be_opened(
    served: ServedApp, tmp_path: Path
) -> None:
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("", encoding="utf-8")

    result = _web(
        ["--port", str(_free_port()), "--db", str(blocker / "events.db")],
        env=_scratch_env(tmp_path),
    )

    assert result.exit_code == 1
    assert result.stderr.startswith("error: cannot create the directory of the event database")
    assert result.stdout == ""
    assert served.app is None


def test_prints_token_url_when_started(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()

    result = _web(["--port", str(port)], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    token = _token_of(result.stdout.rstrip("\n"), f"127.0.0.1:{port}")
    assert served.app is not None
    settings = served.app.state.settings
    assert settings.session_token == token
    assert settings.sessions_off is False


def test_mints_new_token_when_started_twice(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()
    first = _web(["--port", str(port)], env=_scratch_env(tmp_path))
    second = _web(["--port", str(port)], env=_scratch_env(tmp_path))

    tokens = {_token_of(r.stdout.rstrip("\n"), f"127.0.0.1:{port}") for r in (first, second)}

    assert len(tokens) == 2


def test_writes_token_to_no_file_and_no_log_when_started(
    served: ServedApp, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    port = _free_port()
    caplog.set_level(logging.DEBUG)

    result = _web(["--port", str(port)], env=_scratch_env(tmp_path))
    token = _token_of(result.stdout.rstrip("\n"), f"127.0.0.1:{port}")
    assert served.app is not None
    with TestClient(
        served.app, base_url=f"http://127.0.0.1:{port}", follow_redirects=False
    ) as client:
        exchanged = client.get("/", params={"token": token})
        signed = client.get(
            "/api/v1/agent-sessions/capabilities",
            headers={"Cookie": f"{cookie_name(port)}={token}"},
        )

    assert exchanged.status_code == 303
    assert signed.status_code != 401
    assert token not in result.stderr
    # The test client (httpx) logs the URL it requests; the server's own records never hold it.
    server_records = [r for r in caplog.records if not r.name.startswith("httpx")]
    assert server_records, "the request log should have written, or the scan proves nothing"
    assert all(token not in repr(vars(record)) for record in server_records)
    assert token not in repr(served.app.state.settings)
    written = [path for path in tmp_path.rglob("*") if path.is_file()]
    assert written, "the database should exist, or the scan proves nothing"
    assert all(token.encode() not in path.read_bytes() for path in written)


def test_prints_plain_url_when_in_container(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()
    env = _scratch_env(tmp_path) | {"AGENT_HUB_IN_CONTAINER": "1"}

    result = _web(["--port", str(port)], env=env)

    assert result.exit_code == 0, result.output
    assert result.stdout == f"agent-hub at http://127.0.0.1:{port}\n"
    assert served.app is not None
    settings = served.app.state.settings
    assert (settings.session_token, settings.sessions_off) == (None, True)


LIMIT_VARIABLES = {
    "AGENT_HUB_SESSIONS_MAX": ("sessions_max", 2),
    "AGENT_HUB_SESSION_IDLE_SECONDS": ("idle_seconds", 60),
    "AGENT_HUB_PERMISSION_TIMEOUT_SECONDS": ("permission_timeout_seconds", 30),
    "AGENT_HUB_SESSION_LOG_RECORDS": ("log_records", 1000),
    "AGENT_HUB_SESSION_LOG_BYTES": ("log_bytes", 131072),
    "AGENT_HUB_MESSAGE_MAX_BYTES": ("message_max_bytes", 2048),
    "AGENT_HUB_CLOUD_TIMEOUT_SECONDS": ("cloud_timeout_seconds", 10),
    "AGENT_HUB_SESSION_RETENTION_DAYS": ("retention_days", 7),
}


def test_reads_limits_when_env_set(served: ServedApp, tmp_path: Path) -> None:
    env = _scratch_env(tmp_path) | {
        name: str(value) for name, (_, value) in LIMIT_VARIABLES.items()
    }

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 0, result.output
    assert served.app is not None
    limits = served.app.state.settings.limits
    assert {field: getattr(limits, field) for field, _ in LIMIT_VARIABLES.values()} == {
        field: value for field, value in LIMIT_VARIABLES.values()
    }


def test_uses_default_limits_when_no_limit_given(served: ServedApp, tmp_path: Path) -> None:
    env = _scratch_env(tmp_path) | dict.fromkeys(LIMIT_VARIABLES)

    result = _web(["--port", str(_free_port())], env=env)

    assert result.exit_code == 0, result.output
    assert served.app is not None
    assert served.app.state.settings.limits == SessionLimits()


def test_reads_limit_option_when_option_given(served: ServedApp, tmp_path: Path) -> None:
    result = _web(
        ["--port", str(_free_port()), "--sessions-max", "16", "--session-retention-days", "1"],
        env=_scratch_env(tmp_path),
    )

    assert result.exit_code == 0, result.output
    assert served.app is not None
    limits = served.app.state.settings.limits
    assert (limits.sessions_max, limits.retention_days) == (16, 1)


@pytest.mark.parametrize(
    "args",
    [
        ["--sessions-max", "0"],
        ["--sessions-max", "17"],
        ["--session-idle-seconds", "86401"],
        ["--permission-timeout-seconds", "0"],
        ["--session-log-records", "99"],
        ["--session-log-bytes", "65535"],
        ["--message-max-bytes", "524289"],
        ["--cloud-timeout-seconds", "4"],
        ["--session-retention-days", "3651"],
    ],
)
def test_exits_two_when_limits_out_of_range(
    served: ServedApp, tmp_path: Path, args: list[str]
) -> None:
    result = _web(["--port", str(_free_port()), *args], env=_scratch_env(tmp_path))

    assert result.exit_code == 2
    assert served.app is None


def test_opens_token_url_when_open_given(
    served: ServedApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(web_command.webbrowser, "open", opened.append)
    port = _free_port()

    result = _web(["--port", str(port), "--open"], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    token = _token_of(result.stdout.rstrip("\n"), f"127.0.0.1:{port}")
    assert opened == [f"http://127.0.0.1:{port}/?token={token}"]


def test_opens_nothing_when_open_not_given(
    served: ServedApp, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    monkeypatch.setattr(web_command.webbrowser, "open", opened.append)

    result = _web(["--port", str(_free_port())], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    assert opened == []
