"""The feature folder reader on real folders (plan F.6): bounded, no link followed."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from agent_hub.core.features.feature_evals import EVAL_HEAD_BYTES
from agent_hub.core.features.feature_reviews import REVIEW_HEAD_BYTES
from agent_hub.core.features.feature_status import (
    HEAD_BYTES,
    MAX_PLAN_BYTES,
    MAX_UX_FILES,
    UX_HEAD_BYTES,
    FeatureFolder,
    RecordHead,
)
from agent_hub.generator.feature_files import (
    FOLDER_COST_BYTES,
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
            plan=b"# Plan\n",
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
    (folder / "evals" / "acme-1521.md").write_bytes(b"---\nverdict: NO-SHIP\n---\n")
    (folder / "evals" / "acme-1520.md").write_bytes(b"x" * (EVAL_HEAD_BYTES + 10))
    (folder / "evals" / ".draft.md").write_bytes(b"hidden\n")
    (folder / "evals" / "notes.txt").write_bytes(b"not an eval\n")

    [read] = read_feature_folders(tmp_path)

    assert read.evals == (
        RecordHead(name="acme-1520.md", head=b"x" * EVAL_HEAD_BYTES, problem=None),
        RecordHead(name="acme-1521.md", head=b"---\nverdict: NO-SHIP\n---\n", problem=None),
    )
    assert (read.evals_skipped, read.reviews) == (0, ())
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

    assert (read.evals, read.evals_skipped, read.reviews) == ((), 0, ())


def test_reads_review_heads_when_reviews_present_reviews(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    (folder / "reviews").mkdir()
    (folder / "reviews" / "acme-1520.md").write_bytes(b"y" * (REVIEW_HEAD_BYTES + 1))
    (folder / "reviews" / "acme-1521.md").write_bytes(b"---\noutcome: approved\n---\n")
    (folder / "reviews" / "acme-1522.md").write_bytes(b"---\n---\n")
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_REVIEW_FILES", 2)

    [read] = read_feature_folders(tmp_path)

    assert read.reviews == (
        RecordHead(name="acme-1520.md", head=b"y" * REVIEW_HEAD_BYTES, problem=None),
        RecordHead(name="acme-1521.md", head=b"---\noutcome: approved\n---\n", problem=None),
    )
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
        {"research.md": b"r" * 100_000, "issues.md": b"i"},
    )
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.files == ("research.md", "issues.md")
    assert reads.bytes == 0


# AGH-325 (two-level-flows AC-1.2): brief.md is a record file, checked present and never read.
def test_lists_brief_when_only_present(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    a_feature(features_of(tmp_path), "demo-feature", {"brief.md": b"b" * 100})
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.files == ("brief.md",)
    assert reads.bytes == 0


# AGH-325 (two-level-flows AC-1.3, P2): the folder's own ux-*.md heads, at most 50, 4 KiB each.
def test_reads_ux_design_heads_when_designs_present(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(
        features_of(tmp_path),
        "demo-feature",
        {"ux-b.md": b"---\nstatus: draft\n---\n", "ux-a.md": b"u" * (UX_HEAD_BYTES + 10)},
    )
    (folder / "sub").mkdir()
    (folder / "sub" / "ux-c.md").write_bytes(b"---\nstatus: approved\n---\n")
    (folder / "ux-notes.txt").write_bytes(b"not a design\n")
    (folder / ".ux-hidden.md").write_bytes(b"hidden\n")
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.ux_designs == (
        RecordHead(name="ux-a.md", head=b"u" * UX_HEAD_BYTES, problem=None),
        RecordHead(name="ux-b.md", head=b"---\nstatus: draft\n---\n", problem=None),
    )
    assert read.ux_skipped == 0
    assert reads.bytes == UX_HEAD_BYTES + len(b"---\nstatus: draft\n---\n")
    assert UX_HEAD_BYTES == 4096


def test_counts_ux_design_skipped_when_over_cap(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    for index in range(MAX_UX_FILES + 1):
        (folder / f"ux-{index:02}.md").write_bytes(b"---\n---\n")

    [read] = read_feature_folders(tmp_path)

    assert len(read.ux_designs) == MAX_UX_FILES
    assert read.ux_designs[-1].name == "ux-49.md"
    assert read.ux_skipped == 1
    assert MAX_UX_FILES == 50


def test_lists_ux_design_problem_when_linked(tmp_path: Path) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    secret = tmp_path / "secret.md"
    secret.write_bytes(b"---\nstatus: approved\n---\n")
    (folder / "ux-linked.md").symlink_to(secret)

    [read] = read_feature_folders(tmp_path)

    assert read.ux_designs == (
        RecordHead(name="ux-linked.md", head=None, problem="not a regular file"),
    )


# AGH-323 (two-level-flows P1): plan.md is read whole up to MAX_PLAN_BYTES, amendments included.
def test_reads_plan_whole_when_under_its_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = features_of(tmp_path)
    a_feature(features, "fits", {"plan.md": b"p" * 102_400})
    a_feature(features, "over", {"plan.md": b"q" * (MAX_PLAN_BYTES + 1)})
    reads = Reads(monkeypatch)

    fits, over = read_feature_folders(tmp_path)

    assert (fits.plan, fits.plan_too_large) == (b"p" * 102_400, False)
    assert (over.plan, over.plan_too_large) == (None, True)
    assert "plan.md" in fits.files
    assert "plan.md" in over.files
    assert reads.bytes == 102_400 + MAX_PLAN_BYTES + 1


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

    assert legacy is not None
    assert mixed is not None
    # The round names are listed (AGH-326), never read; every record is the same.
    assert mixed.review_rounds == (
        "DEM-1/quality-r1.json",
        "DEM-1/spec-r1.json",
        "DEM-3/spec-r1.json",
    )
    assert replace(mixed, review_rounds=()) == legacy
    assert [head.name for head in legacy.evals] == ["dem-1.md", "dem-2.md"]
    assert [head.name for head in legacy.reviews] == ["DEM-1.md"]
    assert legacy.evals_skipped == 1


# AGH-326 (two-level-flows AC-1.8, P3): the review round names of each ticket, never their bytes.
def test_lists_review_round_names_when_ticket_folders_hold_rounds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    reviews = folder / "reviews"
    for name in ("spec-r1.json", "quality-r1.json", "notes.txt", "spec-r01.json", "lint-r1.json"):
        (reviews / "AGH-1").mkdir(parents=True, exist_ok=True)
        (reviews / "AGH-1" / name).write_bytes(b"{}")
    (reviews / "AGH-1" / "spec-r2.json").mkdir()
    (reviews / "AGH-1" / "quality-r2.json").symlink_to(reviews / "AGH-1" / "spec-r1.json")
    (reviews / "AGH-1.md").write_bytes(b"---\n---\n")
    (reviews / ".hidden").mkdir()
    (reviews / ".hidden" / "spec-r1.json").write_bytes(b"{}")
    (reviews / "AGH-2").symlink_to(reviews / "AGH-1")
    (reviews / "spec-r3.json").write_bytes(b"{}")
    odd = os.fsencode(reviews) + b"/AGH-\xff"
    os.mkdir(odd)
    os.close(os.open(odd + b"/spec-r1.json", os.O_CREAT | os.O_WRONLY))
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.review_rounds == ("AGH-1/quality-r1.json", "AGH-1/spec-r1.json")
    assert {"spec-r1.json", "quality-r1.json"}.isdisjoint(reads.opened)


def test_opens_first_ticket_folders_only_when_rounds_over_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    folder = a_feature(features_of(tmp_path), "demo-feature", {})
    for ticket in ("AGH-4", "AGH-1", "AGH-3", "AGH-2"):
        (folder / "reviews" / ticket).mkdir(parents=True)
        for name in ("spec-r1.json", "quality-r1.json"):
            (folder / "reviews" / ticket / name).write_bytes(b"{}")
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_ROUND_TICKETS", 3)
    monkeypatch.setattr("agent_hub.generator.feature_files.MAX_ROUND_NAMES", 3)
    reads = Reads(monkeypatch)

    [read] = read_feature_folders(tmp_path)

    assert read.review_rounds == (
        "AGH-1/quality-r1.json",
        "AGH-1/spec-r1.json",
        "AGH-2/quality-r1.json",
    )
    assert [name for name in reads.opened if name.startswith("AGH-")] == ["AGH-1", "AGH-2"]


def test_lists_folders_unread_when_ticket_folders_spend_read_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    features = features_of(tmp_path)
    alpha = a_feature(features, "alpha", {})
    for ticket in ("AGH-1", "AGH-2"):
        (alpha / "reviews" / ticket).mkdir(parents=True)
    a_feature(features, "beta", {"spec.md": b"b"})
    monkeypatch.setattr(
        "agent_hub.generator.feature_files.READ_BUDGET_BYTES", 2 * FOLDER_COST_BYTES
    )

    _, beta = read_feature_folders(tmp_path)

    assert beta == FeatureFolder(slug="beta", files=(), features_json=OVER_BUDGET)
