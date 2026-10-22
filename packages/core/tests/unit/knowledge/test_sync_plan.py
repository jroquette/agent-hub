"""Which listed files a sync reads, reports and drops (AGH-391, D-sync, D-version,
D-skipreport): only what changed since the rows were written."""

import pytest

from agent_hub.core.knowledge.document_rules import NOT_REGULAR, RULE_MATCH, THROUGH_LINK
from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    Fingerprint,
    SkippedFile,
    StoredFile,
    StoredIndex,
)
from agent_hub.core.knowledge.sync_plan import FileToRead, ListedFile, SyncPlan, plan_sync

SHA: str = "0" * 64
NOTHING = SyncPlan(to_read=(), skipped_now=(), dropped=(), rebuild=False)


def _print(size: int = 10, mtime_ns: int = 1) -> Fingerprint:
    return Fingerprint(size=size, mtime_ns=mtime_ns)


def _indexed(path: str, fingerprint: Fingerprint | None = None) -> StoredFile:
    return StoredFile(path=path, fingerprint=fingerprint or _print(), sha256=SHA)


def _skipped(path: str, reason: str, fingerprint: Fingerprint | None = None) -> StoredFile:
    return StoredFile(path=path, fingerprint=fingerprint or _print(), skip_reason=reason)


def _stored(*files: StoredFile, version: int | None = INDEX_VERSION) -> StoredIndex:
    return StoredIndex(version=version, files={file.path: file for file in files})


def _listed(
    path: str, fingerprint: Fingerprint | None = None, reason: str | None = None
) -> ListedFile:
    if fingerprint is None and reason is None:
        fingerprint = _print()
    return ListedFile(path=path, fingerprint=fingerprint, skip_reason=reason)


def _read(file: ListedFile) -> FileToRead:
    assert file.fingerprint is not None
    return FileToRead(path=file.path, fingerprint=file.fingerprint)


def test_plans_nothing_when_fingerprints_match() -> None:
    stored = _stored(
        _indexed("brain/a.md"),
        _skipped("brain/leak.md", RULE_MATCH),
        _skipped("brain/link.md", THROUGH_LINK),
    )
    listed = (
        _listed("brain/a.md"),
        _listed("brain/leak.md"),
        _listed("brain/link.md", _print(), THROUGH_LINK),
    )

    assert plan_sync(stored, listed, version=INDEX_VERSION) == NOTHING


@pytest.mark.parametrize("fingerprint", [_print(size=11), _print(mtime_ns=2)])
def test_reads_file_when_size_or_mtime_changed(fingerprint: Fingerprint) -> None:
    changed = _listed("brain/a.md", fingerprint)

    plan = plan_sync(_stored(_indexed("brain/a.md")), (changed,), version=INDEX_VERSION)

    assert plan == NOTHING.model_copy(update={"to_read": (_read(changed),)})


def test_reads_file_when_new() -> None:
    new = _listed("brain/b.md")

    plan = plan_sync(_stored(_indexed("brain/a.md")), (_listed("brain/a.md"), new), version=1)

    assert plan == NOTHING.model_copy(update={"to_read": (_read(new),)})


def test_drops_row_when_file_no_longer_listed() -> None:
    stored = _stored(_indexed("brain/a.md"), _skipped("brain/b.md", RULE_MATCH))

    plan = plan_sync(stored, (), version=INDEX_VERSION)

    assert plan == NOTHING.model_copy(update={"dropped": ("brain/a.md", "brain/b.md")})


@pytest.mark.parametrize("version", [INDEX_VERSION - 1, None])
def test_reads_every_file_when_version_differs(version: int | None) -> None:
    stored = _stored(
        _indexed("brain/a.md"),
        _skipped("brain/link.md", THROUGH_LINK),
        _indexed("brain/gone.md"),
        version=version,
    )
    listed = (_listed("brain/a.md"), _listed("brain/link.md", _print(), THROUGH_LINK))

    plan = plan_sync(stored, listed, version=INDEX_VERSION)

    assert plan == SyncPlan(
        to_read=(_read(listed[0]),),
        skipped_now=(SkippedFile(path="brain/link.md", fingerprint=_print(), reason=THROUGH_LINK),),
        dropped=(),
        rebuild=True,
    )


def test_plans_nothing_when_hub_has_no_row_and_nothing_listed() -> None:
    assert plan_sync(_stored(version=None), (), version=INDEX_VERSION) == NOTHING


def test_reexamines_skipped_file_when_fingerprint_changed() -> None:
    stored = _stored(
        _skipped("brain/leak.md", RULE_MATCH),
        _skipped("brain/link.md", THROUGH_LINK),
        _skipped("brain/pipe.md", NOT_REGULAR),
    )
    leak = _listed("brain/leak.md", _print(mtime_ns=2))
    link = _listed("brain/link.md", _print(mtime_ns=2), THROUGH_LINK)
    pipe = _listed("brain/pipe.md", _print(), THROUGH_LINK)

    plan = plan_sync(stored, (leak, link, pipe), version=INDEX_VERSION)

    assert plan.to_read == (_read(leak),)
    assert plan.skipped_now == (
        SkippedFile(path="brain/link.md", fingerprint=_print(mtime_ns=2), reason=THROUGH_LINK),
        SkippedFile(path="brain/pipe.md", fingerprint=_print(), reason=THROUGH_LINK),
    )


def test_reads_file_when_row_skipped_by_listing_and_fingerprint_same() -> None:
    # A link replaced by a regular file of the same size and mtime: the listing decided the
    # skip, so the row says nothing about the file's text.
    file = _listed("brain/link.md")

    plan = plan_sync(_stored(_skipped("brain/link.md", THROUGH_LINK)), (file,), version=1)

    assert plan.to_read == (_read(file),)


def test_reports_listed_skip_every_time_when_no_fingerprint() -> None:
    unreachable = _listed("brain/linked/a.md", None, THROUGH_LINK)

    plan = plan_sync(_stored(), (unreachable,), version=INDEX_VERSION)

    assert plan.skipped_now == (
        SkippedFile(path="brain/linked/a.md", fingerprint=None, reason=THROUGH_LINK),
    )


def test_refuses_listed_file_when_neither_fingerprint_nor_reason() -> None:
    with pytest.raises(ValueError, match="fingerprint"):
        ListedFile(path="brain/a.md", fingerprint=None, skip_reason=None)
