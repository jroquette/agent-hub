import json
from pathlib import Path

import pytest

from scripts.export_openapi import OPENAPI_PATH, REPO_ROOT, main, openapi_bytes


def test_writes_document_when_run_on_repo_root(tmp_path: Path) -> None:
    (tmp_path / OPENAPI_PATH).parent.mkdir(parents=True)

    assert main([], root=tmp_path) == 0

    written = (tmp_path / OPENAPI_PATH).read_bytes()
    assert written == openapi_bytes()
    assert written.endswith(b"}\n")
    assert b"\r\n" not in written
    assert json.loads(written)["info"]["title"] == "agent-hub"


def test_writes_sorted_keys_when_document_exported() -> None:
    document = json.loads(openapi_bytes())

    assert list(document) == sorted(document)


def test_writes_committed_bytes_when_app_unchanged() -> None:
    assert (REPO_ROOT / OPENAPI_PATH).read_bytes() == openapi_bytes()


def test_passes_check_when_file_matches(tmp_path: Path) -> None:
    (tmp_path / OPENAPI_PATH).parent.mkdir(parents=True)
    (tmp_path / OPENAPI_PATH).write_bytes(openapi_bytes())

    assert main(["--check"], root=tmp_path) == 0


@pytest.mark.parametrize("content", [b"{}\n", None], ids=["stale", "missing"])
def test_fails_check_naming_file_when_file_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], content: bytes | None
) -> None:
    (tmp_path / OPENAPI_PATH).parent.mkdir(parents=True)
    if content is not None:
        (tmp_path / OPENAPI_PATH).write_bytes(content)

    assert main(["--check"], root=tmp_path) == 1

    assert "packages/api/openapi.json is stale: run make openapi" in capsys.readouterr().err
    if content is not None:
        assert (tmp_path / OPENAPI_PATH).read_bytes() == content


def test_prints_usage_when_unknown_argument_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--write"], root=tmp_path) == 2

    assert "usage: python -m scripts.export_openapi [--check]" in capsys.readouterr().err
