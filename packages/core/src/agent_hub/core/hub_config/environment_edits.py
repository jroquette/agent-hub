"""The pure edits ``hub env`` makes to a parsed ``hub.json`` or ``hub.local.json``.

Each edit takes the parsed document and returns a new one, the document given left as it is, or
an ``EditRefusal`` naming why (docs/design/environments.md § ``hub env``). Every other key and
the key order are kept: a new entry goes last in its map, and a map an edit empties is dropped,
so an add followed by its remove gives the document back. Whether the result is a valid file is
not checked here: the caller validates it with the same checks as a read. A name starting
with ``_`` is a comment key, never a name: every edit refuses one. A name given by the
caller is echoed in a refusal only when it is a valid name without a secret's shape.
"""

import copy
import re
from collections.abc import Collection, Mapping
from typing import Final, NamedTuple

from agent_hub.core.hub_config.environments import MAX_NAME_CHARS
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT
from agent_hub.core.json_form import JsonValue
from agent_hub.core.secret_shapes import secret_kind

type Document = dict[str, JsonValue]

# What a refusal shows in place of a name that is not a valid one or has a secret's shape.
HIDDEN_NAME: Final = "<name>"
_NAME = re.compile(SAFE_SEGMENT)


class EditRefusal(NamedTuple):
    """Why an edit is not made, as one line."""

    message: str


def _comment_refusal(*names: str | None) -> EditRefusal | None:
    """A refusal for the first name that is a comment key (``_`` first), else ``None``."""
    for name in names:
        if name is not None and name.startswith("_"):
            return EditRefusal(
                f"{shown_name(name)}: a name starting with _ is a comment key; choose another name"
            )
    return None


def shown_name(name: str) -> str:
    """``name`` as given when it is a valid name with no secret's shape, else ``<name>``."""
    if len(name) <= MAX_NAME_CHARS and _NAME.fullmatch(name) and secret_kind(name) is None:
        return name
    return HIDDEN_NAME


def add_environment(
    document: Document, name: str, entry: Document, *, declared: Mapping[str, str], file: str
) -> Document | EditRefusal:
    """``document`` with the environment ``name`` added last.

    Refused when a name equal ignoring case is in ``document`` or in ``declared`` (the other
    file's names, each with its file); the refusal names the name already declared.
    """
    if refusal := _comment_refusal(name):
        return refusal
    edited = copy.deepcopy(document)
    environments = _map(edited, "environments")
    taken = {key: file for key in environments if not key.startswith("_")} | dict(declared)
    for existing, source in taken.items():
        if existing.lower() == name.lower():
            return EditRefusal(f"environment {existing} is already declared in {source}")
    environments[name] = entry
    edited["environments"] = environments
    return edited


def set_environment(
    document: Document,
    name: str,
    changes: Mapping[str, JsonValue | None],
    *,
    file: str,
    may_create: bool,
    credentials: Mapping[str, JsonValue | None] | None = None,
) -> Document | EditRefusal:
    """``document`` with ``changes`` made to the environment ``name``: a key set to ``None`` is
    removed. ``credentials`` changes keys of its ``credentials`` the same way (an emptied map is
    dropped). With ``may_create`` an absent environment is added (a local tightening)."""
    if refusal := _comment_refusal(name):
        return refusal
    edited = copy.deepcopy(document)
    environments = _map(edited, "environments")
    entry = environments.get(name)
    if not isinstance(entry, dict):
        if not may_create:
            return EditRefusal(f"no environment {shown_name(name)} in {file}")
        entry = {}
    _change(entry, changes)
    if credentials:
        found = _map(entry, "credentials")
        _change(found, credentials)
        entry["credentials"] = found
        _drop_if_empty(entry, "credentials")
    environments[name] = entry
    edited["environments"] = environments
    return edited


def remove_environment(document: Document, name: str, *, file: str) -> Document | EditRefusal:
    """``document`` without the environment ``name``; refused while an endpoint names it."""
    if refusal := _comment_refusal(name):
        return refusal
    edited = copy.deepcopy(document)
    environments = _map(edited, "environments")
    if name not in environments:
        return EditRefusal(f"no environment {shown_name(name)} in {file}")
    users = [
        f"{repo} {service}" for repo, service, endpoints in _services(edited) if name in endpoints
    ]
    if users:
        return EditRefusal(
            f"environment {name} still has endpoints ({', '.join(users)});"
            " remove them first: ./hub env service remove"
        )
    del environments[name]
    _drop_if_empty(edited, "environments")
    return edited


