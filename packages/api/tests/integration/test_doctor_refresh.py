"""The doctor in the background part of ``hub web`` (AGH-608, AC-21..AC-28): the composed app's
health routes answer from each hub's last check, and the refresher's ticks are what run the
doctor, never a request.

Seam: ``build_app(..., hub_reader=, refresh_ticker=)``. ``Composed.refresh()`` runs one tick of
the app's ``refresh_ticker`` (a ``ManualTicker``) on the caller's thread; the app's clock is
``ApiSettings.clock``, which the test moves. A hub runs at most once per 10 s after its last run
ends, except right after a write through the app (A9). ``HoldingReader`` is ``HubFileSystem``
whose ``doctor_snapshot`` can be held mid-run. No sleep, not ``serial``.
"""

import json
import os
import threading
from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.api.doctor_fix import DoctorFixResult
from agent_hub.api.doctor_refresher import DaemonTicker
from agent_hub.api.routes import hubs as hub_routes
from agent_hub.api.settings import ApiSettings
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.generator.registered_hub_files import HubFileSystem
from agent_hub.storage.hub_registry import JsonHubRegistry

HUBS = "/api/v1/hubs"
PROJECTS = "/api/v1/projects"
FINDINGS = "/api/v1/doctor/findings"
# The registry and config writes require this server's Origin (A11).
OWN = {"Origin": "http://127.0.0.1:7420"}
START = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
# ``checked_at`` as the API writes it: the clock at the end of the run, UTC, milliseconds, Z.
AT_START = "2026-10-11T12:00:00.000Z"
ONE_SECOND_LATER = "2026-10-11T12:00:01.000Z"
SEVEN_SECONDS_LATER = "2026-10-11T12:00:07.000Z"
ELEVEN_SECONDS_LATER = "2026-10-11T12:00:11.000Z"
# How long a held doctor run waits for the test before it gives up (longer than any join).
HOLD_SECONDS = 30.0
DEAD_LINK = ("links.dead", "brain/now.md")
DRIFTED_AGENTS = ("lock.drift", "AGENTS.md")


class MovableClock:
    """The app's clock: ``START`` until the test moves it."""

    def __init__(self) -> None:
        self.now = START

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class HoldingReader(HubFileSystem):
    """``HubFileSystem`` whose ``doctor_snapshot`` records the thread it runs on; once ``hold()``
    was called it sets ``entered`` and waits for ``release``; ``fail`` is raised by the next run
    instead of reading."""

    def __init__(self) -> None:
        super().__init__()
        self.threads: list[threading.Thread] = []
        self.held = False
        self.entered = threading.Event()
        self.release = threading.Event()
        self.fail: Exception | None = None

    def hold(self) -> None:
        self.held = True

    def doctor_snapshot(self, hub_path: str, **options: Any) -> Any:
        self.threads.append(threading.current_thread())
        if self.fail is not None:
            error, self.fail = self.fail, None
            raise error
        if self.held:
            self.entered.set()
            assert self.release.wait(HOLD_SECONDS), "the test never released the doctor run"
        return super().doctor_snapshot(hub_path, **options)


@pytest.fixture
def clock() -> MovableClock:
    return MovableClock()


@pytest.fixture
def settings(composed_settings: ApiSettings, clock: MovableClock) -> ApiSettings:
    return replace(composed_settings, clock=clock)


@pytest.fixture
def reader() -> Iterator[HoldingReader]:
    holding = HoldingReader()
    yield holding
    holding.release.set()


def _register(composed: Any, hub: Path) -> dict[str, Any]:
    response = composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN)
    assert response.status_code == 201, response.text
    view: dict[str, Any] = response.json()
    return view


def _findings(composed: Any, project: str) -> dict[str, Any]:
    response = composed.client.get(FINDINGS, params={"project": project})
    assert response.status_code == 200, response.text
    answer: dict[str, Any] = response.json()
    return answer


def _rules_at(answer: dict[str, Any]) -> set[tuple[str, str]]:
    return {(item["rule"], item["path"]) for item in answer["items"]}


def _tick_held(composed: Any, reader: HoldingReader) -> threading.Thread:
    """A tick on a helper thread, returned once its doctor run is held."""
    reader.hold()
    tick = threading.Thread(target=composed.refresh, name="test-tick", daemon=True)
    tick.start()
    assert reader.entered.wait(5), "the tick ran no doctor"
    return tick


def _answer_within(seconds: float, request: Callable[[], httpx.Response]) -> httpx.Response:
    answers: list[httpx.Response] = []
    helper = threading.Thread(target=lambda: answers.append(request()), daemon=True)
    helper.start()
    helper.join(seconds)
    assert answers, f"no answer within {seconds} s while the doctor run is held"
    return answers[0]


