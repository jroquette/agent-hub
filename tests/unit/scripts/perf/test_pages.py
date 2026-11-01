"""The perf suite's page rows (``scripts/perf/pages.py``): the Chromium and web-dependency
lookups, the page rows skipped with a reason when a piece is missing, the page child
environment, the Playwright call made like the smoke's and the
rows read back from the results file the spec writes.

Every process is injected, so no test starts npm, node or a browser, and no socket is opened.
Seam: ``chromium_executable(environ, *, web_dir)`` returns a path string or ``None``
(``AGENT_HUB_CHROMIUM`` first, else a headless shell under ``PLAYWRIGHT_BROWSERS_PATH``);
``web_deps_missing(web_dir)``; ``page_env(base, *, node_dir, browsers, chromium, url, token)``;
``page_rows(env, *, npm, node, chromium, web_dir, pages, runs, results, runner)`` returns one item
per page with ``kind``, ``path``, ``samples_ms``, ``api_calls`` and ``reason`` (set only when
skipped). ``runner`` is called like ``environment.Runner`` (``argv``, ``cwd``, ``env``); the spec
appends one JSON object per line, ``{path, run, ready_ms, api_calls, dom_nodes}``, to
``PERF_PAGES_OUT``; ``dom_nodes`` is a reported field only, and an older line has none."""

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from scripts.perf.environment import child_env
from scripts.perf.fixture import FEATURE_SLUG, PAGE_SESSION
from scripts.perf.pages import chromium_executable, page_env, page_rows, web_deps_missing

# The page rows, written out by hand: the sessions list and a note in a 100-note Brain folder
# come last.
SESSIONS_PAGE = "/sessions"
BRAIN_PAGE = "/projects/perf/brain/tree-3/note-050.md"
PAGES = (
    "/",
    "/features",
    f"/features/perf/{FEATURE_SLUG}",
    f"/sessions/{PAGE_SESSION}",
    SESSIONS_PAGE,
    BRAIN_PAGE,
)
NPM = "/usr/local/bin/npm"
NODE = "/usr/local/bin/node"
CHROMIUM = "/opt/browsers/chrome-headless-shell"
WEB_URL = "http://127.0.0.1:7431"
URL_NONCE = "synthetic-token"
SENSOR_URL = "http://127.0.0.1:9/"
SHELL_PARTS = (
    "chromium_headless_shell-1243",
    "chrome-headless-shell-linux64",
    "chrome-headless-shell",
)


@dataclass
class RecordingRunner:
    """Records each call; writes ``lines`` to ``PERF_PAGES_OUT`` as the Playwright spec would."""

    lines: Sequence[Mapping[str, object]] = ()
    calls: list[tuple[list[str], Path | None, dict[str, str]]] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> object:
        given = dict(env or {})
        self.calls.append((list(argv), None if cwd is None else Path(cwd), given))
        out = given.get("PERF_PAGES_OUT")
        if out is not None:
            text = "".join(json.dumps(line) + "\n" for line in self.lines)
            Path(out).write_text(text, encoding="utf-8")
        return None


def _web_dir(root: Path, *, deps: bool) -> Path:
    web_dir = root / "web"
    web_dir.mkdir()
    if deps:
        package = web_dir / "node_modules" / "@playwright" / "test"
        package.mkdir(parents=True)
        (package / "package.json").write_text('{"version": "1.63.0"}', encoding="utf-8")
    assert web_deps_missing(web_dir) is not deps
    return web_dir


def _results_lines() -> list[dict[str, object]]:
    return [
        {"path": page, "run": run, "ready_ms": 100.0 * (index + 1) + run, "api_calls": index + 2}
        for index, page in enumerate(PAGES)
        for run in range(2)
    ]


def _assert_skipped(rows: Sequence[Any], runner: RecordingRunner) -> None:
    assert len(rows) == len(PAGES)
    assert [row.path for row in rows] == list(PAGES)
    for row in rows:
        assert row.kind == "page"
        assert list(row.samples_ms) == []
        assert isinstance(row.reason, str)
        assert row.reason.strip()
    assert runner.calls == []


