"""What a listed file becomes in the knowledge index (AGH-391, D-kind, D-meta, D-files,
D-secret): its kind, title, frontmatter, and whether it is indexed or skipped and why."""

import hashlib

import pytest

from agent_hub.core.knowledge.document_rules import (
    MAX_DOCUMENT_BYTES,
    MAX_LISTED_FILES,
    MAX_LISTING_BYTES,
    MAX_META_CHARS,
    NOT_UTF8,
    RULE_MATCH,
    TOO_LARGE,
    document_from,
    document_meta,
    is_indexed_name,
    kind_of,
)
from agent_hub.core.knowledge.knowledge_index import (
    INDEX_VERSION,
    KINDS,
    Fingerprint,
    IndexedDocument,
    Kind,
    SkippedFile,
)
from agent_hub.core.knowledge.search_query import MAX_RESULTS, MAX_SNIPPET_CHARS


def test_states_bounds_when_constants_read() -> None:
    assert MAX_DOCUMENT_BYTES == 262_144
    assert MAX_META_CHARS == 200
    assert MAX_LISTED_FILES == 20_000
    assert MAX_LISTING_BYTES == 64 * 1024 * 1024
    assert INDEX_VERSION == 1
    assert MAX_RESULTS == 50
    assert MAX_SNIPPET_CHARS == 160
    assert len(KINDS) == 10
    assert (RULE_MATCH, TOO_LARGE, NOT_UTF8) == (
        "matches a secret rule",
        "larger than 256 KiB",
        "not UTF-8",
    )


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("brain/decisions/0001-worktrees.md", "decision"),
        ("brain/domain/x.md", "domain"),
        ("brain/learnings/gotchas/x.md", "learning"),
        ("brain/playbooks/x.md", "playbook"),
        ("brain/system/x.md", "system"),
        ("brain/_inbox/x.md", "inbox"),
        ("brain/features/x/spec.md", "feature"),
        ("brain/journal/2026/10/x.md", "journal"),
        ("demo-api/docs/adr/x.md", "adr"),
        ("demo-api/docs/guide.md", "doc"),
        ("demo-api/docs/design/x.md", "doc"),
    ],
)
def test_names_kind_when_path_in_kind_folder(path: str, kind: Kind) -> None:
    assert kind_of(path) == kind


@pytest.mark.parametrize(
    "path",
    ["brain/now.md", "brain/index.md", "brain/workflow/x.md", "brain/decisions.md"],
)
def test_names_doc_kind_when_brain_file_outside_kind_folders(path: str) -> None:
    assert kind_of(path) == "doc"


@pytest.mark.parametrize(
    "path",
    [
        "brain/x.txt",
        "brain/s.jsonl",
        "brain/auto/workspace/me.md",
        "brain/AUTO/x.md",
        "brain/notes.MD",
        "brain/.md",
    ],
)
def test_refuses_path_when_not_markdown_or_personal(path: str) -> None:
    assert not is_indexed_name(path)


@pytest.mark.parametrize(
    "path", ["brain/now.md", "brain/automation/x.md", "demo-api/docs/auto/x.md"]
)
def test_accepts_path_when_markdown_outside_personal_folder(path: str) -> None:
    assert is_indexed_name(path)


def test_reads_title_and_frontmatter_when_note_has_both() -> None:
    text = '---\nstatus: "draft"\nprovenance: agent\nsources: [a, b]\n---\n## Plan\n\nThe body.\n'

    meta = document_meta(text, "plan.md")

    assert (meta.title, meta.status, meta.provenance) == ("Plan", "draft", "agent")
    assert meta.body == "## Plan\n\nThe body.\n"


@pytest.mark.parametrize(
    ("name", "text", "title"),
    [
        ("notes.md", "Just text, no heading.\n", "notes.md"),
        ("notes.md", "#hashtag is not a heading\n", "notes.md"),
    ],
)
def test_uses_file_name_as_title_when_note_has_no_heading(name: str, text: str, title: str) -> None:
    meta = document_meta(text, name)

    assert meta.title == title
    assert (meta.status, meta.provenance) == (None, None)
    assert meta.body == text


