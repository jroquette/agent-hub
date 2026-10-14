"""The agent output reader on real folders (AGH-139 E12): bounded, no link followed."""

import os
import stat
from pathlib import Path

import pytest

from agent_hub.core.features.feature_evals import EVAL_HEAD_BYTES
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES
from agent_hub.generator.output_files import (
    NOT_READ_AS_REGULAR,
    EvalInputs,
    read_eval_inputs,
    read_output,
)

OUTPUT = b'{"schema": "agent-hub/eval/1"}\n'
SIBLING = b"---\nverdict: SHIP\n---\n"
RECORD = b'{"acs": []}\n'


def an_evals_folder(root: Path, files: dict[str, bytes]) -> Path:
    evals = root / "feature" / "evals"
    evals.mkdir(parents=True)
    for name, content in files.items():
        (evals / name).write_bytes(content)
    return evals


def tree_of(root: Path) -> list[tuple[str, int, int, bool]]:
    """Every name under ``root`` with its size, mtime and whether it is a link."""
    found: list[tuple[str, int, int, bool]] = []
    for folder, names, files in os.walk(root):
        for name in sorted([*names, *files]):
            status = os.lstat(Path(folder) / name)
            path = os.path.relpath(Path(folder) / name, root)
            found.append((path, status.st_size, status.st_mtime_ns, stat.S_ISLNK(status.st_mode)))
    return sorted(found)


def test_reads_output_when_regular_file(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT})

    assert read_output(evals / "abc-1.json") == OUTPUT


def test_refuses_link_when_output_is_symlink(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT})
    (evals / "abc-2.json").symlink_to("abc-1.json")

    assert read_output(evals / "abc-2.json") == NOT_READ_AS_REGULAR


def test_refuses_folder_when_output_is_directory(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {})
    (evals / "abc-1.json").mkdir()

    assert read_output(evals / "abc-1.json") == NOT_READ_AS_REGULAR


@pytest.mark.parametrize("missing", ["abc-1.json", "nowhere/abc-1.json"])
def test_reports_cause_when_output_missing(tmp_path: Path, missing: str) -> None:
    evals = an_evals_folder(tmp_path, {})

    assert read_output(evals / missing) == "No such file or directory"


def test_reads_one_byte_over_when_output_over_bound(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": b"x" * (MAX_OUTPUT_BYTES + 10)})

    assert read_output(evals / "abc-1.json") == b"x" * (MAX_OUTPUT_BYTES + 1)


def test_reads_sibling_head_and_record_when_eval_inputs_read(tmp_path: Path) -> None:
    sibling = SIBLING + b"y" * EVAL_HEAD_BYTES
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT, "abc-1.md": sibling})
    (evals.parent / "features.json").write_bytes(b"z" * (MAX_RECORD_BYTES + 10))

    inputs = read_eval_inputs(evals / "abc-1.json")

    assert inputs == EvalInputs(
        content=OUTPUT,
        sibling_head=sibling[:EVAL_HEAD_BYTES],
        record=b"z" * (MAX_RECORD_BYTES + 1),
    )


def test_reports_absent_when_sibling_or_record_missing(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT})

    assert read_eval_inputs(evals / "abc-1.json") == EvalInputs(
        content=OUTPUT, sibling_head=None, record=None
    )


def test_reads_no_sibling_when_output_name_not_json(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.txt": OUTPUT, "abc-1.md": SIBLING})

    assert read_eval_inputs(evals / "abc-1.txt") == EvalInputs(
        content=OUTPUT, sibling_head=None, record=None
    )


def test_refuses_link_when_sibling_is_symlink(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT, "real.md": SIBLING})
    (evals / "abc-1.md").symlink_to("real.md")

    inputs = read_eval_inputs(evals / "abc-1.json")

    assert inputs.sibling_head == NOT_READ_AS_REGULAR


def test_refuses_link_when_record_is_symlink(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT, "abc-1.md": SIBLING})
    (evals.parent / "real.json").write_bytes(RECORD)
    (evals.parent / "features.json").symlink_to("real.json")

    inputs = read_eval_inputs(evals / "abc-1.json")

    assert inputs == EvalInputs(content=OUTPUT, sibling_head=SIBLING, record=NOT_READ_AS_REGULAR)


def test_reads_no_inputs_when_eval_output_unreadable(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.md": SIBLING})
    (evals.parent / "features.json").write_bytes(RECORD)
    (evals / "abc-1.json").symlink_to("abc-1.md")

    assert read_eval_inputs(evals / "abc-1.json") == EvalInputs(
        content=NOT_READ_AS_REGULAR, sibling_head=None, record=None
    )


def test_reads_physical_parent_when_evals_folder_is_link(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path / "real", {"abc-1.json": OUTPUT, "abc-1.md": SIBLING})
    (evals.parent / "features.json").write_bytes(RECORD)
    logical = tmp_path / "logical"
    logical.mkdir()
    (logical / "features.json").write_bytes(b'{"other": true}\n')
    (logical / "evals").symlink_to(evals)

    inputs = read_eval_inputs(logical / "evals" / "abc-1.json")

    assert inputs == EvalInputs(content=OUTPUT, sibling_head=SIBLING, record=RECORD)


def test_leaves_tree_unchanged_when_inputs_read(tmp_path: Path) -> None:
    evals = an_evals_folder(tmp_path, {"abc-1.json": OUTPUT, "abc-1.md": SIBLING})
    (evals.parent / "features.json").write_bytes(RECORD)
    (evals / "abc-2.json").symlink_to("abc-1.json")
    before = tree_of(tmp_path)

    read_output(evals / "abc-1.json")
    read_eval_inputs(evals / "abc-1.json")
    read_eval_inputs(evals / "abc-2.json")
    read_eval_inputs(evals / "missing.json")

    assert tree_of(tmp_path) == before
