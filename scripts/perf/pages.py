"""``make perf``'s page rows: each page opened in Playwright's Chromium by ``e2e/perf.spec.ts``.

``chromium_executable`` finds the browser as the web smoke does (``AGENT_HUB_CHROMIUM`` first,
else a headless shell under ``PLAYWRIGHT_BROWSERS_PATH`` or Playwright's cache); nothing is ever
downloaded. ``page_env`` adds node's folder, the browsers and the server's URL and token to the
suite's child environment. ``page_rows`` runs the spec once through ``npm exec --no`` (never
installs from the registry) and reads back the JSON lines it appended to ``PERF_PAGES_OUT``. When
Chromium, npm or the web dependencies are missing, every page row is skipped with the reason
(plan Q7), and nothing is started.
"""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from scripts.perf.environment import Runner
from scripts.perf.fixture import FEATURE_SLUG, PAGE_SESSION, PROJECT
from scripts.perf.process_probes import SuiteError

PAGE = "page"
PAGE_PATHS = ("/", "/features", f"/features/{PROJECT}/{FEATURE_SLUG}", f"/sessions/{PAGE_SESSION}")
SPEC = "e2e/perf.spec.ts"


@dataclass(frozen=True)
class PageRow:
    """One page row's samples; ``reason`` is set only when the row is skipped.

    ``api_calls`` is the most calls seen in one run, ``None`` when skipped."""

    kind: str
    path: str
    samples_ms: list[float] = field(default_factory=list)
    api_calls: int | None = None
    reason: str | None = None


def chromium_executable(environ: Mapping[str, str], *, web_dir: Path) -> str | None:
    """``AGENT_HUB_CHROMIUM`` when set, else the headless shell Playwright expects, else the
    newest one found."""
    chosen = environ.get("AGENT_HUB_CHROMIUM")
    if chosen:
        return chosen
    configured = environ.get("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"
    # The playwright-core under @playwright/test is the one `playwright install` runs.
    modules = web_dir / "node_modules"
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
    folder = f"chromium_headless_shell-{revision}"
    return sorted(
        [
            *root.glob(f"{folder}/chrome-*/headless_shell"),
            *root.glob(f"{folder}/chrome-headless-shell-*/chrome-headless-shell"),
        ]
    )


def web_deps_missing(web_dir: Path) -> bool:
    """True when ``npm ci`` has not put ``@playwright/test`` under ``web_dir``."""
    return not (web_dir / "node_modules" / "@playwright" / "test" / "package.json").is_file()


def page_env(
    base: Mapping[str, str], *, node_dir: Path, browsers: Path, chromium: str, url: str, token: str
) -> dict[str, str]:
    """``base`` (the suite's child env) plus node on ``PATH``, the browsers, the URL and token."""
    return {
        **base,
        "PATH": os.pathsep.join((base["PATH"], str(node_dir))),
        "PLAYWRIGHT_BROWSERS_PATH": str(browsers),
        "AGENT_HUB_CHROMIUM": chromium,
        "AGENT_HUB_WEB_URL": url,
        "PERF_TOKEN": token,
    }


def page_rows(
    env: Mapping[str, str],
    *,
    npm: str | None,
    chromium: str | None,
    web_dir: Path,
    pages: Sequence[str],
    runs: int,
    results: Path,
    runner: Runner,
) -> list[PageRow]:
    """Run the spec once over ``pages`` × ``runs`` and return one row per page, in order."""
    reason = _missing(npm=npm, chromium=chromium, web_dir=web_dir)
    # A missing npm always has a reason; the second test only narrows the type.
    if reason is not None or npm is None:
        return [PageRow(PAGE, path, reason=reason) for path in pages]
    results.unlink(missing_ok=True)
    argv = [
        npm,
        "--prefix",
        str(web_dir),
        "exec",
        "--no",
        "--",
        "playwright",
        "test",
        "--config",
        str(web_dir / "playwright.config.ts"),
        SPEC,
    ]
    spec_env = {
        **env,
        "PERF_PAGES": json.dumps(list(pages)),
        "PERF_RUNS": str(runs),
        "PERF_PAGES_OUT": str(results),
    }
    runner(argv, cwd=web_dir, env=spec_env)
    return _read(results, pages)


def _missing(*, npm: str | None, chromium: str | None, web_dir: Path) -> str | None:
    if chromium is None:
        return "no Chromium: set AGENT_HUB_CHROMIUM or PLAYWRIGHT_BROWSERS_PATH"
    if npm is None:
        return "npm not found on PATH"
    if web_deps_missing(web_dir):
        return f"web dependencies missing: run npm ci in {web_dir}"
    return None


def _read(results: Path, pages: Sequence[str]) -> list[PageRow]:
    lines = results.read_text(encoding="utf-8").splitlines() if results.is_file() else []
    samples: dict[str, list[tuple[int, float]]] = {path: [] for path in pages}
    calls: dict[str, int] = {}
    for line in filter(None, (text.strip() for text in lines)):
        item = json.loads(line)
        path = item["path"]
        if path not in samples:
            continue
        samples[path].append((int(item["run"]), float(item["ready_ms"])))
        calls[path] = max(calls.get(path, 0), int(item["api_calls"]))
    rows = []
    for path in pages:
        if not samples[path]:
            raise SuiteError(f"{path}: the page spec wrote no result")
        ordered = [ready for _, ready in sorted(samples[path])]
        rows.append(PageRow(PAGE, path, samples_ms=ordered, api_calls=calls[path]))
    return rows
