"""A unit's stored form (AGH-295, S2): a file's raw bytes, a folder's sorted frames, and the
bounds a decoded row is held to."""

import pytest
from pydantic import ValidationError

from agent_hub.core.item_versions.unit_content import (
    MAX_UNIT_FILES,
    CorruptVersionError,
    UnitContent,
    UnitFile,
    decode,
    encode,
    size_of,
)
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES


def _folder() -> UnitContent:
    return UnitContent(
        files=(
            UnitFile(path="SKILL.md", content=b"---\nname: demo\n---\nBody\n", executable=False),
            UnitFile(path="assets/logo.bin", content=b"\x00\x01\xff", executable=False),
            UnitFile(path="scripts/run.sh", content=b"#!/bin/sh\necho run\n", executable=True),
        )
    )


def _frame(path: bytes, mark: bytes, content: bytes) -> bytes:
    return path + b"\0" + mark + b"\0" + str(len(content)).encode() + b"\0" + content


def test_round_trips_when_folder_encoded() -> None:
    content = _folder()

    decoded = decode(encode(content, folder=True), folder=True)

    assert decoded == content


def test_writes_sorted_frames_when_folder_encoded() -> None:
    blob = encode(_folder(), folder=True)

    assert blob == (
        _frame(b"SKILL.md", b"-", b"---\nname: demo\n---\nBody\n")
        + _frame(b"assets/logo.bin", b"-", b"\x00\x01\xff")
        + _frame(b"scripts/run.sh", b"x", b"#!/bin/sh\necho run\n")
    )


def test_stores_raw_bytes_when_file_encoded() -> None:
    content = UnitContent(files=(UnitFile(path="hooks.json", content=b"{}\n"),))

    blob = encode(content, folder=False)

    assert blob == b"{}\n"
    assert decode(blob, folder=False, name="hooks.json") == content


@pytest.mark.parametrize("name", [None, ""])
def test_refuses_file_decode_when_name_missing(name: str | None) -> None:
    with pytest.raises(ValueError, match="name"):
        decode(b"{}\n", folder=False, name=name)


def test_refuses_file_unit_when_not_one_file() -> None:
    with pytest.raises(ValueError, match="one file"):
        encode(_folder(), folder=False)


def test_refuses_corrupt_blob_when_frame_truncated() -> None:
    blob = encode(_folder(), folder=True)

    with pytest.raises(CorruptVersionError):
        decode(blob[:-3], folder=True)


@pytest.mark.parametrize(
    "blob",
    [
        pytest.param(_frame(b"a.md", b"-", b"ok") + b"extra", id="trailing"),
        pytest.param(_frame(b"a.md", b"?", b"ok"), id="mark"),
        pytest.param(b"a.md\0-\0two\0ok", id="length"),
        pytest.param(b"a.md\0-\0+2\0ok", id="signed-length"),
        pytest.param(_frame(b"", b"-", b"ok"), id="empty-path"),
        pytest.param(_frame(b"../a.md", b"-", b"ok"), id="parent-path"),
        pytest.param(_frame(b"/a.md", b"-", b"ok"), id="absolute-path"),
        pytest.param(_frame(b"\xff.md", b"-", b"ok"), id="not-utf8-path"),
        pytest.param(_frame(b"b.md", b"-", b"") + _frame(b"a.md", b"-", b""), id="unsorted"),
        pytest.param(_frame(b"a.md", b"-", b"") + _frame(b"a.md", b"-", b""), id="duplicate"),
        pytest.param(b"a.md", id="no-separator"),
    ],
)
def test_refuses_corrupt_blob_when_frame_bad(blob: bytes) -> None:
    with pytest.raises(CorruptVersionError, match="corrupt"):
        decode(blob, folder=True)


def test_refuses_corrupt_blob_when_too_many_files() -> None:
    blob = b"".join(_frame(f"f{index:04}.md".encode(), b"-", b"") for index in range(202))

    assert MAX_UNIT_FILES == 201
    with pytest.raises(CorruptVersionError, match="files"):
        decode(blob, folder=True)


def test_refuses_corrupt_blob_when_file_too_large() -> None:
    big = b"a" * (MAX_SKILL_FILE_BYTES + 1)

    with pytest.raises(CorruptVersionError, match="bytes"):
        decode(_frame(b"a.md", b"-", big), folder=True)
    with pytest.raises(CorruptVersionError, match="bytes"):
        decode(big, folder=False, name="a.md")


def test_keeps_bounds_when_file_at_limit() -> None:
    full = b"a" * MAX_SKILL_FILE_BYTES

    assert decode(_frame(b"SKILL.md", b"-", full), folder=True).files[0].content == full


@pytest.mark.parametrize(
    "path",
    [pytest.param("../x", id="parent"), pytest.param("/x", id="absolute"), "a//b", "", "a\0b"],
)
def test_refuses_file_when_path_not_relative(path: str) -> None:
    with pytest.raises(ValidationError, match="relative"):
        UnitFile(path=path, content=b"")


def test_refuses_content_when_paths_repeat_or_unordered() -> None:
    first, second = UnitFile(path="SKILL.md", content=b""), UnitFile(path="a.md", content=b"")

    with pytest.raises(ValidationError, match="path order"):
        UnitContent(files=(first, first))
    with pytest.raises(ValidationError, match="path order"):
        UnitContent(files=(second, first))


@pytest.mark.parametrize(
    "blob",
    [pytest.param(b"", id="empty"), pytest.param(_frame(b"a.md", b"-", b"ok"), id="no-skill-md")],
)
def test_refuses_corrupt_blob_when_folder_has_no_skill_md(blob: bytes) -> None:
    with pytest.raises(CorruptVersionError, match="SKILL.md"):
        decode(blob, folder=True)


def test_counts_file_bytes_when_size_taken() -> None:
    assert size_of(_folder()) == 24 + 3 + 19
