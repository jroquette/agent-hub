"""The web app against an installed ``hub web`` (AC-200.63, AC-200.57), and its bundle's hosts
(AC-200.56).

The smoke starts ``hub web`` on a temp database and registry, registers two synthetic hubs,
ingests a synthetic scenario (two projects, one live session, one failed run, one guard denial,
one open guard ask, one 5,000-event session) through ``POST /events/hooks`` and ``hub collect``,
then runs ``apps/web/e2e/smoke.spec.ts`` with Playwright: nine pages, no console error, no
request to another host, axe without serious or critical violations, and Session detail of the
long session complete in under 2 s. Without Chromium the smoke is skipped, and fails under CI.
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.core.testing.builders import an_event, events_to_jsonl
from agent_hub.core.testing.hook_inputs import a_hook_input
from agent_hub.core.testing.run_lines import run_lines_failed_in_verify
from tests.e2e.conftest import REPO_ROOT, InstalledHub, RunningWeb

WEB_DIR = REPO_ROOT / "apps" / "web"
WEB_DIST = REPO_ROOT / "packages" / "api" / "src" / "agent_hub" / "api" / "web_dist"
PLAYWRIGHT_SECONDS = 300
REQUEST_SECONDS = 10
LONG_SESSION_EVENTS = 5_000
LIVE_SESSION = "live-7f3a"
ASK_SESSION = "ask-2c9e"
LONG_SESSION = "long-81d0"
FAILED_RUN = "5e6f7a8b"
# The hub-init spec's flags, so git is never asked; one hub per project.
HUB_FLAGS = (
    "--tracker",
    "linear:DEM",
    "--branch-prefix",
    "jdoe/",
    "--author-name",
    "Jane Doe",
    "--author-email",
    "jane@example.com",
)
FEATURE_SPEC = "---\ntype: spec\nprocess_size: bounded\nrepos: [demo-api]\nlinear: [DEM-7]\n---\n"

# Absolute URLs the built bundle may contain, each exact. None is ever requested: React's and
# React Router's error texts name their docs, the XML namespaces are identifiers, and
# ``http://localhost`` is React Router's base for parsing relative URLs, as
# ``https://same-origin.invalid/app`` (a reserved TLD that never resolves) is ``safeHref``'s.
# Any other absolute URL, such as a font, script or API on another host, fails the check.
INERT_BUNDLE_URLS = frozenset(
    {
        "https://reactjs.org/docs/error-decoder.html",
        "https://reactrouter.com/en/main/routers/picking-a-router",
        "https://github.com/ungap/url-search-params",
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1998/Math/MathML",
        "http://www.w3.org/XML/1998/namespace",
        "http://localhost",
        "https://same-origin.invalid/app",
    }
)
_ABSOLUTE_URL = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(?:/[A-Za-z0-9._~/\-]*)?")


def bundle_urls(dist: Path) -> set[str]:
    """Every absolute URL in the built JS, CSS and HTML, up to its path (query cut, dot trimmed)."""
    found: set[str] = set()
    for path in sorted(dist.rglob("*")):
        if path.suffix in {".js", ".css", ".html"}:
            text = path.read_text(encoding="utf-8")
            found.update(match.rstrip("./") for match in _ABSOLUTE_URL.findall(text))
    return found


def test_bundle_names_no_other_host_when_web_app_built() -> None:
    """AC-200.56 on the committed build (``make web-dist-check`` proves it is the fresh build)."""
    urls = bundle_urls(WEB_DIST)

    assert urls - INERT_BUNDLE_URLS == set()
    assert "https://reactjs.org/docs/error-decoder.html" in urls


def test_bundle_check_fails_when_bundle_loads_external_font_or_script(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<script src="https://cdn.example.com/app.js"></script>', encoding="utf-8"
    )
    (tmp_path / "app.css").write_text(
        "@font-face{src:url(https://fonts.example.org/geist.woff2)}", encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        'fetch("https://reactjs.org/api");x="http://www.w3.org/2000/svg"', encoding="utf-8"
    )

    assert bundle_urls(tmp_path) - INERT_BUNDLE_URLS == {
        "https://cdn.example.com/app.js",
        "https://fonts.example.org/geist.woff2",
        "https://reactjs.org/api",
    }


@dataclass(frozen=True)
class Scenario:
    """What the smoke pages open: ids the synthetic scenario stored."""

    live_session: str
    long_session: str
    run_id: str
    project: str


def chromium_executable() -> str | None:
    """A Chromium headless shell for Playwright: the revision it expects, else the newest found.

    The browsers come from ``PLAYWRIGHT_BROWSERS_PATH`` (else Playwright's cache); nothing is
    ever downloaded here.
    """
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"
    # The playwright-core under @playwright/test is the one `playwright install` runs; another
    # copy (from @axe-core/playwright) can sit at the top of node_modules with a newer revision.
    modules = WEB_DIR / "node_modules"
    nested = modules / "playwright" / "node_modules" / "playwright-core" / "browsers.json"
    browsers = nested if nested.is_file() else modules / "playwright-core" / "browsers.json"
    if browsers.is_file():
        listed = json.loads(browsers.read_text(encoding="utf-8"))["browsers"]
        revision = next(b["revision"] for b in listed if b["name"] == "chromium-headless-shell")
        expected = _headless_shells(root, revision)
        if expected:
            return str(expected[0])
    found = _headless_shells(root, "*")
    return str(found[-1]) if found else None


def _headless_shells(root: Path, revision: str) -> list[Path]:
    # Older Playwright builds ship chrome-linux/headless_shell; newer ones (1.5x+) ship
    # chrome-headless-shell-linux64/chrome-headless-shell.
    folder = f"chromium_headless_shell-{revision}"
    return sorted(
        [
            *root.glob(f"{folder}/chrome-*/headless_shell"),
            *root.glob(f"{folder}/chrome-headless-shell-*/chrome-headless-shell"),
        ]
    )


def _make_hub(installed_hub: InstalledHub, root: Path, *, project: str, repo: str) -> Path:
    hub = root / f"{project}-hub"
    command = [
        str(installed_hub.executable),
        "init",
        project,
        "--repos",
        f"acme/{repo}",
        "--hub-repo",
        f"acme/{project}-hub",
        *HUB_FLAGS,
        "--dir",
        str(hub),
    ]
    result = subprocess.run(
        command, cwd=root, env=installed_hub.env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return hub


def _write_feature(hub: Path) -> None:
    folder = hub / "brain" / "features" / "export-button"
    folder.mkdir(parents=True)
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": f"Criterion {index}",
            "repo": "demo-api",
            "verification": "make check",
            "passes": index < 3,
            "evidence": "test run" if index < 3 else None,
        }
        for index in (1, 2, 3)
    ]
    record = {"feature": "export-button", "linear": ["DEM-7"], "acs": acs}
    (folder / "features.json").write_text(json.dumps(record), encoding="utf-8")
    criteria = "".join(f"- AC-7.{index} Criterion {index}\n" for index in (1, 2, 3))
    (folder / "spec.md").write_text(
        f"{FEATURE_SPEC}# Export button\n\n{criteria}", encoding="utf-8"
    )
    (folder / "plan.md").write_text("# Plan\n", encoding="utf-8")


def _envelope(
    project: str, repo: str, hook: dict[str, Any], *, at: datetime, **extra: Any
) -> dict[str, Any]:
    return {
        "v": 1,
        "project": project,
        "repo": repo,
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": at.isoformat(),
        "hook": hook,
    } | extra


def _hooks(now: datetime) -> list[dict[str, Any]]:
    """A live session in ``demo`` with a guard denial, and one in ``ops`` waiting on a guard ask."""
    live = {"session_id": LIVE_SESSION, "cwd": "/work/demo-api"}
    ask = {"session_id": ASK_SESSION, "cwd": "/work/ops-api"}
    push = {
        "tool_name": "Bash",
        "tool_input": {"command": "git push origin main"},
        "tool_use_id": "toolu_push",
    }
    edit = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/work/ops-api/docs/adr/0009.md",
            "old_string": "a",
            "new_string": "b",
        },
        "tool_use_id": "toolu_adr",
    }
    deny = {"by": "guard", "kind": "deny", "rule": "push-to-main"}
    ask_decision = {"by": "guard", "kind": "ask", "rule": "ask_before_edit"}
    at = [now - timedelta(seconds=seconds) for seconds in (90, 80, 70, 60, 50, 40)]
    return [
        _envelope("demo", "demo-api", a_hook_input("SessionStart") | live, at=at[0]),
        _envelope("demo", "demo-api", a_hook_input("UserPromptSubmit") | live, at=at[1]),
        _envelope("demo", "demo-api", a_hook_input("PreToolUse") | live, at=at[2]),
        _envelope("demo", "demo-api", a_hook_input("PostToolUse") | live, at=at[3]),
        _envelope(
            "demo", "demo-api", a_hook_input("PreToolUse", **push) | live, at=at[4], decision=deny
        ),
        _envelope("ops", "ops-api", a_hook_input("SessionStart") | ask, at=at[3]),
        _envelope(
            "ops",
            "ops-api",
            a_hook_input("PreToolUse", **edit) | ask,
            at=at[5],
            decision=ask_decision,
        ),
    ]


def _long_session(now: datetime) -> list[Any]:
    """An ended ``demo`` session of 5,000 events: a start, tool calls and results, an end."""
    start = now - timedelta(hours=2)

    def event(index: int, kind: str, payload: dict[str, Any]) -> Any:
        return an_event(
            session=LONG_SESSION,
            type=kind,
            timestamp=start + timedelta(milliseconds=500 * index),
            source="claude_code",
            source_id=f"{LONG_SESSION}:{index}",
            repo="demo-api",
            agent="main",
            payload=payload,
        )

    events = [event(0, "session.start", {"trigger": "startup", "cwd": "/work/demo-api"})]
    pairs = (LONG_SESSION_EVENTS - 2) // 2
    for pair in range(pairs):
        tool_use_id = f"toolu_{pair:05d}"
        call = {"tool": "Bash", "tool_use_id": tool_use_id, "command": f"make test-{pair % 7}"}
        events.append(event(2 * pair + 1, "tool.call", call))
        result = {"tool": "Bash", "tool_use_id": tool_use_id, "status": "ok", "duration_ms": 40}
        events.append(event(2 * pair + 2, "tool.result", result))
    events.append(
        event(len(events), "session.end", {"end_reason": "prompt_input_exit", "outcome": "stopped"})
    )
    return events


def ingest_scenario(web: RunningWeb, installed_hub: InstalledHub, root: Path) -> Scenario:
    """Registers the two hubs and stores the scenario in ``web``'s database."""
    demo = _make_hub(installed_hub, root, project="demo", repo="demo-api")
    ops = _make_hub(installed_hub, root, project="ops", repo="ops-api")
    _write_feature(demo)
    now = datetime.now(UTC)
    with httpx.Client(base_url=web.url, timeout=REQUEST_SECONDS) as client:
        for hub in (demo, ops):
            response = client.post("/api/v1/hubs", json={"path": str(hub)})
            assert response.status_code == 201, response.text
        for envelope in _hooks(now):
            response = client.post("/api/v1/events/hooks", json=envelope)
            assert response.status_code == 202, response.text
    long_file = root / "long.jsonl"
    long_file.write_text(events_to_jsonl(_long_session(now)), encoding="utf-8")
    runs = root / "runs.jsonl"
    records = run_lines_failed_in_verify(run_id=FAILED_RUN)
    runs.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    hub_exe = str(installed_hub.executable)
    db = ["--db", str(web.db_path)]
    for command in (
        [hub_exe, "collect", str(long_file), *db],
        [hub_exe, "collect", "--runs", str(runs), "--project", "demo", *db],
    ):
        result = subprocess.run(
            command, cwd=root, env=web.env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
    with httpx.Client(base_url=web.url, timeout=REQUEST_SECONDS) as client:
        runs_page = client.get("/api/v1/workflow-runs").json()["items"]
    [run_id] = [item["id"] for item in runs_page]
    return Scenario(
        live_session=LIVE_SESSION, long_session=LONG_SESSION, run_id=run_id, project="demo"
    )


def test_loads_nine_pages_without_console_error_or_axe_violation_when_scenario_ingested(
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    npm = shutil.which("npm")
    executable = chromium_executable()
    if npm is None or executable is None:
        reason = "the smoke needs npm and a Playwright Chromium"
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    scenario = ingest_scenario(hub_web, installed_hub, tmp_path)
    env = {
        **os.environ,
        "AGENT_HUB_WEB_URL": hub_web.url,
        "AGENT_HUB_CHROMIUM": executable,
        "SMOKE_LIVE_SESSION": scenario.live_session,
        "SMOKE_LONG_SESSION": scenario.long_session,
        "SMOKE_RUN": scenario.run_id,
    }

    result = run(
        [
            npm,
            "--prefix",
            str(WEB_DIR),
            "exec",
            "--",
            "playwright",
            "test",
            "--config",
            str(WEB_DIR / "playwright.config.ts"),
        ],
        env=env,
        cwd=WEB_DIR,
        timeout=PLAYWRIGHT_SECONDS,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # Nine pages and the long-session timing, none skipped.
    assert re.search(r"\b10 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout
