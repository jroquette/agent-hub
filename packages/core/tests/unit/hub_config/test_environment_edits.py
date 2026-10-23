import copy
from typing import Any

from agent_hub.core.hub_config.environment_edits import (
    EditRefusal,
    add_endpoint,
    add_environment,
    remove_endpoint,
    remove_environment,
    rename_environment,
    set_environment,
    set_service,
)
from agent_hub.core.testing.builders import a_local_environments_document, an_environments_document


def _w() -> dict[str, Any]:
    return {"_comment": "first", **an_environments_document()}


def test_adds_environment_when_name_new() -> None:
    document = _w()
    before = copy.deepcopy(document)

    edited = add_environment(document, "qa", {"access": "ask"}, declared={}, file="hub.json")

    assert isinstance(edited, dict)
    assert list(edited["environments"]) == ["local", "staging", "live", "qa"]
    assert edited["environments"]["qa"] == {"access": "ask"}
    # Pure: the document given is not changed.
    assert document == before


def test_adds_environments_key_when_document_has_none() -> None:
    edited = add_environment({"project": {}}, "local", {"access": "write"}, declared={}, file="x")

    assert edited == {"project": {}, "environments": {"local": {"access": "write"}}}


def test_refuses_add_when_name_exists_in_either_file() -> None:
    own = add_environment(_w(), "Live", {"access": "ask"}, declared={}, file="hub.json")
    other = add_environment(
        _w(),
        "jane-cloud",
        {"access": "ask"},
        declared={"jane-cloud": "hub.local.json"},
        file="hub.json",
    )

    assert own == EditRefusal("environment live is already declared in hub.json")
    assert other == EditRefusal("environment jane-cloud is already declared in hub.local.json")


def test_sets_access_when_environment_declared() -> None:
    edited = set_environment(
        _w(), "live", {"access": "ask", "production": None}, file="hub.json", may_create=False
    )

    assert isinstance(edited, dict)
    assert edited["environments"]["live"] == {
        "access": "ask",
        "credentials": {"aws_profile": "demo-live-ro", "env": ["DEMO_LIVE_DB_URL"]},
    }


def test_creates_entry_when_set_may_create() -> None:
    local = a_local_environments_document()

    edited = set_environment(
        local,
        "staging",
        {"access": "read", "production": None},
        file="hub.local.json",
        may_create=True,
    )

    assert isinstance(edited, dict)
    assert list(edited["environments"]) == ["jane-cloud", "staging"]
    assert edited["environments"]["staging"] == {"access": "read"}


def test_sets_and_removes_values_when_value_changes_given() -> None:
    document = _w()
    document["environments"]["staging"]["values"] = {"region": "eu-west-1", "user_name": "ci"}

    edited = set_environment(
        document,
        "staging",
        {},
        file="hub.json",
        may_create=False,
        values={"user_name": None, "account_id": "123"},
    )

    assert isinstance(edited, dict)
    assert edited["environments"]["staging"]["values"] == {
        "region": "eu-west-1",
        "account_id": "123",
    }
    emptied = set_environment(
        edited,
        "staging",
        {},
        file="hub.json",
        may_create=False,
        values={"region": None, "account_id": None},
    )
    assert isinstance(emptied, dict)
    assert "values" not in emptied["environments"]["staging"]


def test_drops_created_entry_when_its_values_removed_again() -> None:
    local = a_local_environments_document()
    before = copy.deepcopy(local)

    added = set_environment(
        local, "staging", {}, file="hub.local.json", may_create=True, values={"user_name": "jane"}
    )
    assert isinstance(added, dict)
    assert added["environments"]["staging"] == {"values": {"user_name": "jane"}}
    removed = set_environment(
        added, "staging", {}, file="hub.local.json", may_create=True, values={"user_name": None}
    )

    assert removed == before


def test_refuses_set_when_environment_undeclared() -> None:
    assert set_environment(_w(), "qa", {"access": "ask"}, file="hub.json", may_create=False) == (
        EditRefusal("no environment qa in hub.json")
    )


def test_refuses_remove_when_endpoints_name_environment() -> None:
    assert remove_environment(_w(), "staging", file="hub.json") == EditRefusal(
        "environment staging still has endpoints (demo-api api, demo-api orders);"
        " remove them first: ./hub env service remove"
    )
    assert remove_environment(_w(), "qa", file="hub.json") == EditRefusal(
        "no environment qa in hub.json"
    )


