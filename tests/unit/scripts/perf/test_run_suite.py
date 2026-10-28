"""``make perf``'s entry point (``scripts/perf/run_suite.py``): the settings read from the
environment, the exit code of a run over fake phase functions, and the Makefile's
gates, which never reach the ``perf`` target. No process, socket or database."""

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.perf.budgets import Budget
from scripts.perf.process_probes import SuiteError
from scripts.perf.report import Row
from scripts.perf.run_suite import Settings, main, run

REPO_ROOT = Path(__file__).resolve().parents[4]
MAKEFILE = REPO_ROOT / "Makefile"
PROPOSED = "AGH-601 proposed"
SESSIONS_BUDGET_MS = 100
VERSION_BUDGET_MS = 150
_RULE = re.compile(r"^([A-Za-z0-9_.-]+(?:[ \t]+[A-Za-z0-9_.-]+)*)[ \t]*:(?![=:])(.*)$")
_WORD = re.compile(r"[A-Za-z0-9_-]+")

type Phase = Callable[..., Sequence[Row]]


def _row(kind: str, path: str, *, p95_ms: float, budget_ms: int) -> Row:
    return Row(
        kind=kind,
        path=path,
        runs=2,
        median_ms=p95_ms,
        p95_ms=p95_ms,
        budget=Budget(p95_ms=budget_ms, api_calls=None, rss_mb=None, source=PROPOSED),
        status="over" if p95_ms > budget_ms else "pass",
        reason=None,
        api_calls=None,
        rss_mb=None,
        events=2_000,
        seed=599,
        commit="0123abc",
        machine={"platform": "linux", "cpus": 4},
    )


def _phase(rows: Sequence[Row]) -> Phase:
    def phase(*_args: object, **_kwargs: object) -> list[Row]:
        return list(rows)

    return phase


def _budgets_file(tmp_path: Path) -> Path:
    path = tmp_path / "budgets.json"
    entries = [
        {"kind": "cli", "path": "hub --version", "p95_ms": VERSION_BUDGET_MS, "source": PROPOSED},
        {
            "kind": "route",
            "path": "/api/v1/sessions",
            "p95_ms": SESSIONS_BUDGET_MS,
            "source": PROPOSED,
        },
    ]
    path.write_text(json.dumps({"rows": entries}), "utf-8")
    return path


def test_reads_the_defaults_when_no_variable_is_set() -> None:
    settings = Settings.from_env({})

    assert (settings.events, settings.runs, settings.restart_runs) == (400_000, 10, 3)
    assert (settings.strict, settings.rebuild) == (False, False)
    assert Path(settings.out).resolve() == REPO_ROOT / "perf.json"
    assert Path(settings.budgets).resolve() == REPO_ROOT / "scripts" / "perf" / "budgets.json"
    assert Path(settings.cache).resolve() == REPO_ROOT / ".perf"


def test_reads_every_knob_when_variables_are_set(tmp_path: Path) -> None:
    environ = {
        "PERF_EVENTS": "2000",
        "PERF_RUNS": "4",
        "PERF_RESTART_RUNS": "2",
        "PERF_STRICT": "1",
        "PERF_REBUILD": "1",
        "PERF_OUT": str(tmp_path / "out" / "perf.json"),
        "PERF_BUDGETS": str(tmp_path / "budgets.json"),
        "PERF_CACHE": str(tmp_path / "cache"),
    }

    settings = Settings.from_env(environ)

    assert (settings.events, settings.runs, settings.restart_runs) == (2_000, 4, 2)
    assert (settings.strict, settings.rebuild) == (True, True)
    assert Path(settings.out) == tmp_path / "out" / "perf.json"
    assert Path(settings.budgets) == tmp_path / "budgets.json"
    assert Path(settings.cache) == tmp_path / "cache"


@dataclass(frozen=True)
class ExitCase:
    strict_env: Mapping[str, str]
    sessions_p95_ms: float
    expected: int


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(ExitCase({}, 250.0, 0), id="over-strict-off"),
        pytest.param(ExitCase({"PERF_STRICT": "1"}, 250.0, 1), id="over-strict-on"),
        pytest.param(ExitCase({"PERF_STRICT": "1"}, 50.0, 0), id="within-strict-on"),
    ],
)
def test_returns_the_report_exit_when_rows_are_over(tmp_path: Path, case: ExitCase) -> None:
    environ = {
        "PERF_OUT": str(tmp_path / "perf.json"),
        "PERF_BUDGETS": str(_budgets_file(tmp_path)),
        "PERF_CACHE": str(tmp_path / "cache"),
        **case.strict_env,
    }
    settings = Settings.from_env(environ)
    assert settings.strict is bool(case.strict_env)
    passing = _row("cli", "hub --version", p95_ms=50.0, budget_ms=VERSION_BUDGET_MS)
    sessions = _row(
        "route", "/api/v1/sessions", p95_ms=case.sessions_p95_ms, budget_ms=SESSIONS_BUDGET_MS
    )
    assert passing.status == "pass"
    assert sessions.status == ("over" if case.sessions_p95_ms > SESSIONS_BUDGET_MS else "pass")

    code = run(settings, [_phase([passing]), _phase([]), _phase([sessions])])

    assert code == case.expected


