"""``/hubs`` on the composed app, over a real ``hubs.json`` and real hub folders (AC-200.34)."""

import json
import stat
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import an_event
from agent_hub.core.testing.repo_edit_cases import MODEL_CASES, REFUSAL_CASES, RepoEditCase

HUBS = "/api/v1/hubs"
# The registry writes require this server's Origin (A11).
OWN = {"Origin": "http://127.0.0.1:7420"}


def test_registers_hub_with_project_pin_lock_and_repos_when_path_is_a_hub(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()

    response = composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN)

    assert response.status_code == 201, response.text
    view = response.json()
    assert view["project"] == "demo"
    assert view["platform_pin"] == composed.settings.running_version
    assert view["lock_state"] is not None
    assert view["repos"] == ["demo-api"]
    assert view["valid"] is True
    assert view["path"] == str(hub.resolve())
    assert [item["id"] for item in composed.client.get(HUBS).json()["items"]] == [view["id"]]


def test_writes_registry_only_its_owner_can_read_when_hub_registered(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN)

    registry = composed.settings.registry_path
    assert stat.S_IMODE(registry.stat().st_mode) == 0o600
    assert stat.S_IMODE(registry.parent.stat().st_mode) == 0o700


def test_refuses_unprocessable_no_hub_json_when_folder_has_none(
    composed: Any, tmp_path: Path
) -> None:
    folder = tmp_path / "empty"
    folder.mkdir()

    response = composed.client.post(HUBS, json={"path": str(folder)}, headers=OWN)

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "No hub.json"
    assert composed.client.get(HUBS).json()["items"] == []


def test_refuses_unprocessable_with_pointers_when_hub_json_invalid(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    document = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
    document["repos"][0]["dir"] = 7
    document["tracker"] = "linear"
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    response = composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN)

    assert response.status_code == 422, response.text
    problem = response.json()
    assert problem["title"] == "Invalid hub.json"
    pointers = {error["pointer"] for error in problem["errors"]}
    assert {"/repos/0/dir", "/tracker"} <= pointers


def test_refuses_conflict_when_project_registered_by_another_hub(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN)
    twin = make_hub(folder="twin-hub")

    response = composed.client.post(HUBS, json={"path": str(twin)}, headers=OWN)

    assert response.status_code == 409, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert len(composed.client.get(HUBS).json()["items"]) == 1