def test_removes_environment_and_empty_map_when_last_one_goes() -> None:
    document = {"project": {}, "environments": {"qa": {"access": "ask"}}}

    assert remove_environment(document, "qa", file="hub.json") == {"project": {}}


def test_keeps_key_order_when_document_edited() -> None:
    document = _w()

    edited = add_environment(document, "qa", {"access": "ask"}, declared={}, file="hub.json")

    assert isinstance(edited, dict)
    assert list(edited) == list(document)
    assert list(edited["repos"][0]) == list(document["repos"][0])


def test_adds_endpoint_when_service_new() -> None:
    edited = add_endpoint(
        _w(),
        repo="demo-api",
        service="cache",
        environment="local",
        endpoint={"url": "redis://localhost:6379"},
        kind="redis",
        file="hub.json",
        creates_repo=False,
    )

    assert isinstance(edited, dict)
    services = edited["repos"][0]["services"]
    assert list(services) == ["api", "orders", "cache"]
    assert services["cache"] == {
        "kind": "redis",
        "endpoints": {"local": {"url": "redis://localhost:6379"}},
    }


def test_adds_local_repo_when_creates_repo() -> None:
    edited = add_endpoint(
        {"project": {"branch_prefix": "jane/"}},
        repo="demo-api",
        service="api",
        environment="jane-cloud",
        endpoint={"resource": "jane-api"},
        kind=None,
        file="hub.local.json",
        creates_repo=True,
        known_repos=("demo-api",),
    )

    assert edited == {
        "project": {"branch_prefix": "jane/"},
        "repos": [
            {
                "dir": "demo-api",
                "services": {"api": {"endpoints": {"jane-cloud": {"resource": "jane-api"}}}},
            }
        ],
    }


def test_refuses_endpoint_when_repo_unknown_or_endpoint_taken() -> None:
    unknown = add_endpoint(
        _w(),
        repo="demo-web",
        service="api",
        environment="local",
        endpoint={"url": "http://localhost:3000"},
        kind=None,
        file="hub.json",
        creates_repo=False,
    )
    taken = add_endpoint(
        _w(),
        repo="demo-api",
        service="api",
        environment="local",
        endpoint={"url": "http://localhost:3000"},
        kind=None,
        file="hub.json",
        creates_repo=False,
    )

    assert unknown == EditRefusal("no repo demo-web in hub.json")
    assert taken == EditRefusal("demo-api api already has an endpoint in local")


def test_removes_service_endpoint_when_env_given() -> None:
    edited = remove_endpoint(
        _w(), repo="demo-api", service="api", environment="live", file="hub.json"
    )

    assert isinstance(edited, dict)
    assert list(edited["repos"][0]["services"]["api"]["endpoints"]) == ["local", "staging"]


def test_removes_service_and_empty_maps_when_last_one_goes() -> None:
    document = _w()
    del document["repos"][0]["services"]["orders"]

    edited = remove_endpoint(
        document, repo="demo-api", service="api", environment=None, file="hub.json"
    )

    assert isinstance(edited, dict)
    assert "services" not in edited["repos"][0]
    local = remove_endpoint(
        a_local_environments_document(),
        repo="demo-api",
        service="api",
        environment="jane-cloud",
        file="hub.local.json",
    )
    assert isinstance(local, dict)
    assert "repos" not in local


def test_refuses_remove_endpoint_when_absent() -> None:
    def remove(repo: str, service: str, environment: str | None) -> object:
        return remove_endpoint(
            _w(), repo=repo, service=service, environment=environment, file="hub.json"
        )

    assert remove("demo-web", "api", None) == EditRefusal("no repo demo-web in hub.json")
    assert remove("demo-api", "cache", None) == EditRefusal(
        "no service cache on demo-api in hub.json"
    )
    assert remove("demo-api", "orders", "live") == EditRefusal(
        "demo-api orders has no endpoint in live in hub.json"
    )


