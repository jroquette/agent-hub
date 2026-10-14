"""``hub validate-output``: one agent output checked from the command line (AGH-139 S7, E12, E17).

Every case builds a synthetic feature folder under ``tmp_path`` and asserts the folder tree is the
same before and after the run: the command reads, never writes.
"""

import json
import os
import stat
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli import validate_output_command
from agent_hub.cli.main import app
from agent_hub.core.features.feature_record import MAX_RECORD_BYTES
from agent_hub.core.features.output_models import MAX_OUTPUT_BYTES

type Tree = list[tuple[str, int, int, bool]]

SIBLING = (
    b"---\ntype: eval\ndelivery: dem-7\nverdict: SHIP\ncommit: feb9c4c\n"
    b"tickets: [DEM-7]\nacs: all\n---\n# Eval\n"
)
NOT_REGULAR = "not read as a regular file (links are never followed)"


def a_review_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "agent-hub/review/1",
        "reviewer": "spec",
        "ticket": "DEM-7",
        "task": "T2",
        "round": 1,
        "commit": "feb9c4c",
        "verdict": "PASS",
        "findings": [
            {
                "id": "F1",
                "kind": "quality",
                "severity": "minor",
                "path": "src/demo/module.py",
                "line": 12,
                "acs": ["A1"],
                "what": "The helper name says what, not why.",
                "expected": "A name that reveals intent.",
            }
        ],
    }
    return document | overrides


def an_eval_document(**overrides: object) -> dict[str, object]:
    document: dict[str, object] = {
        "schema": "agent-hub/eval/1",
        "delivery": "dem-7",
        "verdict": "SHIP",
        "commit": "feb9c4c",
        "tickets": ["DEM-7"],
        "acs": "all",
        "results": [
            {
                "ac": "A1",
                "command": "uv run pytest tests -q",
                "exit_code": 0,
                "status": "pass",
                "summary": "Every case passes.",
            }
        ],
        "gates": [{"repo": "demo", "name": "check", "exit_code": 0, "status": "pass"}],
        "red_on_parent": [],
        "owner_steps": [],
    }
    return document | overrides


def a_record(*ac_ids: str) -> bytes:
    acs = [{"id": ac_id, "description": "A criterion.", "passes": False} for ac_id in ac_ids]
    return json.dumps({"linear": [], "tickets": [], "acs": acs}).encode()


def a_review_file(root: Path, document: object, name: str = "spec-r1.json") -> Path:
    folder = root / "feature" / "reviews" / "DEM-7"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_text(json.dumps(document))
    return path


def an_eval_file(root: Path, document: object, *, sibling: bytes | None = SIBLING) -> Path:
    folder = root / "feature" / "evals"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "dem-7.json"
    path.write_text(json.dumps(document))
    if sibling is not None:
        (folder / "dem-7.md").write_bytes(sibling)
    return path


def tree_of(root: Path) -> Tree:
    """Every name under ``root`` with its size, mtime and whether it is a link."""
    found: Tree = []
    for folder, names, files in os.walk(root):
        for name in [*names, *files]:
            status = os.lstat(Path(folder) / name)
            path = os.path.relpath(Path(folder) / name, root)
            found.append((path, status.st_size, status.st_mtime_ns, stat.S_ISLNK(status.st_mode)))
    return sorted(found)


def invoke(kind: str, path: Path) -> Result:
    return CliRunner().invoke(app, ["validate-output", kind, str(path)])


def run_unchanged(root: Path, kind: str, path: Path) -> Result:
    """Run the command on ``path`` and assert the tree under ``root`` is the same after it."""
    before = tree_of(root)
    result = invoke(kind, path)
    assert tree_of(root) == before
    return result


def test_prints_valid_when_review_output_valid(tmp_path: Path) -> None:
    path = a_review_file(tmp_path, a_review_document())

    result = run_unchanged(tmp_path, "review", path)

    assert result.exit_code == 0
    assert result.stdout == f"{path}: valid\n"
    assert result.stderr == ""


