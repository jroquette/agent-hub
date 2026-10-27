"""``hub repo``: list, add, change and remove a hub's repos (AGH-578, spec D-fields..D-list).

Each test builds a hub folder holding ``hub.json`` (written with indent 2 and its keys in the
file's order, a ``_comment`` first) and, when asked, the developer's ``hub.local.json``, then
runs the command in process with ``AGENT_HUB_ROOT`` naming it.
"""

import json
import socket
import subprocess
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.env_files import document_bytes
from agent_hub.cli.main import app
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.repo_edit_cases import (
    MODEL_CASES,
    REFUSAL_CASES,
    RepoEditCase,
    RepoFiles,
    a_referenced_document,
    a_repos_document,
)


def hub_bytes(document: dict[str, Any]) -> bytes:
    """``document`` as ``hub repo`` writes it: the file's key order, indent 2, a final newline."""
    return (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()


def pinned(document: dict[str, Any]) -> dict[str, Any]:
    """``document`` with a ``_comment`` first and the pin of the running CLI."""
    document["platform"]["version"] = version("agent-hub-cli")
    return {"_comment": "A synthetic demo hub.", **document}


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    """A hub with the spec's ``D`` (``demo-api`` and ``demo-web``) and no ``hub.local.json``."""
    root = tmp_path / "hub"
    root.mkdir()
    (root / "hub.json").write_bytes(hub_bytes(pinned(a_repos_document())))
    return root


def run_repo(root: Path, *args: str) -> Result:
    return CliRunner().invoke(app, ["repo", *args], env={"AGENT_HUB_ROOT": str(root)}, input="")


def test_lists_repos_when_hub_has_two(hub: Path) -> None:
    result = run_repo(hub, "list")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "demo-api (acme/demo-api, app, branch main): check_fast=make check-fast, check=make check",
        "demo-web (acme/demo-web, app, branch trunk): check_fast=-, check=make check",
    ]


def test_prints_json_when_list_json(hub: Path) -> None:
    result = run_repo(hub, "list", "--json")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert json.loads(result.stdout) == {
        "repos": [
            {
                "dir": "demo-api",
                "github": "acme/demo-api",
                "role": "app",
                "check_fast": "make check-fast",
                "check": "make check",
                "default_branch": "main",
            },
            {
                "dir": "demo-web",
                "github": "acme/demo-web",
                "role": "app",
                "check_fast": None,
                "check": "make check",
                "default_branch": "trunk",
            },
        ]
    }


def test_lists_repos_when_local_file_broken(hub: Path) -> None:
    listed = run_repo(hub, "list")
    as_json = run_repo(hub, "list", "--json")
    (hub / "hub.local.json").write_bytes(b"{ not json")

    assert run_repo(hub, "list").output == listed.output
    broken = run_repo(hub, "list", "--json")
    assert (broken.exit_code, broken.stdout) == (0, as_json.stdout), broken.output


def snapshot(root: Path) -> dict[str, bytes]:
    """Every file of the hub folder and its bytes: a refused write must leave them all."""
    return {path.name: path.read_bytes() for path in sorted(root.iterdir())}


@pytest.fixture
def api_hub(tmp_path: Path) -> Path:
    """A hub whose only repo is ``demo-api``, as ``hub init``'s demo writes it."""
    root = tmp_path / "api-hub"
    root.mkdir()
    (root / "hub.json").write_bytes(hub_bytes(pinned(a_hub_document())))
    return root


SYNC_LINE = "run ./hub sync to update AGENTS.md and .claude/settings.json"
ADD_ARGS = (
    "add",
    "demo-web",
    "--github",
    "acme/demo-web",
    "--check",
    "make check",
    "--check-fast",
    "make check-fast",
    "--default-branch",
    "trunk",
)


def test_adds_repo_when_options_valid(
    api_hub: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    document = json.loads((api_hub / "hub.json").read_bytes())
    no_tools = tmp_path / "no-tools"
    no_tools.mkdir()
    started: list[object] = []
    connected: list[object] = []

    def record_start(*args: object, **_kwargs: object) -> None:
        started.append(args)
        raise OSError("no child process in this test")

    def record_connect(_socket: object, address: object) -> None:
        connected.append(address)
        raise OSError("no network in this test")

    monkeypatch.setattr(subprocess, "Popen", record_start)
    monkeypatch.setattr(socket.socket, "connect", record_connect)

    result = CliRunner().invoke(
        app,
        ["repo", *ADD_ARGS],
        env={"AGENT_HUB_ROOT": str(api_hub), "PATH": str(no_tools)},
        input="",
    )

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "hub.json: added repo demo-web",
        SYNC_LINE,
        "run ./hub setup to clone ../demo-web",
        "run /onboard to set demo-web's gates and project rules",
    ]
    document["repos"].append(
        {
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check_fast": "make check-fast",
            "check": "make check",
            "default_branch": "trunk",
        }
    )
    assert (api_hub / "hub.json").read_bytes() == hub_bytes(document)
    assert (started, connected) == ([], [])
    assert sorted(path.name for path in tmp_path.iterdir()) == ["api-hub", "no-tools"]


