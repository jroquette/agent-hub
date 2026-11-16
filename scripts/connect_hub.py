"""``make connect HUB=<path>``: register a hub with the running control plane and check its sensor.

POSTs the hub's absolute path to ``/api/v1/hubs`` with the server's own ``Origin`` (the
registry writes require it), 409 (registered already) is fine, then
checks that the hub sends its sessions' events: ``plugin/hub-workflow/hooks/event_sensor.py``
exists and ``.claude/settings.json`` runs it for each of the sensor's hook events. When it does
not, it prints the way out: move ``platform.version`` to this release, ``./hub sync``, a PR.
In Docker the server sees only the hubs under ``AGENT_HUB_HUBS_ROOT``; a refusal says so.
Exits 0 when the hub is registered (with or without the sensor), 1 otherwise.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import httpx

from agent_hub.generator.built_json import HOOK_EVENTS

DEFAULT_URL = "http://127.0.0.1:7420"
SENSOR_FILE = "event_sensor.py"
SENSOR_PATH = f"plugin/hub-workflow/hooks/{SENSOR_FILE}"
SETTINGS_PATH = ".claude/settings.json"
REQUEST_SECONDS = 10
SENSOR_EVENTS = tuple(hook.event for hook in HOOK_EVENTS if hook.file == SENSOR_FILE)


def sensor_problems(hub: Path) -> list[str]:
    """What keeps ``hub`` from sending events: the sensor file, then the settings entries."""
    problems: list[str] = []
    if not (hub / SENSOR_PATH).is_file():
        problems.append(f"missing {SENSOR_PATH}")
    missing = [event for event in SENSOR_EVENTS if event not in _sensor_entries(hub)]
    if missing:
        problems.append(f"{SETTINGS_PATH}: no sensor entry for {', '.join(missing)}")
    return problems


def _sensor_entries(hub: Path) -> set[str]:
    """The hook events whose commands in the hub's settings run the sensor."""
    try:
        settings = json.loads((hub / SETTINGS_PATH).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return set()
    hooks = settings.get("hooks") if isinstance(settings, dict) else None
    if not isinstance(hooks, dict):
        return set()
    return {event for event, groups in hooks.items() if SENSOR_FILE in json.dumps(groups)}


def origin_of(client: httpx.Client) -> str:
    """The origin of ``client``'s server, as a page it served would send it in ``Origin``."""
    base = client.base_url
    return f"{base.scheme}://{base.netloc.decode('ascii')}"


def _pinned_version(hub: Path) -> str:
    try:
        config = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
        return str(config["platform"]["version"])
    except OSError, ValueError, KeyError, TypeError:
        return "unknown"


def main(argv: Sequence[str] | None = None, *, transport: httpx.BaseTransport | None = None) -> int:
    """Register the hub and report its sensor; see the module docstring for the exit codes."""
    arguments = _parser().parse_args(argv)
    hub = Path(arguments.hub).expanduser().resolve()
    url: str = arguments.url.rstrip("/")
    if not (hub / "hub.json").is_file():
        print(f"error: {hub}: not a hub: no hub.json", file=sys.stderr)
        return 1
    registered = _register(hub, url=url, transport=transport)
    if not registered:
        return 1
    _report_sensor(hub)
    return 0


def _register(hub: Path, *, url: str, transport: httpx.BaseTransport | None) -> bool:
    try:
        with httpx.Client(base_url=url, timeout=REQUEST_SECONDS, transport=transport) as client:
            response = client.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": origin_of(client)}
            )
    except httpx.HTTPError:
        print(
            f"error: no agent-hub answers at {url}; start it with make up or make run",
            file=sys.stderr,
        )
        return False
    if response.status_code == httpx.codes.CREATED:
        print(f"registered {hub} with {url}")
        return True
    if response.status_code == httpx.codes.CONFLICT:
        print(f"{hub} is registered already")
        return True
    problem = _problem(response)
    title = problem.get("title") or response.reason_phrase
    detail = problem.get("detail") or ""
    print(f"error: {response.status_code} {title}: {detail}".rstrip(": "), file=sys.stderr)
    print(
        "  In Docker the server sees only the hubs under AGENT_HUB_HUBS_ROOT (see .env.example).",
        file=sys.stderr,
    )
    return False


def _problem(response: httpx.Response) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _report_sensor(hub: Path) -> None:
    problems = sensor_problems(hub)
    if not problems:
        print(f"sensor: ok ({SENSOR_PATH}, {len(SENSOR_EVENTS)} hook events)")
        return
    for problem in problems:
        print(f"sensor: {problem}")
    print(
        f"  The hub's release (platform.version {_pinned_version(hub)}) does not send events. "
        f"Move platform.version in hub.json to {version('agent-hub-cli')} or later, run "
        "./hub sync in the hub, and land the change through a PR. Until then the app shows the "
        "hub's files and health, but no live sessions."
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m scripts.connect_hub", description=__doc__)
    parser.add_argument("hub", help="the hub folder (with hub.json)")
    parser.add_argument(
        "--url", default=DEFAULT_URL, help=f"the control plane (default {DEFAULT_URL})"
    )
    return parser


if __name__ == "__main__":
    sys.exit(main())
