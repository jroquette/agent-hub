from collections.abc import Callable

import pytest

from agent_hub.core.doctor.snapshot import (
    ConfigFailure,
    DoctorSnapshot,
    PinMismatch,
    hub_paths,
    lines_of,
    text_of,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.tree_snapshot import (
    FileEntry,
    FolderEntry,
    LinkEntry,
    OtherEntry,
    TreeEntry,
)
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]


def test_reads_config_when_snapshot_config_valid(snapshot_of: SnapshotFactory) -> None:
    config = HubConfig.model_validate(a_hub_document())

    assert snapshot_of(config=config).hub_config is config


@pytest.mark.parametrize(
    "failure",
    [
        pytest.param(
            ConfigFailure(problems=(ConfigProblem("$", "invalid JSON"),), pin=None), id="problems"
        ),
        pytest.param(
            ConfigFailure(
                problems=(), pin=PinMismatch(pinned="0.0.1", running="0.2.0", command=None)
            ),
            id="pin",
        ),
    ],
)
def test_raises_when_rule_reads_config_of_failed_snapshot(
    snapshot_of: SnapshotFactory, failure: ConfigFailure
) -> None:
    snapshot = snapshot_of(config=failure)

    assert snapshot.config is failure
    with pytest.raises(ValueError, match="hub.json is not valid"):
        _ = snapshot.hub_config


def test_lists_fixed_paths_when_project_named() -> None:
    config = HubConfig.model_validate(a_hub_document())

    assert config.project.name == "demo"
    assert hub_paths(config) == (
        "hub.lock",
        ".claude/settings.json",
        ".claude/settings.project.json",
        ".mcp.json",
        "Makefile",
        "Makefile.project",
        "package.json",
        "plugin/demo/hooks/project_guard.py",
    )


def test_names_project_plugin_when_project_renamed() -> None:
    document = a_hub_document()
    document["project"]["name"] = "other-project"

    paths = hub_paths(HubConfig.model_validate(document))

    assert paths[-1] == "plugin/other-project/hooks/project_guard.py"


@pytest.mark.parametrize(
    ("entry", "text"),
    [
        pytest.param(FileEntry(executable=False, content="é ok\n".encode()), "é ok\n", id="utf8"),
        pytest.param(FileEntry(executable=True, content=b""), "", id="empty-executable"),
        pytest.param(FileEntry(executable=False, content=b"\xff\xfe"), None, id="not-utf8"),
        pytest.param(FileEntry(executable=False, content=b"a\x00b"), None, id="nul"),
        pytest.param(LinkEntry(target="AGENTS.md", outside=False), None, id="link"),
        pytest.param(FileEntry(executable=False, content=None), None, id="no-content"),
        pytest.param(FolderEntry(), None, id="folder"),
        pytest.param(OtherEntry(kind="fifo"), None, id="fifo"),
        pytest.param(None, None, id="absent"),
    ],
)
def test_reads_text_when_file_is_utf8(entry: TreeEntry | None, text: str | None) -> None:
    assert text_of(entry) == text


@pytest.mark.parametrize(
    ("text", "lines"),
    [
        pytest.param("a b\nc", ("a b", "c"), id="line-separator"),
        pytest.param("a\x85b\x0cc\rd\n", ("a\x85b\x0cc\rd",), id="other-breaks"),
        pytest.param("a\n\nb\n", ("a", "", "b"), id="blank-line"),
        pytest.param("a", ("a",), id="no-final-newline"),
        pytest.param("\n", ("",), id="one-empty-line"),
        pytest.param("", (), id="empty"),
    ],
)
def test_splits_on_newline_only_when_lines_read(text: str, lines: tuple[str, ...]) -> None:
    assert lines_of(text) == lines
