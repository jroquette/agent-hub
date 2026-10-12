from typing import Any

import pytest

from agent_hub.core.brain.brain_note import BrainNoteNotFoundError, BrainNoteTooLargeError
from agent_hub.core.brain.brain_path import BrainPathError
from agent_hub.core.projects.project_views import ProjectDetail, ProjectNow, RepoView, TrackerView
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
