"""Which credentials an action gets and which every other child loses (AC-350.9, P-9)."""

import pytest

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
)
from agent_hub.core.hub_config.environments import Credentials, Endpoint
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.scenarios.access_policy import find_environment
from agent_hub.core.scenarios.credentials import (
    CredentialNames,
    CredentialsError,
    action_credentials,
    credentials_for,
    hidden_environment,
)
from agent_hub.core.testing.builders import a_local_environments_document, an_environments_document

SECRET = "x-" + "secret" + "-y"


def a_view() -> EffectiveEnvironments:
    document = an_environments_document()
    document["environments"]["staging"]["credentials"] = {
        "aws_profile": "demo-staging",
        "env": ["DEMO_DB_URL"],
    }
    orders = document["repos"][0]["services"]["orders"]["endpoints"]["staging"]
    orders["credentials"] = {"env": ["DEMO_ORDERS_KEY"]}
    local = LocalConfig.model_validate(a_local_environments_document())
    return effective_environments(HubConfig.model_validate(document), local)


def test_drops_declared_names_when_hidden_environment_built() -> None:
    environ = {
        "PATH": "/bin",
        "DEMO_DB_URL": SECRET,
        "DEMO_LIVE_DB_URL": SECRET,
        "DEMO_ORDERS_KEY": SECRET,
    }

    hidden = hidden_environment(environ, CredentialNames.of(a_view()))

    assert hidden == {"PATH": "/bin"}


@pytest.mark.parametrize("profile", ["demo-staging", "demo-live-ro", "jane-sandbox"])
def test_drops_aws_profile_when_value_is_declared_profile(profile: str) -> None:
    hidden = hidden_environment({"AWS_PROFILE": profile}, CredentialNames.of(a_view()))

    assert hidden == {}


def test_keeps_aws_profile_when_value_undeclared() -> None:
    environ = {"AWS_PROFILE": "demo-dev", "HOME": "/home/demo"}

    assert hidden_environment(environ, CredentialNames.of(a_view())) == environ


def test_prefers_endpoint_credentials_when_both_declared() -> None:
    staging = find_environment(a_view(), "staging")
    assert staging is not None
    endpoint = Endpoint(resource="demo-orders", credentials=Credentials(env=("DEMO_ORDERS_KEY",)))
    plain = Endpoint(url="https://api.staging.example.com")

    assert credentials_for(staging, [plain, endpoint, endpoint]) == endpoint.credentials
    assert credentials_for(staging, [plain]) == staging.credentials


def test_reports_problem_when_endpoints_disagree() -> None:
    staging = find_environment(a_view(), "staging")
    assert staging is not None
    first = Endpoint(resource="a", credentials=Credentials(aws_profile="demo-a"))
    second = Endpoint(resource="b", credentials=Credentials(aws_profile="demo-b"))

    with pytest.raises(CredentialsError) as raised:
        credentials_for(staging, [first, second])

    assert str(raised.value) == (
        "environment staging: the action's endpoints declare different credentials"
    )


def test_injects_every_env_file_variable_when_action_credentials_built() -> None:
    credentials = Credentials(
        aws_profile="demo-staging", env=("DEMO_DB_URL", "DEMO_ABSENT"), env_file="demo-api/.env"
    )
    environ = {"DEMO_DB_URL": SECRET, "PATH": "/bin"}
    from_file = {"DEMO_TOKEN": SECRET + "-2", "AWS_PROFILE": "from-file", "DEMO_REGION": "eu"}

    injected = action_credentials(credentials, environ=environ, env_file_values=from_file)

    assert injected == {
        "DEMO_TOKEN": SECRET + "-2",
        "DEMO_REGION": "eu",
        "AWS_PROFILE": "demo-staging",
        "DEMO_DB_URL": SECRET,
    }
    assert action_credentials(None, environ=environ, env_file_values={}) == {}
