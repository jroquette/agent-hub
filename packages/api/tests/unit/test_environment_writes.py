"""The Hub config screen's environment edits (AC-416.3 to .9; docs/design/environments.md)."""

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

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


# AC-416.3
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


# AC-416.3
def test_creates_local_file_when_own_environment_added(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    _edit(hub, op="add_environment", scope="local", name="mine", access="write")

    assert _read(hub / "hub.local.json") == {"environments": {"mine": {"access": "write"}}}


# AC-416.3
def test_refuses_local_access_when_looser_than_team(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "read"}})

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="set_environment", scope="local", name="staging", access="write")

    assert "may only tighten" in raised.value.problems[0].message
    assert not (hub / "hub.local.json").exists()


# AC-416.3
def test_tightens_team_environment_when_local_file_sets_it(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "write"}})

    _edit(hub, op="set_environment", scope="local", name="staging", access="read")

    assert _read(hub / "hub.local.json") == {"environments": {"staging": {"access": "read"}}}


# AC-416.4
def test_adds_and_removes_endpoint_when_repo_is_team(tmp_path: Path) -> None:
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


# AC-416.3
def test_refuses_removing_environment_when_endpoint_uses_it(tmp_path: Path) -> None:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "ask"}}
    document["repos"][0]["services"] = {
        "api": {"endpoints": {"staging": {"resource": "orders-table"}}}
    }
    (tmp_path / "hub.json").write_text(json.dumps(document))

    with pytest.raises(HubInvalidError) as raised:
        _edit(tmp_path, op="remove_environment", scope="team", name="staging")

    assert "still has endpoints" in raised.value.problems[0].message


# AC-416.4
def test_refuses_endpoint_when_it_has_url_and_resource(tmp_path: Path) -> None:
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


# AC-416.4
def test_refuses_url_when_it_has_user_info(tmp_path: Path) -> None:
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


# AC-416.3
def test_removes_local_file_when_last_entry_removed(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    (hub / "hub.local.json").write_text(json.dumps({"environments": {"mine": {"access": "read"}}}))

    _edit(hub, op="remove_environment", scope="local", name="mine")

    assert not (hub / "hub.local.json").exists()


# AC-416.5
def test_keeps_service_kind_when_endpoint_replaced(tmp_path: Path) -> None:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "ask"}}
    document["repos"][0]["services"] = {
        "api": {"kind": "api", "endpoints": {"staging": {"url": "https://old.example.com"}}}
    }
    (tmp_path / "hub.json").write_text(json.dumps(document))

    _edit(
        tmp_path,
        op="add_endpoint",
        scope="team",
        repo="demo-api",
        service="api",
        environment="staging",
        resource="orders-staging",
        replace=True,
    )

    assert _read(tmp_path / "hub.json")["repos"][0]["services"] == {
        "api": {"kind": "api", "endpoints": {"staging": {"resource": "orders-staging"}}}
    }


