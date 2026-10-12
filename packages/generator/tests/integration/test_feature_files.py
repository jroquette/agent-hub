"""The feature folder reader on real folders (plan F.6): bounded, no link followed."""

import os
from pathlib import Path

import pytest

from agent_hub.core.features.feature_status import HEAD_BYTES, FeatureFolder
from agent_hub.generator.feature_files import (
    MAX_FEATURE_FOLDERS,
    MAX_RECORD_BYTES,
    read_feature_folders,
)


def features_of(hub: Path) -> Path:
    folder = hub / "brain" / "features"
    folder.mkdir(parents=True)
    return folder


def a_feature(features: Path, slug: str, files: dict[str, bytes]) -> Path:
    folder = features / slug
    folder.mkdir()
    for name, content in files.items():
        (folder / name).write_bytes(content)
    return folder


def test_reads_record_files_when_feature_folder_complete(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    a_feature(
        features,
        "demo-feature",
        {
            "spec.md": b"---\nprocess_size: bounded\n---\n",
            "plan.md": b"# Plan\n",
            "features.json": b'{"acs": []}',
            "eval.md": b"Verdict: SHIP\n",
            "notes.txt": b"not a record file",
        },
    )

    assert read_feature_folders(tmp_path) == (
        FeatureFolder(
            slug="demo-feature",
            files=("spec.md", "plan.md", "features.json", "eval.md"),
            features_json=b'{"acs": []}',
            spec_head=b"---\nprocess_size: bounded\n---\n",
            eval_head=b"Verdict: SHIP\n",
        ),
    )


def test_reads_nothing_when_hub_has_no_features(tmp_path: Path) -> None:
    assert read_feature_folders(tmp_path) == ()


def test_lists_slugs_sorted_when_hidden_and_files_mixed(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    for slug in ("zeta", "alpha", ".hidden"):
        a_feature(features, slug, {})
    (features / "README.md").write_text("index\n", encoding="utf-8")

    assert [folder.slug for folder in read_feature_folders(tmp_path)] == ["alpha", "zeta"]


def test_skips_linked_folder_when_slug_is_link(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "spec.md").write_text("secret\n", encoding="utf-8")
    (features / "linked").symlink_to(outside)

    assert read_feature_folders(tmp_path) == ()


def test_reads_nothing_when_features_folder_is_link(tmp_path: Path) -> None:
    (tmp_path / "brain").mkdir()
    outside = tmp_path / "outside"
    a_feature(outside.parent, outside.name, {})
    (outside / "real").mkdir()
    (tmp_path / "brain" / "features").symlink_to(outside)

    assert read_feature_folders(tmp_path) == ()


def test_reports_problem_when_record_is_link(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    folder = a_feature(features, "linked-record", {"spec.md": b"# Spec\n"})
    target = tmp_path / "record.json"
    target.write_bytes(b'{"acs": []}')
    (folder / "features.json").symlink_to(target)
    (folder / "eval.md").symlink_to(target)

    [read] = read_feature_folders(tmp_path)

    assert read.files == ("spec.md",)
    assert isinstance(read.features_json, str)
    assert "not a regular file" in read.features_json
    assert read.eval_head is None


def test_reports_problem_when_record_too_large(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    a_feature(features, "big", {"features.json": b" " * (MAX_RECORD_BYTES + 1)})

    [read] = read_feature_folders(tmp_path)

    assert read.features_json == f"larger than {MAX_RECORD_BYTES} bytes"


def test_reads_head_only_when_spec_long(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    a_feature(features, "long", {"spec.md": b"x" * (HEAD_BYTES + 10)})

    [read] = read_feature_folders(tmp_path)

    assert read.spec_head is not None
    assert len(read.spec_head) == HEAD_BYTES


def test_reads_without_blocking_when_record_is_fifo(tmp_path: Path) -> None:
    features = features_of(tmp_path)
    folder = a_feature(features, "fifo", {})
    os.mkfifo(folder / "features.json")

    [read] = read_feature_folders(tmp_path)

    assert read.features_json == "not a regular file"


def test_stops_at_bound_when_folders_too_many(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = features_of(tmp_path)
    for index in range(4):
        a_feature(features, f"feature-{index}", {})
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_FEATURE_FOLDERS", 3)

    assert [folder.slug for folder in read_feature_folders(tmp_path)] == [
        "feature-0",
        "feature-1",
        "feature-2",
    ]
    assert MAX_FEATURE_FOLDERS == 500
