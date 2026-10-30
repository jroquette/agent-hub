"""The perf budgets file (``scripts/perf/budgets.py``, ``scripts/perf/budgets.json``): entries keyed
by ``(kind, path)``, unknown fields ignored, edits seen on the next load, a malformed file named
in the error, the seeded budget values, and no value looser than ADR 0053's ceiling table."""

import itertools
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.perf import budgets as budgets_module
from scripts.perf.budgets import Budget, BudgetFileError, load_budgets
from scripts.perf.fixture import FEATURE_SLUG, PAGE_SESSION

SHIPPED = Path(__file__).resolve().parents[4] / "scripts" / "perf" / "budgets.json"
PROPOSED = "AGH-601 proposed"
# The source of an entry added after the seed, at a value ADR 0053 sets.
ADR_SOURCE = "ADR 0053"
# The list-command rows, at ADR 0053's `every` cli ceiling of 300 ms rather than AGH-601's proposal.
LIST_COMMAND_PATHS = (
    "hub repo list",
    "hub env list",
    "hub action list",
    "hub scenario list",
    "hub workflow list",
)
RESTART_API = "hub web start → /api/v1/sessions"
# The shim row on the one-call commit path: ADR 0053's `hub` row plus 300 ms.
SHIM_PATH = "./hub --version (local uvx stand-in)"
ADR_PATHS = (*LIST_COMMAND_PATHS, SHIM_PATH)


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
                "owner": "AGH-601",
                "note": "seeded",
            }
        ],
        comment="unknown top-level field",
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


def test_reads_enforced_as_false_when_the_entry_omits_it(tmp_path: Path) -> None:
    budgets = load_budgets(_two_entries(tmp_path))
    assert len(budgets) == 2

    assert [budget.enforced for budget in budgets.values()] == [False, False]


def test_reads_enforced_from_the_file_when_an_entry_sets_it(tmp_path: Path) -> None:
    path = _write(
        tmp_path / "budgets.json",
        [
            {
                "kind": "route",
                "path": "/api/v1/sessions",
                "p95_ms": 150,
                "source": PROPOSED,
                "enforced": True,
            },
            {
                "kind": "hook",
                "path": "session_end",
                "p95_ms": 80,
                "source": PROPOSED,
                "enforced": False,
            },
        ],
    )

    budgets = load_budgets(path)

    assert budgets.get(("route", "/api/v1/sessions")) == Budget(
        p95_ms=150, api_calls=None, rss_mb=None, source=PROPOSED, enforced=True
    )
    assert budgets.get(("hook", "session_end")) == Budget(
        p95_ms=80, api_calls=None, rss_mb=None, source=PROPOSED, enforced=False
    )


@pytest.mark.parametrize(
    ("top", "expected"), [({}, 0.2), ({"margin": 0.5}, 0.5), ({"margin": 0}, 0.0)]
)
def test_reads_the_margin_when_the_file_sets_or_omits_it(
    tmp_path: Path, top: dict[str, object], expected: float
) -> None:
    path = _write(
        tmp_path / "budgets.json",
        [{"kind": "route", "path": "/api/v1/sessions", "p95_ms": 150, "source": PROPOSED}],
        **top,
    )

    assert budgets_module.load_margin(path) == pytest.approx(expected)


@pytest.mark.parametrize("margin", ["0.2", -0.1, True, None, float("nan"), float("inf")])
def test_raises_budget_file_error_when_the_margin_is_not_a_fraction(
    tmp_path: Path, margin: object
) -> None:
    path = _write(
        tmp_path / "bad-margin-budgets.json",
        [{"kind": "route", "path": "/api/v1/sessions", "p95_ms": 150, "source": PROPOSED}],
        margin=margin,
    )

    with pytest.raises(BudgetFileError, match=re.escape("bad-margin-budgets.json")):
        budgets_module.load_margin(path)


