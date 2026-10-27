"""The Hub config screen's repo edits (AGH-578, spec D-api, AC-6).

Each case of ``repo_edit_cases`` is posted as a body and must give the CLI's lines: one problem
per line, at its path, with the CLI's text after its lead. The files are written as ``hub repo``
writes them (indent 2, the file's key order, a final newline), so an accepted edit can be
compared byte for byte with what the CLI writes.
"""

import json
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from agent_hub.api import repo_writes
from agent_hub.api.repo_writes import AddRepo, RemoveRepo, RepoEdit, SetRepo, write_repo_edit
from agent_hub.core.hub_config.repo_edits import set_repo
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.json_form import JsonValue
from agent_hub.core.testing.repo_edit_cases import (
    MODEL_CASES,
    REFUSAL_CASES,
    RepoEditCase,
    RepoFiles,
    a_referenced_document,
    a_repos_document,
)

_EDIT: TypeAdapter[Any] = TypeAdapter(RepoEdit)


def hub_bytes(document: Mapping[str, Any]) -> bytes:
    """``document`` as ``hub repo`` writes it: the file's key order, indent 2, a final newline."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def write_files(root: Path, files: RepoFiles) -> Path:
    (root / "hub.json").write_bytes(hub_bytes(files.hub))
    if files.local is not None:
        (root / "hub.local.json").write_bytes(hub_bytes(files.local))
    return root


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the hub folder and its bytes: a refused write must leave them all."""
    return {path.name: path.read_bytes() for path in sorted(root.iterdir())}


def edit(root: Path, body: Mapping[str, JsonValue]) -> None:
    write_repo_edit(str(root), _EDIT.validate_python(body))


def refused(root: Path, body: Mapping[str, JsonValue]) -> list[tuple[str, str]]:
    """The problems of ``body``'s refusal, as (pointer, message) pairs."""
    with pytest.raises(HubInvalidError) as raised:
        edit(root, body)
    assert raised.value.title == "This change was not saved"
    return [(problem.pointer, problem.message) for problem in raised.value.problems]


def test_parses_each_op_when_body_valid() -> None:
    added = _EDIT.validate_python(
        {
            "op": "add_repo",
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check": "make check",
            "check_fast_timeout": 120,
        }
    )
    changed = _EDIT.validate_python({"op": "set_repo", "dir": "demo-web", "unset": ["role"]})
    removed = _EDIT.validate_python({"op": "remove_repo", "dir": "demo-web"})

    assert isinstance(added, AddRepo)
    assert (added.check_fast_timeout, added.role) == (120, None)
    assert isinstance(changed, SetRepo)
    assert (changed.dir, tuple(changed.unset), changed.github) == ("demo-web", ("role",), None)
    assert isinstance(removed, RemoveRepo)


