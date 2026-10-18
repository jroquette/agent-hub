from typing import Any

import pytest
from pydantic import ValidationError

from agent_hub.core.hub_config.environments import Endpoint, Environment, Service
from agent_hub.core.testing.builders import an_environments_document

# Assembled at run time, so the repo holds no secret-shaped text.
AWS_KEY = "AK" + "IA" + "A" * 16
JWT = "ey" + "J" + "a" * 15 + "." + "b" * 15


def a_live_environment() -> dict[str, Any]:
    environment: dict[str, Any] = an_environments_document()["environments"]["live"]
    return environment


def error_locs(model: type[Any], data: object) -> list[tuple[str | int, ...]]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return [error["loc"] for error in caught.value.errors()]


def test_loads_environment_when_access_given() -> None:
    local = Environment.model_validate({"access": "write", "description": "a local stack"})
    live = Environment.model_validate(a_live_environment())

    assert (local.access, local.production, local.description) == ("write", False, "a local stack")
    assert local.credentials is None
    assert (live.access, live.production) == ("read", True)
    assert live.credentials is not None
    assert live.credentials.aws_profile == "demo-live-ro"
    assert live.credentials.env == ("DEMO_LIVE_DB_URL",)


@pytest.mark.parametrize(
    ("change", "loc"),
    [
        pytest.param({"access": "admin"}, ("access",), id="access_admin"),
        pytest.param({"access": None}, ("access",), id="access_null"),
        pytest.param({"production": "yes"}, ("production",), id="production_text"),
        pytest.param({"stage": "x"}, ("stage",), id="unknown_key"),
        pytest.param(
            {"credentials": {"aws_profile": "a b"}}, ("credentials", "aws_profile"), id="profile"
        ),
        pytest.param(
            {"credentials": {"env": ["lower"]}}, ("credentials", "env", 0), id="env_lower"
        ),
        pytest.param(
            {"credentials": {"env": [f"DEMO_{index}" for index in range(11)]}},
            ("credentials", "env"),
            id="env_eleven",
        ),
        pytest.param(
            {"credentials": {"profile": "demo-live-ro"}}, ("credentials", "profile"), id="cred_key"
        ),
    ],
)
def test_rejects_environment_when_fault_given(
    change: dict[str, Any], loc: tuple[str | int, ...]
) -> None:
    environment = {**a_live_environment(), **change}

    assert error_locs(Environment, environment) == [loc]


def test_rejects_environment_when_access_missing() -> None:
    environment = a_live_environment()
    del environment["access"]

    assert error_locs(Environment, environment) == [("access",)]


def error_messages(model: type[Any], data: object) -> list[tuple[tuple[str | int, ...], str]]:
    with pytest.raises(ValidationError) as caught:
        model.model_validate(data)
    return [(error["loc"], error["msg"]) for error in caught.value.errors()]


@pytest.mark.parametrize(
    ("url", "part"),
    [
        # Split, so the host grep of AC-277.26 reads no user info as a host.
        pytest.param("https://" + "u:pw@db.example.com", "pw", id="user_info"),
        pytest.param("https://api.example.com/?token=x", "token=x", id="query"),
        pytest.param("https://api.example.com/#k", "#k", id="fragment"),
        pytest.param("https://api.example.com/" + "a" * 177, "a" * 177, id="201_chars"),
        pytest.param("https://api.example.com/a b", "a b", id="space"),
        pytest.param("api.example.com", "api.example.com", id="no_scheme"),
    ],
)
def test_rejects_endpoint_when_url_holds_secret_part(url: str, part: str) -> None:
    messages = error_messages(Endpoint, {"url": url})

    assert [loc for loc, _ in messages] == [("url",)]
    assert all(part not in message for _, message in messages)


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8000", "https://api.example.com", "https://api.example.com/v1/x-y_z.json"],
)
def test_loads_endpoint_when_url_plain(url: str) -> None:
    assert Endpoint.model_validate({"url": url}).url == url


def test_loads_endpoint_when_resource_given() -> None:
    endpoint = Endpoint.model_validate({"resource": "demo-orders-staging", "note": "a table"})

    assert (endpoint.url, endpoint.resource, endpoint.note) == (
        None,
        "demo-orders-staging",
        "a table",
    )


@pytest.mark.parametrize("data", [{}, {"note": "a table"}, {"url": None}])
def test_rejects_endpoint_when_neither_url_nor_resource(data: dict[str, Any]) -> None:
    assert error_locs(Endpoint, data) == [("url",)]


@pytest.mark.parametrize(
    ("model", "data", "loc", "secret", "kind"),
    [
        pytest.param(
            Endpoint,
            {"resource": "t", "note": f"key {AWS_KEY}"},
            ("note",),
            AWS_KEY,
            "AWS access key",
            id="note_aws",
        ),
        pytest.param(
            Endpoint, {"resource": "t", "note": JWT}, ("note",), JWT, "JWT", id="note_jwt"
        ),
        pytest.param(
            Service,
            {"description": f"uses {JWT}"},
            ("description",),
            JWT,
            "JWT",
            id="service_description_jwt",
        ),
        pytest.param(
            Environment,
            {"access": "read", "description": AWS_KEY},
            ("description",),
            AWS_KEY,
            "AWS access key",
            id="environment_description_aws",
        ),
        pytest.param(
            Environment,
            {"access": "read", "credentials": {"aws_profile": AWS_KEY}},
            ("credentials", "aws_profile"),
            AWS_KEY,
            "AWS access key",
            id="aws_profile_aws",
        ),
        pytest.param(
            Endpoint,
            {"url": f"https://api.example.com/{AWS_KEY}"},
            ("url",),
            AWS_KEY,
            "AWS access key",
            id="url_aws",
        ),
    ],
)
def test_rejects_text_when_secret_shape_given(
    model: type[Any], data: dict[str, Any], loc: tuple[str | int, ...], *, secret: str, kind: str
) -> None:
    messages = error_messages(model, data)

    assert [where for where, _ in messages] == [loc]
    assert all(kind in message and secret not in message for _, message in messages)


@pytest.mark.parametrize("kind", ["Api", "dynamo_db", "-api", "a" * 33, ""])
def test_rejects_service_when_kind_not_kebab(kind: str) -> None:
    assert error_locs(Service, {"kind": kind}) == [("kind",)]


def test_loads_service_when_endpoints_given() -> None:
    document = an_environments_document()
    service = Service.model_validate(document["repos"][0]["services"]["api"])

    assert service.kind == "api"
    assert list(service.endpoints) == ["local", "staging", "live"]
    assert service.endpoints["live"].url == "https://api.example.com"