@pytest.mark.parametrize("enforced", ["yes", 1, None])
def test_raises_budget_file_error_when_enforced_is_not_a_boolean(
    tmp_path: Path, enforced: object
) -> None:
    path = _write(
        tmp_path / "bad-enforced-budgets.json",
        [
            {
                "kind": "route",
                "path": "/api/v1/sessions",
                "p95_ms": 150,
                "source": PROPOSED,
                "enforced": enforced,
            }
        ],
    )

    with pytest.raises(BudgetFileError, match=re.escape("bad-enforced-budgets.json")):
        load_budgets(path)


def test_enforces_nothing_with_the_default_margin_when_shipped() -> None:
    budgets = load_budgets(SHIPPED)
    assert len(budgets) == 29

    assert [key for key, budget in budgets.items() if budget.enforced] == []
    assert budgets_module.load_margin(SHIPPED) == pytest.approx(0.2)


def test_marks_every_seeded_entry_proposed_when_shipped() -> None:
    rows = json.loads(SHIPPED.read_text("utf-8"))["rows"]
    keys = [(row["kind"], row["path"]) for row in rows]
    seeded = [row for row in rows if row["path"] not in ADR_PATHS]

    assert len(seeded) == 23
    assert [row["source"] for row in seeded if row["source"] != PROPOSED] == []
    assert len(set(keys)) == len(keys)


