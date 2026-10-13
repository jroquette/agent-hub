from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader

HUB = "/home/demo/demo-hub"


def a_reader() -> FakeHubFileReader:
    hub = FakeHub(
        brain={
            "index.md": b"# Index\n",
            "decisions/index.md": b"# Decisions\n",
            "auto/workspace/me.md": b"personal",
            ".obsidian/x.md": b"hidden",
            "notes.txt": b"not markdown",
            "linked.md": b"# Linked\n",
        },
        brain_links=frozenset({"linked.md"}),
    )
    return FakeHubFileReader({HUB: hub})


def test_lists_markdown_when_brain_tree_read() -> None:
    listing = a_reader().brain_tree(HUB)

    assert listing.entries == (
        BrainEntry(path="decisions/index.md", size=12),
        BrainEntry(path="index.md", size=8),
    )


def test_lists_top_folders_when_brain_folders_read() -> None:
    hub = FakeHub(
        brain={
            "index.md": b"#",
            "decisions/index.md": b"#",
            "playbooks/deep/x.md": b"#",
            "Auto/me.md": b"#",
            ".obsidian/x.md": b"#",
            "linked/x.md": b"#",
        },
        brain_links=frozenset({"linked/x.md"}),
    )

    folders = FakeHubFileReader({HUB: hub}).brain_folders(HUB)

    assert folders == ("decisions", "playbooks")


def test_reads_note_when_brain_file_regular() -> None:
    assert a_reader().read_brain_file(HUB, "index.md", max_bytes=100) == b"# Index\n"


def test_reports_kind_when_brain_file_unreadable() -> None:
    reader = a_reader()

    link = reader.read_brain_file(HUB, "linked.md", max_bytes=100)
    large = reader.read_brain_file(HUB, "index.md", max_bytes=4)
    missing = reader.read_brain_file(HUB, "absent.md", max_bytes=100)

    assert [getattr(read, "kind", None) for read in (link, large, missing)] == [
        "not_regular",
        "too_large",
        "missing",
    ]


def test_sizes_file_when_brain_file_regular() -> None:
    reader = a_reader()

    assert reader.brain_file_size(HUB, "index.md") == 8
    assert reader.brain_file_size(HUB, "linked.md") is None
    assert reader.brain_file_size(HUB, "absent.md") is None


def test_records_feature_reads_when_folders_listed_or_read() -> None:
    folder = FeatureFolder(slug="demo-feature", files=())
    reader = FakeHubFileReader({"/hubs/demo": FakeHub(features=(folder,))})

    assert reader.feature_folders("/hubs/demo") == (folder,)
    assert reader.feature_folder("/hubs/demo", "demo-feature") == folder
    assert reader.feature_folder("/hubs/demo", "nope") is None
    assert reader.feature_reads == [
        ("*", "/hubs/demo"),
        ("demo-feature", "/hubs/demo"),
        ("nope", "/hubs/demo"),
    ]
