import json
import os
import subprocess
import sys
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
import typer

from agent_hub.cli.hub_config_reader import load_hub_config_or_exit, load_hub_json_or_exit
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document


def a_pinned_document() -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["version"] = version("agent-hub-cli")
    return document


def write_document(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "hub.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def stderr_lines_on_exit(path: Path, capsys: pytest.CaptureFixture[str]) -> list[str]:
    with pytest.raises(typer.Exit) as caught:
        load_hub_config_or_exit(path)
    captured = capsys.readouterr()
    assert caught.value.exit_code == 1
    assert captured.out == ""
    assert captured.err.endswith("\n")
    return captured.err.splitlines()


def test_returns_config_when_file_valid_and_pin_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = a_pinned_document()

    config = load_hub_config_or_exit(write_document(tmp_path, document))

    assert config == HubConfig.model_validate(document)
    assert capsys.readouterr() == ("", "")


def test_exits_with_one_line_when_schema_version_unsupported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = a_pinned_document()
    document["schema_version"] = 2
    document["unknown"] = True
    document["project"]["name"] = "Not Kebab"

    lines = stderr_lines_on_exit(write_document(tmp_path, document), capsys)

    assert len(lines) == 1
    assert lines[0].startswith("hub.json: schema_version: ")
    assert "update the file to schema version 1" in lines[0]


def test_reports_pin_when_pin_and_schema_version_both_differ(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = a_pinned_document()
    document["platform"]["version"] = "999.0.0"
    document["schema_version"] = 2

    lines = stderr_lines_on_exit(write_document(tmp_path, document), capsys)

    assert len(lines) == 1
    assert lines[0].startswith("hub.json: platform.version: ")
    assert "999.0.0" in lines[0]
    assert version("agent-hub-cli") in lines[0]


def test_prints_one_line_per_error_when_fields_invalid(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = a_pinned_document()
    document["project"]["name"] = "Not Kebab"
    document["repos"][0]["dir"] = "a/b"

    lines = stderr_lines_on_exit(write_document(tmp_path, document), capsys)

    assert len(lines) == 2
    assert all(line.startswith("hub.json: ") for line in lines)
    assert sorted(line.split(": ")[1] for line in lines) == ["project.name", "repos[0].dir"]


def test_keeps_each_error_on_one_line_when_value_has_newline(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    document = a_pinned_document()
    document["a\nhub.json: forged"] = "b\nc"

    lines = stderr_lines_on_exit(write_document(tmp_path, document), capsys)

    assert lines == ['hub.json: ["a\\nhub.json: forged"]: Extra inputs are not permitted']


def test_returns_exact_bytes_when_hub_json_loaded(tmp_path: Path) -> None:
    document = a_pinned_document()
    document["project"]["author_name"] = "Zoë Ångström"
    content = json.dumps(document, indent=2, ensure_ascii=False).replace("\n", "\r\n").encode()
    path = tmp_path / "hub.json"
    path.write_bytes(content)

    loaded = load_hub_json_or_exit(path)

    assert loaded.content == content
    assert b"\r\n" in loaded.content
    assert "Zoë Ångström".encode() in loaded.content
    assert loaded.config == HubConfig.model_validate(document)


def test_reads_file_once_when_hub_json_loaded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = write_document(tmp_path, a_pinned_document())
    read_bytes = Path.read_bytes
    calls: list[Path] = []

    def spy(self: Path) -> bytes:
        calls.append(self)
        return read_bytes(self)

    monkeypatch.setattr(Path, "read_bytes", spy)

    loaded = load_hub_json_or_exit(path)

    assert calls == [path]
    assert loaded.content == path.read_bytes()


def test_counts_lines_as_before_when_file_uses_bare_carriage_returns(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # The reader used to read text with universal newlines, so a bare CR ends a line in messages.
    path = tmp_path / "hub.json"
    path.write_bytes(b'{\r"schema_version": }')

    lines = stderr_lines_on_exit(path, capsys)

    assert lines == ["hub.json: $: not valid JSON: Expecting value at line 2 column 19"]


LONG_INTEGER = b"1" * 5000
TOO_MANY_DIGITS = (
    "not valid JSON here: a number has more than 4300 digits, which this reader does not accept"
)


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (None, "cannot read {path}: No such file or directory"),
        (b"\xff\xfe{}", "not UTF-8 text: "),
        (b'{"schema_version": 1,', "not valid JSON: "),
        (b"[]", "must be a JSON object"),
        # Whether this depth raises RecursionError depends on the C stack size, so both outcomes are
        # a "not valid JSON" line; the RecursionError branch has its own test below.
        (b"[" * 100_000, "not valid JSON"),
        (LONG_INTEGER, TOO_MANY_DIGITS),
        (b'{"schema_version": ' + LONG_INTEGER + b"}", TOO_MANY_DIGITS),
        (
            b"\xef\xbb\xbf{}",
            "not valid JSON: the file starts with a UTF-8 byte order mark; save it without one",
        ),
    ],
    ids=[
        "missing",
        "not-utf8",
        "syntax-error",
        "top-level-array",
        "too-deep",
        "long-integer",
        "nested-long-integer",
        "byte-order-mark",
    ],
)
def test_exits_with_root_line_when_file_missing_or_not_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], *, content: bytes | None, reason: str
) -> None:
    path = tmp_path / "hub.json"
    if content is not None:
        path.write_bytes(content)

    lines = stderr_lines_on_exit(path, capsys)

    assert len(lines) == 1
    assert lines[0].startswith(f"hub.json: $: {reason.format(path=json.dumps(str(path)))}")
    assert "Traceback" not in lines[0]


def test_exits_with_root_line_when_nesting_exceeds_recursion_limit(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def too_deep(*_: object, **__: object) -> object:
        raise RecursionError

    monkeypatch.setattr(json, "loads", too_deep)

    lines = stderr_lines_on_exit(write_document(tmp_path, {}), capsys)

    assert lines == ["hub.json: $: not valid JSON here: it is nested too deeply"]


def test_exits_with_root_line_when_path_is_directory(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "hub.json"
    path.mkdir()

    lines = stderr_lines_on_exit(path, capsys)

    assert lines == [f"hub.json: $: cannot read {json.dumps(str(path))}: not a regular file"]


# Loads hub.json in a fresh interpreter, which exits with the loader's code.
LOAD_SCRIPT = """
import sys
from pathlib import Path

import typer

from agent_hub.cli.hub_config_reader import load_hub_config_or_exit, load_hub_json_or_exit

try:
    load_hub_config_or_exit(Path(sys.argv[1]))
except typer.Exit as error:
    sys.exit(error.exit_code)
"""


def make_directory(path: Path) -> None:
    path.mkdir()


def make_fifo(path: Path) -> None:
    os.mkfifo(path)


def link_to_fifo(path: Path) -> None:
    fifo = path.with_name("hub.fifo")
    os.mkfifo(fifo)
    path.symlink_to(fifo)


def link_to_device(path: Path) -> None:
    path.symlink_to(os.devnull)


@pytest.mark.parametrize(
    "make_hub_file",
    [make_directory, make_fifo, link_to_fifo, link_to_device],
    ids=["directory", "fifo", "link-to-fifo", "link-to-device"],
)
def test_exits_with_root_line_when_path_not_regular_file(
    tmp_path: Path, make_hub_file: Callable[[Path], None]
) -> None:
    path = tmp_path / "hub.json"
    make_hub_file(path)

    # Opening a FIFO with no writer blocks forever: a subprocess with a timeout shows the loader
    # returned without opening it.
    completed = subprocess.run(  # noqa: S603 - this interpreter, a fixed script, a tmp_path path
        [sys.executable, "-c", LOAD_SCRIPT, str(path)],
        capture_output=True,
        text=True,
        check=False,
        timeout=10,
    )

    assert completed.returncode == 1
    assert completed.stdout == ""
    assert completed.stderr == (
        f"hub.json: $: cannot read {json.dumps(str(path))}: not a regular file\n"
    )
