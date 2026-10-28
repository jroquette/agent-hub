"""The pure edits ``hub repo`` makes to the ``repos`` of a parsed ``hub.json``.

Each edit takes the parsed document and returns a new one, the document given left as it is, or
every ``EditRefusal`` it finds, each at the JSON path it is about. Every other key and the key
order are kept: a new repo goes last, a new key last in its entry. Whether the result is a valid
file is not checked here: the caller validates it with the same checks as a read, which refuse a
bad ``github``, ``check``, ``dir`` or timeout. A dir given by the caller is echoed only when it
is a valid name without a secret's shape (``shown_name``).
"""

import copy
from collections.abc import Collection, Iterator, Mapping
from typing import Final

from agent_hub.core.hub_config.environment_edits import Document, EditRefusal, shown_name
from agent_hub.core.hub_config.problems import json_path
from agent_hub.core.json_form import JsonValue

# The model's key order (``Repo``), which a new entry is written in.
REPO_KEY_ORDER: Final = (
    "dir",
    "github",
    "role",
    "check_fast",
    "check_fast_timeout",
    "check",
    "default_branch",
)

# The optional keys ``hub repo`` sets, which ``--unset`` removes; ``hub.json`` needs the others.
UNSET_KEYS: Final = ("role", "check_fast", "check_fast_timeout", "default_branch")
_REQUIRED_KEYS: Final = ("dir", "github", "check")

type Edited = Document | tuple[EditRefusal, ...]


def add_repo(document: Document, entry: Mapping[str, JsonValue]) -> Edited:
    """``document`` with ``entry`` last in ``repos``, its keys in ``REPO_KEY_ORDER`` (any other
    key left out).

    Refused when a repo's dir equals the entry's ignoring case (one folder on macOS).
    """
    new_dir = str(entry.get("dir"))
    for index, existing in enumerate(_dirs(document)):
        if existing is not None and existing.lower() == new_dir.lower():
            return (
                EditRefusal(
                    f"repo dir {shown_name(new_dir)} is already used by repos[{index}]"
                    f" ({shown_name(existing)}), ignoring case",
                    json_path(("repos", index, "dir")),
                ),
            )
    ordered: Document = {key: entry[key] for key in REPO_KEY_ORDER if key in entry}
    edited = copy.deepcopy(document)
    repos = edited.get("repos")
    repos = repos if isinstance(repos, list) else []
    repos.append(ordered)
    edited["repos"] = repos
    return edited


def set_repo(
    document: Document,
    repo: str,
    changes: Mapping[str, JsonValue],
    *,
    unset: Collection[str] = (),
) -> Edited:
    """``document`` with ``changes`` made to the repo whose dir is ``repo`` and its ``unset``
    keys removed: a key present keeps its place, a new one goes last in the entry.

    Refused for a dir no repo has exactly, and for each ``unset`` key that ``hub.json`` needs,
    that is not one of ``UNSET_KEYS`` or that ``changes`` also sets.
    """
    index = _index(document, repo)
    if isinstance(index, EditRefusal):
        return (index,)
    refusals = tuple(
        refusal for key in unset if (refusal := _unset_refusal(key, index, changes)) is not None
    )
    if refusals:
        return refusals
    edited = copy.deepcopy(document)
    entry = _entry(edited, index)
    entry.update(changes)
    for key in unset:
        entry.pop(key, None)
    return edited


def remove_repo(document: Document, repo: str, *, local_document: Document | None) -> Edited:
    """``document`` without the repo whose dir is ``repo``, its ``services`` with it.

    Refused for a dir no repo has exactly, for the only repo, and while ``repo_references``
    finds the dir in ``document`` or ``local_document`` (the developer's ``hub.local.json``,
    ``None`` when there is none): then every reference is returned, none is edited.
    """
    index = _index(document, repo)
    if isinstance(index, EditRefusal):
        return (index,)
    if len(_dirs(document)) == 1:
        return (
            EditRefusal(
                f"{shown_name(repo)} is the only repo; hub.json needs at least one",
                json_path(("repos",)),
            ),
        )
    if refusals := repo_references(document, local_document, repo):
        return refusals
    edited = copy.deepcopy(document)
    repos = edited["repos"]
    if isinstance(repos, list):
        del repos[index]
    return edited


