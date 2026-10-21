from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.brain.brain_note import BrainNoteNotFoundError, BrainNoteTooLargeError
from agent_hub.core.brain.brain_path import BrainPathError
from agent_hub.core.hub_config.config_view import HubConfigView, hub_config_view
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.projects.project_views import ProjectDetail, ProjectNow, RepoView, TrackerView
from agent_hub.core.testing.builders import a_conventions_document
from agent_hub.core.testing.read_model_builders import (
    HUB_ID,
    a_brain_note,
    a_brain_tree,
    a_project_summary,
)


def _detail() -> ProjectDetail:
    return ProjectDetail(
        name="demo",
        hub_id=HUB_ID,
        hub_path="/home/demo/demo-hub",
        hub_repo="acme/demo-hub",
        tracker=TrackerView(kind="linear", teams=("DEM",), ready_label=None, failed_label=None),
        default_branch="main",
        branch_prefix="jdoe/",
        platform_version="0.8.0",
        lock_version="0.8.0",
        lock_state="in_sync",
        modules=(),
    )


def test_maps_cards_when_projects_listed(wired: Any) -> None:
    wired.hubs.projects.append(a_project_summary())

    response = wired.client.get("/api/v1/projects")

    assert response.json()["items"] == [a_project_summary().model_dump(mode="json")]


def test_maps_detail_now_and_repos_when_project_parts_requested(wired: Any) -> None:
    wired.hubs.details["demo"] = _detail()
    wired.hubs.nows["demo"] = ProjectNow(
        project="demo", focus=(), next=(), watch=(), source_path="brain/now.md"
    )
    wired.hubs.repos["demo"] = [
        RepoView(
            name="demo-api",
            dir="demo-api",
            github="acme/demo-api",
            role=None,
            default_branch="main",
            check_fast="make check-fast",
            check="make check",
            agents_md_present=True,
            agents_md_lines=40,
        )
    ]

    detail = wired.client.get("/api/v1/projects/demo").json()
    now = wired.client.get("/api/v1/projects/demo/now").json()
    repos = wired.client.get("/api/v1/projects/demo/repos").json()

    assert detail["hub_path"] == "/home/demo/demo-hub"
    assert now["source_path"] == "brain/now.md"
    assert repos["items"][0]["name"] == "demo-api"


def test_answers_not_found_when_project_unknown(wired: Any) -> None:
    for suffix in ("", "/now", "/repos"):
        response = wired.client.get(f"/api/v1/projects/nope{suffix}")

        assert response.status_code == 404, suffix
        assert response.json()["detail"] == "No project with id 'nope'."


def test_maps_brain_tree_when_brain_requested(wired: Any) -> None:
    wired.hubs.brains["demo"] = a_brain_tree()

    response = wired.client.get("/api/v1/projects/demo/brain")

    assert response.json() == a_brain_tree().model_dump(mode="json")
    assert wired.hubs.calls == [("brain_tree", "demo")]


def test_maps_brain_note_when_note_requested(wired: Any) -> None:
    wired.hubs.notes[("demo", "_inbox/testing-x.md")] = a_brain_note()

    response = wired.client.get(
        "/api/v1/projects/demo/brain/note", params={"path": "_inbox/testing-x.md"}
    )

    assert response.json() == a_brain_note().model_dump(mode="json")
    assert wired.hubs.calls == [("brain_note", ("demo", "_inbox/testing-x.md"))]


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (BrainPathError("Path has an empty, hidden or parent segment"), 400),
        (BrainNoteNotFoundError(project="demo", path="auto/me.md"), 404),
        (BrainNoteTooLargeError(project="demo", path="a.md", size=300_000, limit=262_144), 413),
    ],
)
def test_answers_problem_when_brain_note_refused(wired: Any, error: Exception, status: int) -> None:
    wired.hubs.failure = error

    response = wired.client.get("/api/v1/projects/demo/brain/note", params={"path": "../x.md"})

    assert response.status_code == status
    assert response.headers["content-type"] == "application/problem+json"


def test_answers_not_found_when_brain_of_unknown_project_requested(wired: Any) -> None:
    response = wired.client.get("/api/v1/projects/nope/brain")

    assert response.status_code == 404
    assert response.json()["detail"] == "No project with id 'nope'."


@pytest.mark.parametrize("note_path", ["", "a" * 513])
def test_rejects_note_path_when_out_of_bounds(wired: Any, note_path: str) -> None:
    response = wired.client.get("/api/v1/projects/demo/brain/note", params={"path": note_path})

    assert response.status_code == 400


def _config() -> HubConfigView:
    return hub_config_view(
        hub_path="/home/demo/demo-hub",
        config=HubConfig.model_validate(a_conventions_document()),
        local=LocalConfig(),
        read_git=lambda _keys: {},
    )


# AC-PG-38.1: GET /projects/{project}/config answers the project's config view: per repo its
# branch, patterns with examples and checks; the tracker and the models, each with its source.
def test_answers_config_view_when_project_config_requested(wired: Any) -> None:
    wired.hubs.configs["demo"] = _config()

    response = wired.client.get("/api/v1/projects/demo/config")

    assert response.status_code == 200, response.text
    body = response.json()
    assert body == _config().model_dump(mode="json")
    assert [(repo["dir"], repo["check_fast"], repo["check"]) for repo in body["repos"]] == [
        ("demo-api", "make check-fast", "make check"),
        ("demo-web", "make check-fast", "make check"),
    ]
    assert body["repos"][1]["pr_title"]["example"] == "DEM-42: feat(api): add the hub config view"
    assert body["repos"][0]["default_branch"]["source"] == "default"
    assert body["tracker"]["transport"]["source"] == "default"
    assert body["model_tiers"] == {"small": "haiku", "medium": "sonnet", "large": "opus"}
    assert body["author_email"]["source"] == "team"
    assert wired.hubs.calls == [("hub_config", "demo")]


# AC-PG-38.1: an unknown project answers 404.
def test_answers_not_found_when_config_of_unknown_project_requested(wired: Any) -> None:
    response = wired.client.get("/api/v1/projects/nope/config")

    assert response.status_code == 404
    assert response.json()["detail"] == "No project with id 'nope'."


def test_lists_env_file_names_only_when_env_file_keys_requested(wired: Any, tmp_path: Path) -> None:
    (tmp_path / "demo-hub").mkdir()
    (tmp_path / "demo-api").mkdir()
    (tmp_path / "demo-api" / "dotenv.staging").write_text(
        "DATABASE_URL=postgres://pw@db\nTOKEN=x\n"
    )
    wired.hubs.configs["demo"] = hub_config_view(
        hub_path=str(tmp_path / "demo-hub"),
        config=HubConfig.model_validate(a_conventions_document()),
        local=LocalConfig(),
        read_git=lambda _keys: {},
    )

    response = wired.client.get(
        "/api/v1/projects/demo/env-file-keys", params={"path": "demo-api/dotenv.staging"}
    )

    assert response.status_code == 200
    assert response.json()["keys"] == ["DATABASE_URL", "TOKEN"]
    assert "pw@db" not in response.text


@pytest.mark.parametrize("path", ["../outside", "/etc/passwd", "~/x", "a b"])
def test_rejects_env_file_path_when_it_escapes_the_workspace(wired: Any, path: str) -> None:
    wired.hubs.configs["demo"] = _config()

    response = wired.client.get("/api/v1/projects/demo/env-file-keys", params={"path": path})

    assert response.status_code == 400
