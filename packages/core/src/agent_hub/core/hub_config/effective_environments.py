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
from collections.abc import Iterator, Mapping
from typing import Final

from agent_hub.core.hub_config.environments import Access, Service
from agent_hub.core.hub_config.local_config import LocalConfig, LocalEnvironment, LocalRepo
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem, json_path

HUB_FILE: Final = "hub.json"
LOCAL_FILE: Final = "hub.local.json"
# Higher is stricter: a local ``access`` must rank above the committed one.
STRICTNESS: Final[Mapping[Access, int]] = {"write": 0, "ask": 1, "read": 2}
NEEDS_ACCESS_MESSAGE: Final = "a new environment needs an access: read, write or ask"

type Location = tuple[str | int, ...]


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