def test_exits_two_when_github_or_check_missing(api_hub: Path) -> None:
    before = snapshot(api_hub)

    for args in (
        ("add", "demo-web", "--check", "make check"),
        ("add", "demo-web", "--github", "acme/demo-web"),
    ):
        result = run_repo(api_hub, *args)

        assert (result.exit_code, result.stdout) == (2, ""), result.output
    assert snapshot(api_hub) == before


def test_refuses_add_when_dir_duplicate(api_hub: Path) -> None:
    before = snapshot(api_hub)

    for dir_ in ("Demo-API", "demo-api"):
        result = run_repo(api_hub, "add", dir_, "--github", "acme/x", "--check", "make check")

        assert (result.exit_code, result.stdout) == (1, ""), result.output
        assert result.stderr == (
            f"hub.json: not changed: repo dir {dir_} is already used by repos[0] (demo-api),"
            " ignoring case\n"
        )
    assert snapshot(api_hub) == before


def test_updates_repo_in_place_when_set(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())

    result = run_repo(
        hub,
        "set",
        "demo-web",
        "--github",
        "acme/web2",
        "--role",
        "app",
        "--check",
        "make ci",
        "--check-fast-timeout",
        "120",
    )

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == ["hub.json: updated repo demo-web", SYNC_LINE]
    # The keys present keep their place; the new ones go last, in the model's order.
    document["repos"][1] = {
        "dir": "demo-web",
        "github": "acme/web2",
        "check": "make ci",
        "default_branch": "trunk",
        "role": "app",
        "check_fast_timeout": 120,
    }
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)


def test_unsets_keys_when_unset_given(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())
    added = run_repo(hub, "set", "demo-web", "--check-fast", "make check-fast")

    result = run_repo(hub, "set", "demo-web", "--unset", "check_fast", "--unset", "default_branch")

    assert (added.exit_code, result.exit_code, result.stderr) == (0, 0, ""), result.output
    assert result.stdout.splitlines() == ["hub.json: updated repo demo-web", SYNC_LINE]
    del document["repos"][1]["default_branch"]
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)


def test_exits_two_when_set_has_no_option(hub: Path) -> None:
    before = snapshot(hub)

    result = run_repo(hub, "set", "demo-web")

    assert (result.exit_code, result.stdout) == (2, ""), result.output
    assert "nothing to change" in result.stderr
    assert snapshot(hub) == before


def test_exits_two_when_set_given_dir(hub: Path) -> None:
    before = snapshot(hub)

    result = run_repo(hub, "set", "demo-web", "--dir", "x")

    assert (result.exit_code, result.stdout) == (2, ""), result.output
    assert "--dir" in result.stderr
    assert snapshot(hub) == before


def write_files(root: Path, files: RepoFiles) -> None:
    """``files`` as the hub's ``hub.json`` (pinned) and, when there is one, ``hub.local.json``."""
    (root / "hub.json").write_bytes(hub_bytes(pinned(files.hub)))
    if files.local is not None:
        (root / "hub.local.json").write_bytes(hub_bytes(files.local))


def test_refuses_remove_when_references_left(hub: Path) -> None:
    write_files(hub, a_referenced_document())
    before = snapshot(hub)

    result = run_repo(hub, "remove", "demo-web")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr.splitlines() == [
        "hub.json: not changed: repo demo-web is still named at guard.ask_before_edit[0]",
        "hub.json: not changed: repo demo-web is still named at events[0].repo",
        "hub.json: not changed: repo demo-web is still named at modules.contract-sync.target",
        "hub.json: not changed: repo demo-web is still named in hub.local.json at repos[0].dir",
    ]
    assert sorted(before) == ["hub.json", "hub.local.json"]
    assert snapshot(hub) == before