# AC-416.6
def test_writes_addresses_to_their_files_when_environments_span_both(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    (hub / "hub.local.json").write_text(json.dumps({"environments": {"mine": {"access": "write"}}}))

    _edit(
        hub,
        op="add_service",
        repo="demo-api",
        service="api",
        kind="api",
        addresses=[
            {"environment": "staging", "address": "https://staging.example.com"},
            {"environment": "mine", "address": "http://localhost:8000"},
        ],
    )

    assert _read(hub / "hub.json")["repos"][0]["services"] == {
        "api": {"kind": "api", "endpoints": {"staging": {"url": "https://staging.example.com"}}}
    }
    assert _read(hub / "hub.local.json")["repos"] == [
        {
            "dir": "demo-api",
            "services": {"api": {"endpoints": {"mine": {"url": "http://localhost:8000"}}}},
        }
    ]


# AC-416.6
def test_keeps_resource_and_kind_in_local_file_when_only_own_addresses(tmp_path: Path) -> None:
    hub = _hub(tmp_path)
    (hub / "hub.local.json").write_text(json.dumps({"environments": {"mine": {"access": "write"}}}))

    _edit(
        hub,
        op="add_service",
        repo="demo-api",
        service="orders",
        kind="database",
        addresses=[{"environment": "mine", "address": "orders-table"}],
    )

    assert _read(hub / "hub.local.json")["repos"][0]["services"] == {
        "orders": {"kind": "database", "endpoints": {"mine": {"resource": "orders-table"}}}
    }
    assert "services" not in _read(hub / "hub.json")["repos"][0]


# AC-416.6
def test_writes_neither_file_when_one_address_is_invalid(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    (hub / "hub.local.json").write_text(json.dumps({"environments": {"mine": {"access": "write"}}}))
    before = ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes())

    with pytest.raises(HubInvalidError):
        _edit(
            hub,
            op="add_service",
            repo="demo-api",
            service="api",
            addresses=[
                {"environment": "staging", "address": "https://staging.example.com"},
                {"environment": "mine", "address": "http://user:pw@localhost"},
            ],
        )

    assert ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes()) == before


def _team_and_local(tmp_path: Path) -> Path:
    document = a_hub_document()
    document["environments"] = {"staging": {"access": "write"}, "live": {"access": "read"}}
    document["repos"][0]["services"] = {
        "api": {"kind": "api", "endpoints": {"staging": {"url": "https://staging.example.com"}}}
    }
    (tmp_path / "hub.json").write_text(json.dumps(document, indent=2) + "\n")
    local = {
        "environments": {"staging": {"access": "read"}, "mine": {"access": "write"}},
        "repos": [
            {"dir": "demo-api", "services": {"api": {"endpoints": {"mine": {"resource": "t"}}}}}
        ],
    }
    (tmp_path / "hub.local.json").write_text(json.dumps(local, indent=2) + "\n")
    return tmp_path


# AC-416.7
def test_renames_local_tightening_too_when_team_environment_renamed(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)

    _edit(hub, op="rename_environment", scope="team", name="staging", new_name="qa")

    team = _read(hub / "hub.json")
    assert list(team["environments"]) == ["qa", "live"]
    assert list(team["repos"][0]["services"]["api"]["endpoints"]) == ["qa"]
    assert list(_read(hub / "hub.local.json")["environments"]) == ["qa", "mine"]


# AC-416.7
def test_renames_own_environment_and_endpoints_when_scope_is_local(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)
    before = (hub / "hub.json").read_bytes()

    _edit(hub, op="rename_environment", scope="local", name="mine", new_name="sandbox")

    local = _read(hub / "hub.local.json")
    assert list(local["environments"]) == ["staging", "sandbox"]
    assert local["repos"][0]["services"]["api"]["endpoints"] == {"sandbox": {"resource": "t"}}
    assert (hub / "hub.json").read_bytes() == before


@pytest.mark.parametrize(
    ("rename", "message"),
    [
        (("team", "staging", "Mine"), "environment mine is already declared"),
        (("local", "mine", "LIVE"), "environment live is already declared"),
        (("local", "staging", "qa"), "hub.json declares staging; rename it there"),
        (("team", "qa", "uat"), "no environment qa in hub.json"),
    ],
)
# AC-416.7
def test_refuses_environment_rename_when_name_taken_or_not_its_file(
    tmp_path: Path, rename: tuple[str, str, str], message: str
) -> None:
    hub = _team_and_local(tmp_path)
    scope, name, new_name = rename

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="rename_environment", scope=scope, name=name, new_name=new_name)

    assert raised.value.problems[0].message == message


