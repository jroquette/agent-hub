"""A unit's content hash (AGH-295, S2): a file's bytes, a folder's sorted path, bit and hash
lines; never the time."""

import hashlib

from agent_hub.core.item_versions.unit_content import UnitFile
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash


def _files(*, executable: bool = True) -> tuple[UnitFile, ...]:
    return (
        UnitFile(path="scripts/run.sh", content=b"echo run\n", executable=executable),
        UnitFile(path="SKILL.md", content=b"Body\n"),
    )


def test_same_hash_when_bytes_and_bits_equal() -> None:
    assert folder_hash(_files()) == folder_hash(tuple(reversed(_files())))
    assert file_hash(b"Body\n") == file_hash(b"Body\n")


def test_changes_hash_when_executable_bit_flips() -> None:
    assert folder_hash(_files(executable=True)) != folder_hash(_files(executable=False))


def test_changes_hash_when_file_bytes_change() -> None:
    changed = (_files()[0], UnitFile(path="SKILL.md", content=b"Body!\n"))

    assert folder_hash(changed) != folder_hash(_files())


def test_hashes_bytes_when_file_unit() -> None:
    assert file_hash(b"{}\n") == "sha256:" + hashlib.sha256(b"{}\n").hexdigest()


def test_hashes_sorted_lines_when_folder_unit() -> None:
    lines = (
        b"SKILL.md\0-\0" + hashlib.sha256(b"Body\n").hexdigest().encode() + b"\n"
        b"scripts/run.sh\0x\0" + hashlib.sha256(b"echo run\n").hexdigest().encode() + b"\n"
    )

    assert folder_hash(_files()) == "sha256:" + hashlib.sha256(lines).hexdigest()