def test_prints_valid_when_eval_output_valid(tmp_path: Path) -> None:
    path = an_eval_file(tmp_path, an_eval_document())

    result = run_unchanged(tmp_path, "eval", path)

    assert result.exit_code == 0
    assert result.stdout == f"{path}: valid\n"
    assert result.stderr == ""


def test_prints_every_problem_when_output_breaks_rules(tmp_path: Path) -> None:
    document = a_review_document(round=0, commit="XYZ", verdict="FAIL")
    document["findings"] = [{**document["findings"][0], "colour": "red"}]  # type: ignore[index]
    path = a_review_file(tmp_path, document)

    result = run_unchanged(tmp_path, "review", path)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr.splitlines() == [
        f"{path}: round: Input should be greater than or equal to 1",
        f"{path}: commit: String should match pattern '^[0-9a-f]{{7,40}}$'",
        f"{path}: findings[0].colour: Extra inputs are not permitted",
        f"{path}: verdict: the verdict is FAIL but no finding is blocking",
    ]


def test_escapes_newline_when_problems_echo_value(tmp_path: Path) -> None:
    path = a_review_file(tmp_path, a_review_document(**{"a\nb": 0}))

    result = run_unchanged(tmp_path, "review", path)

    assert result.exit_code == 1
    assert result.stderr == f'{path}: ["a\\nb"]: Extra inputs are not permitted\n'


def extra_keys(count: int) -> dict[str, object]:
    return {f"x{index}": 0 for index in range(count)}


def test_prints_first_problems_and_total_when_problems_over_cap(tmp_path: Path) -> None:
    path = a_review_file(tmp_path, a_review_document(**extra_keys(1000)))

    result = run_unchanged(tmp_path, "review", path)

    lines = result.stderr.splitlines()
    assert result.exit_code == 1
    assert len(lines) == 201
    assert lines[0] == f"{path}: x0: Extra inputs are not permitted"
    assert lines[199] == f"{path}: x199: Extra inputs are not permitted"
    assert lines[200] == f"{path}: … and 800 more problems (1000 in total)"


def test_prints_no_summary_when_problems_at_cap(tmp_path: Path) -> None:
    path = a_review_file(tmp_path, a_review_document(**extra_keys(200)))

    result = run_unchanged(tmp_path, "review", path)

    lines = result.stderr.splitlines()
    assert result.exit_code == 1
    assert len(lines) == 200
    assert lines[-1] == f"{path}: x199: Extra inputs are not permitted"


def test_prints_summary_when_problems_one_over_cap(tmp_path: Path) -> None:
    path = a_review_file(tmp_path, a_review_document(**extra_keys(201)))

    result = run_unchanged(tmp_path, "review", path)

    lines = result.stderr.splitlines()
    assert result.exit_code == 1
    assert len(lines) == 201
    assert lines[-2] == f"{path}: x199: Extra inputs are not permitted"
    assert lines[-1] == f"{path}: … and 1 more problems (201 in total)"


def test_states_print_cap_as_literal_when_problems_capped() -> None:
    assert validate_output_command.MAX_PRINTED_PROBLEMS == 200


def unreadable_case(root: Path, case: str) -> tuple[str, Path, str]:
    """The kind, the path and the expected cause of one unreadable input."""
    if case == "missing":
        return "review", root / "spec-r1.json", "No such file or directory"
    if case == "folder":
        (root / "spec-r1.json").mkdir()
        return "review", root / "spec-r1.json", NOT_REGULAR
    if case == "link to a valid output":
        target = a_review_file(root, a_review_document())
        link = target.with_name("spec-r2.json")
        link.symlink_to(target.name)
        return "review", link, NOT_REGULAR
    if case == "over bound":
        path = a_review_file(root, a_review_document())
        path.write_bytes(b" " * MAX_OUTPUT_BYTES + b"{}")
        return "review", path, f"$: the file is over {MAX_OUTPUT_BYTES} bytes"
    if case == "eval without sibling":
        path = an_eval_file(root, an_eval_document(), sibling=None)
        return "eval", path, "$: evals/dem-7.md is missing"
    path = an_eval_file(root, an_eval_document(), sibling=None)
    (path.parent / "real.md").write_bytes(SIBLING)
    (path.parent / "dem-7.md").symlink_to("real.md")
    return "eval", path, f"dem-7.md: {NOT_REGULAR}"


