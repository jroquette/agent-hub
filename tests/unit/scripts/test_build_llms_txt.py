from pathlib import Path

import pytest

from scripts.build_llms_txt import (
    ADR_DIR,
    FULL_FILE,
    INDEX_FILE,
    RAW_BASE,
    REPO_ROOT,
    SECTIONS,
    TITLES,
    USER_DOCS,
    build,
    main,
    title_of,
)


def write_docs(root: Path) -> None:
    """One file per listed doc and one ADR under ``root``, each titled after its path."""
    for path in {p for _, paths in SECTIONS for p in paths}:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(f"# Title of {path}\n\nBody of {path}.\n", encoding="utf-8")
    adr = root / ADR_DIR / "0001-first.md"
    adr.parent.mkdir(parents=True, exist_ok=True)
    adr.write_text("# 0001. First\n", encoding="utf-8")


def test_title_is_first_h1_when_doc_has_one() -> None:
    assert title_of("intro\n## Sub\n# Main title \n# Later\n", "a.md") == "Main title"


def test_title_is_override_when_doc_has_one() -> None:
    assert title_of("# Ignored\n", "README.md") == TITLES["README.md"]


def test_title_falls_back_to_path_when_doc_has_no_h1() -> None:
    assert title_of("## Only a subheading\n", "docs/a.md") == "docs/a.md"


def test_index_links_each_doc_and_adr_with_its_title_when_built(tmp_path: Path) -> None:
    write_docs(tmp_path)

    index = build(tmp_path)[INDEX_FILE]

    assert index.startswith("# agent-hub\n\n> ")
    for path in [p for _, paths in SECTIONS for p in paths if p not in TITLES]:
        assert f"- [Title of {path}]({RAW_BASE}{path}): `{path}`\n" in index
    assert f"## Optional\n\n- [0001. First]({RAW_BASE}{ADR_DIR}/0001-first.md)" in index


def test_full_holds_only_user_docs_in_order_when_built(tmp_path: Path) -> None:
    write_docs(tmp_path)

    full = build(tmp_path)[FULL_FILE]

    positions = [full.index(f"Body of {path}.") for path in USER_DOCS]
    assert positions == sorted(positions)
    assert "Body of docs/SPEC.md." not in full
    assert "0001. First" not in full


def test_writes_both_files_when_run_without_arguments(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_docs(tmp_path)

    assert main([], root=tmp_path) == 0

    built = build(tmp_path)
    assert (tmp_path / INDEX_FILE).read_text(encoding="utf-8") == built[INDEX_FILE]
    assert (tmp_path / FULL_FILE).read_text(encoding="utf-8") == built[FULL_FILE]
    assert capsys.readouterr().out == f"wrote {INDEX_FILE}\nwrote {FULL_FILE}\n"


def test_prints_usage_when_arguments_given(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["--check"], root=tmp_path) == 2

    assert "usage: python -m scripts.build_llms_txt" in capsys.readouterr().err
    assert not (tmp_path / INDEX_FILE).exists()


def test_leaves_files_unchanged_when_docs_unchanged() -> None:
    for name, text in build(REPO_ROOT).items():
        assert (REPO_ROOT / name).read_text(encoding="utf-8") == text, (
            f"{name} is stale: make llms-txt"
        )