@pytest.mark.parametrize(
    "body",
    [
        {"op": "add_repo", "dir": "x" * 201, "github": "acme/x", "check": "make check"},
        {"op": "add_repo", "dir": "demo-web", "github": "acme/x", "check": "c" * 201},
        {"op": "set_repo", "dir": "demo-web", "role": "r" * 201},
        {"op": "set_repo", "dir": "demo-web", "unset": ["k" * 201]},
        {"op": "set_repo", "dir": "demo-web", "unset": ["role"] * 11},
        {"op": "remove_repo", "dir": ""},
    ],
    ids=["dir", "check", "role", "unset-item", "unset-items", "dir-empty"],
)
def test_rejects_body_when_text_too_long(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _EDIT.validate_python(body)


@pytest.mark.parametrize(
    "body",
    [
        {"op": "add_repo", "dir": "demo-web", "github": "acme/x", "check": "c", "services": {}},
        {"op": "set_repo", "dir": "demo-web", "new_dir": "demo-www"},
        {"op": "set_repo", "dir": "demo-web", "conventions": "docs"},
        {"op": "remove_repo", "dir": "demo-web", "force": True},
        {"op": "rename_repo", "dir": "demo-web"},
        {"op": "add_repo", "dir": "demo-web", "github": "acme/x", "check": "c", "scope": "team"},
    ],
    ids=["add-services", "set-new-dir", "set-conventions", "remove-force", "op", "scope"],
)
def test_rejects_body_when_unknown_key(body: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        _EDIT.validate_python(body)


def test_rejects_body_when_timeout_not_integer() -> None:
    for timeout in (1.5, "120", True):
        with pytest.raises(ValidationError):
            _EDIT.validate_python(
                {"op": "set_repo", "dir": "demo-web", "check_fast_timeout": timeout}
            )


@pytest.mark.parametrize(
    ("case", "by_model"),
    [
        *(pytest.param(case, False, id=case.id) for case in REFUSAL_CASES),
        *(pytest.param(case, True, id=case.id) for case in MODEL_CASES),
    ],
)
def test_keeps_bytes_when_case_refused(
    tmp_path: Path, case: RepoEditCase, *, by_model: bool
) -> None:
    hub = write_files(tmp_path, case.setup())
    before = snapshot(hub)

    problems = refused(hub, case.body)

    # A model line carries the read's ``hub.json: `` lead; core's reason is the message alone.
    lead = "hub.json: " if by_model else ""
    assert problems == [(path, f"{lead}{message}") for path, message in case.expected]
    assert snapshot(hub) == before


# E1: one problem per reference, at its path; the local one names its file.
def test_names_each_reference_when_remove_refused(tmp_path: Path) -> None:
    hub = write_files(tmp_path, a_referenced_document())
    before = snapshot(hub)

    problems = refused(hub, {"op": "remove_repo", "dir": "demo-web"})

    assert problems == [
        ("guard.ask_before_edit[0]", "repo demo-web is still named at guard.ask_before_edit[0]"),
        ("events[0].repo", "repo demo-web is still named at events[0].repo"),
        (
            "modules.contract-sync.target",
            "repo demo-web is still named at modules.contract-sync.target",
        ),
        ("repos[0].dir", "repo demo-web is still named in hub.local.json at repos[0].dir"),
    ]
    assert snapshot(hub) == before


def a_commented_document() -> dict[str, Any]:
    """``D`` with ``_comment`` keys at the top and in a repo, keys not sorted."""
    document: dict[str, Any] = {"_comment": "A synthetic demo hub.", **a_repos_document()}
    document["repos"][0] = {"_comment": "the API", **document["repos"][0]}
    document["guard"]["_comment"] = "asks before an ADR edit"
    return document


def _added(document: dict[str, Any]) -> None:
    document["repos"].append(
        {"dir": "demo-docs", "github": "acme/demo-docs", "role": "docs", "check": "make check"}
    )


def _changed(document: dict[str, Any]) -> None:
    document["repos"][0]["check"] = "make ci"
    document["repos"][0]["default_branch"] = "develop"


def _removed(document: dict[str, Any]) -> None:
    del document["repos"][1]


# The CLI's accepted changes (test_repo_command.ACCEPTED), as bodies.
ACCEPTED: dict[str, tuple[dict[str, JsonValue], Callable[[dict[str, Any]], None]]] = {
    "add": (
        {
            "op": "add_repo",
            "dir": "demo-docs",
            "github": "acme/demo-docs",
            "check": "make check",
            "role": "docs",
        },
        _added,
    ),
    "set": (
        {"op": "set_repo", "dir": "demo-api", "check": "make ci", "default_branch": "develop"},
        _changed,
    ),
    "remove": ({"op": "remove_repo", "dir": "demo-web"}, _removed),
}


@pytest.mark.parametrize("change", list(ACCEPTED))
def test_writes_same_bytes_as_cli_when_accepted(tmp_path: Path, change: str) -> None:
    body, make_change = ACCEPTED[change]
    (tmp_path / "hub.json").write_bytes(hub_bytes(a_commented_document()))

    edit(tmp_path, body)

    expected = a_commented_document()
    make_change(expected)
    assert (tmp_path / "hub.json").read_bytes() == hub_bytes(expected)
    assert sorted(path.name for path in tmp_path.iterdir()) == ["hub.json"]


def test_unsets_keys_when_unset_given(tmp_path: Path) -> None:
    document: dict[str, Any] = a_repos_document()
    document["repos"][1]["check_fast"] = "make check-fast"
    write_files(tmp_path, RepoFiles(document, None))

    edit(
        tmp_path,
        {"op": "set_repo", "dir": "demo-web", "unset": ["check_fast", "default_branch"]},
    )

    written = json.loads((tmp_path / "hub.json").read_bytes())
    assert written["repos"][1] == {
        "dir": "demo-web",
        "github": "acme/demo-web",
        "check": "make check",
    }


# The body's ``dir`` names the repo to change; it is never a change (``set_repo`` would write it,
# and a rename would skip the reference check a remove makes).
def test_leaves_dir_out_of_changes_when_set_repo_posted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_files(tmp_path, RepoFiles(a_repos_document(), None))
    seen: list[Mapping[str, JsonValue]] = []

    def recording(document: Any, repo: str, changes: Mapping[str, JsonValue], **kwargs: Any) -> Any:
        seen.append(dict(changes))
        return set_repo(document, repo, changes, **kwargs)

    monkeypatch.setattr(repo_writes, "set_repo", recording)

    edit(
        tmp_path,
        {
            "op": "set_repo",
            "dir": "demo-web",
            "github": "acme/web2",
            "role": "app",
            "check_fast": "make fast",
            "check_fast_timeout": 120,
            "check": "make ci",
            "default_branch": "main",
        },
    )

    assert seen == [
        {
            "github": "acme/web2",
            "role": "app",
            "check_fast": "make fast",
            "check_fast_timeout": 120,
            "check": "make ci",
            "default_branch": "main",
        }
    ]
    written = json.loads((tmp_path / "hub.json").read_bytes())
    assert [repo["dir"] for repo in written["repos"]] == ["demo-api", "demo-web"]
