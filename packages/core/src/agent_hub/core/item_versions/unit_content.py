"""A unit's content and its stored form (AGH-295, S2, S8).

A file unit (an agent, a hook file, a workflow file) is one ``UnitFile`` named after the file and
is stored as its raw bytes. A folder unit (a skill) holds every file below the folder by its
relative path, each with its executable bit, and is stored as one frame per file in path order:
``<path> NUL <x|-> NUL <length> NUL <bytes>``. ``decode`` holds a stored row to the bounds the
reader holds the disk to (256 KiB per file, ``SKILL.md`` and 200 bundled files, a folder always
holding ``SKILL.md``) and refuses any other shape with ``CorruptVersionError``, whose message
never quotes the content. The path rule (relative, in order, each once) belongs to the models,
so ``encode`` and ``decode`` share it.
"""

import itertools
from collections.abc import Iterator
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, ValidationError, field_validator, model_validator

from agent_hub.core.errors import AgentHubError
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS, MAX_SKILL_FILE_BYTES, SKILL_FILE

# ``SKILL.md`` and the bundled files a skill folder may hold.
MAX_UNIT_FILES: Final = DEFAULT_LIMITS.files_per_skill + 1

_SEPARATOR: Final = b"\0"
_EXECUTABLE: Final = b"x"
_PLAIN: Final = b"-"
_MARKS: Final = {_EXECUTABLE: True, _PLAIN: False}
# The longest decimal length a bounded file can have.
_LENGTH_DIGITS: Final = len(str(MAX_SKILL_FILE_BYTES))
_BAD_SEGMENTS: Final = frozenset({"", ".", ".."})


class CorruptVersionError(AgentHubError):
    """A stored version's content does not decode within the bounds."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"stored version content is corrupt: {reason}")


class UnitFile(BaseModel):
    """One file of a unit: ``path`` is relative to the folder (a file unit: the file's name),
    with no empty, ``.`` or ``..`` segment, no leading ``/`` and no NUL."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    path: str
    content: bytes
    executable: bool = False

    @field_validator("path")
    @classmethod
    def _relative(cls, path: str) -> str:
        if "\0" in path or any(segment in _BAD_SEGMENTS for segment in path.split("/")):
            msg = "path must be relative, without an empty, . or .. segment or a NUL"
            raise ValueError(msg)
        return path


class UnitContent(BaseModel):
    """Every file of a unit, in path order, each path once."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    files: tuple[UnitFile, ...]

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        paths = [file.path for file in self.files]
        if any(earlier >= later for earlier, later in itertools.pairwise(paths)):
            msg = "files must be in path order, each path once"
            raise ValueError(msg)
        return self


def size_of(content: UnitContent) -> int:
    """The bytes of a unit's files, added up."""
    return sum(len(file.content) for file in content.files)


def encode(content: UnitContent, *, folder: bool) -> bytes:
    """The stored form of ``content``: a file unit's bytes, or a folder's frames in path order."""
    if not folder:
        if len(content.files) != 1:
            msg = "a file unit holds exactly one file"
            raise ValueError(msg)
        return content.files[0].content
    frames = (
        _SEPARATOR.join(
            (
                file.path.encode(),
                _EXECUTABLE if file.executable else _PLAIN,
                str(len(file.content)).encode(),
                file.content,
            )
        )
        for file in content.files
    )
    return b"".join(frames)


def decode(blob: bytes, *, folder: bool, name: str | None = None) -> UnitContent:
    """``encode``'s inverse; a file unit's one file is named ``name``, which it needs."""
    if not folder:
        if not name:
            msg = "a file unit needs its file's name"
            raise ValueError(msg)
        _check_size(len(blob))
        return UnitContent(files=(UnitFile(path=name, content=blob),))
    try:
        content = UnitContent(files=tuple(_frames(blob)))
    except ValidationError as error:
        # The validation message would quote the stored path.
        msg = "a path is not relative, or the paths are not in order and unique"
        raise CorruptVersionError(msg) from error
    if SKILL_FILE not in {file.path for file in content.files}:
        msg = f"the folder holds no {SKILL_FILE}"
        raise CorruptVersionError(msg)
    return content


def _check_size(size: int) -> None:
    if size > MAX_SKILL_FILE_BYTES:
        msg = f"a file holds more than {MAX_SKILL_FILE_BYTES} bytes"
        raise CorruptVersionError(msg)


def _frames(blob: bytes) -> Iterator[UnitFile]:
    position = 0
    count = 0
    while position < len(blob):
        count += 1
        if count > MAX_UNIT_FILES:
            msg = f"more than {MAX_UNIT_FILES} files"
            raise CorruptVersionError(msg)
        file, position = _frame(blob, position)
        yield file


def _field(blob: bytes, start: int) -> tuple[bytes, int]:
    end = blob.find(_SEPARATOR, start)
    if end < 0:
        msg = "a frame is truncated"
        raise CorruptVersionError(msg)
    return blob[start:end], end + 1


def _frame(blob: bytes, start: int) -> tuple[UnitFile, int]:
    raw_path, position = _field(blob, start)
    mark, position = _field(blob, position)
    raw_length, position = _field(blob, position)
    if mark not in _MARKS:
        msg = "a frame has no executable mark"
        raise CorruptVersionError(msg)
    if not raw_length.isdigit() or len(raw_length) > _LENGTH_DIGITS:
        msg = "a frame has no length"
        raise CorruptVersionError(msg)
    length = int(raw_length)
    _check_size(length)
    end = position + length
    if end > len(blob):
        msg = "a frame is truncated"
        raise CorruptVersionError(msg)
    path = _path(raw_path)
    return UnitFile(path=path, content=blob[position:end], executable=_MARKS[mark]), end


def _path(raw: bytes) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as error:
        msg = "a frame's path is not UTF-8"
        raise CorruptVersionError(msg) from error
