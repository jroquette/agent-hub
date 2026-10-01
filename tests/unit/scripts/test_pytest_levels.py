import re
import socket

import pytest
import pytest_socket

from scripts.pytest_levels import level_of, pytest_collection_modifyitems


@pytest.mark.parametrize(
    ("path", "level"),
    [
        ("packages/core/tests/unit/x/test_a.py", "unit"),
        ("packages/storage/tests/integration/test_m.py", "integration"),
        ("tests/e2e/test_hub_cli.py", "e2e"),
        ("packages/core/tests/contract/test_c.py", "contract"),
    ],
)
def test_returns_level_when_path_is_under_tests_level_folder(path: str, level: str) -> None:
    assert level_of(path) == level


def test_returns_none_when_level_folder_is_outside_tests() -> None:
    assert level_of("/home/unit/repo/packages/core/tests/test_a.py") is None


# pytest-socket warns before raising; the raise is what this test checks.
@pytest.mark.filterwarnings("ignore:A test tried to use socket.socket")
def test_blocks_socket_when_test_is_unit_level() -> None:
    with pytest.raises(pytest_socket.SocketBlockedError):
        socket.socket()


LIVE_VARIABLES = {
    "LINEAR_API_KEY": "lin_api_secret_value",
    "AGENT_HUB_LIVE": "1",
    "AGENT_HUB_LIVE_ISSUE": "AGH-1",
    "AGENT_HUB_LIVE_LABEL": "agent-ready",
}


class _FakeItem:
    """The slice of ``pytest.Item`` the plugin uses: its path and its markers."""

    def __init__(self, path: str, *names: str) -> None:
        self.path = path
        self.markers = [getattr(pytest.mark, name).mark for name in names]

    def get_closest_marker(self, name: str) -> pytest.Mark | None:
        return next((mark for mark in self.markers if mark.name == name), None)

    def add_marker(self, marker: pytest.MarkDecorator) -> None:
        self.markers.append(marker.mark)


def _set_live_variables(monkeypatch: pytest.MonkeyPatch, **overrides: str | None) -> None:
    for name, value in {**LIVE_VARIABLES, **overrides}.items():
        if value is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, value)


def _names(reason: str, variable: str) -> bool:
    return re.search(rf"\b{variable}\b", reason) is not None


def _skip_reasons(item: _FakeItem) -> list[str]:
    return [mark.kwargs["reason"] for mark in item.markers if mark.name == "skip"]


def _collect(item: _FakeItem) -> None:
    pytest_collection_modifyitems([item])  # type: ignore[list-item]


@pytest.mark.parametrize("missing", list(LIVE_VARIABLES))
def test_skips_live_test_naming_variable_when_variable_missing(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    _set_live_variables(monkeypatch, **{missing: None})
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py", "live")

    _collect(item)

    reasons = _skip_reasons(item)
    assert len(reasons) == 1
    assert _names(reasons[0], missing)
    assert not any(value in reasons[0] for value in LIVE_VARIABLES.values() if len(value) > 1)


def test_names_first_missing_variable_when_several_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _set_live_variables(monkeypatch, LINEAR_API_KEY=None, AGENT_HUB_LIVE_LABEL=None)
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py", "live")

    _collect(item)

    assert _names(_skip_reasons(item)[0], "LINEAR_API_KEY")
    assert not _names(_skip_reasons(item)[0], "AGENT_HUB_LIVE_LABEL")


def test_skips_live_test_when_live_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch, AGENT_HUB_LIVE="0")
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py", "live")

    _collect(item)

    reasons = _skip_reasons(item)
    assert len(reasons) == 1
    assert _names(reasons[0], "AGENT_HUB_LIVE")


def test_runs_live_test_when_every_variable_set(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch)
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py", "live")

    _collect(item)

    assert _skip_reasons(item) == []


def test_leaves_skip_off_when_test_not_live(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch, **dict.fromkeys(LIVE_VARIABLES))
    item = _FakeItem("packages/tracker_linear/tests/integration/test_graphql.py")

    _collect(item)

    assert _skip_reasons(item) == []


def _mcp_live_item() -> _FakeItem:
    item = _FakeItem("packages/tracker_linear/tests/integration/test_mcp_live.py")
    item.markers.append(pytest.mark.live("mcp").mark)
    return item


def test_needs_no_key_when_mcp_live_marked(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch, LINEAR_API_KEY=None)
    item = _mcp_live_item()

    _collect(item)

    assert _skip_reasons(item) == []


def test_needs_key_when_live_marked_bare(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch, LINEAR_API_KEY=None)
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py", "live")

    _collect(item)

    [reason] = _skip_reasons(item)
    assert _names(reason, "LINEAR_API_KEY")


@pytest.mark.parametrize(
    ("missing", "first"),
    [
        (("AGENT_HUB_LIVE",), "AGENT_HUB_LIVE"),
        (("AGENT_HUB_LIVE_ISSUE", "AGENT_HUB_LIVE_LABEL"), "AGENT_HUB_LIVE_ISSUE"),
        (("AGENT_HUB_LIVE_LABEL",), "AGENT_HUB_LIVE_LABEL"),
    ],
    ids=["switch", "issue-and-label", "label"],
)
def test_names_first_missing_variable_when_mcp_live_skipped(
    monkeypatch: pytest.MonkeyPatch, *, missing: tuple[str, ...], first: str
) -> None:
    _set_live_variables(monkeypatch, LINEAR_API_KEY=None, **dict.fromkeys(missing))
    item = _mcp_live_item()

    _collect(item)

    [reason] = _skip_reasons(item)
    assert _names(reason, first)
    assert not _names(reason, "LINEAR_API_KEY")
    assert [name for name in missing if name != first and _names(reason, name)] == []
    assert not any(value in reason for value in LIVE_VARIABLES.values() if len(value) > 1)


def test_rejects_live_marker_when_transport_unknown(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_live_variables(monkeypatch)
    item = _FakeItem("packages/tracker_linear/tests/integration/test_live.py")
    item.markers.append(pytest.mark.live("connector").mark)

    with pytest.raises(pytest.UsageError, match="'connector'"):
        _collect(item)