def test_skips_page_rows_with_a_reason_when_no_chromium_is_found(tmp_path: Path) -> None:
    browsers = tmp_path / "browsers"
    browsers.mkdir()
    web_dir = _web_dir(tmp_path, deps=True)
    chromium = chromium_executable({"PLAYWRIGHT_BROWSERS_PATH": str(browsers)}, web_dir=web_dir)
    assert chromium is None
    runner = RecordingRunner(_results_lines())

    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=NPM,
        node=NODE,
        chromium=chromium,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=runner,
    )

    _assert_skipped(rows, runner)


def test_skips_page_rows_with_a_reason_when_npm_is_missing(tmp_path: Path) -> None:
    web_dir = _web_dir(tmp_path, deps=True)
    runner = RecordingRunner(_results_lines())

    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=None,
        node=NODE,
        chromium=CHROMIUM,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=runner,
    )

    _assert_skipped(rows, runner)


def test_skips_page_rows_with_a_reason_naming_node_when_node_is_missing(tmp_path: Path) -> None:
    web_dir = _web_dir(tmp_path, deps=True)
    runner = RecordingRunner(_results_lines())

    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=NPM,
        node=None,
        chromium=CHROMIUM,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=runner,
    )

    _assert_skipped(rows, runner)
    for row in rows:
        assert row.reason is not None
        assert "node" in row.reason
        assert "npm" not in row.reason


def test_skips_page_rows_with_a_reason_when_web_dependencies_are_missing(tmp_path: Path) -> None:
    web_dir = _web_dir(tmp_path, deps=False)
    runner = RecordingRunner(_results_lines())

    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=NPM,
        node=NODE,
        chromium=CHROMIUM,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=runner,
    )

    _assert_skipped(rows, runner)


def test_prefers_agent_hub_chromium_when_it_is_set(tmp_path: Path) -> None:
    browsers = tmp_path / "browsers"
    shell = browsers.joinpath(*SHELL_PARTS)
    shell.parent.mkdir(parents=True)
    shell.write_text("#!/bin/sh\n", encoding="utf-8")
    chosen = tmp_path / "chosen" / "chrome"
    chosen.parent.mkdir()
    chosen.write_text("#!/bin/sh\n", encoding="utf-8")
    environ = {"AGENT_HUB_CHROMIUM": str(chosen), "PLAYWRIGHT_BROWSERS_PATH": str(browsers)}

    found = chromium_executable(environ, web_dir=_web_dir(tmp_path, deps=False))

    assert found == str(chosen)


def test_finds_the_headless_shell_when_browsers_path_holds_one(tmp_path: Path) -> None:
    browsers = tmp_path / "browsers"
    shell = browsers.joinpath(*SHELL_PARTS)
    shell.parent.mkdir(parents=True)
    shell.write_text("#!/bin/sh\n", encoding="utf-8")
    assert shell.is_file()

    found = chromium_executable(
        {"PLAYWRIGHT_BROWSERS_PATH": str(browsers)}, web_dir=_web_dir(tmp_path, deps=False)
    )

    assert found == str(shell)