def test_refuses_comment_key_when_any_edit_names_one() -> None:
    document = _w()
    document["environments"]["_note"] = "a comment"
    document["repos"][0]["services"]["_note"] = "a comment"
    refusal = EditRefusal("_note: a name starting with _ is a comment key; choose another name")

    assert add_environment(document, "_note", {"access": "ask"}, declared={}, file="x") == refusal
    assert (
        set_environment(document, "_note", {"access": "ask"}, file="x", may_create=True) == refusal
    )
    assert remove_environment(document, "_note", file="x") == refusal
    for repo, service, environment in (
        ("_note", "api", "local"),
        ("demo-api", "_note", "local"),
        ("demo-api", "api", "_note"),
    ):
        assert (
            add_endpoint(
                document,
                repo=repo,
                service=service,
                environment=environment,
                endpoint={"url": "http://localhost:1"},
                kind=None,
                file="x",
                creates_repo=False,
            )
            == refusal
        )
        assert (
            remove_endpoint(document, repo=repo, service=service, environment=environment, file="x")
            == refusal
        )


def test_refuses_local_repo_when_hub_json_lacks_it() -> None:
    aws_key = "AK" + "IA" + "A" * 16

    refused = add_endpoint(
        {},
        repo=aws_key,
        service="api",
        environment="jane-cloud",
        endpoint={"url": "http://localhost:1"},
        kind=None,
        file="hub.local.json",
        creates_repo=True,
        known_repos=("demo-api",),
    )

    assert refused == EditRefusal("no repo <name> in hub.json")


# AC-416.7
def test_renames_environment_and_its_endpoints_in_place_when_name_free() -> None:
    document = _w()
    before = copy.deepcopy(document)

    edited = rename_environment(document, "staging", "qa", declared=(), file="hub.json")

    assert isinstance(edited, dict)
    assert list(edited["environments"]) == ["local", "qa", "live"]
    assert edited["environments"]["qa"] == before["environments"]["staging"]
    services = edited["repos"][0]["services"]
    assert list(services["api"]["endpoints"]) == ["local", "qa", "live"]
    assert services["orders"]["endpoints"] == {"qa": {"resource": "demo-orders-staging"}}
    assert document == before


# AC-416.7
def test_renames_environment_when_only_case_changes() -> None:
    edited = rename_environment(_w(), "live", "Live", declared=("live",), file="hub.json")

    assert isinstance(edited, dict)
    assert list(edited["environments"]) == ["local", "staging", "Live"]


# AC-416.7
def test_refuses_rename_when_new_name_taken_absent_or_comment() -> None:
    def rename(name: str, new_name: str, declared: tuple[str, ...] = ()) -> object:
        return rename_environment(_w(), name, new_name, declared=declared, file="hub.json")

    assert rename("staging", "LIVE") == EditRefusal("environment live is already declared")
    assert rename("staging", "jane-cloud", ("jane-cloud",)) == EditRefusal(
        "environment jane-cloud is already declared"
    )
    assert rename("qa", "uat") == EditRefusal("no environment qa in hub.json")
    assert rename("staging", "_qa") == EditRefusal(
        "_qa: a name starting with _ is a comment key; choose another name"
    )


# AC-416.8
def test_sets_service_fields_and_renames_it_in_place_when_name_free() -> None:
    edited = set_service(
        _w(),
        repo="demo-api",
        service="api",
        changes={"kind": None, "description": "the public API"},
        new_name="gateway",
        taken=(),
        file="hub.json",
    )

    assert isinstance(edited, dict)
    services = edited["repos"][0]["services"]
    assert list(services) == ["gateway", "orders"]
    assert services["gateway"]["description"] == "the public API"
    assert "kind" not in services["gateway"]
    assert list(services["gateway"]["endpoints"]) == ["local", "staging", "live"]


# AC-416.8
def test_refuses_set_service_when_name_taken_or_service_absent() -> None:
    def change(service: str, new_name: str | None, taken: tuple[str, ...] = ()) -> object:
        return set_service(
            _w(),
            repo="demo-api",
            service=service,
            changes={},
            new_name=new_name,
            taken=taken,
            file="hub.json",
        )

    assert change("api", "orders") == EditRefusal("demo-api already has a service orders")
    assert change("api", "cache", ("cache",)) == EditRefusal("demo-api already has a service cache")
    assert change("cache", None) == EditRefusal("no service cache on demo-api in hub.json")
    assert change("api", "_x") == EditRefusal(
        "_x: a name starting with _ is a comment key; choose another name"
    )
