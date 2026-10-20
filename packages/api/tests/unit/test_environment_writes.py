import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter

from agent_hub.api.environment_writes import EnvironmentEdit, write_environment_edit
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.testing.builders import a_hub_document

_EDIT: TypeAdapter[Any] = TypeAdapter(EnvironmentEdit)


def _hub(tmp_path: Path, **keys: Any) -> Path:
    document = a_hub_document() | keys
    (tmp_path / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    return tmp_path


def _read(path: Path) -> dict[str, Any]:
    loaded: dict[str, Any] = json.loads(path.read_text())
    return loaded


def _edit(hub: Path, **body: Any) -> None:
    write_environment_edit(str(hub), _EDIT.validate_python(body))


def test_adds_team_environment_last_when_scope_is_team(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"local": {"access": "write"}})

    _edit(
        hub,
        op="add_environment",
        scope="team",
        name="staging",
        access="ask",
        aws_profile="demo-staging",
        credential_env=["DEMO_DB_URL", " "],
    )

    assert _read(hub / "hub.json")["environments"] == {
        "local": {"access": "write"},
        "staging": {
            "access": "ask",
            "credentials": {"aws_profile": "demo-staging", "env": ["DEMO_DB_URL"]},
        },
    }
    assert not (hub / "hub.local.json").exists()


def test_creates_local_file_when_own_environment_added(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    _edit(hub, op="add_environment", scope="local", name="mine", access="write")

    assert _read(hub / "hub.local.json") == {"environments": {"mine": {"access": "write"}}}


def test_refuses_local_access_looser_than_team(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "read"}})

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="set_environment", scope="local", name="staging", access="write")

    assert "may only tighten" in raised.value.problems[0].message
    assert not (hub / "hub.local.json").exists()


def test_tightens_team_environment_in_local_file(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "write"}})

    _edit(hub, op="set_environment", scope="local", name="staging", access="read")

    assert _read(hub / "hub.local.json") == {"environments": {"staging": {"access": "read"}}}


def test_adds_and_removes_endpoint_on_team_repo(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    before = (hub / "hub.json").read_text()

    _edit(
        hub,
        op="add_endpoint",
        scope="team",
        repo="demo-api",
        service="api",
        environment="staging",
        url="https://staging.example.com",
        kind="api",
    )
    services = _read(hub / "hub.json")["repos"][0]["services"]
    _edit(hub, op="remove_endpoint", scope="team", repo="demo-api", service="api")

    assert services == {
        "api": {"kind": "api", "endpoints": {"staging": {"url": "https://staging.example.com"}}}
    }
    assert (hub / "hub.json").read_text() == before


def test_refuses_removing_environment_while_endpoint_uses_it(tmp_path: Path) -> None:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "ask"}}
    document["repos"][0]["services"] = {
        "api": {"endpoints": {"staging": {"resource": "orders-table"}}}
    }
    (tmp_path / "hub.json").write_text(json.dumps(document))

    with pytest.raises(HubInvalidError) as raised:
        _edit(tmp_path, op="remove_environment", scope="team", name="staging")

    assert "still has endpoints" in raised.value.problems[0].message


def test_refuses_endpoint_with_url_and_resource(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})

    with pytest.raises(HubInvalidError) as raised:
        _edit(
            hub,
            op="add_endpoint",
            scope="team",
            repo="demo-api",
            service="api",
            environment="staging",
            url="https://x.example.com",
            resource="t",
        )

    assert raised.value.problems[0].message == "give either a URL or a resource name"


def test_refuses_url_with_user_info(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    before = (hub / "hub.json").read_bytes()

    with pytest.raises(HubInvalidError):
        _edit(
            hub,
            op="add_endpoint",
            scope="team",
            repo="demo-api",
            service="api",
            environment="staging",
            url="https://user:pw@x.example.com",
        )

    assert (hub / "hub.json").read_bytes() == before


def test_removes_local_file_when_last_entry_removed(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    (hub / "hub.local.json").write_text(json.dumps({"environments": {"mine": {"access": "read"}}}))

    _edit(hub, op="remove_environment", scope="local", name="mine")

    assert not (hub / "hub.local.json").exists()