UNREADABLE_CASES = [
    "missing",
    "folder",
    "link to a valid output",
    "over bound",
    "eval without sibling",
    "sibling link",
]


@pytest.mark.parametrize("case", UNREADABLE_CASES)
def test_fails_one_line_when_output_unreadable(tmp_path: Path, case: str) -> None:
    kind, path, cause = unreadable_case(tmp_path, case)

    result = run_unchanged(tmp_path, kind, path)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"{path}: {cause}\n"


@pytest.mark.parametrize("case", UNREADABLE_CASES)
def test_behaves_same_when_unreadable_outside_hub(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.delenv("AGENT_HUB_ROOT", raising=False)
    kind, path, cause = unreadable_case(tmp_path, case)

    result = run_unchanged(tmp_path, kind, path)

    assert not (elsewhere / "hub.json").exists()
    assert result.exit_code == 1
    assert result.stderr == f"{path}: {cause}\n"


@pytest.mark.parametrize(
    "arguments",
    [["foo", "DECOY"], ["review"], ["eval"], []],
    ids=["kind foo", "review without file", "eval without file", "nothing"],
)
def test_exits_two_before_reading_when_usage_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, arguments: list[str]
) -> None:
    decoy = an_eval_file(tmp_path, an_eval_document())

    def refuse_read(path: Path) -> None:
        raise AssertionError(f"read {path}")

    monkeypatch.setattr(validate_output_command, "read_output", refuse_read)
    monkeypatch.setattr(validate_output_command, "read_eval_inputs", refuse_read)
    shown = [str(decoy) if argument == "DECOY" else argument for argument in arguments]
    before = tree_of(tmp_path)

    result = CliRunner().invoke(app, ["validate-output", *shown])

    assert tree_of(tmp_path) == before
    assert result.exit_code == 2
    assert result.stdout == ""


def test_names_missing_ac_when_record_present(tmp_path: Path) -> None:
    path = an_eval_file(tmp_path, an_eval_document())
    (path.parent.parent / "features.json").write_bytes(a_record("A1", "A2"))

    result = run_unchanged(tmp_path, "eval", path)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == f"{path}: results: no result for A2, which the scope names\n"


def test_checks_document_only_when_record_absent(tmp_path: Path) -> None:
    path = an_eval_file(tmp_path, an_eval_document())

    result = run_unchanged(tmp_path, "eval", path)

    assert result.exit_code == 0
    assert result.stdout == f"{path}: valid\n"


@pytest.mark.parametrize("case", ["link", "over bound"])
def test_fails_one_line_when_record_link_or_oversize(tmp_path: Path, case: str) -> None:
    path = an_eval_file(tmp_path, an_eval_document())
    feature = path.parent.parent
    if case == "link":
        (feature / "real.json").write_bytes(a_record("A1"))
        (feature / "features.json").symlink_to("real.json")
        expected = f"{path}: features.json: {NOT_REGULAR}\n"
    else:
        (feature / "features.json").write_bytes(b" " * MAX_RECORD_BYTES + a_record("A1"))
        expected = f"{path}: $: features.json is over {MAX_RECORD_BYTES} bytes\n"

    result = run_unchanged(tmp_path, "eval", path)

    assert result.exit_code == 1
    assert result.stdout == ""
    assert result.stderr == expected
