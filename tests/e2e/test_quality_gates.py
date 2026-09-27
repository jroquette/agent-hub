"""The gate configs enforce the conventions (ADR 0006): a config "cleanup" that switches a rule
off fails here. The tests run the real tools with the repo's configs against scratch modules."""

import json
import sys
import tomllib
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

# One violation per convention. `branchy` has McCabe complexity exactly 9 (8 ifs + 1), one over
# the limit of 8, so lowering the bar by one is caught as well as switching the rule off.
BREAKS_CONVENTIONS = """\
def branchy(value: int) -> int:
    total = 0
    if value > 1:
        total += 1
    if value > 2:
        total += 1
    if value > 3:
        total += 1
    if value > 4:
        total += 1
    if value > 5:
        total += 1
    if value > 6:
        total += 1
    if value > 7:
        total += 1
    if value > 8:
        total += 1
    return total


def add_four(first: int, second: int, third: int, fourth: int) -> int:
    return first + second + third + fourth


def toggle(flag: bool) -> bool:
    return not flag


def swallow() -> None:
    try:
        add_four(1, 2, 3, 4)
    except Exception:
        pass


# print(add_four(1, 2, 3, 4))
"""


def _ruff(*args: str) -> list[str]:
    return [sys.executable, "-m", "ruff", *args, "--no-cache", "--config", "pyproject.toml"]


def _mypy(*args: str) -> list[str]:
    return [sys.executable, "-m", "mypy", *args]


def test_reports_each_rule_when_module_breaks_conventions(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    module = tmp_path / "scratch.py"
    module.write_text(BREAKS_CONVENTIONS)

    # JSON output, because ruff's text output names rules instead of printing their codes.
    result = run([*_ruff("check", "--output-format", "json"), str(module)])

    assert result.returncode == 1, result.stderr
    diagnostics = json.loads(result.stdout)
    codes = {diagnostic["code"] for diagnostic in diagnostics}
    assert {"C901", "PLR0917", "FBT001", "BLE001", "S110", "ERA001"} <= codes, codes
    complexity = [d["message"] for d in diagnostics if d["code"] == "C901"]
    assert complexity == ["`branchy` is too complex (9 > 8)"]


def test_selects_exact_positional_rule_code_when_ruff_configured(repo_root: Path) -> None:
    pyproject = tomllib.loads((repo_root / "pyproject.toml").read_text())
    select = pyproject["tool"]["ruff"]["lint"]["select"]

    # The exact code, never a prefix of it: on ruff < 0.16 (preview rule, explicit-preview-rules)
    # "PLR" enables nothing; from 0.16 it enables every PLR rule, which is a different policy.
    assert "PLR0917" in select
    assert [code for code in select if code != "PLR0917" and "PLR0917".startswith(code)] == []


def test_fails_format_check_when_code_unformatted(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    module = tmp_path / "unformatted.py"
    module.write_text("def f(x,y): return x+y\n")

    result = run([*_ruff("format", "--check"), str(module)])

    assert result.returncode == 1, result.stdout + result.stderr


def test_fails_typecheck_when_function_unannotated(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    module = tmp_path / "untyped.py"
    module.write_text("def bad(x):\n    return x + 1\n")

    cache = str(tmp_path / "mypy-cache")
    result = run([*_mypy("--config-file", "mypy.ini", "--cache-dir", cache), str(module)])

    assert result.returncode != 0
    assert "[no-untyped-def]" in result.stdout, result.stdout


def test_passes_typecheck_when_skeleton_unchanged(
    run: Callable[..., CompletedProcess[str]],
) -> None:
    result = run(_mypy())

    assert result.returncode == 0, result.stdout + result.stderr
