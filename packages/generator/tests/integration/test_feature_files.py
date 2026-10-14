"""The feature folder reader on real folders (plan F.6): bounded, no link followed."""

import os
from pathlib import Path

import pytest

from agent_hub.core.features.feature_evals import EVAL_HEAD_BYTES
from agent_hub.core.features.feature_reviews import REVIEW_HEAD_BYTES
from agent_hub.core.features.feature_status import HEAD_BYTES, FeatureFolder, RecordHead
from agent_hub.generator.feature_files import (
    MAX_EVAL_FILES,
    MAX_FEATURE_FOLDERS,
    MAX_RECORD_BYTES,
    MAX_REVIEW_FILES,
    OVER_BUDGET,
    READ_BUDGET_BYTES,
    read_feature_folder,
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


def test_reads_eval_heads_when_evals_folder_present_evals(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "evals").mkdir()
    (folder / "evals" / "tip-1521.md").write_bytes(b"---\nverdict: NO-SHIP\n---\n")
    (folder / "evals" / "tip-1520.md").write_bytes(b"x" * (EVAL_HEAD_BYTES + 10))
    (folder / "evals" / ".draft.md").write_bytes(b"hidden\n")
    (folder / "evals" / "notes.txt").write_bytes(b"not an eval\n")

    [read] = read_feature_folders(tmp_path)

    assert read.evals == (
        RecordHead(name="tip-1520.md", head=b"x" * EVAL_HEAD_BYTES, problem=None),
        RecordHead(name="tip-1521.md", head=b"---\nverdict: NO-SHIP\n---\n", problem=None),
    )
    assert (read.evals_skipped, read.reviews, read.reviews_skipped) == (0, (), 0)
    assert read.files == ()


def test_counts_skipped_when_evals_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "evals").mkdir()
    for index in range(5):
        (folder / "evals" / f"dem-{index}.md").write_bytes(b"---\n---\n")
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_EVAL_FILES", 3)

    [read] = read_feature_folders(tmp_path)

    assert [head.name for head in read.evals] == ["dem-0.md", "dem-1.md", "dem-2.md"]
    assert read.evals_skipped == 2
    assert MAX_EVAL_FILES == 200


def test_counts_skipped_when_eval_name_not_utf8(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "evals").mkdir()
    (folder / "evals" / "dem-1.md").write_bytes(b"---\n---\n")
    os.close(os.open(os.fsencode(folder / "evals") + b"/dem-\xff.md", os.O_CREAT | os.O_WRONLY))

    [read] = read_feature_folders(tmp_path)

    assert [head.name for head in read.evals] == ["dem-1.md"]
    assert read.evals_skipped == 1


def test_refuses_link_when_eval_is_symlink(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "evals").mkdir()
    secret = tmp_path / "secret.md"
    secret.write_bytes(b"---\nverdict: SHIP\n---\n")
    (folder / "evals" / "dem-1.md").symlink_to(secret)
    (folder / "evals" / "dem-2.md").mkdir()
    os.mkfifo(folder / "evals" / "dem-3.md")

    [read] = read_feature_folders(tmp_path)

    assert read.evals == tuple(
        RecordHead(name=name, head=None, problem="not a regular file")
        for name in ("dem-1.md", "dem-2.md", "dem-3.md")
    )


def test_reads_nothing_when_evals_folder_is_link(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "dem-1.md").write_bytes(b"---\nverdict: SHIP\n---\n")
    (folder / "evals").symlink_to(outside)
    (folder / "reviews").write_bytes(b"a file, not a folder\n")

    [read] = read_feature_folders(tmp_path)

    assert (read.evals, read.evals_skipped, read.reviews, read.reviews_skipped) == ((), 0, (), 0)


def test_reads_review_heads_when_reviews_present_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "reviews").mkdir()
    (folder / "reviews" / "tip-1520.md").write_bytes(b"y" * (REVIEW_HEAD_BYTES + 1))
    (folder / "reviews" / "tip-1521.md").write_bytes(b"---\noutcome: approved\n---\n")
    (folder / "reviews" / "tip-1522.md").write_bytes(b"---\n---\n")
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_REVIEW_FILES", 2)

    [read] = read_feature_folders(tmp_path)

    assert read.reviews == (
        RecordHead(name="tip-1520.md", head=b"y" * REVIEW_HEAD_BYTES, problem=None),
        RecordHead(name="tip-1521.md", head=b"---\noutcome: approved\n---\n", problem=None),
    )
    assert read.reviews_skipped == 1
    assert MAX_REVIEW_FILES == 500


def test_reports_problem_when_record_is_folder(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "features.json").mkdir()

    [read] = read_feature_folders(tmp_path)

    assert (read.features_json, read.files) == ("not a regular file", ())


