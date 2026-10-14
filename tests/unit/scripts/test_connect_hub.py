import json
from pathlib import Path

import httpx
import pytest

from agent_hub.generator.built_json import HOOK_EVENTS
from scripts.connect_hub import SENSOR_PATH, main, sensor_problems

URL = "http://127.0.0.1:7420"


def _hub(root: Path, *, sensor: bool = True, events: tuple[str, ...] | None = None) -> Path:
    """A hub folder with hub.json, and the sensor file and settings entries when asked."""
    hub = root / "acme-hub"
    hub.mkdir()
    (hub / "hub.json").write_text(json.dumps({"platform": {"version": "0.8.0"}}), "utf-8")
    if sensor:
        (hub / SENSOR_PATH).parent.mkdir(parents=True)
        (hub / SENSOR_PATH).write_text("# sensor\n", "utf-8")
    wanted = events if events is not None else _sensor_events()
    hooks = {
        event: [{"hooks": [{"type": "command", "command": f"python3 hooks/{name}"}]}]
        for event, name in [(event, "event_sensor.py") for event in wanted]
    }
    (hub / ".claude").mkdir()
    (hub / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}), "utf-8")
    return hub


def _sensor_events() -> tuple[str, ...]:
    return tuple(hook.event for hook in HOOK_EVENTS if hook.file == "event_sensor.py")


def _answering(status: int, body: dict[str, object] | None = None) -> httpx.MockTransport:
    def answer(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/hubs"
        return httpx.Response(status, json=body or {})

    return httpx.MockTransport(answer)


def test_finds_no_problem_when_hub_has_sensor_and_every_entry(tmp_path: Path) -> None:
    assert sensor_problems(_hub(tmp_path)) == []


def test_names_sensor_file_when_missing(tmp_path: Path) -> None:
    problems = sensor_problems(_hub(tmp_path, sensor=False))

    assert problems[0] == f"missing {SENSOR_PATH}"


def test_names_hook_events_when_settings_entries_missing(tmp_path: Path) -> None:
    problems = sensor_problems(_hub(tmp_path, events=("SessionStart", "PreToolUse")))

    assert len(problems) == 1
    assert problems[0].startswith(".claude/settings.json: no sensor entry for ")
    assert "Stop" in problems[0]
    assert "SessionStart," not in problems[0]


def test_registers_and_confirms_sensor_when_hub_ready(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = _hub(tmp_path)

    code = main([str(hub), "--url", URL], transport=_answering(201, {"path": str(hub)}))

    out = capsys.readouterr().out
    assert code == 0
    assert f"registered {hub} with {URL}" in out
    assert "sensor: ok" in out


def test_explains_sync_when_hub_lacks_sensor(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = _hub(tmp_path, sensor=False)

    code = main([str(hub), "--url", URL], transport=_answering(201))

    out = capsys.readouterr().out
    assert code == 0
    assert "sensor: missing" in out
    assert "platform.version" in out
    assert "./hub sync" in out


def test_reports_registered_already_when_server_answers_conflict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = _hub(tmp_path)

    code = main([str(hub), "--url", URL], transport=_answering(409, {"detail": "registered"}))

    assert code == 0
    assert f"{hub} is registered already" in capsys.readouterr().out


def test_fails_with_detail_and_mount_hint_when_server_refuses_hub(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hub = _hub(tmp_path)
    problem = {"title": "Invalid hub", "detail": "no hub.json at that path"}

    code = main([str(hub), "--url", URL], transport=_answering(422, problem))

    err = capsys.readouterr().err
    assert code == 1
    assert "error: 422 Invalid hub: no hub.json at that path" in err
    assert "AGENT_HUB_HUBS_ROOT" in err


def test_fails_naming_url_when_no_server_answers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    code = main([str(_hub(tmp_path)), "--url", URL], transport=httpx.MockTransport(refuse))

    assert code == 1
    assert f"error: no agent-hub answers at {URL}" in capsys.readouterr().err


def test_fails_when_folder_is_not_hub(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code = main([str(tmp_path), "--url", URL], transport=_answering(201))

    assert code == 1
    assert "not a hub: no hub.json" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("url", "origin"),
    [(URL, URL), (f"{URL}/", URL), ("http://localhost:8000/x/", "http://localhost:8000")],
)
def test_sends_server_origin_when_registering(tmp_path: Path, url: str, origin: str) -> None:
    sent: list[str | None] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request.headers.get("origin"))
        return httpx.Response(201, json={})

    code = main([str(_hub(tmp_path)), "--url", url], transport=httpx.MockTransport(answer))

    assert code == 0
    assert sent == [origin]
