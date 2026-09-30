import json
import re
import shutil
from pathlib import Path

import pytest

from scripts.check_release import REPO_ROOT, main

CLI = "packages/cli/pyproject.toml"
META = "packages/agent-hub/pyproject.toml"


def write_pyprojects(root: Path, *, cli: str | int | None, meta: str | int | None) -> None:
    """Write the cli and meta ``pyproject.toml`` under ``root``; ``None`` leaves out the version."""
    for relative, name, version in ((CLI, "agent-hub-cli", cli), (META, "agent-hub", meta)):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        lines = ["[project]", f"name = {json.dumps(name)}"]
        if version is not None:
            lines.append(f"version = {json.dumps(version)}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path, capsys: pytest.CaptureFixture[str], *arguments: str) -> tuple[int, str, str]:
    exit_code = main([f"--root={root}", *arguments])
    captured = capsys.readouterr()
    return exit_code, captured.out, captured.err


def test_exits_zero_when_versions_equal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")

    exit_code, out, err = run(tmp_path, capsys)

    assert exit_code == 0
    assert out == f'version lockstep ok: {CLI} and {META} are "0.2.0"\n'
    assert err == ""


def test_names_both_files_when_versions_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.1.0")

    exit_code, out, err = run(tmp_path, capsys)

    assert exit_code == 1
    assert out == ""
    assert err == (f'version lockstep: {CLI} has "0.2.0", {META} has "0.1.0"; they must be equal\n')


@pytest.mark.parametrize(
    ("cli", "meta", "expected"),
    [
        pytest.param(
            None,
            "0.2.0",
            f'version lockstep: {CLI} has no project.version, {META} has "0.2.0";'
            " they must be equal\n",
            id="cli-missing",
        ),
        pytest.param(
            "0.2.0",
            None,
            f'version lockstep: {CLI} has "0.2.0", {META} has no project.version;'
            " they must be equal\n",
            id="meta-missing",
        ),
        pytest.param(
            "0.2.0",
            1,
            f'version lockstep: {CLI} has "0.2.0", {META} has no project.version;'
            " they must be equal\n",
            id="meta-not-a-string",
        ),
    ],
)
def test_names_both_files_when_version_missing(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    *,
    cli: str | None,
    meta: str | int | None,
    expected: str,
) -> None:
    write_pyprojects(tmp_path, cli=cli, meta=meta)

    exit_code, out, err = run(tmp_path, capsys)

    assert exit_code == 1
    assert out == ""
    assert err == expected


@pytest.mark.parametrize("breakage", ["absent", "invalid-toml"])
def test_reports_file_when_pyproject_unreadable(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], breakage: str
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")
    meta_path = tmp_path / META
    if breakage == "absent":
        meta_path.unlink()
    else:
        meta_path.write_text("[project\nversion = \n", encoding="utf-8")

    exit_code, out, err = run(tmp_path, capsys)

    assert exit_code == 1
    assert out == ""
    assert err.startswith(f"{META}: cannot read: ")
    assert err.endswith("\n")
    assert err.count("\n") == 1


def test_fails_when_repo_copy_versions_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for relative in (CLI, META):
        (tmp_path / relative).parent.mkdir(parents=True)
        shutil.copyfile(REPO_ROOT / relative, tmp_path / relative)
    meta_path = tmp_path / META
    text = meta_path.read_text(encoding="utf-8")
    bumped = "\n".join(
        'version = "9.9.9"' if line.startswith("version = ") else line for line in text.splitlines()
    )
    meta_path.write_text(bumped + "\n", encoding="utf-8")

    exit_code, _, err = run(tmp_path, capsys)

    assert exit_code == 1
    assert '"9.9.9"' in err


def test_exits_zero_when_repo_versions_in_lockstep(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([]) == 0
    assert capsys.readouterr().out.startswith("version lockstep ok: ")


def test_exits_zero_when_tag_matches_both_versions(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")

    exit_code, out, err = run(tmp_path, capsys, "--tag=v0.2.0")

    assert exit_code == 0
    assert out == f'tag "v0.2.0" ok: equals the version "0.2.0" of {CLI} and {META}\n'
    assert err == ""


@pytest.mark.parametrize(
    ("tag", "shown_tag"),
    [
        pytest.param("0.2.0", '"0.2.0"', id="no-v"),
        pytest.param("v0.2", '"v0.2"', id="two-numbers"),
        pytest.param("v0.2.0-rc1", '"v0.2.0-rc1"', id="suffix"),
        pytest.param("v0.2.0\n", '"v0.2.0\\n"', id="final-newline"),
        pytest.param("v٠.2.0", '"v\\u0660.2.0"', id="arabic-indic-digit"),
        pytest.param("V0.2.0", '"V0.2.0"', id="capital-v"),
    ],
)
def test_rejects_tag_when_form_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, tag: str, shown_tag: str
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")

    exit_code, out, err = run(tmp_path, capsys, f"--tag={tag}")

    assert exit_code == 1
    assert out == ""
    assert err == f"tag {shown_tag}: must be v<major>.<minor>.<patch> with ASCII digits\n"


def test_rejects_tag_when_version_differs(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")

    exit_code, out, err = run(tmp_path, capsys, "--tag=v0.2.1")

    assert exit_code == 1
    assert out == ""
    assert err == f'tag "v0.2.1": must be v + the version "0.2.0" of {CLI} and {META}\n'


def test_rejects_tag_when_cli_and_meta_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.1.0")

    exit_code, out, err = run(tmp_path, capsys, "--tag=v0.2.0")

    assert exit_code == 1
    assert out == ""
    assert err == (
        f'tag "v0.2.0": version lockstep: {CLI} has "0.2.0", {META} has "0.1.0";'
        " they must be equal\n"
    )


def test_cuts_tag_when_longer_than_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    write_pyprojects(tmp_path, cli="0.2.0", meta="0.2.0")

    exit_code, _, err = run(tmp_path, capsys, "--tag=" + "٠" * 200)

    shown_tag = err.removeprefix("tag ").split(": must be ")[0]
    assert exit_code == 1
    assert err.startswith('tag "\\u0660')
    assert len(shown_tag) <= 80
    assert shown_tag.endswith("…")
    assert re.fullmatch(r'"(\\u0660)+…', shown_tag)
