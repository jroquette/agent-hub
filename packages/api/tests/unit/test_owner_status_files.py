"""The owner's status decision on the file system (ADR 0065): ``HubStatusWriter`` replaces
``brain/features/<slug>/status.md`` through a fresh temporary file, never through a link."""

from pathlib import Path

import pytest

from agent_hub.api.owner_status_files import HubStatusWriter

SLUG = "demo-feature"


def _feature(tmp_path: Path) -> tuple[Path, Path]:
    hub = tmp_path / "demo-hub"
    feature = hub / "brain" / "features" / SLUG
    feature.mkdir(parents=True)
    return hub, feature


def test_replaces_status_and_leaves_no_temporary_file_when_decided_twice(tmp_path: Path) -> None:
    hub, feature = _feature(tmp_path)
    writer = HubStatusWriter()

    writer.write_status(str(hub), slug=SLUG, name="status.md", text="first\n")
    writer.write_status(str(hub), slug=SLUG, name="status.md", text="second\n")

    assert (feature / "status.md").read_text(encoding="utf-8") == "second\n"
    assert sorted(path.name for path in feature.iterdir()) == ["status.md"]


def test_refuses_without_writing_when_feature_has_no_folder(tmp_path: Path) -> None:
    hub, _ = _feature(tmp_path)

    with pytest.raises(FileNotFoundError):
        HubStatusWriter().write_status(str(hub), slug="other", name="status.md", text="x")

    assert not (hub / "brain" / "features" / "other").exists()


@pytest.mark.parametrize("slug", ["../escape", ".hidden", "a/b"])
def test_refuses_when_slug_is_not_one_plain_name(tmp_path: Path, slug: str) -> None:
    hub, _ = _feature(tmp_path)

    with pytest.raises(FileNotFoundError):
        HubStatusWriter().write_status(str(hub), slug=slug, name="status.md", text="x")


def test_refuses_and_keeps_link_target_when_status_is_a_link(tmp_path: Path) -> None:
    hub, feature = _feature(tmp_path)
    outside = tmp_path / "outside.md"
    outside.write_text("kept\n", encoding="utf-8")
    (feature / "status.md").symlink_to(outside)

    with pytest.raises(FileNotFoundError):
        HubStatusWriter().write_status(str(hub), slug=SLUG, name="status.md", text="x")

    assert outside.read_text(encoding="utf-8") == "kept\n"


def test_refuses_when_feature_folder_is_a_link(tmp_path: Path) -> None:
    hub, feature = _feature(tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (feature.parent / "linked").symlink_to(elsewhere, target_is_directory=True)

    with pytest.raises(FileNotFoundError):
        HubStatusWriter().write_status(str(hub), slug="linked", name="status.md", text="x")

    assert list(elsewhere.iterdir()) == []
