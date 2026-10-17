"""An item version's models (AGH-295, S1, S3): UTC time, origins, authors and hashes."""

from datetime import UTC, datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from agent_hub.core.item_versions.item_version import (
    ItemVersion,
    NewItemVersion,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.testing.builders import an_item_version

_HASH = "sha256:" + "ab" * 32


def _new(**overrides: object) -> NewItemVersion:
    fields: dict[str, object] = {
        "project": "demo",
        "unit_path": "plugin/demo/agents/reviewer.md",
        "kind": UnitKind.AGENT,
        "seq": 1,
        "origin": VersionOrigin.EXTERNAL,
        "first": True,
        "author": None,
        "recorded_at": datetime(2026, 10, 17, 9, 0, tzinfo=UTC),
        "content_hash": _HASH,
        "size": 5,
        "restored_from": None,
        "content": b"hello",
    }
    return NewItemVersion.model_validate(fields | overrides)


def test_refuses_naive_time_when_version_built() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        _new(recorded_at=datetime(2026, 10, 17, 9, 0))


def test_keeps_utc_when_time_has_other_offset() -> None:
    local = datetime(2026, 10, 17, 11, 0, tzinfo=timezone(timedelta(hours=2)))

    version = _new(recorded_at=local)

    assert version.recorded_at == datetime(2026, 10, 17, 9, 0, tzinfo=UTC)
    assert version.recorded_at.utcoffset() == timedelta(0)


def test_refuses_hash_when_not_sha256_form() -> None:
    with pytest.raises(ValidationError, match="content_hash"):
        _new(content_hash="ab" * 32)


def test_refuses_author_when_origin_external() -> None:
    with pytest.raises(ValidationError, match="author"):
        _new(author=VersionAuthor(name="Jane Doe", email="jane@example.com"))


def test_refuses_publish_when_author_missing() -> None:
    with pytest.raises(ValidationError, match="author"):
        _new(origin=VersionOrigin.PUBLISH, first=False)


def test_refuses_first_when_origin_not_external() -> None:
    author = VersionAuthor(name="Jane Doe", email="jane@example.com")

    with pytest.raises(ValidationError, match="first"):
        _new(origin=VersionOrigin.PUBLISH, author=author)


def test_refuses_restored_from_when_origin_not_restore() -> None:
    with pytest.raises(ValidationError, match="restored_from"):
        _new(restored_from="0199f0a0-0000-7000-8000-000000000001")


def test_refuses_restore_when_source_missing() -> None:
    author = VersionAuthor(name="Jane Doe", email="jane@example.com")

    with pytest.raises(ValidationError, match="restored_from"):
        _new(origin=VersionOrigin.RESTORE, first=False, author=author)


def test_carries_meta_and_content_when_version_built() -> None:
    version = an_item_version(content=b"body", size=4)

    assert isinstance(version, ItemVersion)
    assert version.content == b"body"
    assert version.meta().model_dump() == version.model_dump(exclude={"content"})


def test_refuses_change_when_version_frozen() -> None:
    version = an_item_version()

    with pytest.raises(ValidationError, match="frozen"):
        version.seq = 2  # type: ignore[misc]