def test_removes_hub_and_keeps_its_events_when_deleted(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub_id = composed.client.post(HUBS, json={"path": str(make_hub())}, headers=OWN).json()["id"]
    composed.store.append([an_event(project="demo")])

    response = composed.client.delete(f"{HUBS}/{hub_id}", headers=OWN)

    assert response.status_code == 204
    assert composed.client.get(HUBS).json()["items"] == []
    assert [row.project for row in composed.rows()] == ["demo"]
    assert composed.client.delete(f"{HUBS}/{hub_id}", headers=OWN).status_code == 404


# AC-PG-38.1: the composed GET /projects/{project}/config reads the registered hub's hub.json and
# hub.local.json: per repo its checks and patterns, the tracker, the models, each with a source.
def test_answers_project_config_from_files_when_hub_registered(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    (hub / "hub.local.json").write_text(
        json.dumps({"project": {"author_email": "me@example.com"}}), encoding="utf-8"
    )
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201

    response = composed.client.get("/api/v1/projects/demo/config")

    assert response.status_code == 200, response.text
    view = response.json()
    [repo] = view["repos"]
    assert (repo["dir"], repo["check_fast"], repo["check"]) == (
        "demo-api",
        "make check-fast",
        "make check",
    )
    assert repo["pr_title"]["source"] == "commit_title"
    assert repo["pr_title"]["example"] == "feat(api): add the hub config view (DEM-42)"
    assert (view["tracker"]["kind"], view["tracker"]["teams"]) == ("linear", ["DEM"])
    assert set(view["model_tiers"]) == {"small", "medium", "large"}
    assert (view["author_email"]["value"], view["author_email"]["source"]) == (
        "me@example.com",
        "local",
    )
    assert view["author_email"]["team_value"] == "jane@example.com"
    assert view["local_file"]["problems"] == []


# AC-PG-38.1: an invalid hub.local.json is reported with its problems and ignored.
def test_reports_and_ignores_local_file_when_invalid_over_composed_app(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    (hub / "hub.local.json").write_text(
        json.dumps({"project": {"author_email": "not an email"}}), encoding="utf-8"
    )
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201

    view = composed.client.get("/api/v1/projects/demo/config").json()

    assert view["local_file"]["problems"] != []
    assert (view["author_email"]["value"], view["author_email"]["source"]) == (
        "jane@example.com",
        "team",
    )


# AC-416.10: the composed POST /projects/{project}/config/environments writes the registered hub's
# files and answers the new Hub config view; a team rename also renames the local tightening.
def test_renames_team_environment_and_answers_view_when_edit_posted(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    document = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
    document["environments"] = {"staging": {"access": "write"}}
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    (hub / "hub.local.json").write_text(
        json.dumps({"environments": {"staging": {"access": "read"}}}), encoding="utf-8"
    )
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201

    response = composed.client.post(
        "/api/v1/projects/demo/config/environments",
        json={
            "op": "batch",
            "ops": [
                {"op": "rename_environment", "scope": "team", "name": "staging", "new_name": "qa"},
                {"op": "set_environment", "scope": "team", "name": "qa", "description": "QA"},
            ],
        },
        headers=OWN,
    )

    assert response.status_code == 200, response.text
    [environment] = response.json()["environments"]["environments"]
    assert (environment["name"], environment["access"], environment["team_access"]) == (
        "qa",
        "read",
        "write",
    )
    assert environment["description"] == "QA"
    assert json.loads((hub / "hub.local.json").read_text(encoding="utf-8")) == {
        "environments": {"qa": {"access": "read"}}
    }


# AC-416.9, AC-416.10: a refused edit answers a problem naming it and writes nothing.
def test_refuses_unprocessable_and_writes_nothing_when_edit_refused(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    before = (hub / "hub.json").read_bytes()
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201

    response = composed.client.post(
        "/api/v1/projects/demo/config/environments",
        json={
            "op": "batch",
            "ops": [
                {"op": "add_environment", "scope": "team", "name": "qa", "access": "read"},
                {"op": "remove_environment", "scope": "team", "name": "missing"},
            ],
        },
        headers=OWN,
    )

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert response.json()["title"] == "This change was not saved"
    assert (hub / "hub.json").read_bytes() == before
    assert not (hub / "hub.local.json").exists()


REPOS = "/api/v1/projects/demo/config/repos"


# AGH-578 AC-6: the composed POST /projects/{project}/config/repos adds the repo to the
# registered hub's hub.json and answers the new Hub config view.
def test_adds_repo_when_config_repos_posted(composed: Any, make_hub: Callable[..., Path]) -> None:
    hub = make_hub()
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201

    response = composed.client.post(
        REPOS,
        json={
            "op": "add_repo",
            "dir": "demo-web",
            "github": "acme/demo-web",
            "check": "make check",
            "check_fast": "make check-fast",
            "default_branch": "trunk",
        },
        headers=OWN,
    )

    assert response.status_code == 200, response.text
    assert [repo["dir"] for repo in response.json()["repos"]] == ["demo-api", "demo-web"]
    written = json.loads((hub / "hub.json").read_text(encoding="utf-8"))
    assert written["repos"][-1] == {
        "dir": "demo-web",
        "github": "acme/demo-web",
        "check_fast": "make check-fast",
        "check": "make check",
        "default_branch": "trunk",
    }
    assert not (hub / "hub.local.json").exists()


# AGH-578 AC-6: each refusal of the shared case table answers one problem per CLI line, at its
# path, and writes nothing.
@pytest.mark.parametrize(
    ("case", "by_model"),
    [
        *(pytest.param(case, False, id=case.id) for case in REFUSAL_CASES),
        *(pytest.param(case, True, id=case.id) for case in MODEL_CASES),
    ],
)
def test_refuses_repo_edit_when_case_refused(
    composed: Any, make_hub: Callable[..., Path], case: RepoEditCase, *, by_model: bool
) -> None:
    hub = make_hub()
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201
    files = case.setup()
    document = {**files.hub, "platform": {"version": version("agent-hub-cli")}}
    (hub / "hub.json").write_bytes(dump_json(document))
    if files.local is not None:
        (hub / "hub.local.json").write_bytes(dump_json(files.local))
    before = {path.name: path.read_bytes() for path in hub.glob("hub*.json")}

    response = composed.client.post(REPOS, json=case.body, headers=OWN)

    assert response.status_code == 422, response.text
    assert response.headers["content-type"] == "application/problem+json"
    problem = response.json()
    assert problem["title"] == "This change was not saved"
    lead = "hub.json: " if by_model else ""
    assert [(error["pointer"], error["message"]) for error in problem["errors"]] == [
        (path, f"{lead}{message}") for path, message in case.expected
    ]
    assert {path.name: path.read_bytes() for path in hub.glob("hub*.json")} == before


# AGH-578 AC-6: a repo edit without this server's Origin is refused as config/environments is.
def test_refuses_repo_edit_when_origin_missing(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    assert composed.client.post(HUBS, json={"path": str(hub)}, headers=OWN).status_code == 201
    before = (hub / "hub.json").read_bytes()

    response = composed.client.post(REPOS, json={"op": "remove_repo", "dir": "demo-api"})

    assert response.status_code == 403, response.text
    assert (hub / "hub.json").read_bytes() == before