# AC-416.8
def test_renames_local_endpoints_too_when_team_service_renamed(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)

    _edit(
        hub,
        op="set_service",
        scope="team",
        repo="demo-api",
        service="api",
        new_name="gateway",
        kind="",
        description="the public API",
    )

    assert _read(hub / "hub.json")["repos"][0]["services"] == {
        "gateway": {
            "description": "the public API",
            "endpoints": {"staging": {"url": "https://staging.example.com"}},
        }
    }
    assert list(_read(hub / "hub.local.json")["repos"][0]["services"]) == ["gateway"]


# AC-416.8
def test_refuses_local_service_change_when_team_declares_it(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="set_service", scope="local", repo="demo-api", service="api", kind="lambda")

    assert raised.value.problems[0].message == (
        "hub.json declares api; hub.local.json may only add its endpoints"
    )


# AC-416.6
def test_keeps_description_with_kind_when_service_added(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})

    _edit(
        hub,
        op="add_service",
        repo="demo-api",
        service="api",
        kind="api",
        description="the public API",
        addresses=[{"environment": "staging", "address": "https://staging.example.com"}],
    )

    assert _read(hub / "hub.json")["repos"][0]["services"]["api"] == {
        "kind": "api",
        "description": "the public API",
        "endpoints": {"staging": {"url": "https://staging.example.com"}},
    }


# AC-416.9
def test_writes_every_op_together_when_batch_is_valid(tmp_path: Path) -> None:
    hub = _hub(tmp_path)

    _edit(
        hub,
        op="batch",
        ops=[
            {"op": "add_environment", "scope": "team", "name": "staging", "access": "ask"},
            {"op": "add_environment", "scope": "local", "name": "mine", "access": "write"},
            {
                "op": "add_service",
                "repo": "demo-api",
                "service": "api",
                "addresses": [
                    {"environment": "staging", "address": "https://staging.example.com"},
                    {"environment": "mine", "address": "http://localhost:8000"},
                ],
            },
            {"op": "rename_environment", "scope": "team", "name": "staging", "new_name": "qa"},
        ],
    )

    assert _read(hub / "hub.json")["repos"][0]["services"] == {
        "api": {"endpoints": {"qa": {"url": "https://staging.example.com"}}}
    }
    assert _read(hub / "hub.local.json")["environments"] == {"mine": {"access": "write"}}


# AC-416.9
def test_writes_neither_file_and_names_op_when_batch_op_refused(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)
    before = ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes())

    with pytest.raises(HubInvalidError) as raised:
        _edit(
            hub,
            op="batch",
            ops=[
                {"op": "add_environment", "scope": "team", "name": "uat", "access": "ask"},
                {"op": "remove_environment", "scope": "team", "name": "qa"},
            ],
        )

    assert raised.value.problems[0].message == "op 2: no environment qa in hub.json"
    assert ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes()) == before


# AC-416.9
def test_writes_neither_file_when_batch_result_is_invalid(tmp_path: Path) -> None:
    hub = _team_and_local(tmp_path)
    before = ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes())

    with pytest.raises(HubInvalidError):
        _edit(
            hub,
            op="batch",
            ops=[
                {"op": "rename_environment", "scope": "local", "name": "mine", "new_name": "ok"},
                {"op": "set_environment", "scope": "local", "name": "staging", "access": "write"},
            ],
        )
    with pytest.raises(HubInvalidError):
        _edit(
            hub,
            op="batch",
            ops=[
                {"op": "rename_environment", "scope": "local", "name": "mine", "new_name": "ok"},
                {"op": "rename_environment", "scope": "team", "name": "live", "new_name": "a b"},
            ],
        )

    assert ((hub / "hub.json").read_bytes(), (hub / "hub.local.json").read_bytes()) == before


