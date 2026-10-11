import json

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hubs.hub_document import json_pointer, read_hub_document
from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hub_fakes import hub_json_bytes

RUNNING = "4.5.6"


def test_reads_config_without_warning_when_pin_is_running_version() -> None:
    document = read_hub_document(hub_json_bytes(pin=RUNNING), running_version=RUNNING)

    assert isinstance(document.config, HubConfig)
    assert document.valid
    assert document.project == "demo"
    assert document.pin == RUNNING
    assert document.problems == ()
    assert document.warnings == ()


def test_reads_config_with_warning_when_pinned_to_other_version() -> None:
    document = read_hub_document(hub_json_bytes(pin="0.1.0"), running_version=RUNNING)

    assert document.valid
    assert document.pin == "0.1.0"
    assert document.warnings == (f"pinned 0.1.0, running {RUNNING}",)


def test_refuses_with_pointers_when_schema_invalid() -> None:
    raw = a_hub_document()
    raw["platform"]["version"] = RUNNING
    raw["repos"][0]["dir"] = 7
    raw["unknown"] = True

    document = read_hub_document(json.dumps(raw).encode(), running_version=RUNNING)

    assert not document.valid
    assert document.project == "demo"
    assert {problem.pointer for problem in document.problems} == {"/repos/0/dir", "/unknown"}


def test_refuses_at_root_when_json_invalid() -> None:
    document = read_hub_document(b"{", running_version=RUNNING)

    assert not document.valid
    assert document.project is None
    assert [problem.pointer for problem in document.problems] == [""]
    assert document.problems[0].message.startswith("not valid JSON")


def test_refuses_pin_when_pin_malformed() -> None:
    document = read_hub_document(hub_json_bytes(pin="latest"), running_version=RUNNING)

    assert not document.valid
    assert [problem.pointer for problem in document.problems] == ["/platform/version"]


def test_marks_missing_when_file_absent() -> None:
    unread = UnreadHubFile(message="cannot read: No such file or directory", is_missing=True)

    document = read_hub_document(unread, running_version=RUNNING)

    assert not document.valid
    assert document.is_missing
    assert document.problems[0].message == unread.message


@pytest.mark.parametrize(
    ("path", "pointer"),
    [
        ("$", ""),
        ("repos[0].dir", "/repos/0/dir"),
        ('doctor.rules["bench.tasks"]', "/doctor/rules/bench.tasks"),
        ('x["a/b~c"]', "/x/a~1b~0c"),
        ("modules.contract-sync", "/modules/contract-sync"),
    ],
)
def test_converts_json_path_when_pointer_built(path: str, pointer: str) -> None:
    assert json_pointer(path) == pointer
