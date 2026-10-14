from pathlib import Path

import pytest

from agent_hub.core.features.agent_outputs import (
    OUTPUT_SCHEMA_FILES,
    OutputKind,
    export_output_schema_text,
)
from scripts.export_output_schemas import OUTPUT_SCHEMA_DIR, REPO_ROOT, main


def test_writes_both_schemas_when_script_run(tmp_path: Path) -> None:
    folder = tmp_path / OUTPUT_SCHEMA_DIR
    folder.mkdir(parents=True)
    (folder / "review.v1.json").write_text("{}\n", encoding="utf-8")

    assert main([], root=tmp_path) == 0

    written = {path.name: path.read_bytes() for path in folder.iterdir()}
    assert written == {
        "review.v1.json": export_output_schema_text("review").encode(),
        "eval.v1.json": export_output_schema_text("eval").encode(),
    }
    assert all(b"\r" not in content for content in written.values())
    assert all(content.endswith(b"}\n") for content in written.values())


def test_exits_two_when_arguments_given(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    folder = tmp_path / OUTPUT_SCHEMA_DIR
    folder.mkdir(parents=True)

    assert main(["extra"], root=tmp_path) == 2

    assert "usage: python -m scripts.export_output_schemas" in capsys.readouterr().err
    assert list(folder.iterdir()) == []


@pytest.mark.parametrize("kind", ["review", "eval"])
def test_matches_repo_files_when_schemas_exported(kind: OutputKind) -> None:
    shipped = REPO_ROOT / OUTPUT_SCHEMA_DIR / OUTPUT_SCHEMA_FILES[kind]

    assert shipped.read_bytes() == export_output_schema_text(kind).encode()