def _released(reader: HoldingReader, tick: threading.Thread) -> None:
    reader.release.set()
    tick.join(10)
    assert not tick.is_alive()


@pytest.mark.parametrize(
    "sessions_off", [pytest.param(False, id="sessions-on"), pytest.param(True, id="sessions-off")]
)
def test_shows_new_finding_after_next_tick_when_watched_file_changes(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    clock: MovableClock,
    *,
    hub_world: Any,
    sessions_off: bool,
) -> None:
    """AC-21 (A9): a brain note gains a dead link; the first tick 10 s after the last run
    shows it."""
    composed = open_composed(replace(settings, sessions_off=sessions_off))
    _register(composed, hub_world.hub)
    composed.refresh()
    first = _findings(composed, "demo")
    assert first["checked_at"] == AT_START
    assert DEAD_LINK not in _rules_at(first)
    note = hub_world.hub / "brain" / "now.md"
    note.write_text(
        note.read_text(encoding="utf-8") + "\nSee [the plan](missing-plan.md).\n", encoding="utf-8"
    )
    clock.advance(11)

    composed.refresh()

    second = _findings(composed, "demo")
    assert second["checked_at"] == ELEVEN_SECONDS_LATER
    assert DEAD_LINK in _rules_at(second)


HEALTH_ROUTES = [
    pytest.param(HUBS, id="hubs"),
    pytest.param(PROJECTS, id="projects"),
    pytest.param("/api/v1/projects/demo", id="project"),
    pytest.param("/api/v1/projects/demo/brain", id="brain"),
    pytest.param("/api/v1/projects/demo/skills", id="skills"),
    pytest.param("/api/v1/features", id="features"),
    pytest.param(f"{FINDINGS}?project=demo", id="findings"),
]


@pytest.mark.parametrize("path", HEALTH_ROUTES)
def test_answers_with_previous_result_when_doctor_run_is_held(
    open_composed: Callable[..., Any],
    reader: HoldingReader,
    settings: ApiSettings,
    *,
    clock: MovableClock,
    make_hub: Callable[..., Path],
    path: str,
) -> None:
    """AC-22: while a doctor run is held mid-run, the route answers with the previous check."""
    hub = make_hub()
    composed = open_composed(settings, hub_reader=reader)
    _register(composed, hub)
    composed.refresh()
    assert _findings(composed, "demo")["checked_at"] == AT_START
    (hub / "AGENTS.md").write_text("# edited by hand\n", encoding="utf-8")
    clock.advance(11)
    before = composed.client.get(path)
    assert before.status_code == 200, before.text
    tick = _tick_held(composed, reader)

    held = _answer_within(5, lambda: composed.client.get(path))

    assert held.status_code == 200, held.text
    assert held.json() == before.json()
    assert tick.is_alive(), "the doctor run ended before the route answered"
    _released(reader, tick)


def _post_session_hook(composed: Any) -> None:
    hook = a_hook_input("PreToolUse", session_id="session-health")
    envelope = an_envelope(hook, project="demo", sent_at="2026-10-11T11:58:00.000Z")
    posted = composed.client.post("/api/v1/events/hooks", json=envelope.model_dump(mode="json"))
    assert posted.status_code == 202, posted.text


def test_reads_no_hub_path_on_request_thread_when_health_routes_answer(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    make_hub: Callable[..., Path],
    *,
    request_reads: Any,
) -> None:
    """AC-23: after the first refresh, the three health routes open no hub file and not the
    registry on the request's thread."""
    hub = make_hub()
    composed = open_composed(settings)
    _register(composed, hub)
    _post_session_hook(composed)
    composed.refresh()
    request_reads.wrap(composed.client.app)
    # The brain route walks the brain on the request's thread: the recorder must see it.
    brain = composed.client.get("/api/v1/projects/demo/brain")
    assert brain.status_code == 200, brain.text
    assert request_reads.under(hub) != set(), "the recorder saw no read of the brain walk"
    request_reads.clear()

    answers = [composed.client.get(path) for path in (f"{FINDINGS}?project=demo", HUBS, PROJECTS)]

    assert [answer.status_code for answer in answers] == [200, 200, 200]
    assert answers[0].json()["checked_at"] == AT_START
    assert [card["name"] for card in answers[2].json()["items"]] == ["demo"]
    assert request_reads.under(hub) == set()
    assert request_reads.under(composed.settings.registry_path) == set()
    assert request_reads.relative() == set()


