"""What a listed file becomes in the knowledge index (AGH-391, D-kind, D-meta, D-files,
D-secret): its kind, title, frontmatter, and whether it is indexed or skipped and why."""

import pytest

from agent_hub.core.knowledge.document_rules import (
    MAX_DOCUMENT_BYTES,
    MAX_LISTED_FILES,
    MAX_LISTING_BYTES,
    MAX_META_CHARS,
    NOT_UTF8,
    RULE_MATCH,
    TOO_LARGE,
    is_indexed_name,
    kind_of,
)
from agent_hub.core.knowledge.knowledge_index import INDEX_VERSION, KINDS, Kind
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