@pytest.mark.parametrize(
    ("name", "text", "title"),
    [
        ("x.md", "# Title\n\nText.\n", "Title"),
        ("x.md", "Intro line.\n\n###   Deep heading ##\n", "Deep heading"),
    ],
)
def test_reads_title_from_first_heading_when_note_has_one(name: str, text: str, title: str) -> None:
    meta = document_meta(text, name)

    assert meta.title == title
    assert (meta.status, meta.provenance) == (None, None)
    assert meta.body == text


def test_reads_frontmatter_and_title_when_note_starts_with_byte_order_mark() -> None:
    meta = document_meta("\ufeff---\nstatus: draft\n---\n# T\n", "bom.md")

    assert (meta.title, meta.status) == ("T", "draft")
    assert meta.body == "# T\n"


def test_reads_title_when_note_starts_with_byte_order_mark_and_heading() -> None:
    meta = document_meta("\ufeff# Title\n", "bom.md")

    assert meta.title == "Title"
    assert meta.body == "# Title\n"


def test_ignores_frontmatter_when_block_not_at_start() -> None:
    text = "Intro.\n---\nstatus: draft\nprovenance: agent\n---\n# Late\n"

    meta = document_meta(text, "late.md")

    assert (meta.title, meta.status, meta.provenance) == ("Late", None, None)
    assert meta.body == text


def test_ignores_frontmatter_value_when_not_text() -> None:
    meta = document_meta("---\nstatus: [a, b]\nprovenance:\n---\nBody.\n", "x.md")

    assert (meta.status, meta.provenance) == (None, None)


def test_cuts_title_when_longer_than_limit() -> None:
    long = "a" * 300
    text = f"---\nstatus: {long}\nprovenance: {long}\n---\n# {long}\n"

    meta = document_meta(text, "long.md")

    assert meta.title == "a" * MAX_META_CHARS
    assert meta.status == "a" * MAX_META_CHARS
    assert meta.provenance == "a" * MAX_META_CHARS


def _token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def _fingerprint(data: bytes) -> Fingerprint:
    return Fingerprint(size=len(data), mtime_ns=1_700_000_000_000_000_000)


def test_builds_document_when_file_eligible() -> None:
    data = b"---\nstatus: accepted\n---\n# Worktrees from origin\n\nUse worktrees.\n"
    path = "brain/decisions/0001-worktrees.md"

    document = document_from(path, data, _fingerprint(data))

    assert document == IndexedDocument(
        path=path,
        kind="decision",
        title="Worktrees from origin",
        status="accepted",
        provenance=None,
        fingerprint=_fingerprint(data),
        sha256=hashlib.sha256(data).hexdigest(),
        body="# Worktrees from origin\n\nUse worktrees.\n",
    )


def test_skips_file_when_secret_rule_matches() -> None:
    data = f"marker\nUse {_token()} to push.\n".encode()
    path = "brain/_inbox/leak.md"

    skipped = document_from(path, data, _fingerprint(data))

    assert skipped == SkippedFile(path=path, fingerprint=_fingerprint(data), reason=RULE_MATCH)
    assert _token() not in repr(skipped)


def test_skips_file_when_not_utf8() -> None:
    data = b"marker \xe9"

    skipped = document_from("brain/latin.md", data, _fingerprint(data))

    assert skipped == SkippedFile(
        path="brain/latin.md", fingerprint=_fingerprint(data), reason=NOT_UTF8
    )


def test_skips_file_when_larger_than_limit() -> None:
    exact = b"marker " + b"x" * (MAX_DOCUMENT_BYTES - len(b"marker "))
    over = exact + b"x"

    indexed = document_from("brain/exact.md", exact, _fingerprint(exact))
    skipped = document_from("brain/big.md", over, _fingerprint(over))

    assert isinstance(indexed, IndexedDocument)
    assert len(indexed.body) == MAX_DOCUMENT_BYTES
    assert skipped == SkippedFile(
        path="brain/big.md", fingerprint=_fingerprint(over), reason=TOO_LARGE
    )


def test_reads_title_in_linear_time_when_heading_holds_long_space_run() -> None:
    # A backtracking heading pattern takes minutes on this line; the bound is the file's size.
    line = "# a" + " " * (MAX_DOCUMENT_BYTES - 8) + "b ##"

    meta = document_meta(line, "spaces.md")

    assert meta.title == "a" + " " * (MAX_META_CHARS - 1)