class Reads:
    """Counts what the reader opens and reads, through ``os.open`` and ``os.read``."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.opened: list[str] = []
        self.bytes = 0
        real_open, real_read = os.open, os.read

        def counting_open(path: object, flags: int, *args: object, **kwargs: object) -> int:
            self.opened.append(os.fsdecode(path) if isinstance(path, str | bytes) else str(path))
            return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

        def counting_read(descriptor: int, size: int) -> bytes:
            chunk = real_read(descriptor, size)
            self.bytes += len(chunk)
            return chunk

        monkeypatch.setattr(os, "open", counting_open)
        monkeypatch.setattr(os, "read", counting_read)


def test_opens_only_named_folder_when_one_slug_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = features_of(tmp_path)
    a_feature(features, "alpha", {"features.json": b'{"acs": []}'})
    a_feature(features, "beta", {"spec.md": b"# Beta\n"})
    a_feature(features, "gamma", {"features.json": b'{"acs": []}'})
    reads = Reads(monkeypatch)

    read = read_feature_folder(tmp_path, "beta")

    assert read == FeatureFolder(slug="beta", files=("spec.md",), spec_head=b"# Beta\n")
    assert "alpha" not in reads.opened
    assert "gamma" not in reads.opened
    assert reads.bytes == len(b"# Beta\n")


@pytest.mark.parametrize("slug", ["", ".hidden", "linked", "a-file", "nested/inner", "..", "nope"])
def test_reads_no_folder_when_slug_not_a_feature_folder(tmp_path: Path, slug: str) -> None:
    features = features_of(tmp_path)
    a_feature(features, ".hidden", {})
    a_feature(features, "nested", {})
    (features / "nested" / "inner").mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (features / "linked").symlink_to(outside)
    (features / "a-file").write_bytes(b"not a folder\n")

    assert read_feature_folder(tmp_path, slug) is None


def test_reads_no_folder_when_hub_has_no_features(tmp_path: Path) -> None:
    assert read_feature_folder(tmp_path, "demo-feature") is None


def test_lists_folders_unread_when_read_budget_spent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = features_of(tmp_path)
    a_feature(features, "alpha", {"features.json": b"x" * 20})
    a_feature(features, "beta", {"features.json": b"y" * 20})
    a_feature(features, "gamma", {"spec.md": b"z" * 20})
    monkeypatch.setattr("agent_hub.generator.feature_files.READ_BUDGET_BYTES", 10)
    reads = Reads(monkeypatch)

    alpha, beta, gamma = read_feature_folders(tmp_path)

    assert alpha.features_json == b"x" * 20
    assert beta == FeatureFolder(slug="beta", files=(), features_json=OVER_BUDGET)
    assert gamma == FeatureFolder(slug="gamma", files=(), features_json=OVER_BUDGET)
    assert reads.bytes == 20
    assert "beta" not in reads.opened
    assert READ_BUDGET_BYTES == 32 * 1_048_576


def test_reads_no_byte_when_record_file_only_checked_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    a_feature(
        features_of(tmp_path),
        "demo-feature",
        {"plan.md": b"p" * 100_000, "research.md": b"r" * 100_000, "issues.md": b"i"},
    )
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.files == ("research.md", "plan.md", "issues.md")
    assert reads.bytes == 0


def test_reads_first_names_only_when_reviews_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "reviews").mkdir()
    for index in (4, 0, 3, 1, 2):
        (folder / "reviews" / f"dem-{index}.md").write_bytes(b"---\n---\n")
    os.close(os.open(os.fsencode(folder / "reviews") + b"/dem-\xff.md", os.O_CREAT | os.O_WRONLY))
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_REVIEW_FILES", 2)
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert [head.name for head in read.reviews] == ["dem-0.md", "dem-1.md"]
    assert read.reviews_skipped == 4
    assert [name for name in reads.opened if name.startswith("dem-")] == ["dem-0.md", "dem-1.md"]


# AGH-139 AC-139.24: the agent outputs beside the records are never read as records.
LEGACY_RECORDS = {
    "features.json": b'{"acs": []}',
    "spec.md": b"---\nprocess_size: bounded\n---\n",
    "eval.md": b"Verdict: SHIP\n",
    "evals/dem-1.md": b"---\ntype: eval\ndelivery: dem-1\nverdict: SHIP\n---\n",
    "evals/dem-2.md": b"---\ntype: eval\ndelivery: dem-2\nverdict: NO-SHIP\n---\n",
    "evals/dem-3.md": b"---\n---\n",
    "reviews/DEM-1.md": b"---\ntype: review\noutcome: approved\n---\n",
    "reviews/DEM-2.md": b"---\n---\n",
}
AGENT_OUTPUTS = {
    "evals/dem-1.json": b'{"schema": "agent-hub/eval/1"}',
    "evals/dem-0.json": b"{}",
    "reviews/DEM-1/spec-r1.json": b'{"schema": "agent-hub/review/1"}',
    "reviews/DEM-1/quality-r1.json": b"{}",
    "reviews/DEM-3/spec-r1.json": b"{}",
}


def a_tree_feature(hub: Path, files: dict[str, bytes]) -> None:
    folder = features_of(hub) / "demo-feature"
    for name, content in files.items():
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)


def test_reads_same_folder_when_outputs_added(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Caps of two: the third record of each kind is skipped, and no output counts against them.
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_EVAL_FILES", 2)
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_REVIEW_FILES", 1)
    a_tree_feature(tmp_path / "legacy", LEGACY_RECORDS)
    a_tree_feature(tmp_path / "mixed", LEGACY_RECORDS | AGENT_OUTPUTS)

    legacy = read_feature_folder(tmp_path / "legacy", "demo-feature")
    mixed = read_feature_folder(tmp_path / "mixed", "demo-feature")

    assert mixed == legacy
    assert legacy is not None
    assert [head.name for head in legacy.evals] == ["dem-1.md", "dem-2.md"]
    assert [head.name for head in legacy.reviews] == ["DEM-1.md"]
    assert (legacy.evals_skipped, legacy.reviews_skipped) == (1, 1)
