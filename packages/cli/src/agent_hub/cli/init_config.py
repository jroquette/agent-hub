"""The ``hub.json`` that ``hub init`` builds from its flags, and the flag behind each problem.

The document holds exactly the keys of spec Q-7: ``$schema``, ``schema_version``, the running
release as the pin, the five ``project`` values, ``tracker`` and ``repos``. Defaults
(``default_branch``, labels, ``guard``, ``modules``, ``doctor``) are left out, so the file says
only what the user chose. A value that is still missing is left out too: the model then reports
it as required, and every missing flag is named in the same run (Q-10). The document is checked
with ``check_hub_document``, and ``flag_problems`` prints each problem as ``<flag>: <message>``.
"""

from collections.abc import Sequence
from typing import Final

from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.json_form import JsonValue

SCHEMA_URI: Final = "./hub.schema.json"
SCHEMA_VERSION: Final = 1
REPO_ROLE: Final = "app"
REPO_CHECK_FAST: Final = "make check-fast"
REPO_CHECK: Final = "make check"
# How the help names the positional argument that holds ``project.name``.
PROJECT_ARGUMENT: Final = "PROJECT"


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
    its last ``/``. ``tracker`` is ``kind:team`` split on the first ``:``.
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
        "repos": [_repo(github) for github in repos.split(",")],
    }


def flag_problems(problems: Sequence[ConfigProblem]) -> list[str]:
    """One ``<flag>: <message>`` line per problem, the flag found from the problem's JSON path.

    A path no flag sets (the pin is the running release) is printed as the path itself.
    """
    return [f"{_flag(problem.path)}: {problem.message}" for problem in problems]


def _tracker(value: str) -> dict[str, JsonValue]:
    kind, colon, team = value.partition(":")
    if not colon:
        # No kind given: an empty one, which the model refuses by naming the kinds it takes.
        return {"kind": "", "team": value}
    return {"kind": kind, "team": team}


def _repo(github: str) -> dict[str, JsonValue]:
    return {
        "dir": github.rpartition("/")[2],
        "github": github,
        "role": REPO_ROLE,
        "check_fast": REPO_CHECK_FAST,
        "check": REPO_CHECK,
    }


def _flag(path: str) -> str:
    if path == "project.name":
        return PROJECT_ARGUMENT
    if path.startswith("project."):
        return "--" + path.removeprefix("project.").replace("_", "-")
    if path.startswith("tracker."):
        return "--tracker"
    if path.startswith("repos"):
        return "--repos"
    return path
