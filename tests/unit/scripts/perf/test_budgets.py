"""The perf budgets file (``scripts/perf/budgets.py``, ``scripts/perf/budgets.json``): entries keyed
by ``(kind, path)``, unknown fields ignored, edits seen on the next load, a malformed file named
in the error, and the seeded budget values."""

import json
import re
from pathlib import Path

import pytest

from scripts.perf.budgets import Budget, BudgetFileError, load_budgets
from scripts.perf.fixture import FEATURE_SLUG, PAGE_SESSION

SHIPPED = Path(__file__).resolve().parents[4] / "scripts" / "perf" / "budgets.json"
PROPOSED = "AGH-601 proposed"
RESTART_API = "hub web start → /api/v1/sessions"


def _write(path: Path, rows: list[dict[str, object]], **top: object) -> Path:
    path.write_text(json.dumps({"rows": rows, **top}), "utf-8")
    assert json.loads(path.read_text("utf-8"))["rows"] == rows
    return path


def _two_entries(tmp_path: Path) -> Path:
    return _write(
        tmp_path / "budgets.json",
        [
            {"kind": "route", "path": "/api/v1/sessions", "p95_ms": 150, "source": PROPOSED},
            {
                "kind": "restart",
                "path": RESTART_API,
                "p95_ms": 1000,
                "rss_mb": 300,
                "source": PROPOSED,
            },
        ],
    )


def test_returns_the_entry_when_kind_and_path_match(tmp_path: Path) -> None:
    budgets = load_budgets(_two_entries(tmp_path))

    assert budgets.get(("restart", RESTART_API)) == Budget(
        p95_ms=1000, api_calls=None, rss_mb=300, source=PROPOSED
    )
    assert budgets.get(("route", "/api/v1/sessions")) == Budget(
        p95_ms=150, api_calls=None, rss_mb=None, source=PROPOSED
    )


@pytest.mark.parametrize(
    ("kind", "path"),
    [
        ("route", "/api/v1/features"),
        ("page", "/api/v1/sessions"),
        ("route", "/api/v1/sessions?issue=AGH-7"),
    ],
)
def test_returns_none_when_no_entry_names_the_path(tmp_path: Path, kind: str, path: str) -> None:
    budgets = load_budgets(_two_entries(tmp_path))
    assert budgets.get(("route", "/api/v1/sessions")) is not None

    assert budgets.get((kind, path)) is None


def test_ignores_unknown_fields_when_an_entry_has_them(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "budgets.json",
        [
            {
                "kind": "hook",
                "path": "guard (PreToolUse Bash)",
                "p95_ms": 80,
                "source": PROPOSED,
                "enforced": True,
                "margin": 0.2,
            }
        ],
        margin=0.2,
    )

    assert load_budgets(path).get(("hook", "guard (PreToolUse Bash)")) == Budget(
        p95_ms=80, api_calls=None, rss_mb=None, source=PROPOSED
    )


def test_shows_the_new_value_when_the_file_is_edited(tmp_path: Path) -> None:
    path = tmp_path / "budgets.json"
    sessions = {"kind": "route", "path": "/api/v1/sessions", "source": PROPOSED}
    _write(path, [{**sessions, "p95_ms": 150}])
    before = load_budgets(path)
    assert before.get(("route", "/api/v1/sessions")) == Budget(
        p95_ms=150, api_calls=None, rss_mb=None, source=PROPOSED
    )
    assert before.get(("page", "/features")) is None

    page = {"kind": "page", "path": "/features", "p95_ms": 800, "api_calls": 5, "source": PROPOSED}
    _write(path, [{**sessions, "p95_ms": 90}, page])
    after = load_budgets(path)

    assert after.get(("route", "/api/v1/sessions")) == Budget(
        p95_ms=90, api_calls=None, rss_mb=None, source=PROPOSED
    )
    assert after.get(("page", "/features")) == Budget(
        p95_ms=800, api_calls=5, rss_mb=None, source=PROPOSED
    )