def test_answers_null_health_when_first_run_has_not_ended(
    open_composed: Callable[..., Any],
    reader: HoldingReader,
    settings: ApiSettings,
    *,
    make_hub: Callable[..., Path],
) -> None:
    """AC-24: before the first doctor run ends, the cards and hub views answer at once with null
    health, and no doctor runs on a request's thread."""
    composed = open_composed(settings, hub_reader=reader)
    view = _register(composed, make_hub())
    # A lock matching the pin: its state needs the doctor's drift check.
    assert view["platform_pin"] == view["running_version"] == view["lock_version"]
    tick = _tick_held(composed, reader)

    hubs = _answer_within(5, lambda: composed.client.get(HUBS))
    projects = _answer_within(5, lambda: composed.client.get(PROJECTS))

    assert (hubs.status_code, projects.status_code) == (200, 200)
    [hub_view] = hubs.json()["items"]
    assert (hub_view["checked_at"], hub_view["lock_state"]) == (None, None)
    [card] = projects.json()["items"]
    assert (card["checked_at"], card["hub_health"], card["lock_state"]) == (None, None, None)
    assert reader.threads == [tick]
    _released(reader, tick)


def test_keeps_previous_findings_when_refresh_raises(
    open_composed: Callable[..., Any],
    reader: HoldingReader,
    settings: ApiSettings,
    *,
    clock: MovableClock,
    make_hub: Callable[..., Path],
) -> None:
    """AC-25: a run that raises keeps the previous findings and ``checked_at``; the next tick
    runs the doctor again."""
    hub = make_hub()
    composed = open_composed(settings, hub_reader=reader)
    _register(composed, hub)
    composed.refresh()
    first = _findings(composed, "demo")
    assert first["checked_at"] == AT_START
    assert DRIFTED_AGENTS not in _rules_at(first)
    (hub / "AGENTS.md").write_text("# edited by hand\n", encoding="utf-8")
    clock.advance(11)
    reader.fail = OSError("synthetic read failure")

    composed.refresh()

    assert len(reader.threads) == 2, "the second tick ran no doctor"
    assert _findings(composed, "demo") == first
    composed.refresh()
    again = _findings(composed, "demo")
    assert again["checked_at"] == ELEVEN_SECONDS_LATER
    assert DRIFTED_AGENTS in _rules_at(again)


type Write = Callable[[Any, Callable[..., Path], pytest.MonkeyPatch], str]


