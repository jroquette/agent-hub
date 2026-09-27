"""Per-package coverage floors (ADR 0005): 90% for core, 80% for every other package.

coverage.py and pytest-cov only offer a global ``--fail-under``, so this reads ``coverage.json``
and groups its files by the ``packages/<name>/`` segment. A package's percentage counts lines
and branches together: ``(covered_lines + covered_branches) / (num_statements + num_branches)``.
A package with no data in the report fails; a package with nothing to measure (0/0) is 100%.

Run it as ``python -m scripts.check_coverage coverage.json`` from the repo root.
"""

import json
import sys
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from scripts.check_test_layout import discover_packages

CORE_FLOOR = 90
DEFAULT_FLOOR = 80
FLOORS = {"core": CORE_FLOOR}
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class PackageCoverage:
    """Covered and measurable lines plus branches of one ``packages/<name>/`` directory."""

    name: str
    covered: int
    total: int
    has_data: bool

    @property
    def floor(self) -> int:
        return FLOORS.get(self.name, DEFAULT_FLOOR)

    @property
    def percent(self) -> float:
        return 100.0 if self.total == 0 else 100.0 * self.covered / self.total

    @property
    def passed(self) -> bool:
        # Integer comparison, so 90% exactly passes a 90% floor without float rounding.
        return self.has_data and self.covered * 100 >= self.floor * self.total

    def __str__(self) -> str:
        verdict = "ok" if self.passed else "FAIL"
        measured = f"{self.percent:.2f}%" if self.has_data else "no coverage data"
        return f"{self.name}: {measured} (floor {self.floor}%) {verdict}"


def measure_packages(report: Mapping[str, Any], packages: Iterable[str]) -> list[PackageCoverage]:
    """Coverage of each expected package directory name, from a coverage.py JSON report."""
    covered: dict[str, int] = {}
    total: dict[str, int] = {}
    for path, data in report.get("files", {}).items():
        parts = PurePosixPath(path).parts
        if len(parts) < 3 or parts[0] != "packages":
            continue
        summary = data["summary"]
        name = parts[1]
        covered[name] = (
            covered.get(name, 0) + summary["covered_lines"] + summary["covered_branches"]
        )
        total[name] = total.get(name, 0) + summary["num_statements"] + summary["num_branches"]
    return [
        PackageCoverage(name, covered.get(name, 0), total.get(name, 0), name in total)
        for name in sorted(packages)
    ]


def run(report: Mapping[str, Any], packages: Iterable[str]) -> int:
    """Print one line per package and return 1 when any package misses its floor."""
    results = measure_packages(report, packages)
    for result in results:
        print(result)
    failed = [result.name for result in results if not result.passed]
    if failed:
        print(f"coverage below the floor: {', '.join(failed)}")
    return 1 if failed else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Check the report named in ``argv`` against the packages found in the repo."""
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: python -m scripts.check_coverage <coverage.json>", file=sys.stderr)
        return 2
    report = json.loads(Path(args[0]).read_text(encoding="utf-8"))
    return run(report, _repo_packages())


def _repo_packages() -> set[str]:
    """Directory names under packages/ that hold an ``agent_hub.<name>`` module."""
    paths = (
        path.relative_to(REPO_ROOT).as_posix()
        for path in REPO_ROOT.glob("packages/*/src/agent_hub/*/*.py")
    )
    return {PurePosixPath(src).parts[1] for src in discover_packages(paths).values()}


if __name__ == "__main__":
    sys.exit(main())
