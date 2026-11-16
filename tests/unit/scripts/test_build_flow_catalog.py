from pathlib import Path

import pytest

from agent_hub.generator.flow_catalog import builtin_flows, flow_table
from scripts.build_flow_catalog import END, FLOWS_DOC, START, catalog_block, main

BEFORE = "# Guide\n\nIntro.\n\n## Pick a flow\n\nWhich flow.\n\n"
AFTER = "\n\n## Later\n\nMore.\n"


def test_rewrites_only_the_marked_block_when_catalog_built(tmp_path: Path) -> None:
    path = tmp_path / "FLOWS.md"
    path.write_text(f"{BEFORE}{START}\nstale table\n{END}{AFTER}", encoding="utf-8")

    assert main([str(path)]) == 0

    text = path.read_text(encoding="utf-8")
    assert text == f"{BEFORE}{START}\n{flow_table(builtin_flows())}{END}{AFTER}"


def test_exits_one_when_markers_are_missing_when_catalog_built(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "FLOWS.md"
    path.write_text(BEFORE, encoding="utf-8")

    assert main([str(path)]) == 1

    assert capsys.readouterr().err == f"build_flow_catalog: no flow-catalog markers in {path}\n"
    assert path.read_text(encoding="utf-8") == BEFORE


# The invariant: FLOWS.md's table is the generated one, never a list kept by hand.
def test_matches_builtin_catalog_when_flows_doc_read() -> None:
    block = catalog_block(FLOWS_DOC.read_text(encoding="utf-8"))

    assert block == flow_table(builtin_flows()), "docs/FLOWS.md is stale: run `make llms-txt`"
