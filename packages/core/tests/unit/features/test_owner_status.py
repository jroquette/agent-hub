from dataclasses import replace
from datetime import UTC, datetime

import pytest

from agent_hub.core.features.feature_status import FeatureFolder, feature_view, owner_status
from agent_hub.core.features.feature_view import OwnerStatus
from agent_hub.core.features.owner_status import SetOwnerStatus, status_note
from agent_hub.core.readmodels.read_ports import EntityNotFoundError
from agent_hub.core.testing.read_model_builders import READ_TIME

DECIDED = datetime(2026, 11, 14, 10, 30, tzinfo=UTC)
SPEC = b"---\ntype: spec\nlast_verified: 2026-10-02\n---\n# Spec\n"


def a_folder(**overrides: object) -> FeatureFolder:
    folder = FeatureFolder(slug="demo-feature", files=("spec.md",), spec_head=SPEC)
    return replace(folder, **overrides)  # type: ignore[arg-type]


@pytest.mark.parametrize("status", ["shipped", "closed", "paused"])
def test_reads_decision_when_owner_wrote_one(status: str) -> None:
    note = status_note(slug="demo-feature", status=status, at=DECIDED, note="Replaced by v2.")  # type: ignore[arg-type]

    assert owner_status(note.encode()) == OwnerStatus(
        status=status,  # type: ignore[arg-type]
        decided_at="2026-11-14T10:30:00+00:00",
        note="Replaced by v2.",
    )


def test_reads_no_decision_when_owner_reopened() -> None:
    note = status_note(slug="demo-feature", status="active", at=DECIDED)

    assert owner_status(note.encode()) is None
    assert owner_status(None) is None


def test_dates_last_activity_when_decision_newer_than_spec() -> None:
    head = status_note(slug="demo-feature", status="paused", at=DECIDED).encode()

    view = feature_view(a_folder(status_head=head), project="demo", now=READ_TIME)

    assert view.owner_status is not None and view.owner_status.status == "paused"
    assert view.last_activity_on == "2026-11-14"


def test_dates_last_activity_from_spec_when_no_decision() -> None:
    view = feature_view(a_folder(), project="demo", now=READ_TIME)

    assert (view.owner_status, view.last_activity_on) == (None, "2026-10-02")


class FakeHubs:
    def hub_path_of(self, project: str) -> str:
        return f"/hubs/{project}"


class FakeWriter:
    def __init__(self, *, missing: bool = False) -> None:
        self.written: list[tuple[str, str, str, str]] = []
        self.missing = missing

    def write_status(self, hub_path: str, *, slug: str, name: str, text: str) -> None:
        if self.missing:
            raise FileNotFoundError(slug)
        self.written.append((hub_path, slug, name, text))


def test_writes_status_note_when_owner_closes_feature() -> None:
    writer = FakeWriter()

    SetOwnerStatus(FakeHubs(), writer, clock=lambda: DECIDED)(
        "demo", "demo-feature", status="closed", note="Not needed."
    )

    [(hub, slug, name, text)] = writer.written
    assert (hub, slug, name) == ("/hubs/demo", "demo-feature", "status.md")
    assert "status: closed\n" in text and "provenance: owner\n" in text
    assert text.rstrip().endswith("Not needed.")


def test_raises_not_found_when_feature_has_no_folder() -> None:
    with pytest.raises(EntityNotFoundError):
        SetOwnerStatus(FakeHubs(), FakeWriter(missing=True), clock=lambda: DECIDED)(
            "demo", "gone", status="shipped"
        )
