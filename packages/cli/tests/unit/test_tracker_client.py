from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.tracker_linear import graphql
from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient
from agent_hub.tracker_linear.mcp import McpTrackerClient


class _SpyEnviron(Mapping[str, str]):
    """An environment that records every key read, membership test and iteration."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values
        self.reads: list[str] = []

    def __getitem__(self, key: str) -> str:
        self.reads.append(key)
        return self._values[key]

    def __contains__(self, key: object) -> bool:
        self.reads.append(str(key))
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        self.reads.append("<iteration>")
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


def _linear_config() -> HubConfig:
    config = HubConfig.model_validate(a_hub_document())
    assert config.tracker.kind == "linear"
    return config


def _no_transport(*_args: object, **_kwargs: object) -> tuple[int, bytes]:
    msg = "resolution and a keyless call send no request"
    raise AssertionError(msg)


def test_returns_graphql_adapter_when_tracker_kind_is_linear(tmp_path: Path) -> None:
    client = resolve_tracker_client(_linear_config(), {}, hub_root=tmp_path)

    assert isinstance(client, LinearGraphqlTrackerClient)


def test_reads_no_environment_value_when_resolving(tmp_path: Path) -> None:
    environ = _SpyEnviron({"LINEAR_API_KEY": "lin_api_synthetic"})

    resolve_tracker_client(_linear_config(), environ, hub_root=tmp_path)

    assert environ.reads == []


def test_first_call_names_missing_key_when_resolved_without_it(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(graphql, "urllib_post", _no_transport)
    client = resolve_tracker_client(_linear_config(), {}, hub_root=tmp_path)

    with pytest.raises(TrackerError, match="LINEAR_API_KEY is not set"):
        client.get_issue("DEM-1")


def _config(transport: str | None) -> HubConfig:
    document = a_hub_document()
    if transport is not None:
        document["tracker"]["transport"] = transport
    return HubConfig.model_validate(document)


def test_resolves_mcp_adapter_in_hub_root_when_transport_mcp(tmp_path: Path) -> None:
    client = resolve_tracker_client(_config("mcp"), {}, hub_root=tmp_path)

    assert isinstance(client, McpTrackerClient)
    assert client.cwd == tmp_path


@pytest.mark.parametrize("transport", [None, "api"], ids=["absent", "api"])
def test_resolves_graphql_adapter_when_transport_absent_or_api(
    tmp_path: Path, transport: str | None
) -> None:
    client = resolve_tracker_client(_config(transport), {}, hub_root=tmp_path)

    assert isinstance(client, LinearGraphqlTrackerClient)


@pytest.mark.parametrize("transport", ["api", "mcp"])
@pytest.mark.parametrize("key", ["lin" + "_api_" + "x" * 40, None], ids=["key", "no-key"])
def test_resolves_same_adapter_when_key_present_or_absent(
    tmp_path: Path, transport: str, key: str | None
) -> None:
    environ = _SpyEnviron({} if key is None else {"LINEAR_API_KEY": key})
    expected = McpTrackerClient if transport == "mcp" else LinearGraphqlTrackerClient

    client = resolve_tracker_client(_config(transport), environ, hub_root=tmp_path)

    assert type(client) is expected
    assert environ.reads == []


def test_names_only_command_modules_when_sources_scanned() -> None:
    # The modules that resolve the adapter; run_command.py joins them (PR 3).
    sources = Path(__file__).resolve().parents[2] / "src" / "agent_hub" / "cli"
    assert sources.is_dir(), sources  # an empty scan would pass anywhere
    naming = sorted(
        module.name
        for module in sources.rglob("*.py")
        if "resolve_tracker_client" in module.read_text()
    )

    assert naming == ["next_command.py", "tracker_client.py"]


MISSING_KEY = (
    'hub next: LINEAR_API_KEY is not set; export it, or set tracker.transport: "mcp"'
    " in hub.json to reach Linear through its MCP server with claude -p"
)


@pytest.mark.parametrize("transport", [None, "api"], ids=["absent", "api"])
@pytest.mark.parametrize("environ", [{}, {"LINEAR_API_KEY": ""}], ids=["unset", "empty"])
def test_names_key_and_alternative_when_api_key_missing(
    transport: str | None, environ: dict[str, str]
) -> None:
    line = missing_key_line(_config(transport), environ, command="next")

    assert line == MISSING_KEY


def test_passes_when_transport_api_and_key_set() -> None:
    key = "lin" + "_api_" + "x" * 40

    assert missing_key_line(_config("api"), {"LINEAR_API_KEY": key}, command="run") is None


@pytest.mark.parametrize("environ", [{}, {"LINEAR_API_KEY": ""}], ids=["unset", "empty"])
def test_passes_when_transport_mcp_and_key_absent(environ: dict[str, str]) -> None:
    assert missing_key_line(_config("mcp"), environ, command="next") is None


def test_names_transport_when_line_built() -> None:
    assert transport_line(_config(None)) == 'tracker: Linear API (tracker.transport "api")'
    assert transport_line(_config("api")) == 'tracker: Linear API (tracker.transport "api")'
    assert transport_line(_config("mcp")) == (
        'tracker: Linear MCP via claude -p (tracker.transport "mcp")'
    )