def test_writes_the_rows_measured_so_far_when_a_phase_fails(tmp_path: Path) -> None:
    out = tmp_path / "perf.json"
    environ = {
        "PERF_OUT": str(out),
        "PERF_BUDGETS": str(_budgets_file(tmp_path)),
        "PERF_CACHE": str(tmp_path / "cache"),
    }
    passing = _row("cli", "hub --version", p95_ms=50.0, budget_ms=VERSION_BUDGET_MS)

    def failing(*_args: object, **_kwargs: object) -> list[Row]:
        raise SuiteError("/api/v1/sessions: ReadTimeout: timed out")

    with pytest.raises(SuiteError, match="ReadTimeout"):
        run(Settings.from_env(environ), [_phase([passing]), failing])

    rows = json.loads(out.read_text("utf-8"))
    assert [(row["kind"], row["path"]) for row in rows] == [("cli", "hub --version")]


@pytest.mark.parametrize(
    "knob",
    [
        pytest.param({"PERF_RUNS": "abc"}, id="bad-runs"),
        pytest.param({"PERF_RESTART_RUNS": "1.5"}, id="bad-restart-runs"),
    ],
)
def test_reports_a_suite_failure_when_an_unexpected_error_is_raised(
    tmp_path: Path, knob: Mapping[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    environ = {
        "PERF_OUT": str(tmp_path / "perf.json"),
        "PERF_BUDGETS": str(_budgets_file(tmp_path)),
        "PERF_CACHE": str(tmp_path / "cache"),
        **knob,
    }

    code = main(environ)

    assert code == 2
    assert "make perf: ValueError" in capsys.readouterr().err
    assert not (tmp_path / "perf.json").exists()


@pytest.mark.parametrize(
    "knob",
    [
        pytest.param(("PERF_RUNS", "0"), id="zero-runs"),
        pytest.param(("PERF_RESTART_RUNS", "-1"), id="negative-restart-runs"),
    ],
)
def test_fails_the_suite_with_one_line_when_a_run_count_is_below_one(
    tmp_path: Path, knob: tuple[str, str], capsys: pytest.CaptureFixture[str]
) -> None:
    name, value = knob
    environ = {
        "PERF_OUT": str(tmp_path / "perf.json"),
        "PERF_BUDGETS": str(_budgets_file(tmp_path)),
        "PERF_CACHE": str(tmp_path / "cache"),
        name: value,
    }

    code = main(environ)

    assert code == 2
    err = capsys.readouterr().err
    assert err.splitlines() == [f"make perf: {name} must be 1 or more, got {value}"]
    assert not (tmp_path / "perf.json").exists()


def _rules(text: str) -> dict[str, tuple[list[str], list[str], list[str]]]:
    """Each Makefile target's prerequisite words, recipe words and the words of its recipe lines
    that call ``$(MAKE)`` (continuations joined)."""
    rules: dict[str, tuple[list[str], list[str], list[str]]] = {}
    current: list[str] = []
    for line in text.replace("\\\n", " ").splitlines():
        if line.startswith("\t"):
            for target in current:
                rules[target][1].extend(_WORD.findall(line))
                if "$(MAKE)" in line:
                    rules[target][2].extend(_WORD.findall(line))
            continue
        match = _RULE.match(line)
        if match is None:
            if line.strip() and not line.lstrip().startswith("#"):
                current = []
            continue
        prerequisites = _WORD.findall(match.group(2).split("##")[0])
        current = [target for target in match.group(1).split() if not target.startswith(".")]
        for target in current:
            rules.setdefault(target, ([], [], []))[0].extend(prerequisites)
    return rules


def _reached(rules: Mapping[str, tuple[list[str], list[str], list[str]]], start: str) -> set[str]:
    seen: set[str] = set()
    todo = [start]
    while todo:
        target = todo.pop()
        if target in seen or target not in rules:
            continue
        seen.add(target)
        prerequisites, _recipe, sub_makes = rules[target]
        todo.extend(prerequisites)
        todo.extend(word for word in sub_makes if word in rules)
    return seen


@pytest.mark.parametrize(
    ("gate", "steps"),
    [
        pytest.param(
            "check-fast", {"lane-checks-fast", "lane-tests-fast", "test-fast"}, id="check-fast"
        ),
        pytest.param("check", {"lane-checks", "lane-tests", "test-suite", "coverage"}, id="check"),
    ],
)
def test_keeps_perf_out_of_the_gates_when_the_makefile_is_read(gate: str, steps: set[str]) -> None:
    rules = _rules(MAKEFILE.read_text("utf-8"))
    assert "perf" in rules
    assert {"scripts", "perf", "run_suite"} <= set(rules["perf"][1])
    reached = _reached(rules, gate)
    assert steps <= reached

    assert "perf" not in reached
    named = {word for target in reached for word in rules[target][0] + rules[target][1]}
    assert "perf" not in named
    assert "run_suite" not in named
