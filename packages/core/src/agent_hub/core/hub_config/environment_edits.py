"""The pure edits ``hub env`` makes to a parsed ``hub.json`` or ``hub.local.json``.

Each edit takes the parsed document and returns a new one, the document given left as it is, or
an ``EditRefusal`` naming why (docs/design/environments.md § ``hub env``). Every other key and
the key order are kept: a new entry goes last in its map, and a map an edit empties is dropped,
so an add followed by its remove gives the document back. Whether the result is a valid file is
not checked here: the caller validates it with the same checks as a read. A name starting
with ``_`` is a comment key, never a name: every edit refuses one. A name given by the
caller is echoed in a refusal only when it is a valid name without a secret's shape.

A rename keeps the key's place in its map: ``rename_environment`` also moves every endpoint the
same document keys by the old name, ``set_service`` renames a service in its repo. Neither looks
at the other file: the caller renames there too when that file holds the old name.
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
    values: Mapping[str, JsonValue | None] | None = None,
) -> Document | EditRefusal:
    """``document`` with ``changes`` made to the environment ``name``: a key set to ``None`` is
    removed. ``credentials`` and ``values`` change keys of its ``credentials`` and ``values``
    maps the same way (an emptied map is dropped). With ``may_create`` an absent environment is
    added (the developer's setting on a committed one), and dropped again once emptied."""
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
    for key, key_changes in (("credentials", credentials), ("values", values)):
        if key_changes:
            found = _map(entry, key)
            _change(found, key_changes)
            entry[key] = found
            _drop_if_empty(entry, key)
    environments[name] = entry
    edited["environments"] = environments
    if may_create and not entry:
        _drop_if_empty(environments, name)
        _drop_if_empty(edited, "environments")
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
    description: str | None = None,
) -> Document | EditRefusal:
    """``document`` with ``endpoint`` for ``service`` of ``repo`` in ``environment``; the
    service is added when absent, with ``kind`` and ``description`` when given. With
    ``creates_repo`` (the local file), an absent ``repos`` entry is added as ``{dir, services}``,
    for a dir in ``known_repos`` (``hub.json``'s) only."""
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
    if description is not None:
        target["description"] = description
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


def rename_environment(
    document: Document, name: str, new_name: str, *, declared: Collection[str], file: str
) -> Document | EditRefusal:
    """``document`` with the environment ``name`` renamed ``new_name`` in its place, and each
    service's endpoint keyed by ``name`` moved to ``new_name`` in its place.

    Refused when ``new_name`` equals ignoring case another environment of ``document`` or of
    ``declared`` (the other file's names; ``name`` itself is skipped: a change of case renames).
    """
    if refusal := _comment_refusal(name, new_name):
        return refusal
    edited = copy.deepcopy(document)
    environments = _map(edited, "environments")
    if name not in environments:
        return EditRefusal(f"no environment {shown_name(name)} in {file}")
    for existing in (*environment_names(edited), *declared):
        if existing != name and existing.lower() == new_name.lower():
            return EditRefusal(f"environment {shown_name(existing)} is already declared")
    edited["environments"] = _renamed(environments, name, new_name)
    for entry in _repos(edited):
        services = _map(entry, "services")
        for service in services.values():
            if isinstance(service, dict) and name in _map(service, "endpoints"):
                service["endpoints"] = _renamed(_map(service, "endpoints"), name, new_name)
    return edited


def set_service(
    document: Document,
    *,
    repo: str,
    service: str,
    changes: Mapping[str, JsonValue | None],
    new_name: str | None,
    taken: Collection[str],
    file: str,
) -> Document | EditRefusal:
    """``document`` with ``changes`` made to ``service`` of ``repo`` (a key set to ``None`` is
    removed), then renamed ``new_name`` in its place when given.

    Refused when ``new_name`` is another service of that repo in ``document`` or in ``taken``
    (the other file's names for that repo).
    """
    if refusal := _comment_refusal(repo, service, new_name):
        return refusal
    edited = copy.deepcopy(document)
    entry = _repo(edited, repo)
    if entry is None:
        return EditRefusal(f"no repo {shown_name(repo)} in {file}")
    services = _map(entry, "services")
    target = services.get(service)
    if not isinstance(target, dict):
        return EditRefusal(f"no service {shown_name(service)} on {repo} in {file}")
    _change(target, changes)
    if new_name is not None and new_name != service:
        if new_name in services or new_name in taken:
            return EditRefusal(f"{repo} already has a service {shown_name(new_name)}")
        entry["services"] = _renamed(services, service, new_name)
    return edited


def environment_names(document: Document) -> list[str]:
    """The environment names of ``document``, comment keys left out."""
    return [key for key in _map(document, "environments") if not key.startswith("_")]


def repo_dirs(document: Document) -> list[str]:
    """The ``dir`` of each repo of ``document``."""
    return [str(entry.get("dir")) for entry in _repos(document)]


def service_names(document: Document, repo: str) -> list[str]:
    """The service names of ``repo`` in ``document`` (none when it has no such repo)."""
    entry = _repo(document, repo)
    services = _map(entry, "services") if entry is not None else {}
    return [key for key in services if not key.startswith("_")]


def _renamed(found: Document, name: str, new_name: str) -> Document:
    """``found`` with the key ``name`` renamed ``new_name`` in its place."""
    return {new_name if key == name else key: value for key, value in found.items()}


def _repos(document: Document) -> list[Document]:
    repos = document.get("repos")
    return [entry for entry in repos if isinstance(entry, dict)] if isinstance(repos, list) else []


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
