"""Each indexed document's links into the brain (AGH-393, D-links, AM-8): the destinations the
doctor's ``links.dead`` reads, resolved in the workspace, kept when the note route would serve
them, each once, at most ``MAX_LINKS_PER_DOCUMENT`` (AC-393.10)."""

from collections.abc import Iterator
from typing import SupportsIndex, overload

from agent_hub.core.knowledge import document_links as links_module
from agent_hub.core.knowledge.document_links import MAX_LINKS_PER_DOCUMENT, document_links

HUB_FOLDER = "demo-hub"
NOTE = "brain/playbooks/cleanup.md"


def test_keeps_only_brain_targets_when_links_mixed() -> None:
    text = "\n".join(
        [
            "---",
            "status: accepted",
            "---",
            "# Cleanup",
            "",
            "Why: [a](../decisions/x.md#why) and [again](../decisions/x.md).",
            "[b]: <x%20y.md>",
            "![map](../system/map.md)",
            "```",
            "[fenced](fenced.md)",
            "```",
            "A span `[c](span.md)` and <!-- [h](comment.md) --> here.",
            "[w](https://example.com/web.md) [abs](/abs.md) [top](#top)",
            "[me](../auto/workspace/me.md) [txt](notes.txt) [self](cleanup.md)",
            "[out](../../../../out.md)",
            "",
        ]
    )

    links = document_links(NOTE, text, hub_folder=HUB_FOLDER)

    assert links == ("brain/decisions/x.md", "brain/playbooks/x y.md", "brain/system/map.md")


def test_resolves_repo_doc_link_into_hub_when_climbing_workspace() -> None:
    text = (
        "[now](../../demo-hub/brain/now.md)\n"
        "[theirs](../../other-hub/brain/now.md)\n"
        "[sibling](other.md)\n"
    )

    links = document_links("demo-api/docs/guide.md", text, hub_folder=HUB_FOLDER)

    assert links == ("brain/now.md",)


def test_keeps_first_thousand_targets_when_more_given() -> None:
    text = "".join(f"[n{number}](t{number}.md)\n" for number in range(1_001))

    links = document_links(NOTE, text, hub_folder=HUB_FOLDER)

    assert MAX_LINKS_PER_DOCUMENT == 1_000
    assert links == tuple(f"brain/playbooks/t{number}.md" for number in range(1_000))


def test_drops_target_when_note_route_refuses() -> None:
    deepest = "/".join(f"f{depth}" for depth in range(15)) + "/x.md"
    too_deep = "f15/" + deepest
    longest = "a" * 509 + ".md"
    too_long = "a" + longest
    text = (
        "[hidden](.hidden/x.md) [personal](Auto/x.md) [bare](.md)\n"
        f"[deep]({too_deep}) [long]({too_long})\n"
        f"[deepest]({deepest}) [longest]({longest})\n"
    )

    links = document_links("brain/now.md", text, hub_folder=HUB_FOLDER)

    assert len(deepest.split("/")) == 16
    assert len(longest) == 512
    assert links == (f"brain/{deepest}", f"brain/{longest}")


def test_drops_target_when_link_leaves_workspace_and_returns() -> None:
    text = "[back](../../../../demo-hub/brain/x.md) [in](../../../demo-hub/brain/x.md)\n"

    links = document_links(NOTE, text, hub_folder=HUB_FOLDER)

    assert links == ("brain/x.md",)


def test_keeps_target_when_destination_has_query() -> None:
    text = "[raw](../now.md?view=raw#top)\n"

    links = document_links(NOTE, text, hub_folder=HUB_FOLDER)

    assert links == ("brain/now.md",)


class _CountingFolder(list[str]):
    """A folder's segments that count how many of them are read, however they are read."""

    def __init__(self, segments: list[str]) -> None:
        super().__init__(segments)
        self.reads = 0

    def __iter__(self) -> Iterator[str]:
        self.reads += len(self)
        return super().__iter__()

    @overload
    def __getitem__(self, index: SupportsIndex, /) -> str: ...

    @overload
    def __getitem__(self, index: slice, /) -> list[str]: ...

    def __getitem__(self, index: SupportsIndex | slice, /) -> str | list[str]:
        found = super().__getitem__(index)
        self.reads += len(found) if isinstance(found, list) else 1
        return found


def test_reads_no_folder_segment_when_target_too_deep_or_climbing_out() -> None:
    depth = 10_000
    folder = _CountingFolder([HUB_FOLDER, "brain", *(f"f{number}" for number in range(depth))])

    deep = [links_module._brain_target(folder, "x.md", HUB_FOLDER) for _ in range(1_000)]
    out = links_module._brain_target(folder, "../" * (depth + 3) + "x.md", HUB_FOLDER)

    assert deep == [None] * 1_000
    assert out is None
    assert folder.reads == 0
    shallow = _CountingFolder([HUB_FOLDER, "brain", "playbooks"])
    assert links_module._brain_target(shallow, "../now.md", HUB_FOLDER) == "brain/now.md"
    assert shallow.reads == 2
