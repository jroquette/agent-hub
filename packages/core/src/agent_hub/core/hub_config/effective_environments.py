"""The developer's environments over the team's: the rules across ``hub.json`` and
``hub.local.json`` (docs/design/environments.md § The developer's layer).

Neither model alone sees both files, so these rules live here: ``hub.local.json`` adds new
environments (never a ``hub.json`` name, names unique ignoring case across both files), adds
endpoints on local environments to ``hub.json``'s repos and services, and on a committed name
holds only ``access``, stricter than the team's (``write`` → ``ask`` → ``read``). Nothing in it
loosens or removes what ``hub.json`` declares. The CLI and doctor's ``config.schema`` report the
problems at the local file's paths.
"""

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.core.hub_config.environments import Access, Credentials, Endpoint, Service
from agent_hub.core.hub_config.local_config import LocalConfig, LocalEnvironment, LocalRepo
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem, json_path

HUB_FILE: Final = "hub.json"
LOCAL_FILE: Final = "hub.local.json"
# Higher is stricter: a local ``access`` must rank above the committed one.
STRICTNESS: Final[Mapping[Access, int]] = {"write": 0, "ask": 1, "read": 2}
NEEDS_ACCESS_MESSAGE: Final = "a new environment needs an access: read, write or ask"

type Location = tuple[str | int, ...]


class SourcedEnvironment(BaseModel):
    """An effective environment and its source: the file its effective ``access`` comes from."""

    model_config = ConfigDict(frozen=True)

    name: str
    access: Access
    production: bool
    description: str | None
    credentials: Credentials | None
    source: str


class SourcedEndpoint(BaseModel):
    """A service's endpoint in one environment, and the file that declares it."""

    model_config = ConfigDict(frozen=True)

    environment: str
    endpoint: Endpoint
    source: str


class SourcedService(BaseModel):
    """A repo's service with its endpoints from both files, the committed ones first."""

    model_config = ConfigDict(frozen=True)

    repo: str
    name: str
    kind: str | None
    description: str | None
    endpoints: tuple[SourcedEndpoint, ...]


class LayeredEntry(BaseModel):
    """A blocked word, glob or variable name, and the first layer that lists it."""

    model_config = ConfigDict(frozen=True)

    value: str
    layer: str


class EffectiveEnvironments(BaseModel):
    """The union of both files: committed entries first, then the developer's (P-5)."""

    model_config = ConfigDict(frozen=True)

    environments: tuple[SourcedEnvironment, ...]
    services: tuple[SourcedService, ...]
    blocked_words: tuple[LayeredEntry, ...]
    blocked_files: tuple[LayeredEntry, ...]
    blocked_env: tuple[LayeredEntry, ...]


def effective_environments(config: HubConfig, local: LocalConfig) -> EffectiveEnvironments:
    """The merged view of ``config`` and ``local``, which ``local_environment_problems`` has
    passed; a local entry those rules refuse is not shown here."""
    return EffectiveEnvironments(
        environments=_environments(config, local),
        services=tuple(_services(config, local)),
        blocked_words=_layered(config.guard.blocked_words, local.guard.blocked_words),
        blocked_files=_layered(config.guard.blocked_words_files, local.guard.blocked_words_files),
        blocked_env=_layered(config.guard.blocked_words_env, local.guard.blocked_words_env),
    )


def _environments(config: HubConfig, local: LocalConfig) -> tuple[SourcedEnvironment, ...]:
    committed = []
    for name, environment in config.environments.items():
        tightened = local.environments.get(name)
        access, source = environment.access, HUB_FILE
        stricter = tightened.access if tightened is not None else None
        if stricter is not None and STRICTNESS[stricter] > STRICTNESS[access]:
            access, source = stricter, LOCAL_FILE
        committed.append(
            SourcedEnvironment(
                name=name,
                access=access,
                production=environment.production,
                description=environment.description,
                credentials=environment.credentials,
                source=source,
            )
        )
    folded = {name.lower() for name in config.environments}
    own = [
        SourcedEnvironment(
            name=name,
            access=environment.access,
            production=bool(environment.production),
            description=environment.description,
            credentials=environment.credentials,
            source=LOCAL_FILE,
        )
        for name, environment in local.environments.items()
        if name.lower() not in folded and environment.access is not None
    ]
    return (*committed, *own)


