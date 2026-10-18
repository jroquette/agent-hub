"""Connecting hub web to Linear from Settings: the key file, the environment overlay, the check."""

import stat
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path

from agent_hub.api.linear_connection import (
    LinearConnection,
    LinearEnviron,
    LinearKeyFile,
)
from agent_hub.core.errors import TrackerError
from agent_hub.tracker_linear.graphql_viewer import LinearAccount

GOOD = "lin" + "_api_" + "g" * 20
BAD = "lin" + "_api_" + "b" * 20
ACCOUNT = LinearAccount("Ada", "ada@example.com", "Example", "example")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now


class FakeLinear:
    """Accepts ``GOOD`` only, counting the checks."""

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, environ: Mapping[str, str]) -> LinearAccount:
        self.calls += 1
        if environ.get("LINEAR_API_KEY") != GOOD:
            raise TrackerError(
                operation="check",
                cause="Linear refused the key (HTTP 401)",
                fix="check the key",
                kind="unauthorized",
                http_status=401,
            )
        return ACCOUNT


def _connection(
    tmp_path: Path, base: Mapping[str, str] | None = None
) -> tuple[LinearConnection, LinearKeyFile, FakeLinear, Clock]:
    key_file = LinearKeyFile(tmp_path / "config" / "linear-api-key")
    linear, clock = FakeLinear(), Clock()
    environ = LinearEnviron(base or {}, key_file)
    return (
        LinearConnection(environ, key_file, clock=clock, account_of=linear),
        key_file,
        linear,
        clock,
    )


def test_reports_not_connected_without_check_when_no_key(tmp_path: Path) -> None:
    connection, _, linear, _ = _connection(tmp_path)

    view = connection.status()

    assert (view.connected, view.source, view.problem) == (False, None, None)
    assert linear.calls == 0


def test_saves_key_with_owner_only_mode_when_linear_accepts_it(tmp_path: Path) -> None:
    connection, key_file, _, _ = _connection(tmp_path)

    view = connection.connect(f"  {GOOD}\n")

    assert view.connected
    assert view.source == "settings"
    assert view.account is not None
    assert view.account.url == "https://linear.app/example"
    assert key_file.read() == GOOD
    assert stat.S_IMODE(key_file.path.stat().st_mode) == 0o600
    assert GOOD not in view.model_dump_json()


def test_keeps_no_key_when_linear_refuses_it(tmp_path: Path) -> None:
    connection, key_file, _, _ = _connection(tmp_path)

    view = connection.connect(BAD)

    assert not view.connected
    assert view.problem_kind == "unauthorized"
    assert view.problem == "Linear refused the key (HTTP 401)."
    assert key_file.read() == ""


def test_refuses_key_without_check_when_it_has_a_space(tmp_path: Path) -> None:
    connection, _, linear, _ = _connection(tmp_path)

    view = connection.connect("lin api")

    assert not view.connected
    assert linear.calls == 0


def test_caches_check_until_ttl_when_status_is_read_again(tmp_path: Path) -> None:
    connection, _, linear, clock = _connection(tmp_path)
    connection.connect(GOOD)

    connection.status()
    clock.now += timedelta(seconds=61)
    connection.status()
    connection.status(fresh=True)

    assert linear.calls == 3


def test_reads_saved_key_through_environ_when_environment_has_none(tmp_path: Path) -> None:
    key_file = LinearKeyFile(tmp_path / "linear-api-key")
    environ = LinearEnviron({"HOME": "/home/x"}, key_file)
    assert environ.get("LINEAR_API_KEY") is None
    key_file.write(GOOD)

    assert environ["LINEAR_API_KEY"] == GOOD
    assert set(environ) == {"HOME", "LINEAR_API_KEY"}
    assert environ.source() == "settings"


def test_prefers_environment_key_when_both_are_set(tmp_path: Path) -> None:
    connection, key_file, _, _ = _connection(tmp_path, {"LINEAR_API_KEY": BAD})

    view = connection.connect(GOOD)

    assert key_file.read() == GOOD
    assert (view.connected, view.source, view.problem_kind) == (
        False,
        "environment",
        "unauthorized",
    )


def test_forgets_saved_key_when_disconnected(tmp_path: Path) -> None:
    connection, key_file, _, _ = _connection(tmp_path)
    connection.connect(GOOD)

    view = connection.disconnect()

    assert key_file.read() == ""
    assert (view.connected, view.source) == (False, None)
