"""The visual tests' API fixtures (scripts/visual_fixtures.py, AGH-817)."""

import json
from pathlib import Path

import pytest

from scripts.visual_fixtures import FIXTURE_PATH, REPO_ROOT, fixture_text, main


def test_leaves_fixture_unchanged_when_seed_unchanged() -> None:
    assert (REPO_ROOT / FIXTURE_PATH).read_bytes() == fixture_text().encode()


def test_serves_large_flow_from_linear_when_fixture_built() -> None:
    tickets = json.loads(fixture_text())
    readiness = [row["readiness"] for row in tickets["tickets"]]

    assert (tickets["project"], tickets["slug"], tickets["source"]) == (
        "demo",
        "ledger-sync",
        "linear",
    )
    assert len(readiness) == 30
    assert readiness.count("done") == 16
    assert tickets["notice"] is None


def test_writes_fixture_when_run_on_repo_root(tmp_path: Path) -> None:
    assert main([], root=tmp_path) == 0

    assert (tmp_path / FIXTURE_PATH).read_text(encoding="utf-8") == fixture_text()


def test_prints_usage_when_arguments_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["extra"], root=tmp_path) == 2

    assert "usage: python -m scripts.visual_fixtures" in capsys.readouterr().err
    assert not (tmp_path / FIXTURE_PATH).exists()
