import socket
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from typer.testing import CliRunner, Result

from agent_hub.cli import web_command
from agent_hub.cli.main import app


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
    assert result.stdout == f"agent-hub at http://127.0.0.1:{port}\nlistening on 127.0.0.2:{port}\n"


def test_binds_loopback_when_host_is_localhost(served: ServedApp, tmp_path: Path) -> None:
    port = _free_port()

    result = _web(["--host", "localhost", "--port", str(port)], env=_scratch_env(tmp_path))

    assert result.exit_code == 0, result.output
    assert served.address == ("127.0.0.1", port)
    assert result.stdout == f"agent-hub at http://127.0.0.1:{port}\n"


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
    assert result.stdout == f"agent-hub at http://127.0.0.1:{port}\n"
    assert served.address == ("127.0.0.1", port)
    assert served.app is not None
    settings = served.app.state.settings
    assert (settings.db_path, settings.port) == (db_path, port)


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
    assert (result.stdout, result.stderr) in {
        ("agent-hub at http://127.0.0.1:7420\n", ""),
        ("", "error: port 7420 is in use\n"),
    }


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
