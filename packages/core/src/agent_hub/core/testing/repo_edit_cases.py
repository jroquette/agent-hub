"""The shared ``hub repo`` cases: the edits the CLI and ``hub web`` each refuse alike.

Each case is one edit, as ``hub`` arguments (``argv``) and as the body of
``POST /projects/{project}/config/repos`` (``body``), made on the files ``setup`` builds.
``expected`` is the edited ``hub.json``, or the refusal's lines, each a JSON path and a message.
A ``REFUSAL_CASES`` message is ``repo_edits``' reason, which the CLI prints after
``hub.json: not changed: ``; a ``MODEL_CASES`` message is the model's own, which the CLI prints
after ``hub.json: <path>: `` and the API after ``hub.json: ``. Either way ``hub.json`` and
``hub.local.json`` keep their bytes. Synthetic values only; every host is under ``example.com``.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final, NamedTuple

from agent_hub.core.hub_config.environment_edits import Document
from agent_hub.core.hub_config.text_shapes import SAFE_SEGMENT
from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.builders import a_hub_document

type RefusalLines = tuple[tuple[str, str], ...]

# What pydantic says of a ``dir`` or ``github`` without the model's shape.
_DIR_SHAPE: Final = f"String should match pattern '^{SAFE_SEGMENT}$'"
_GITHUB_SHAPE: Final = f"String should match pattern '^{SAFE_SEGMENT}/{SAFE_SEGMENT}$'"


class RepoFiles(NamedTuple):
    """A ``hub.json`` and a ``hub.local.json`` (``None`` when there is none)."""

    hub: Document
    local: Document | None


@dataclass(frozen=True, slots=True)
class RepoEditCase:
    """One ``hub repo`` edit, the files it is made on and what it gives."""

    id: str
    # The arguments after ``hub``.
    argv: tuple[str, ...]
    body: Mapping[str, JsonValue]
    setup: Callable[[], RepoFiles]
    expected: Document | RefusalLines


def a_repos_document() -> Document:
    """Build the spec's ``D``: ``a_hub_document`` plus ``demo-web``, on the branch ``trunk``
    and with no ``check_fast``; a fresh copy per call."""
    document: dict[str, Any] = a_hub_document()
    document["repos"].append(
        {
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check": "make check",
            "default_branch": "trunk",
        }
    )
    return document


def a_referenced_document() -> RepoFiles:
    """Build ``D`` with ``demo-web`` named in each place a remove checks: a guarded path, an
    event, ``contract-sync`` and the developer's ``hub.local.json``; a fresh copy per call."""
    document: dict[str, Any] = a_repos_document()
    document["guard"]["ask_before_edit"] = ["demo-web/docs/adr"]
    document["events"] = [{"workflow": "x", "on": "merge", "repo": "demo-web"}]
    document["modules"]["contract-sync"] = {"source": "demo-api", "target": "demo-web"}
    local: Document = {
        "environments": {"jane-cloud": {"access": "write"}},
        "repos": [
            {
                "dir": "demo-web",
                "services": {
                    "web": {"endpoints": {"jane-cloud": {"url": "https://web.jane.example.com"}}}
                },
            }
        ],
    }
    return RepoFiles(document, local)


def _hub() -> RepoFiles:
    return RepoFiles(a_hub_document(), None)


def _repos() -> RepoFiles:
    return RepoFiles(a_repos_document(), None)


def _add(
    case_id: str, dir_: str, *, github: str, check: str, expected: RefusalLines
) -> RepoEditCase:
    return RepoEditCase(
        id=case_id,
        argv=("repo", "add", dir_, "--github", github, "--check", check),
        body={"op": "add_repo", "dir": dir_, "github": github, "check": check},
        setup=_hub,
        expected=expected,
    )


def _set(
    case_id: str, argv: tuple[str, ...], body: Mapping[str, JsonValue], *, expected: RefusalLines
) -> RepoEditCase:
    return RepoEditCase(
        id=case_id,
        argv=("repo", "set", *argv),
        body={"op": "set_repo", **body},
        setup=_repos,
        expected=expected,
    )


def _unset(case_id: str, key: str, *, expected: RefusalLines) -> RepoEditCase:
    return _set(
        case_id,
        ("demo-web", "--unset", key),
        {"dir": "demo-web", "unset": [key]},
        expected=expected,
    )