def test_marks_list_command_entries_from_adr_when_shipped() -> None:
    rows = json.loads(SHIPPED.read_text("utf-8"))["rows"]
    listed = {row["path"]: row["source"] for row in rows if row["path"] in LIST_COMMAND_PATHS}

    assert listed == dict.fromkeys(LIST_COMMAND_PATHS, ADR_SOURCE)


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
    ("cli", SHIM_PATH, Budget(p95_ms=450, api_calls=None, rss_mb=None, source=ADR_SOURCE)),
    *[
        ("cli", command, Budget(p95_ms=300, api_calls=None, rss_mb=None, source=ADR_SOURCE))
        for command in LIST_COMMAND_PATHS
    ],
    *[
        ("hook", hook, Budget(p95_ms=80, api_calls=None, rss_mb=None, source=PROPOSED))
        for hook in HOOKS
    ],
    (
        "hook",
        "session_start (local uvx stand-in)",
        Budget(p95_ms=300, api_calls=None, rss_mb=None, source=PROPOSED),
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
    assert len(OWNER_TABLE) == 29

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
    assert len(probed) == 29

    assert sorted(set(keys) - probed) == []


# The ADR 0053 ceiling table (B3): the file may be tighter than the ADR, never looser.
ADR = SHIPPED.parents[2] / "docs" / "adr" / "0053-interactive-path-latency-budgets.md"
CEILING_HEADING = "### Budget ceilings"
# ADR column -> budgets.json field.
LIMIT_COLUMNS = {"p95 (ms)": "p95_ms", "API calls": "api_calls", "peak RSS (MB)": "rss_mb"}
NO_LIMIT = "—"
EVERY = "every"


@dataclass(frozen=True)
class Ceiling:
    """One ADR table row: a probe kind, ``every`` or one canonical path, and its limits."""

    kind: str
    paths: str
    limits: Mapping[str, float]


def _cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _ceilings(text: str) -> list[Ceiling]:
    section = text.split(CEILING_HEADING, 1)[1].splitlines()
    start = itertools.dropwhile(lambda line: not line.startswith("|"), section)
    table = list(itertools.takewhile(lambda line: line.startswith("|"), start))
    header = _cells(table[0])
    ceilings = []
    for line in table[2:]:
        row = dict(zip(header, _cells(line), strict=True))
        if row["kind"] == NO_LIMIT:
            continue
        limits = {
            field: float(row[column])
            for column, field in LIMIT_COLUMNS.items()
            if row[column] != NO_LIMIT
        }
        ceilings.append(Ceiling(row["kind"], row["paths"].strip("`"), limits))
    return ceilings


def _probed() -> set[tuple[str, str]]:
    from scripts.perf.pages import PAGE, PAGE_PATHS
    from scripts.perf.process_probes import CLI, CLI_PATHS, HOOK, HOOK_PATHS
    from scripts.perf.web_probes import RESTART, RESTART_PATHS, ROUTE, ROUTE_PATHS

    groups = {CLI: CLI_PATHS, HOOK: HOOK_PATHS, ROUTE: ROUTE_PATHS, PAGE: PAGE_PATHS}
    groups[RESTART] = RESTART_PATHS
    return {(kind, path) for kind, paths in groups.items() for path in paths}


def _ceiling_of(ceilings: list[Ceiling], kind: str, path: str) -> list[Ceiling]:
    named = [c for c in ceilings if c.kind == kind and c.paths == path]
    return named or [c for c in ceilings if c.kind == kind and c.paths == EVERY]


def _drift(ceilings: list[Ceiling], budgets: Mapping[tuple[str, str], Budget]) -> list[str]:
    """Each probed path whose budget is missing or looser than its ADR ceiling."""
    problems = []
    for kind, path in sorted(_probed()):
        (ceiling,) = _ceiling_of(ceilings, kind, path)
        if not ceiling.limits:
            continue
        budget = budgets.get((kind, path))
        if budget is None:
            problems.append(f"{kind} {path!r}: no entry")
            continue
        for field, top in ceiling.limits.items():
            value = getattr(budget, field)
            if value is None or value > top:
                problems.append(f"{kind} {path!r}: {field} {value} over the ADR's {top:g}")
    return problems


def _shipped_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = json.loads(SHIPPED.read_text("utf-8"))["rows"]
    return rows


def _changed(tmp_path: Path, path: str, **fields: object) -> Path:
    rows = [{**row, **fields} if row["path"] == path else row for row in _shipped_rows()]
    return _write(tmp_path / "budgets.json", rows)


def test_keeps_every_budget_under_the_adr_ceiling_when_shipped() -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    assert len(ceilings) == 9

    assert _drift(ceilings, load_budgets(SHIPPED)) == []


def test_names_only_probed_paths_when_the_adr_table_is_read() -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    probed = _probed()
    assert len(probed) == 29

    assert [c for c in ceilings if c.paths != EVERY and (c.kind, c.paths) not in probed] == []
    assert sorted({c.kind for c in ceilings}) == sorted({kind for kind, _path in probed})
    assert [key for key in sorted(probed) if len(_ceiling_of(ceilings, *key)) != 1] == []


def test_reports_the_looser_value_when_the_file_loosens_a_ceiling(tmp_path: Path) -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    loose = _changed(tmp_path, "guard (PreToolUse Bash)", p95_ms=81)

    assert _drift(ceilings, load_budgets(loose)) == [
        "hook 'guard (PreToolUse Bash)': p95_ms 81 over the ADR's 80"
    ]


def test_reports_the_dropped_limit_when_the_file_omits_one(tmp_path: Path) -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    loose = _changed(tmp_path, "/features", api_calls=None)

    assert _drift(ceilings, load_budgets(loose)) == [
        "page '/features': api_calls None over the ADR's 5"
    ]


def test_reports_the_missing_entry_when_a_budgeted_path_has_none(tmp_path: Path) -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    rows = [row for row in _shipped_rows() if row["path"] != "hub brief --no-network"]
    missing = _write(tmp_path / "budgets.json", rows)

    assert _drift(ceilings, load_budgets(missing)) == ["cli 'hub brief --no-network': no entry"]


def test_accepts_a_tighter_value_when_the_file_tightens_a_ceiling(tmp_path: Path) -> None:
    ceilings = _ceilings(ADR.read_text("utf-8"))
    tight = _changed(tmp_path, "/api/v1/sessions", p95_ms=90)
    assert load_budgets(tight).get(("route", "/api/v1/sessions")) == Budget(
        p95_ms=90, api_calls=None, rss_mb=None, source=PROPOSED
    )

    assert _drift(ceilings, load_budgets(tight)) == []
