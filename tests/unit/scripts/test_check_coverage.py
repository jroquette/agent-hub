from typing import Any

import pytest

from scripts.check_coverage import PackageCoverage, measure_packages, run


def file_summary(
    statements: int, covered: int, *, branches: int = 0, covered_branches: int = 0
) -> dict[str, Any]:
    return {
        "summary": {
            "num_statements": statements,
            "covered_lines": covered,
            "num_branches": branches,
            "covered_branches": covered_branches,
        }
    }


def report(files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"meta": {"branch_coverage": True}, "files": files}


CORE_ERRORS = "packages/core/src/agent_hub/core/errors.py"
CORE_INIT = "packages/core/src/agent_hub/core/__init__.py"
STORAGE_DB = "packages/storage/src/agent_hub/storage/db.py"
CLI_MAIN = "packages/cli/src/agent_hub/cli/main.py"


def measured(files: dict[str, dict[str, Any]], packages: list[str]) -> dict[str, PackageCoverage]:
    return {package.name: package for package in measure_packages(report(files), packages)}


def test_fails_when_core_below_90_percent() -> None:
    core = measured({CORE_ERRORS: file_summary(1000, 899)}, ["core"])["core"]

    assert core.floor == 90
    assert core.percent == pytest.approx(89.9)
    assert not core.passed


def test_passes_when_core_at_90_percent() -> None:
    assert measured({CORE_ERRORS: file_summary(10, 9)}, ["core"])["core"].passed


def test_fails_when_storage_below_80_percent() -> None:
    storage = measured({STORAGE_DB: file_summary(1000, 799)}, ["storage"])["storage"]

    assert storage.floor == 80
    assert not storage.passed


def test_passes_when_other_package_at_80_percent() -> None:
    assert measured({CLI_MAIN: file_summary(10, 8)}, ["cli"])["cli"].passed


def test_counts_branches_when_computing_percentage() -> None:
    files = {
        CORE_ERRORS: file_summary(8, 8, branches=2, covered_branches=0),
        CORE_INIT: file_summary(0, 0),
    }

    core = measured(files, ["core"])["core"]

    assert (core.covered, core.total) == (8, 10)
    assert core.percent == pytest.approx(80.0)
    assert not core.passed


def test_passes_when_package_has_no_statements() -> None:
    core = measured({CORE_INIT: file_summary(0, 0)}, ["core"])["core"]

    assert core.percent == pytest.approx(100.0)
    assert core.passed


def test_fails_when_expected_package_missing_from_report() -> None:
    packages = measured({CORE_ERRORS: file_summary(1, 1)}, ["core", "collector"])

    assert not packages["collector"].has_data
    assert not packages["collector"].passed
    assert packages["core"].passed


def test_ignores_files_when_outside_packages() -> None:
    files = {CORE_ERRORS: file_summary(1, 1), "scripts/check_x.py": file_summary(100, 0)}

    assert list(measured(files, ["core"])) == ["core"]
    assert measured(files, ["core"])["core"].passed


def test_exits_nonzero_and_names_package_when_floor_missed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = {CORE_ERRORS: file_summary(10, 9), STORAGE_DB: file_summary(10, 7)}

    exit_code = run(report(files), ["core", "storage"])

    out = capsys.readouterr().out
    assert exit_code == 1
    assert "core: 90.00% (floor 90%) ok" in out
    assert "storage: 70.00% (floor 80%) FAIL" in out


def test_exits_zero_when_every_package_meets_floor(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = run(report({CORE_ERRORS: file_summary(1, 1)}), ["core"])

    assert exit_code == 0
    assert "core: 100.00% (floor 90%) ok" in capsys.readouterr().out