# AC-416.3
def test_sets_and_removes_credentials_when_environment_changed(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})

    _edit(
        hub,
        op="set_environment",
        scope="team",
        name="staging",
        aws_profile="demo-staging",
        credential_env=["DEMO_DB_URL", "DEMO_DB_URL"],
    )
    set_credentials = _read(hub / "hub.json")["environments"]["staging"]
    _edit(hub, op="set_environment", scope="team", name="staging", credential_env=[])
    profile_only = _read(hub / "hub.json")["environments"]["staging"]
    _edit(hub, op="set_environment", scope="team", name="staging", aws_profile="")

    assert set_credentials == {
        "access": "ask",
        "credentials": {"aws_profile": "demo-staging", "env": ["DEMO_DB_URL"]},
    }
    assert profile_only == {"access": "ask", "credentials": {"aws_profile": "demo-staging"}}
    assert _read(hub / "hub.json")["environments"]["staging"] == {"access": "ask"}


@pytest.mark.parametrize(
    "change", [{"aws_profile": "mine"}, {"credential_env": ["MY_URL"]}, {"description": "x"}]
)
# AC-416.3
def test_refuses_local_change_when_not_access_of_team_environment(
    tmp_path: Path, change: dict[str, Any]
) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "write"}})

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="set_environment", scope="local", name="staging", **change)

    assert raised.value.problems[0].message == (
        "hub.json declares staging; hub.local.json may only tighten its access or set values"
    )
    assert not (hub / "hub.local.json").exists()


def test_sets_and_removes_values_when_environment_edits_name_them(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})

    _edit(
        hub,
        op="add_environment",
        scope="team",
        name="sandbox",
        access="write",
        values={"user_name": " team-user ", "region": " "},
    )
    added = _read(hub / "hub.json")["environments"]["sandbox"]
    _edit(
        hub,
        op="set_environment",
        scope="team",
        name="sandbox",
        values={"user_name": "", "account_id": "123456789012"},
    )

    assert added == {"access": "write", "values": {"user_name": "team-user"}}
    assert _read(hub / "hub.json")["environments"]["sandbox"] == {
        "access": "write",
        "values": {"account_id": "123456789012"},
    }


def test_writes_own_values_over_team_environment_when_scope_is_local(tmp_path: Path) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask", "values": {"user_name": "ci"}}})

    _edit(hub, op="set_environment", scope="local", name="staging", values={"user_name": "jane"})
    written = _read(hub / "hub.local.json")
    _edit(hub, op="set_environment", scope="local", name="staging", values={"user_name": ""})

    assert written == {"environments": {"staging": {"values": {"user_name": "jane"}}}}
    # Emptied, the developer's setting goes, and with it the file that held only it.
    assert not (hub / "hub.local.json").exists()
    assert _read(hub / "hub.json")["environments"]["staging"]["values"] == {"user_name": "ci"}


@pytest.mark.parametrize("name", ["Bad-Name", "_token", "1st"])
def test_refuses_value_name_when_not_an_input_name(tmp_path: Path, name: str) -> None:
    # A "_" name is a comment key in the file, which the secret check never reads.
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    before = (hub / "hub.json").read_bytes()
    secret_shaped = "ey" + "J" + "a" * 15 + "." + "b" * 15

    with pytest.raises(ValidationError):
        _edit(hub, op="set_environment", scope="team", name="staging", values={name: secret_shaped})

    assert (hub / "hub.json").read_bytes() == before


@pytest.mark.parametrize(
    ("values", "pointer"),
    [
        ({"token": "ey" + "J" + "a" * 15 + "." + "b" * 15}, "environments.staging.values.token"),
    ],
    ids=["secret_shaped"],
)
def test_refuses_value_when_file_check_fails(
    tmp_path: Path, values: dict[str, str], pointer: str
) -> None:
    hub = _hub(tmp_path, environments={"staging": {"access": "ask"}})
    before = (hub / "hub.json").read_bytes()

    with pytest.raises(HubInvalidError) as raised:
        _edit(hub, op="set_environment", scope="team", name="staging", values=values)

    assert raised.value.problems[0].pointer.startswith(pointer)
    assert "eyJ" not in raised.value.problems[0].message
    assert (hub / "hub.json").read_bytes() == before