def _remove(
    case_id: str, dir_: str, *, setup: Callable[[], RepoFiles], expected: RefusalLines
) -> RepoEditCase:
    return RepoEditCase(
        id=case_id,
        argv=("repo", "remove", dir_),
        body={"op": "remove_repo", "dir": dir_},
        setup=setup,
        expected=expected,
    )


def _still_named(path: str) -> tuple[str, str]:
    return (path, f"repo demo-web is still named at {path}")


REFUSAL_CASES: Final[tuple[RepoEditCase, ...]] = (
    _add(
        "add-dir-taken-ignoring-case",
        "Demo-API",
        github="acme/demo-api",
        check="make check",
        expected=(
            (
                "repos[0].dir",
                "repo dir Demo-API is already used by repos[0] (demo-api), ignoring case",
            ),
        ),
    ),
    _set(
        "set-dir-unknown",
        ("demo-nope", "--role", "app"),
        {"dir": "demo-nope", "role": "app"},
        expected=(("$", "no repo demo-nope in hub.json"),),
    ),
    _set(
        "set-dir-case-differs",
        ("Demo-Web", "--role", "app"),
        {"dir": "Demo-Web", "role": "app"},
        expected=(("$", "no repo Demo-Web in hub.json; did you mean demo-web?"),),
    ),
    _unset(
        "set-unset-github",
        "github",
        expected=(("repos[1].github", "github cannot be unset: hub.json needs it"),),
    ),
    _unset(
        "set-unset-check",
        "check",
        expected=(("repos[1].check", "check cannot be unset: hub.json needs it"),),
    ),
    _unset(
        "set-unset-key-unknown",
        "services",
        expected=(
            (
                "$",
                "services is not a key --unset takes:"
                " role, check_fast, check_fast_timeout, default_branch",
            ),
        ),
    ),
    _set(
        "set-key-set-and-unset",
        ("demo-web", "--role", "app", "--unset", "role"),
        {"dir": "demo-web", "role": "app", "unset": ["role"]},
        expected=(("repos[1].role", "role is both set and unset"),),
    ),
    _remove(
        "remove-dir-unknown",
        "demo-nope",
        setup=_repos,
        expected=(("$", "no repo demo-nope in hub.json"),),
    ),
    _remove(
        "remove-dir-referenced",
        "demo-web",
        setup=a_referenced_document,
        expected=(
            _still_named("guard.ask_before_edit[0]"),
            _still_named("events[0].repo"),
            _still_named("modules.contract-sync.target"),
            ("repos[0].dir", "repo demo-web is still named in hub.local.json at repos[0].dir"),
        ),
    ),
    _remove(
        "remove-last-repo",
        "demo-api",
        setup=_hub,
        expected=(("repos", "demo-api is the only repo; hub.json needs at least one"),),
    ),
)

# Refused by the model, not by ``repo_edits`` (plan E3): the line names the key at its path.
MODEL_CASES: Final[tuple[RepoEditCase, ...]] = (
    _add(
        "add-github-without-name",
        "demo-web",
        github="acme",
        check="make check",
        expected=(("repos[1].github", _GITHUB_SHAPE),),
    ),
    _add(
        "add-github-three-parts",
        "demo-web",
        github="acme/x/y",
        check="make check",
        expected=(("repos[1].github", _GITHUB_SHAPE),),
    ),
    _add(
        "add-check-blank",
        "demo-web",
        github="acme/demo-web",
        check=" ",
        expected=(("repos[1].check", "must hold a non-space character"),),
    ),
    _add(
        "add-dir-parent",
        "../x",
        github="acme/demo-web",
        check="make check",
        expected=(("repos[1].dir", _DIR_SHAPE),),
    ),
    _add(
        "add-dir-space",
        "a b",
        github="acme/demo-web",
        check="make check",
        expected=(("repos[1].dir", _DIR_SHAPE),),
    ),
    _set(
        "set-timeout-zero",
        ("demo-web", "--check-fast-timeout", "0"),
        {"dir": "demo-web", "check_fast_timeout": 0},
        expected=(("repos[1].check_fast_timeout", "Input should be greater than or equal to 1"),),
    ),
    _set(
        "set-timeout-over-budget",
        ("demo-web", "--check-fast-timeout", "161"),
        {"dir": "demo-web", "check_fast_timeout": 161},
        expected=(("repos[1].check_fast_timeout", "Input should be less than or equal to 160"),),
    ),
)