def _services(config: HubConfig, local: LocalConfig) -> Iterator[SourcedService]:
    own_environments = set(local.environments) - set(config.environments)
    for repo in config.repos:
        local_services: dict[str, Service] = {}
        for local_repo in local.repos:
            if local_repo.dir == repo.dir:
                local_services.update(local_repo.services)
        for name, service in repo.services.items():
            yield _sourced(
                repo.dir,
                name,
                committed=service,
                own=local_services.get(name),
                own_environments=own_environments,
            )
        for name, service in local_services.items():
            if name not in repo.services:
                yield _sourced(
                    repo.dir,
                    name,
                    committed=None,
                    own=service,
                    own_environments=own_environments,
                )


def _sourced(
    repo: str,
    name: str,
    *,
    committed: Service | None,
    own: Service | None,
    own_environments: set[str],
) -> SourcedService:
    # The committed service's kind and description; a local one's only when it is new.
    first = committed or own or Service()
    endpoints = [
        SourcedEndpoint(environment=environment, endpoint=endpoint, source=HUB_FILE)
        for environment, endpoint in (committed.endpoints if committed else {}).items()
    ]
    endpoints.extend(
        SourcedEndpoint(environment=environment, endpoint=endpoint, source=LOCAL_FILE)
        for environment, endpoint in (own.endpoints if own else {}).items()
        if environment in own_environments
    )
    return SourcedService(
        repo=repo,
        name=name,
        kind=first.kind,
        description=first.description,
        endpoints=tuple(endpoints),
    )


def _layered(committed: Iterable[str], own: Iterable[str]) -> tuple[LayeredEntry, ...]:
    """Each entry once, by exact text, with the first layer listing it."""
    entries: dict[str, str] = {}
    for layer, values in ((HUB_FILE, committed), (LOCAL_FILE, own)):
        for value in values:
            entries.setdefault(value, layer)
    return tuple(LayeredEntry(value=value, layer=layer) for value, layer in entries.items())


def local_environment_problems(config: HubConfig, local: LocalConfig) -> tuple[ConfigProblem, ...]:
    """The problems of ``local``'s environments, repos and services against ``config``."""
    return tuple(
        ConfigProblem(json_path(loc), message)
        for loc, message in (*_environment_problems(config, local), *_repo_problems(config, local))
    )


def _environment_problems(config: HubConfig, local: LocalConfig) -> Iterator[tuple[Location, str]]:
    first_name = {name.lower(): (name, HUB_FILE) for name in config.environments}
    for name, environment in local.environments.items():
        loc: Location = ("environments", name)
        if name in config.environments:
            yield from _tightening_problems(loc, config.environments[name].access, environment)
            continue
        folded = name.lower()
        if folded in first_name:
            first, source = first_name[folded]
            yield (
                loc,
                f"environment name {json.dumps(name)} is already used by {json.dumps(first)}"
                f" in {source}, ignoring case",
            )
            continue
        first_name[folded] = (name, LOCAL_FILE)
        if environment.access is None:
            yield (*loc, "access"), NEEDS_ACCESS_MESSAGE


def _tightening_problems(
    loc: Location, committed: Access, environment: LocalEnvironment
) -> Iterator[tuple[Location, str]]:
    name = loc[-1]
    for key in sorted(environment.model_fields_set - {"access"}):
        yield (*loc, key), f"hub.json declares {name}; hub.local.json may only tighten its access"
    access = environment.access
    if access is not None and STRICTNESS[access] <= STRICTNESS[committed]:
        yield (*loc, "access"), f"may only tighten hub.json's {committed}"


def _repo_problems(config: HubConfig, local: LocalConfig) -> Iterator[tuple[Location, str]]:
    repos = {repo.dir: repo for repo in config.repos}
    for index, local_repo in enumerate(local.repos):
        committed = repos.get(local_repo.dir)
        if committed is None:
            yield (
                ("repos", index, "dir"),
                f"repo dir {json.dumps(local_repo.dir)} is not in hub.json's repos",
            )
            continue
        yield from _service_problems(
            config, local, index=index, local_repo=local_repo, committed=committed.services
        )


def _service_problems(
    config: HubConfig,
    local: LocalConfig,
    *,
    index: int,
    local_repo: LocalRepo,
    committed: Mapping[str, Service],
) -> Iterator[tuple[Location, str]]:
    for name, service in local_repo.services.items():
        loc: Location = ("repos", index, "services", name)
        if name in committed:
            for key in sorted(service.model_fields_set - {"endpoints"}):
                yield (
                    (*loc, key),
                    f"hub.json declares {name}; hub.local.json may only add its endpoints",
                )
        for environment in service.endpoints:
            if environment in config.environments:
                yield (
                    (*loc, "endpoints", environment),
                    f"{environment} is declared in hub.json; a local endpoint names a local"
                    " environment",
                )
            elif environment not in local.environments:
                yield (
                    (*loc, "endpoints", environment),
                    f"environment {json.dumps(environment)} is not in environments",
                )