def repo_references(
    document: Document, local_document: Document | None, repo: str
) -> tuple[EditRefusal, ...]:
    """A refusal for each place that names the dir ``repo``, at its path: a guarded or denied
    path whose first segment is the dir (a denied one ignoring case), an event's repo,
    ``contract-sync``'s source or target, then each ``repos`` entry of the developer's
    ``hub.local.json``."""
    shown = shown_name(repo)
    hub_paths = (
        *_guard_paths(document, repo),
        *_event_paths(document, repo),
        *_contract_sync_paths(document, repo),
    )
    local_paths = (
        json_path(("repos", index, "dir"))
        for index, found in enumerate(_dirs(local_document or {}))
        if found == repo
    )
    return (
        *(EditRefusal(f"repo {shown} is still named at {path}", path) for path in hub_paths),
        *(
            EditRefusal(f"repo {shown} is still named in hub.local.json at {path}", path)
            for path in local_paths
        ),
    )


def _guard_paths(document: Document, repo: str) -> Iterator[str]:
    """The guarded paths whose first segment is ``repo``: exactly for ``ask_before_edit`` (as
    the model checks it), ignoring case for ``deny_paths`` (as the guard matches it)."""
    guard = _object(document, "guard")
    for key, fold in (("ask_before_edit", False), ("deny_paths", True)):
        for index, path in enumerate(_list(guard, key)):
            if not isinstance(path, str):
                continue
            first = path.split("/", 1)[0]
            if first == repo or (fold and first.lower() == repo.lower()):
                yield json_path(("guard", key, index))


def _event_paths(document: Document, repo: str) -> Iterator[str]:
    for index, event in enumerate(_list(document, "events")):
        if isinstance(event, dict) and event.get("repo") == repo:
            yield json_path(("events", index, "repo"))


def _contract_sync_paths(document: Document, repo: str) -> Iterator[str]:
    settings = _object(_object(document, "modules"), "contract-sync")
    for key in ("source", "target"):
        if settings.get(key) == repo:
            yield json_path(("modules", "contract-sync", key))


def _object(parent: Document, key: str) -> Document:
    found = parent.get(key)
    return found if isinstance(found, dict) else {}


def _list(parent: Document, key: str) -> list[JsonValue]:
    found = parent.get(key)
    return found if isinstance(found, list) else []


def _index(document: Document, repo: str) -> int | EditRefusal:
    """The index of the repo whose dir is exactly ``repo``, else why there is none."""
    dirs = _dirs(document)
    if repo in dirs:
        return dirs.index(repo)
    missing = f"no repo {shown_name(repo)} in hub.json"
    for existing in dirs:
        if existing is not None and existing.lower() == repo.lower():
            return EditRefusal(f"{missing}; did you mean {shown_name(existing)}?")
    return EditRefusal(missing)


def _unset_refusal(key: str, index: int, changes: Mapping[str, JsonValue]) -> EditRefusal | None:
    path = json_path(("repos", index, key))
    if key in _REQUIRED_KEYS:
        return EditRefusal(f"{key} cannot be unset: hub.json needs it", path)
    if key not in UNSET_KEYS:
        return EditRefusal(f"{shown_name(key)} is not a key --unset takes: {', '.join(UNSET_KEYS)}")
    if key in changes:
        return EditRefusal(f"{key} is both set and unset", path)
    return None


def _entry(document: Document, index: int) -> Document:
    """The repo at ``index`` of ``document`` (the same object, to edit in place); ``_index``
    found an object there, so the empty fallback only satisfies the type."""
    repos = document["repos"]
    entry = repos[index] if isinstance(repos, list) else None
    return entry if isinstance(entry, dict) else {}


def _dirs(document: Document) -> list[str | None]:
    """The ``dir`` of each item of ``repos``, by index; ``None`` for an item without one."""
    repos = document.get("repos")
    entries = repos if isinstance(repos, list) else []
    return [_dir_of(entry) for entry in entries]


def _dir_of(entry: JsonValue) -> str | None:
    found = entry.get("dir") if isinstance(entry, dict) else None
    return found if isinstance(found, str) else None
