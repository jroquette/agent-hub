"""Which listed files a sync reads, reports and drops (AGH-391, D-sync, D-version, D-skipreport).

A sync compares what the checkout lists with what the hub's rows remember, without reading any
file: a listed file is read only when it is new or its fingerprint (size, mtime) changed; a
file the listing already rules out is reported only when it is new or changed, or has no
fingerprint to remember; a row whose file is no longer listed is dropped. Rows of another index
version are not trusted at all: the hub is rebuilt, every listed file read.
"""

from collections.abc import Mapping, Sequence
from typing import Final, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent_hub.core.knowledge.document_rules import NOT_UTF8, RULE_MATCH, TOO_LARGE
from agent_hub.core.knowledge.knowledge_index import (
    Fingerprint,
    SkippedFile,
    StoredFile,
    StoredIndex,
)

# The skip reasons a file's text decides. A row skipped for another reason (a link, not a
# regular file, a read that failed) says nothing about the text of a regular file found there.
_TEXT_REASONS: Final = frozenset({TOO_LARGE, NOT_UTF8, RULE_MATCH})


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ListedFile(_Frozen):
    """A file a checkout lists under a source, with its fingerprint from ``lstat``. When the
    listing already rules it out (a link, not a regular file, too large, a name not UTF-8, a
    folder that cannot be opened) ``skip_reason`` says why, and the fingerprint may be missing;
    a file to read always has one."""

    path: str = Field(min_length=1)
    fingerprint: Fingerprint | None = None
    skip_reason: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _readable_or_skipped(self) -> Self:
        if self.fingerprint is None and self.skip_reason is None:
            msg = "a listed file without a skip reason needs a fingerprint"
            raise ValueError(msg)
        return self


class FileToRead(_Frozen):
    """A listed file a sync reads, with the fingerprint its row will remember."""

    path: str = Field(min_length=1)
    fingerprint: Fingerprint


class SyncPlan(_Frozen):
    """What a sync does before any read: the files to read, the files to report as skipped, the
    rows to drop, and whether the hub's rows are rebuilt (then nothing is dropped one by one)."""

    to_read: tuple[FileToRead, ...]
    skipped_now: tuple[SkippedFile, ...]
    dropped: tuple[str, ...]
    rebuild: bool


def plan_sync(stored: StoredIndex, listed: Sequence[ListedFile], *, version: int) -> SyncPlan:
    """The plan that brings the rows ``stored`` up to ``listed`` at index ``version``."""
    rebuild = bool(stored.files) and stored.version != version
    rows: Mapping[str, StoredFile] = {} if rebuild else stored.files
    to_read: list[FileToRead] = []
    skipped_now: list[SkippedFile] = []
    for file in listed:
        row = rows.get(file.path)
        if file.skip_reason is not None:
            if not _is_known_skip(row, file, file.skip_reason):
                skipped_now.append(
                    SkippedFile(
                        path=file.path, fingerprint=file.fingerprint, reason=file.skip_reason
                    )
                )
        elif file.fingerprint is not None and not _is_known_text(row, file.fingerprint):
            to_read.append(FileToRead(path=file.path, fingerprint=file.fingerprint))
    paths = {file.path for file in listed}
    return SyncPlan(
        to_read=tuple(to_read),
        skipped_now=tuple(skipped_now),
        dropped=tuple(sorted(path for path in rows if path not in paths)),
        rebuild=rebuild,
    )


def _is_known_text(row: StoredFile | None, fingerprint: Fingerprint) -> bool:
    """Whether the row already holds what reading the file would give: same fingerprint, and
    either indexed or skipped for its text."""
    if row is None or row.fingerprint != fingerprint:
        return False
    return row.sha256 is not None or row.skip_reason in _TEXT_REASONS


def _is_known_skip(row: StoredFile | None, file: ListedFile, reason: str) -> bool:
    """Whether the row already remembers ``file`` skipped for ``reason`` (so it is not
    reported again)."""
    return (
        row is not None
        and file.fingerprint is not None
        and row.fingerprint == file.fingerprint
        and row.skip_reason == reason
    )
