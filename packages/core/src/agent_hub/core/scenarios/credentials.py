"""Which credentials an action's process gets, and which every other child loses
(docs/design/scenarios.md § Credentials, ADR 0041).

Only names come from the config: ``credentials.env`` names a variable of the developer's own
environment, ``aws_profile`` a profile, ``env_file`` a dotenv file the action runner reads. An
action's process gets every variable of the env file, ``AWS_PROFILE`` from ``aws_profile`` and
each ``credentials.env`` name the developer's environment holds; the endpoint's credentials win
over the environment's when the action's endpoints declare exactly one set. Every other child (an
agent session, a shell, script or ``until_bash`` node) gets an environment without the declared
names and without an ``AWS_PROFILE`` naming a declared profile (``hidden_environment``).
"""

from collections.abc import Iterable, Mapping
from typing import Final, Self

from pydantic import BaseModel, ConfigDict

from agent_hub.core.errors import AgentHubError
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    SourcedEnvironment,
)
from agent_hub.core.hub_config.environments import Credentials, Endpoint

AWS_PROFILE: Final = "AWS_PROFILE"


class CredentialsError(AgentHubError):
    """An action's credentials cannot be chosen: its endpoints declare different sets."""


class CredentialNames(BaseModel):
    """The credential names both config files declare, on environments and endpoints."""

    model_config = ConfigDict(frozen=True)

    env: frozenset[str] = frozenset()
    aws_profiles: frozenset[str] = frozenset()

    @classmethod
    def of(cls, view: EffectiveEnvironments) -> Self:
        declared = [environment.credentials for environment in view.environments]
        declared.extend(
            endpoint.endpoint.credentials
            for service in view.services
            for endpoint in service.endpoints
        )
        found = [credentials for credentials in declared if credentials is not None]
        return cls(
            env=frozenset(name for credentials in found for name in credentials.env),
            aws_profiles=frozenset(
                credentials.aws_profile for credentials in found if credentials.aws_profile
            ),
        )


NO_CREDENTIALS: Final = CredentialNames()


def hidden_environment(environ: Mapping[str, str], names: CredentialNames) -> dict[str, str]:
    """``environ`` without the declared ``credentials.env`` names, and without ``AWS_PROFILE``
    when it names a declared profile (another profile is the developer's own and stays)."""
    return {
        name: value
        for name, value in environ.items()
        if name not in names.env and not (name == AWS_PROFILE and value in names.aws_profiles)
    }


def credentials_for(
    environment: SourcedEnvironment, endpoints: Iterable[Endpoint]
) -> Credentials | None:
    """The credentials of an action bound to ``environment`` that uses ``endpoints``: the one
    set its endpoints declare, else the environment's; raises ``CredentialsError`` when the
    endpoints declare two different sets."""
    declared: list[Credentials] = []
    for endpoint in endpoints:
        if endpoint.credentials is not None and endpoint.credentials not in declared:
            declared.append(endpoint.credentials)
    if len(declared) > 1:
        msg = (
            f"environment {environment.name}: the action's endpoints declare different credentials"
        )
        raise CredentialsError(msg)
    return declared[0] if declared else environment.credentials


def action_credentials(
    credentials: Credentials | None,
    *,
    environ: Mapping[str, str],
    env_file_values: Mapping[str, str],
) -> dict[str, str]:
    """What an action's process gets on top of its plain environment: every variable of the
    env file, then ``AWS_PROFILE`` from ``aws_profile`` and each ``credentials.env`` name
    ``environ`` holds (the declared ones win over a same-named file variable)."""
    injected = dict(env_file_values)
    if credentials is None:
        return injected
    if credentials.aws_profile is not None:
        injected[AWS_PROFILE] = credentials.aws_profile
    injected.update({name: environ[name] for name in credentials.env if name in environ})
    return injected