def test_adds_node_and_browsers_to_the_child_env_when_the_page_env_is_built(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    tool_bin = root / "bin"
    tool_bin.mkdir()
    base = child_env(root, db=root / "fixture.db", tool_bin=tool_bin, sensor_url=SENSOR_URL)
    assert base["PATH"] == str(tool_bin)
    node_dir = tmp_path / "node" / "bin"
    browsers = tmp_path / "browsers"

    env = page_env(
        base, node_dir=node_dir, browsers=browsers, chromium=CHROMIUM, url=WEB_URL, token=URL_NONCE
    )

    entries = env["PATH"].split(os.pathsep)
    assert len(entries) == 2
    assert set(entries) == {str(tool_bin), str(node_dir)}
    assert env["PLAYWRIGHT_BROWSERS_PATH"] == str(browsers)
    assert env["AGENT_HUB_CHROMIUM"] == CHROMIUM
    assert env["AGENT_HUB_WEB_URL"] == WEB_URL
    assert env["PERF_TOKEN"] == URL_NONCE
    # A fresh HOME and no CI would let npm ask the registry for its latest version.
    assert env["npm_config_update_notifier"] == "false"
    assert env["npm_config_offline"] == "true"
    for name in (
        "HOME",
        "XDG_DATA_HOME",
        "XDG_CONFIG_HOME",
        "AGENT_HUB_DB",
        "AGENT_HUB_CLAUDE_PROJECTS",
    ):
        assert env[name] == base[name]
    assert Path(env["HOME"]).is_relative_to(root)


def test_calls_playwright_like_the_smoke_when_pages_are_measured(tmp_path: Path) -> None:
    web_dir = _web_dir(tmp_path, deps=True)
    results = tmp_path / "pages.jsonl"
    runner = RecordingRunner(_results_lines())
    env = {"PATH": "/perf-root/bin", "HOME": "/perf-root/home", "PERF_TOKEN": URL_NONCE}

    page_rows(
        env,
        npm=NPM,
        node=NODE,
        chromium=CHROMIUM,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=results,
        runner=runner,
    )

    assert len(runner.calls) == 1
    argv, cwd, given = runner.calls[0]
    assert argv == [
        NPM,
        "--prefix",
        str(web_dir),
        "exec",
        "--no",
        "--",
        "playwright",
        "test",
        "--config",
        str(web_dir / "playwright.config.ts"),
        "e2e/perf.spec.ts",
    ]
    assert cwd == web_dir
    assert json.loads(given["PERF_PAGES"]) == list(PAGES)
    assert given["PERF_RUNS"] == "2"
    assert given["PERF_PAGES_OUT"] == str(results)
    assert given["HOME"] == "/perf-root/home"
    assert given["PERF_TOKEN"] == URL_NONCE


def test_reads_page_rows_when_the_spec_wrote_results(tmp_path: Path) -> None:
    web_dir = _web_dir(tmp_path, deps=True)
    lines = _results_lines()
    assert len(lines) == 2 * len(PAGES)
    runner = RecordingRunner(lines)

    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=NPM,
        node=NODE,
        chromium=CHROMIUM,
        web_dir=web_dir,
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=runner,
    )

    # By hand from _results_lines: page i is ready at 100*(i+1) ms plus its run, with i+2 calls.
    expected = [
        ("page", "/", [100.0, 101.0], 2, None),
        ("page", "/features", [200.0, 201.0], 3, None),
        ("page", f"/features/perf/{FEATURE_SLUG}", [300.0, 301.0], 4, None),
        ("page", f"/sessions/{PAGE_SESSION}", [400.0, 401.0], 5, None),
        ("page", SESSIONS_PAGE, [500.0, 501.0], 6, None),
        ("page", BRAIN_PAGE, [600.0, 601.0], 7, None),
    ]
    assert [
        (row.kind, row.path, list(row.samples_ms), row.api_calls, row.reason) for row in rows
    ] == expected


def _measured(tmp_path: Path, lines: Sequence[Mapping[str, object]]) -> list[Any]:
    rows = page_rows(
        {"PATH": "/perf-root/bin"},
        npm=NPM,
        node=NODE,
        chromium=CHROMIUM,
        web_dir=_web_dir(tmp_path, deps=True),
        pages=PAGES,
        runs=2,
        results=tmp_path / "pages.jsonl",
        runner=RecordingRunner(lines),
    )
    assert [row.path for row in rows] == list(PAGES)
    return list(rows)


@pytest.mark.parametrize(
    "counts",
    [pytest.param((900, 950), id="rising"), pytest.param((950, 900), id="falling")],
)
def test_keeps_most_dom_nodes_when_page_lines_are_read(
    tmp_path: Path, counts: tuple[int, int]
) -> None:
    lines: list[dict[str, object]] = []
    for line in _results_lines():
        run = line["run"]
        assert isinstance(run, int)
        lines.append({**line, "dom_nodes": counts[run] if line["path"] == BRAIN_PAGE else 40})
    assert [line["dom_nodes"] for line in lines if line["path"] == BRAIN_PAGE] == list(counts)

    rows = _measured(tmp_path, lines)

    # By hand: the most nodes seen in one run of the page, whichever run saw them.
    assert {row.path: row.dom_nodes for row in rows} == {
        **dict.fromkeys(PAGES, 40),
        BRAIN_PAGE: 950,
    }


def test_leaves_dom_nodes_empty_when_lines_have_none(tmp_path: Path) -> None:
    lines = _results_lines()
    assert len(lines) == 2 * len(PAGES)
    assert [line for line in lines if "dom_nodes" in line] == []

    rows = _measured(tmp_path, lines)

    assert len(rows) == len(PAGES)
    assert [row.dom_nodes for row in rows] == [None] * len(PAGES)
