"""The control plane's hub file reader on a real hub folder (plan F.7 wiring)."""

import json
import os
from pathlib import Path

import pytest

from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, select_rules
from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadHubFile
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.registered_hub_files import MAX_HUB_JSON_BYTES, HubFileSystem

RUNNING = "4.5.6"


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    root = tmp_path / "demo-hub"
    (root / "brain" / "features" / "demo-feature").mkdir(parents=True)
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    document["project"].pop("branch_prefix", None)
    document["project"]["author_email"] = "dev@example.com"
    (root / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    (root / "brain" / "now.md").write_text("- **Focus:** demo\n", encoding="utf-8")
    (root / "brain" / "features" / "demo-feature" / "spec.md").write_text("# Spec\n")
    checkout = tmp_path / "demo-api"
    checkout.mkdir()
    (checkout / "AGENTS.md").write_text("one\ntwo\nthree\n", encoding="utf-8")
    return root


def test_implements_reader_port_when_built() -> None:
    reader: HubFileReader = HubFileSystem()

    assert reader.resolve(".") == os.path.realpath(".")


def test_resolves_link_when_path_is_link(hub: Path, tmp_path: Path) -> None:
    link = tmp_path / "link-to-hub"
    link.symlink_to(hub)

    assert HubFileSystem().resolve(str(link)) == str(hub.resolve())


def test_reads_hub_files_when_present(hub: Path) -> None:
    reader = HubFileSystem()
    path = str(hub)

    assert reader.read_hub_json(path) == (hub / "hub.json").read_bytes()
    assert reader.read_lock(path) == LockAbsent()
    assert reader.read_local(path) == LocalConfig()
    assert reader.read_now(path) == b"- **Focus:** demo\n"
    assert reader.agents_md_lines(path, "demo-api") == 3
    assert reader.agents_md_lines(path, "demo-web") is None
    [folder] = reader.feature_folders(path)
    assert (folder.slug, folder.files) == ("demo-feature", ("spec.md",))


def test_reports_missing_when_hub_json_absent(tmp_path: Path) -> None:
    read = HubFileSystem().read_hub_json(str(tmp_path))

    assert isinstance(read, UnreadHubFile)
    assert read.is_missing
    assert read.message.startswith(f"cannot read {json.dumps(str(tmp_path / 'hub.json'))}")


def test_reports_unread_when_hub_json_larger_than_cap(tmp_path: Path) -> None:
    (tmp_path / "hub.json").write_bytes(b" " * (MAX_HUB_JSON_BYTES + 1))

    read = HubFileSystem().read_hub_json(str(tmp_path))

    assert isinstance(read, UnreadHubFile)
    assert not read.is_missing
    assert read.message.endswith(f"larger than {MAX_HUB_JSON_BYTES} bytes")


def test_gives_times_of_present_paths_when_asked(hub: Path) -> None:
    times = HubFileSystem().modified_times(str(hub), ["hub.json", "nope.md"])

    assert times == (os.stat(hub / "hub.json").st_mtime_ns, None)


def test_builds_snapshot_with_file_prefix_when_git_not_injected(hub: Path) -> None:
    config = HubConfig.model_validate(json.loads((hub / "hub.json").read_bytes()))
    selection = select_rules(REGISTRY, config=config, only=())
    assert isinstance(selection, Selection)

    snapshot = HubFileSystem().doctor_snapshot(
        str(hub),
        config=config,
        running_version=RUNNING,
        selection=selection,
        local=LocalConfig(),
    )

    assert snapshot.branch_prefix is not None
    assert snapshot.branch_prefix.value == "dev/"
    assert [repo.dir for repo in snapshot.repos] == ["demo-api"]


def test_reads_brain_note_when_hub_registered(hub: Path) -> None:
    (hub / "brain" / "auto").mkdir()
    (hub / "brain" / "auto" / "me.md").write_text("personal\n", encoding="utf-8")
    reader: HubFileReader = HubFileSystem()
    hub_path = reader.resolve(str(hub))

    listing = reader.brain_tree(hub_path)
    note = reader.read_brain_file(hub_path, "now.md", max_bytes=1024)
    personal = reader.read_brain_file(hub_path, "auto/me.md", max_bytes=1024)

    assert [entry.path for entry in listing.entries] == ["features/demo-feature/spec.md", "now.md"]
    assert note == b"- **Focus:** demo\n"
    assert reader.brain_file_size(hub_path, "now.md") == len(b"- **Focus:** demo\n")
    assert isinstance(personal, UnreadHubFile)
    assert personal.is_missing
    assert reader.brain_file_size(hub_path, "auto/me.md") is None
