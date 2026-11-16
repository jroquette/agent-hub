from pathlib import Path

import pytest

from agent_hub.core.hub_config.schema import export_schema_text
from scripts.export_hub_schema import REPO_ROOT, SCHEMA_PATH, main


def test_writes_model_export_when_run_on_repo_root(tmp_path: Path) -> None:
    target = tmp_path / SCHEMA_PATH
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")

    assert main([], root=tmp_path) == 0

    assert target.read_text(encoding="utf-8") == export_schema_text()


def test_leaves_file_unchanged_when_model_unchanged() -> None:
    assert (REPO_ROOT / SCHEMA_PATH).read_bytes() == export_schema_text().encode()


def test_prints_usage_when_arguments_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["extra"], root=tmp_path) == 2

    assert "usage: python -m scripts.export_hub_schema" in capsys.readouterr().err
    assert not (tmp_path / SCHEMA_PATH).exists()