def test_removes_repo_when_no_reference_left(hub: Path) -> None:
    document = json.loads((hub / "hub.json").read_bytes())
    document["environments"] = {"staging": {"access": "read"}}
    document["repos"][1]["services"] = {
        "web": {"endpoints": {"staging": {"url": "https://web.staging.example.com"}}}
    }
    (hub / "hub.json").write_bytes(hub_bytes(document))
    clone = hub.parent / "demo-web"
    clone.mkdir()
    (clone / "README.md").write_text("a clone\n")

    result = run_repo(hub, "remove", "demo-web")

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "hub.json: removed repo demo-web",
        SYNC_LINE,
        "../demo-web and its worktrees are left in place",
        "a teammate whose hub.local.json names demo-web in repos must drop that entry",
    ]
    # The entry goes with its services; every other key stays.
    del document["repos"][1]
    assert (hub / "hub.json").read_bytes() == hub_bytes(document)
    assert (clone / "README.md").read_text() == "a clone\n"


def test_refuses_remove_when_last_repo(api_hub: Path) -> None:
    before = snapshot(api_hub)

    result = run_repo(api_hub, "remove", "demo-api")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == (
        "hub.json: not changed: demo-api is the only repo; hub.json needs at least one\n"
    )
    assert snapshot(api_hub) == before


def refused_lines(case: RepoEditCase, *, by_model: bool) -> list[str]:
    """The CLI's lines for ``case``'s refusal: core's after ``hub.json: not changed: ``, the
    model's after ``hub.json: <path>: ``."""
    if by_model:
        return [f"hub.json: {path}: {message}" for path, message in case.expected]
    return [f"hub.json: not changed: {message}" for _path, message in case.expected]


@pytest.mark.parametrize(
    ("case", "by_model"),
    [
        *(pytest.param(case, False, id=case.id) for case in REFUSAL_CASES),
        *(pytest.param(case, True, id=case.id) for case in MODEL_CASES),
    ],
)
def test_keeps_bytes_when_case_refused(hub: Path, case: RepoEditCase, *, by_model: bool) -> None:
    (hub / "hub.json").unlink()
    write_files(hub, case.setup())
    before = snapshot(hub)

    result = CliRunner().invoke(app, list(case.argv), env={"AGENT_HUB_ROOT": str(hub)}, input="")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr.splitlines() == refused_lines(case, by_model=by_model)
    assert snapshot(hub) == before


def a_commented_document() -> dict[str, Any]:
    """``D`` pinned, with ``_comment`` keys at the top and in a repo, keys not sorted."""
    document = pinned(a_repos_document())
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


ACCEPTED: dict[str, tuple[tuple[str, ...], Callable[[dict[str, Any]], None]]] = {
    "add": (
        (
            "add",
            "demo-docs",
            "--github",
            "acme/demo-docs",
            "--check",
            "make check",
            "--role",
            "docs",
        ),
        _added,
    ),
    "set": (("set", "demo-api", "--check", "make ci", "--default-branch", "develop"), _changed),
    "remove": (("remove", "demo-web"), _removed),
}


@pytest.mark.parametrize("change", list(ACCEPTED))
def test_writes_exact_bytes_when_change_accepted(hub: Path, change: str) -> None:
    args, make_change = ACCEPTED[change]
    document = a_commented_document()
    (hub / "hub.json").write_bytes(document_bytes(document))

    result = run_repo(hub, *args)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert "rewritten" not in result.stdout
    expected = a_commented_document()
    make_change(expected)
    assert (hub / "hub.json").read_bytes() == document_bytes(expected)


def test_says_reformat_when_indent_differs(hub: Path) -> None:
    document = a_commented_document()
    (hub / "hub.json").write_bytes(json.dumps(document, indent=4).encode() + b"\n")

    result = run_repo(hub, *ACCEPTED["set"][0])

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [
        "hub.json: rewritten with indent 2",
        "hub.json: updated repo demo-api",
        SYNC_LINE,
    ]
    _changed(document)
    assert (hub / "hub.json").read_bytes() == document_bytes(document)


def test_exits_one_when_file_changed_since_read(hub: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from agent_hub.cli import repo_command

    real = repo_command.document_bytes
    changed = b'{"changed": true}\n'

    def change_then_dump(document: Any) -> bytes:
        (hub / "hub.json").write_bytes(changed)
        return real(document)

    monkeypatch.setattr(repo_command, "document_bytes", change_then_dump)

    result = run_repo(hub, "set", "demo-web", "--role", "web")

    assert (result.exit_code, result.stdout) == (1, ""), result.output
    assert result.stderr == "hub.json changed since it was read; run the command again\n"
    assert (hub / "hub.json").read_bytes() == changed
