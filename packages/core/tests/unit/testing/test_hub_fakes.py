from agent_hub.core.brain.brain_note import BrainEntry
from agent_hub.core.doctor.item_leftovers_rule import ITEM_LEFTOVERS
from agent_hub.core.doctor.run_rules import Selection
from agent_hub.core.features.feature_status import FeatureFolder
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
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
    assert reader.feature_folder("/hubs/demo", "nope", tickets=True) is None
    assert reader.ticket_reads == ["nope"]
    assert reader.feature_reads == [
        ("*", "/hubs/demo"),
        ("demo-feature", "/hubs/demo"),
        ("nope", "/hubs/demo"),
    ]


def test_gives_item_leftovers_only_when_rule_selected() -> None:
    hub = FakeHub(
        item_folders=("plugin/demo/skills",),
        item_leftovers=("plugin/demo/skills/.a.hub-tmp-0123abcd",),
    )
    reader = FakeHubFileReader({"/hubs/demo": hub})
    config = HubConfig.model_validate(a_hub_document())

    def snapshot(selection: Selection) -> tuple[object, object]:
        found = reader.doctor_snapshot(
            "/hubs/demo",
            config=config,
            running_version="0.1.0",
            selection=selection,
            local=LocalConfig(),
        )
        return found.item_leftovers, found.item_folders

    selected = Selection(rules=(ITEM_LEFTOVERS,), notes=(), severities={})
    assert snapshot(Selection(rules=(), notes=(), severities={})) == (None, ())
    assert snapshot(selected) == (hub.item_leftovers, hub.item_folders)
