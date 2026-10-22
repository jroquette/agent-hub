"""Each indexed document's links into the brain (AGH-393, D-links, AM-8): the destinations the
doctor's ``links.dead`` reads, resolved in the workspace, kept when the note route would serve
them, each once, at most ``MAX_LINKS_PER_DOCUMENT`` (AC-393.10)."""

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
