"""The lines the CLI prints about declared environments (docs/design/environments.md).

``list_lines`` and ``show_lines`` are ``hub env list`` and ``hub env show``'s text, and
``environments_json`` and ``environment_json`` their ``--json`` data: names, access, sources and
credential names, never a credential value (the files hold none).

``production_line`` is the one explicit line a production environment gets wherever a command
names it (``hub sync``, ``hub env``, later ``hub setup``): its name, its effective access and
the file that access comes from. ``production_lines`` gives one per production environment of an
effective view, committed ones first. Only the ``production`` flag counts, never a name.
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    LayeredEntry,
    SourcedEndpoint,
    SourcedEnvironment,
)
from agent_hub.core.hub_config.environments import Credentials
from agent_hub.core.json_form import JsonValue

# The names are suggestions only: nothing is declared, and no behaviour comes from a name.
NO_ENVIRONMENTS_LINE: Final = (
    "no environments declared; for example: ./hub env add local --access write"
    " (suggested names: local, staging, production)"
)
_LOCAL_FILE: Final = "hub.local.json"


def production_line(name: str, access: str, source: str) -> str:
    """``production environment: <name> (access <access>, <source>)``."""
    return f"production environment: {name} (access {access}, {source})"


def production_lines(view: EffectiveEnvironments) -> tuple[str, ...]:
    """One line per production environment of ``view``, in its order."""
    return tuple(
        production_line(environment.name, environment.access, environment.source)
        for environment in view.environments
        if environment.production
    )


def environment_heading(environment: SourcedEnvironment) -> str:
    """``<name> (<access>[, PRODUCTION], <source>)``."""
    flag = ", PRODUCTION" if environment.production else ""
    return f"{environment.name} ({environment.access}{flag}, {environment.source})"


def list_lines(view: EffectiveEnvironments) -> tuple[str, ...]:
    """One line per environment (or the suggestion line), the services, the blocked entries."""
    lines = [
        environment_heading(environment)
        + (f": {environment.description}" if environment.description else "")
        for environment in view.environments
    ] or [NO_ENVIRONMENTS_LINE]
    if view.services:
        lines.append("services:")
    for service in view.services:
        kind = f" ({service.kind})" if service.kind else ""
        names = ", ".join(endpoint.environment for endpoint in service.endpoints) or "no endpoint"
        lines.append(f"  {service.repo} {service.name}{kind}: {names}")
    for label, entries in (
        ("blocked words", view.blocked_words),
        ("blocked files", view.blocked_files),
        ("blocked variables", view.blocked_env),
    ):
        if entries:
            lines.append(f"{label}: " + ", ".join(entry.value for entry in entries))
    return tuple(lines)


def show_lines(view: EffectiveEnvironments, name: str) -> tuple[str, ...] | None:
    """The environment ``name``: its heading, description, credential names and endpoints;
    ``None`` when neither file declares it."""
    environment = _find(view, name)
    if environment is None:
        return None
    lines = [environment_heading(environment)]
    if environment.description:
        lines.append(f"  description: {environment.description}")
    lines.extend(f"  {line}" for line in _credential_lines(environment.credentials))
    endpoints = [
        f"    {repo} {service}: {_endpoint_text(endpoint)}"
        for repo, service, endpoint in _endpoints_in(view, name)
    ]
    lines.extend(["  endpoints:", *endpoints] if endpoints else ["  endpoints: none"])
    return tuple(lines)


def environments_json(view: EffectiveEnvironments) -> JsonValue:
    """``hub env list --json``: every key always present, ``null`` when not set."""
    return {
        "environments": [_environment_object(environment) for environment in view.environments],
        "services": [
            {
                "repo": service.repo,
                "name": service.name,
                "kind": service.kind,
                "description": service.description,
                "endpoints": [_endpoint_object(endpoint) for endpoint in service.endpoints],
            }
            for service in view.services
        ],
        "blocked_words": _entries(view.blocked_words),
        "blocked_files": _entries(view.blocked_files),
        "blocked_env": _entries(view.blocked_env),
    }


def environment_json(view: EffectiveEnvironments, name: str) -> JsonValue:
    """``hub env show --json``: the environment and its endpoints; ``None`` when undeclared."""
    environment = _find(view, name)
    if environment is None:
        return None
    endpoints: list[JsonValue] = [
        {"repo": repo, "service": service, **_endpoint_object(endpoint)}
        for repo, service, endpoint in _endpoints_in(view, name)
    ]
    return {"environment": _environment_object(environment), "endpoints": endpoints}


def _find(view: EffectiveEnvironments, name: str) -> SourcedEnvironment | None:
    return next((item for item in view.environments if item.name == name), None)


def _endpoints_in(
    view: EffectiveEnvironments, name: str
) -> Iterable[tuple[str, str, SourcedEndpoint]]:
    for service in view.services:
        for endpoint in service.endpoints:
            if endpoint.environment == name:
                yield service.repo, service.name, endpoint


def _credential_lines(credentials: Credentials | None) -> list[str]:
    if credentials is None:
        return []
    lines = []
    if credentials.aws_profile is not None:
        lines.append(f"aws profile: {credentials.aws_profile}")
    if credentials.env:
        lines.append("credential variables: " + ", ".join(credentials.env))
    return lines


def _endpoint_text(sourced: SourcedEndpoint) -> str:
    endpoint = sourced.endpoint
    parts = [] if endpoint.url is None else [endpoint.url]
    if endpoint.resource is not None:
        parts.append(f"resource {endpoint.resource}")
    if endpoint.note is not None:
        parts.append(f"note: {endpoint.note}")
    parts.extend(_credential_lines(endpoint.credentials))
    source = f" ({_LOCAL_FILE})" if sourced.source == _LOCAL_FILE else ""
    return ", ".join(parts) + source


def _credentials_object(credentials: Credentials | None) -> JsonValue:
    if credentials is None:
        return None
    return {"aws_profile": credentials.aws_profile, "env": list(credentials.env)}


def _environment_object(environment: SourcedEnvironment) -> dict[str, JsonValue]:
    return {
        "name": environment.name,
        "access": environment.access,
        "production": environment.production,
        "source": environment.source,
        "description": environment.description,
        "credentials": _credentials_object(environment.credentials),
    }


def _endpoint_object(sourced: SourcedEndpoint) -> dict[str, JsonValue]:
    endpoint = sourced.endpoint
    return {
        "environment": sourced.environment,
        "url": endpoint.url,
        "resource": endpoint.resource,
        "note": endpoint.note,
        "credentials": _credentials_object(endpoint.credentials),
        "source": sourced.source,
    }


def _entries(entries: Iterable[LayeredEntry]) -> list[JsonValue]:
    return [{"value": entry.value, "layer": entry.layer} for entry in entries]
