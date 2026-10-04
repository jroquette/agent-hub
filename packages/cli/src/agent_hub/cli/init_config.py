"""The ``hub.json`` that ``hub init`` builds from its flags, and the flag behind each problem.

The document holds exactly the keys of spec Q-7: ``$schema``, ``schema_version``, the running
release as the pin, the five ``project`` values, ``tracker`` and ``repos``. Defaults
(``default_branch``, labels, ``guard``, ``modules``, ``doctor``) are left out, so the file says
only what the user chose. A value that is still missing is left out too: it is then reported as
required, and every missing flag is named in the same run (Q-10). The document is checked with
``check_flag_document``, and ``flag_problems`` prints each problem as ``<flag>: <message>``.
"""

import json
import re
from collections.abc import Collection, Sequence
from typing import Final

from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig, Project
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_config.versions import find_version_problem
from agent_hub.core.json_form import JsonValue

SCHEMA_URI: Final = "./hub.schema.json"
SCHEMA_VERSION: Final = 1
REPO_ROLE: Final = "app"
REPO_CHECK_FAST: Final = "make check-fast"
REPO_CHECK: Final = "make check"
# How the help names the positional argument that holds ``project.name``.
PROJECT_ARGUMENT: Final = "PROJECT"
REPOS_FLAG: Final = "--repos"
# A problem inside one ``--repos`` item: its index, and the field after it.
_REPO_ITEM: Final = re.compile(r"repos\[(?P<index>\d+)\](?:\.(?P<field>.+))?")
# A ``repos[<i>]`` cited inside a message, such as the item a dir clashes with.
_CITED_ITEM: Final = re.compile(r"repos\[(?P<index>\d+)\]")
# Optional in hub.json (a team hub sets none: each developer's come from hub.local.json or git
# config), but a hub made from flags is one developer's, so ``hub init`` still asks for each.
IDENTITY_KEYS: Final = ("branch_prefix", "author_name", "author_email")
_REQUIRED: Final = "Field required"
# The first key of a JSON path (``repos`` of ``repos[0].dir``, ``$schema``).
_FIRST_KEY: Final = re.compile(r"[^.\[]+")
_TOP_KEYS: Final = tuple(field.alias or name for name, field in HubConfig.model_fields.items())
_PROJECT_KEYS: Final = tuple(Project.model_fields)


def document_from_flags(
    *,
    project: str,
    repos: str,
    tracker: str,
    branch_prefix: str | None,
    author_name: str | None,
    author_email: str | None,
    hub_repo: str | None,
    version: str,
) -> dict[str, JsonValue]:
    """The ``hub.json`` document of these flag values, pinned to ``version``; None is missing.

    ``repos`` is ``owner/name`` items split on ``,`` in order, each one's ``dir`` the part after
    its last ``/``. ``tracker`` is ``kind:team`` split on the first ``:``; with no ``:`` the
    value is the kind, so ``--tracker linear`` reports only the missing team.
    """
    optional = {
        "hub_repo": hub_repo,
        "branch_prefix": branch_prefix,
        "author_name": author_name,
        "author_email": author_email,
    }
    project_values: dict[str, JsonValue] = {"name": project}
    project_values |= {key: value for key, value in optional.items() if value is not None}
    return {
        "$schema": SCHEMA_URI,
        "schema_version": SCHEMA_VERSION,
        "platform": {"version": version},
        "project": project_values,
        "tracker": _tracker(tracker),
        "repos": [_repo(github) for github in _repo_items(repos)],
    }


def check_flag_document(
    document: dict[str, JsonValue], *, running_version: str
) -> HubConfig | tuple[ConfigProblem, ...]:
    """``check_hub_document``, plus ``Field required`` for each identity key the flags left out.

    A version problem stays the only one, as there. The problems keep the model's order: by
    top-level key, then by ``Project`` field, so the identity lines sit where the model put them
    when it required the keys.
    """
    version_problem = find_version_problem(document, running_version=running_version)
    if version_problem is not None:
        return (version_problem,)
    checked = check_hub_document(document, running_version=running_version)
    project = document.get("project")
    missing = [
        ConfigProblem(f"project.{key}", _REQUIRED)
        for key in IDENTITY_KEYS
        if isinstance(project, dict) and key not in project
    ]
    if not missing:
        return checked
    problems = () if isinstance(checked, HubConfig) else checked
    return tuple(sorted([*problems, *missing], key=_model_order))


def _model_order(problem: ConfigProblem) -> tuple[int, int]:
    """Where the model validates the problem's key: its top-level key, then its project field."""
    top = _FIRST_KEY.match(problem.path)
    if top is None or top[0] not in _TOP_KEYS:
        return (len(_TOP_KEYS), 0)
    rest = problem.path[top.end() :]
    field = _FIRST_KEY.match(rest[1:]) if top[0] == "project" and rest.startswith(".") else None
    if field is None or field[0] not in _PROJECT_KEYS:
        return (_TOP_KEYS.index(top[0]), -1)
    return (_TOP_KEYS.index(top[0]), _PROJECT_KEYS.index(field[0]))


def flag_problems(problems: Sequence[ConfigProblem], *, repos: str) -> list[str]:
    """One ``<flag>: <message>`` line per problem, the flag found from the problem's JSON path.

    A problem in one ``--repos`` item names it as ``--repos item <n> (<value>)``: its 1-based
    position and the item as typed, JSON-quoted; a ``repos[<i>]`` the message cites reads as
    ``item <i+1>`` too (``--config`` keeps the JSON path). An item's ``dir`` line is dropped
    when its ``github`` failed too: the dir is derived from it, and the user never typed it. A
    path no flag sets (the pin is the running release) is printed as the path itself.
    """
    items = _repo_items(repos)
    paths = {problem.path for problem in problems}
    return [
        f"{_flag(problem.path, items=items)}: {_CITED_ITEM.sub(_item_number, problem.message)}"
        for problem in problems
        if not _is_dir_of_failed_github(problem.path, paths=paths)
    ]


def _item_number(cited: re.Match[str]) -> str:
    return f"item {int(cited['index']) + 1}"


def _repo_items(repos: str) -> list[str]:
    return repos.split(",")


def _is_dir_of_failed_github(path: str, *, paths: Collection[str]) -> bool:
    item = _REPO_ITEM.fullmatch(path)
    return item is not None and item["field"] == "dir" and f"repos[{item['index']}].github" in paths


def _tracker(value: str) -> dict[str, JsonValue]:
    kind, _, team = value.partition(":")
    # No colon: the value is the kind, and the model names the missing team (owner, E16).
    return {"kind": kind, "team": team}


def _repo(github: str) -> dict[str, JsonValue]:
    return {
        "dir": github.rpartition("/")[2],
        "github": github,
        "role": REPO_ROLE,
        "check_fast": REPO_CHECK_FAST,
        "check": REPO_CHECK,
    }


def _flag(path: str, *, items: Sequence[str]) -> str:
    if path == "project.name":
        return PROJECT_ARGUMENT
    if path.startswith("project."):
        return "--" + path.removeprefix("project.").replace("_", "-")
    if path.startswith("tracker."):
        return "--tracker"
    item = _REPO_ITEM.fullmatch(path)
    if item is not None:
        index = int(item["index"])
        return f"{REPOS_FLAG} item {index + 1} ({json.dumps(items[index])})"
    if path.startswith("repos"):
        return REPOS_FLAG
    return path