def add_endpoint(
    document: Document,
    *,
    repo: str,
    service: str,
    environment: str,
    endpoint: Document,
    kind: str | None,
    file: str,
    creates_repo: bool,
    known_repos: Collection[str] = (),
) -> Document | EditRefusal:
    """``document`` with ``endpoint`` for ``service`` of ``repo`` in ``environment``; the
    service is added when absent, with ``kind`` when given. With ``creates_repo`` (the local
    file), an absent ``repos`` entry is added as ``{dir, services}``, for a dir in
    ``known_repos`` (``hub.json``'s) only."""
    if refusal := _comment_refusal(repo, service, environment):
        return refusal
    edited = copy.deepcopy(document)
    entry = _repo(edited, repo)
    if entry is None:
        if not creates_repo:
            return EditRefusal(f"no repo {shown_name(repo)} in {file}")
        if repo not in known_repos:
            return EditRefusal(f"no repo {shown_name(repo)} in hub.json")
        repos = edited.get("repos")
        repos = repos if isinstance(repos, list) else []
        entry = {"dir": repo, "services": {}}
        repos.append(entry)
        edited["repos"] = repos
    services = _map(entry, "services")
    found = services.get(service)
    target: Document = found if isinstance(found, dict) else {}
    if kind is not None:
        target["kind"] = kind
    endpoints = _map(target, "endpoints")
    if environment in endpoints:
        return EditRefusal(f"{repo} {service} already has an endpoint in {shown_name(environment)}")
    endpoints[environment] = endpoint
    target["endpoints"] = endpoints
    services[service] = target
    entry["services"] = services
    return edited


def remove_endpoint(
    document: Document, *, repo: str, service: str, environment: str | None, file: str
) -> Document | EditRefusal:
    """``document`` without ``service``'s endpoint in ``environment``, or without the whole
    service when ``environment`` is ``None``. A map left empty is dropped (a service left with no
    key too), and so is a local ``repos`` entry left with only its ``dir``."""
    if refusal := _comment_refusal(repo, service, environment):
        return refusal
    edited = copy.deepcopy(document)
    entry = _repo(edited, repo)
    if entry is None:
        return EditRefusal(f"no repo {shown_name(repo)} in {file}")
    services = _map(entry, "services")
    target = services.get(service)
    if not isinstance(target, dict):
        return EditRefusal(f"no service {shown_name(service)} on {repo} in {file}")
    if environment is None:
        del services[service]
    else:
        endpoints = _map(target, "endpoints")
        if environment not in endpoints:
            return EditRefusal(
                f"{repo} {service} has no endpoint in {shown_name(environment)} in {file}"
            )
        del endpoints[environment]
        _drop_if_empty(target, "endpoints")
        _drop_if_empty(services, service)
    _drop_if_empty(entry, "services")
    repos = edited["repos"]
    if isinstance(repos, list) and set(entry) == {"dir"}:
        repos.remove(entry)
        _drop_if_empty(edited, "repos")
    return edited


def _change(entry: Document, changes: Mapping[str, JsonValue | None]) -> None:
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value


def _map(parent: Document, key: str) -> Document:
    """``parent[key]`` when it is an object (the same object, to edit in place), else a new one."""
    found = parent.get(key)
    return found if isinstance(found, dict) else {}


def _drop_if_empty(parent: Document, key: str) -> None:
    if key in parent and parent[key] in ({}, []):
        del parent[key]


def _repo(document: Document, repo: str) -> Document | None:
    repos = document.get("repos")
    if not isinstance(repos, list):
        return None
    return next(
        (item for item in repos if isinstance(item, dict) and item.get("dir") == repo), None
    )


def _services(document: Document) -> list[tuple[str, str, Document]]:
    """Each repo dir, service name and endpoints map of ``document``."""
    found = []
    repos = document.get("repos")
    for entry in repos if isinstance(repos, list) else []:
        if not isinstance(entry, dict):
            continue
        for name, service in _map(entry, "services").items():
            if isinstance(service, dict):
                found.append((str(entry.get("dir")), name, _map(service, "endpoints")))
    return found