def test_raises_budget_file_error_when_the_json_is_malformed(tmp_path: Path) -> None:
    path = tmp_path / "broken-budgets.json"
    path.write_text('{"rows": [{"kind": "route",', "utf-8")
    with pytest.raises(json.JSONDecodeError):
        json.loads(path.read_text("utf-8"))

    with pytest.raises(BudgetFileError, match=re.escape("broken-budgets.json")):
        load_budgets(path)


def test_marks_every_seeded_entry_proposed_when_shipped() -> None:
    rows = json.loads(SHIPPED.read_text("utf-8"))["rows"]
    keys = [(row["kind"], row["path"]) for row in rows]

    assert len(rows) > 0
    assert [row["source"] for row in rows] == [PROPOSED] * len(rows)
    assert len(set(keys)) == len(keys)


HOOKS = (
    "guard (PreToolUse Bash)",
    "event_sensor (PreToolUse, sensor closed)",
    "post_edit (PostToolUse Edit)",
    "readonly_gate (PreToolUse Bash)",
    "session_end",
    "stop_gate (no changes)",
    "pre_compact",
)
ROUTES = (
    "/api/v1/sessions",
    "/api/v1/sessions?issue=AGH-7",
    "/api/v1/features",
    f"/api/v1/features/perf/{FEATURE_SLUG}",
    "/api/v1/projects/perf/skills",
    "/api/v1/search?q=make",
    "/api/v1/live-sessions",
)
PAGES = ("/", "/features", f"/features/perf/{FEATURE_SLUG}", f"/sessions/{PAGE_SESSION}")
# The seeded budgets, one (kind, path, budget) per suite row; None where a row has no budget.
OWNER_TABLE: list[tuple[str, str, Budget | None]] = [
    ("cli", "hub --version", Budget(p95_ms=150, api_calls=None, rss_mb=None, source=PROPOSED)),
    (
        "cli",
        "hub brief --no-network",
        Budget(p95_ms=300, api_calls=None, rss_mb=None, source=PROPOSED),
    ),
    ("cli", "./hub --version (local uvx stand-in)", None),
    *[
        ("hook", hook, Budget(p95_ms=80, api_calls=None, rss_mb=None, source=PROPOSED))
        for hook in HOOKS
    ],
    (
        "hook",
        "session_start (local uvx stand-in)",
        Budget(p95_ms=1500, api_calls=None, rss_mb=None, source=PROPOSED),
    ),
    *[
        ("route", route, Budget(p95_ms=150, api_calls=None, rss_mb=None, source=PROPOSED))
        for route in ROUTES
    ],
    *[
        ("page", page, Budget(p95_ms=800, api_calls=5, rss_mb=None, source=PROPOSED))
        for page in PAGES
    ],
    *[
        ("restart", restart, Budget(p95_ms=1000, api_calls=None, rss_mb=300, source=PROPOSED))
        for restart in ("hub web start → GET /", RESTART_API)
    ],
]


@pytest.mark.parametrize(("kind", "path", "expected"), OWNER_TABLE)
def test_seeds_the_owner_budget_when_shipped(kind: str, path: str, expected: Budget | None) -> None:
    assert len(OWNER_TABLE) == 24

    assert load_budgets(SHIPPED).get((kind, path)) == expected


def test_names_only_probed_paths_when_the_shipped_budgets_are_read() -> None:
    # Imported here so the budget tests above do not depend on the probe modules.
    from scripts.perf.process_probes import CLI_PATHS, HOOK_PATHS
    from scripts.perf.web_probes import RESTART_PATHS, ROUTE_PATHS

    probed = {
        *(("cli", path) for path in CLI_PATHS),
        *(("hook", path) for path in HOOK_PATHS),
        *(("route", path) for path in ROUTE_PATHS),
        *(("restart", path) for path in RESTART_PATHS),
        *(("page", path) for path in PAGES),
    }
    keys = [(row["kind"], row["path"]) for row in json.loads(SHIPPED.read_text("utf-8"))["rows"]]
    assert len(keys) > 0
    assert len(probed) == 24

    assert sorted(set(keys) - probed) == []
