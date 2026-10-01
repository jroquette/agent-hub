from collections.abc import Iterator, Mapping

import pytest

from agent_hub.cli.tracker_client import resolve_tracker_client
from agent_hub.core.errors import TrackerError
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.tracker_linear import graphql
from agent_hub.tracker_linear.graphql import LinearGraphqlTrackerClient


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


def test_returns_graphql_adapter_when_tracker_kind_is_linear() -> None:
    client = resolve_tracker_client(_linear_config(), {})

    assert isinstance(client, LinearGraphqlTrackerClient)


def test_reads_no_environment_value_when_resolving() -> None:
    environ = _SpyEnviron({"LINEAR_API_KEY": "lin_api_synthetic"})

    resolve_tracker_client(_linear_config(), environ)

    assert environ.reads == []


def test_first_call_names_missing_key_when_resolved_without_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(graphql, "urllib_post", _no_transport)
    client = resolve_tracker_client(_linear_config(), {})

    with pytest.raises(TrackerError, match="LINEAR_API_KEY is not set"):
        client.get_issue("DEM-1")