def _register_second_hub(
    composed: Any, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> str:
    _register(composed, make_hub("other"))
    return "other"


def _shows_second_hub_unchecked(composed: Any) -> None:
    views = {view["project"]: view for view in composed.client.get(HUBS).json()["items"]}
    assert set(views) == {"demo", "other"}
    assert views["other"]["checked_at"] is None
    cards = {card["name"]: card for card in composed.client.get(PROJECTS).json()["items"]}
    assert (cards["other"]["hub_health"], cards["other"]["checked_at"]) == (None, None)


def _add_repo(composed: Any, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch) -> str:
    [card] = composed.client.get(PROJECTS).json()["items"]
    assert card["repos"] == ["demo-api"]
    response = composed.client.post(
        "/api/v1/projects/demo/config/repos",
        json={
            "op": "add_repo",
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check": "make check",
            "check_fast": "make check-fast",
        },
        headers=OWN,
    )
    assert response.status_code == 200, response.text
    return "demo"


def _shows_added_repo(composed: Any) -> None:
    [card] = composed.client.get(PROJECTS).json()["items"]
    assert card["repos"] == ["demo-api", "demo-web"]


def _fix_default_branch(
    composed: Any, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> str:
    def fix(hub_id: str, hub_path: str, **_: object) -> DoctorFixResult:
        config = Path(hub_path) / "hub.json"
        document = json.loads(config.read_text(encoding="utf-8"))
        document["project"]["default_branch"] = "release"
        config.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
        return DoctorFixResult(
            hub_id=hub_id,
            ok=True,
            exit_code=0,
            output=(),
            changed_files=("hub.json",),
            errors_left=0,
            warnings_left=0,
        )

    monkeypatch.setattr(hub_routes, "fix_hub", fix)
    assert composed.client.get("/api/v1/projects/demo").json()["default_branch"] == "main"
    [hub] = composed.client.get(HUBS).json()["items"]
    response = composed.client.post(f"{HUBS}/{hub['id']}/doctor-fix", json={}, headers=OWN)
    assert response.status_code == 200, response.text
    return "demo"


def _shows_fixed_default_branch(composed: Any) -> None:
    assert composed.client.get("/api/v1/projects/demo").json()["default_branch"] == "release"


@pytest.mark.parametrize(
    ("write", "shown"),
    [
        pytest.param(_register_second_hub, _shows_second_hub_unchecked, id="register"),
        pytest.param(_add_repo, _shows_added_repo, id="config"),
        pytest.param(_fix_default_branch, _shows_fixed_default_branch, id="action"),
    ],
)
def test_shows_change_on_next_read_when_hub_written_through_app(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    clock: MovableClock,
    *,
    make_hub: Callable[..., Path],
    monkeypatch: pytest.MonkeyPatch,
    write: Write,
    shown: Callable[[Any], None],
) -> None:
    """AC-26 (A7, A9): a hub registered or changed through the app shows on the next read, with
    null health until its first run; the hub it wrote is checked at the next tick, 1 s later.
    Signed in, as the owner's page is: a config write and a hub action are owner writes."""
    composed = open_composed(settings, signed_in=True)
    _register(composed, make_hub())
    composed.refresh()
    assert _findings(composed, "demo")["checked_at"] == AT_START

    project = write(composed, make_hub, monkeypatch)

    shown(composed)
    clock.advance(1)
    composed.refresh()
    assert _findings(composed, project)["checked_at"] == ONE_SECOND_LATER


def test_shows_new_hub_json_after_next_tick_when_its_link_target_changes(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    clock: MovableClock,
    *,
    make_hub: Callable[..., Path],
    tmp_path: Path,
) -> None:
    """A ``hub.json`` that is a link: an edit to the file it points to changes the target's
    time, not the link's, and the next tick still reads the new document."""
    hub = make_hub()
    config = hub / "hub.json"
    target = tmp_path / "shared-config" / "hub.json"
    target.parent.mkdir()
    target.write_bytes(config.read_bytes())
    config.unlink()
    config.symlink_to(target)
    composed = open_composed(settings)
    _register(composed, hub)
    composed.refresh()
    assert composed.client.get("/api/v1/projects/demo").json()["default_branch"] == "main"
    link_time = config.lstat().st_mtime_ns
    document = json.loads(target.read_text(encoding="utf-8"))
    document["project"]["default_branch"] = "release"
    target.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    later = target.stat().st_mtime_ns + 5_000_000_000
    os.utime(target, ns=(later, later))
    assert config.lstat().st_mtime_ns == link_time
    clock.advance(2)

    composed.refresh()

    assert composed.client.get("/api/v1/projects/demo").json()["default_branch"] == "release"


def test_stops_without_waiting_when_doctor_run_is_in_progress(
    open_composed: Callable[..., Any],
    reader: HoldingReader,
    settings: ApiSettings,
    *,
    make_hub: Callable[..., Path],
) -> None:
    """AC-27: ``hub web``'s exit does not wait for a doctor run in progress (a run on
    ``asyncio.to_thread`` would hold uvicorn's close on the default executor)."""
    hub = make_hub()
    JsonHubRegistry(settings.registry_path).add(str(hub.resolve()))
    reader.hold()
    ticker = DaemonTicker(3600, name="test-doctor-refresh")
    composed = open_composed(settings, hub_reader=reader, refresh_ticker=ticker)
    assert reader.entered.wait(5), "the first tick ran no doctor"

    leaving = threading.Thread(
        target=composed.client.__exit__, args=(None, None, None), daemon=True
    )
    leaving.start()
    leaving.join(10)

    assert not leaving.is_alive(), "the app's exit waited for the doctor run"
    assert ticker.thread.is_alive(), "the doctor run ended before the exit"
    reader.release.set()
    ticker.thread.join(5)
    assert not ticker.thread.is_alive()


def test_carries_checked_at_when_hub_refreshed(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    clock: MovableClock,
    *,
    make_hub: Callable[..., Path],
) -> None:
    """AC-28: the findings answer, the card, the detail and the hub view carry the end of the
    run."""
    composed = open_composed(settings)
    _register(composed, make_hub())
    clock.advance(7)

    composed.refresh()

    findings = _findings(composed, "demo")
    [card] = composed.client.get(PROJECTS).json()["items"]
    detail = composed.client.get("/api/v1/projects/demo").json()
    [hub_view] = composed.client.get(HUBS).json()["items"]
    assert [
        findings["checked_at"],
        card["checked_at"],
        detail["checked_at"],
        hub_view["checked_at"],
    ] == [SEVEN_SECONDS_LATER] * 4


def test_answers_registry_unreadable_when_app_starts_with_corrupt_registry(
    open_composed: Callable[..., Any],
    settings: ApiSettings,
    make_hub: Callable[..., Path],
) -> None:
    """The app starts on a registry it cannot read and answers 503, not an empty list; once the
    file is fixed, a tick serves the hubs."""
    hub = make_hub()
    registry = settings.registry_path
    registry.parent.mkdir(parents=True, mode=0o700)
    registry.write_text("{", encoding="utf-8")
    composed = open_composed(settings)

    answers = [composed.client.get(path) for path in (HUBS, PROJECTS)]

    assert [(answer.status_code, answer.json()["title"]) for answer in answers] == [
        (503, "Hub registry unreadable")
    ] * 2
    registry.unlink()
    JsonHubRegistry(registry).add(str(hub.resolve()))
    composed.refresh()
    assert [view["path"] for view in composed.client.get(HUBS).json()["items"]] == [
        os.path.realpath(hub)
    ]
