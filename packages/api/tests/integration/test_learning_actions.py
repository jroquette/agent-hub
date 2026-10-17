"""Accept and reject from the app (AC-201.23 to AC-201.26, AC-201.28, AC-201.31) on the composed
app, through ``hub_git`` against a real bare ``origin`` and a fake ``gh``: one hub pull request
per action, nothing on the default branch, the user's checkout untouched, one ``control_plane``
event, and no git or gh output answered or logged."""

import json
import logging
from typing import Any

import pytest

from agent_hub.core.events.event import Event, EventSource, EventType

ACTION_HEADERS = {"Origin": "http://127.0.0.1:7420"}
NOTE = """---
type: learning
---
# Run the gate before the PR

The fast gate catches format drift before review, so run it before every push.
"""
NOTE_PATH = "brain/_inbox/gate-first.md"
# Synthetic, shaped like a GitHub token so redaction replaces it; never a real secret.
LEAK_SAMPLE = "ghp_SYNTHETICredactionSENTINEL0123456789ab"
PULL_URL_PREFIX = "https://github.com/acme/demo-hub/pull/"


def _accept(app: Any, learning_id: str, target: str = "learnings/gotchas/gate-first.md") -> Any:
    return app.client.post(
        f"/api/v1/learnings/{learning_id}/accept", json={"target": target}, headers=ACTION_HEADERS
    )


def _reject(app: Any, learning_id: str, reason: str) -> Any:
    return app.client.post(
        f"/api/v1/learnings/{learning_id}/reject", json={"reason": reason}, headers=ACTION_HEADERS
    )


def _decisions(app: Any) -> list[Event]:
    decided = {EventType.LEARNING_ACCEPTED, EventType.LEARNING_REJECTED}
    return [event for event in app.rows() if event.type in decided]


def _created_pulls(world: Any) -> list[list[str]]:
    return [argv for argv in world.gh_calls() if argv[:2] == ["pr", "create"]]


def test_pushes_branch_with_moved_note_when_accepted(
    world_app: Any, propose: Any, hub_world: Any
) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE)
    main_before = hub_world.head("main")
    checkout_before = hub_world.snapshot()

    response = _accept(world_app, learning_id)

    assert response.status_code == 201, response.text
    result = response.json()
    branch = "jdoe/learning-accept-gate-first"
    assert result == {
        "state": "accepted_pr_open",
        "pr_url": f"{PULL_URL_PREFIX}1",
        "branch": branch,
    }
    assert hub_world.branches() == {"main", branch}
    assert hub_world.head("main") == main_before
    assert hub_world.origin("rev-list", "--count", f"main..{branch}").stdout.strip() == "1"
    author = hub_world.origin("log", "-1", "--format=%an <%ae>%n%cn <%ce>", branch).stdout
    assert author.split("\n")[:2] == ["Jane Doe <jane@example.com>"] * 2
    message = hub_world.origin("log", "-1", "--format=%B", branch).stdout
    assert "Co-Authored-By" not in message
    assert "Generated with" not in message
    moved = hub_world.file_on(branch, "brain/learnings/gotchas/gate-first.md")
    assert moved is not None
    assert "status: accepted" in moved
    assert "# Run the gate before the PR" in moved
    assert hub_world.file_on(branch, NOTE_PATH) is None
    assert hub_world.snapshot() == checkout_before
    assert list(hub_world.temp.iterdir()) == []
    (pull,) = hub_world.pulls()
    assert (pull["head"], pull["base"]) == (branch, "main")
    assert pull["title"] == "Accept learning: Run the gate before the PR"
    (event,) = _decisions(world_app)
    assert (event.type, event.source, event.session) == (
        EventType.LEARNING_ACCEPTED,
        EventSource.CONTROL_PLANE,
        "control-plane",
    )
    assert event.payload["pr_url"] == result["pr_url"]
    assert event.payload["brain_path"] == "brain/learnings/gotchas/gate-first.md"
    detail = world_app.client.get(f"/api/v1/learnings/{learning_id}").json()
    assert (detail["status"], detail["state"], detail["pr_url"]) == (
        "accepted",
        "accepted_pr_open",
        result["pr_url"],
    )


def test_adds_note_from_checkout_when_accepted_note_never_pushed(
    world_app: Any, propose: Any, hub_world: Any
) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE, push=False)
    main_before = hub_world.head("main")
    checkout_before = hub_world.snapshot()

    response = _accept(world_app, learning_id, "learnings/")

    assert response.status_code == 201, response.text
    branch = response.json()["branch"]
    moved = hub_world.file_on(branch, "brain/learnings/gate-first.md")
    assert moved is not None
    assert "status: accepted" in moved
    assert "# Run the gate before the PR" in moved
    assert hub_world.head("main") == main_before
    assert hub_world.snapshot() == checkout_before


def test_archives_note_with_reason_when_rejected(
    world_app: Any, propose: Any, hub_world: Any
) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE)
    main_before = hub_world.head("main")
    checkout_before = hub_world.snapshot()

    response = _reject(world_app, learning_id, "  Already covered by the testing playbook.  ")

    assert response.status_code == 201, response.text
    result = response.json()
    branch = "jdoe/learning-reject-gate-first"
    assert result == {
        "state": "rejected_pr_open",
        "pr_url": f"{PULL_URL_PREFIX}1",
        "branch": branch,
    }
    archived = hub_world.file_on(branch, "brain/_inbox/_archive/gate-first.md")
    assert archived is not None
    assert "rejected_reason: Already covered by the testing playbook." in archived
    assert hub_world.file_on(branch, NOTE_PATH) is None
    assert hub_world.head("main") == main_before
    assert hub_world.snapshot() == checkout_before
    (event,) = _decisions(world_app)
    assert (event.type, event.source) == (EventType.LEARNING_REJECTED, EventSource.CONTROL_PLANE)
    assert event.payload["reason"] == "Already covered by the testing playbook."
    detail = world_app.client.get(f"/api/v1/learnings/{learning_id}").json()
    assert (detail["state"], detail["rejection_reason"]) == (
        "rejected_pr_open",
        "Already covered by the testing playbook.",
    )


@pytest.mark.parametrize("reason", ["", "   ", "x" * 301])
def test_refuses_reject_when_reason_empty_or_long(
    world_app: Any, propose: Any, *, hub_world: Any, reason: str
) -> None:
    learning_id = propose(world_app, "gate-first.md", NOTE)

    response = _reject(world_app, learning_id, reason)

    assert response.status_code == 422, response.text
    assert response.json()["errors"][0]["pointer"] == "/reason"
    assert hub_world.branches() == {"main"}
    assert _decisions(world_app) == []


def _conflict_case(case: str, app: Any, *, propose: Any, world: Any) -> tuple[str, str]:
    """Set up ``case``; the learning id and the target to accept it to."""
    if case == "already_accepted":
        learning_id = propose(app, "gate-first.md", NOTE)
        assert _accept(app, learning_id).status_code == 201
        return learning_id, "learnings/again.md"
    learning_id = propose(app, "gate-first.md", NOTE)
    if case == "target_exists":
        world.put_note("brain/learnings/taken.md", "# Taken\n")
        return learning_id, "learnings/taken.md"
    targets = {
        "outside_brain": "../hub.json",
        "absolute": "/etc/learnings/",
        "inbox": "_inbox/elsewhere.md",
        "decisions": "decisions/gate-first.md",
        "auto": "auto/workspace/gate-first.md",
    }
    return learning_id, targets[case]


@pytest.mark.parametrize(
    "case",
    [
        "already_accepted",
        "target_exists",
        "outside_brain",
        "absolute",
        "inbox",
        "decisions",
        "auto",
    ],
)
def test_refuses_with_conflict_when_learning_or_target_conflicts(
    world_app: Any, propose: Any, *, hub_world: Any, case: str
) -> None:
    learning_id, target = _conflict_case(case, world_app, propose=propose, world=hub_world)
    branches_before, pulls_before = hub_world.branches(), len(_created_pulls(hub_world))
    decisions_before = len(_decisions(world_app))

    response = _accept(world_app, learning_id, target)

    assert response.status_code == 409, response.text
    problem = response.json()
    assert response.headers["content-type"] == "application/problem+json"
    assert problem["reason"]
    assert problem["detail"] == problem["reason"]
    if case == "already_accepted":
        assert problem["pr_url"] == f"{PULL_URL_PREFIX}1"
    assert hub_world.branches() == branches_before
    assert len(_created_pulls(hub_world)) == pulls_before
    assert len(_decisions(world_app)) == decisions_before
    assert list(hub_world.temp.iterdir()) == []


@pytest.mark.parametrize("failure", ["gh_fails", "push_rejected"])
def test_cleans_up_and_allows_retry_when_failure_in_git_or_gh(
    world_app: Any,
    propose: Any,
    *,
    hub_world: Any,
    caplog: pytest.LogCaptureFixture,
    failure: str,
) -> None:
    caplog.set_level(logging.DEBUG)
    learning_id = propose(world_app, "gate-first.md", NOTE)
    checkout_before = hub_world.snapshot()
    if failure == "gh_fails":
        hub_world.fail_gh()
    else:
        hub_world.reject_pushes()

    failed = _accept(world_app, learning_id)

    assert failed.status_code == 502, failed.text
    problem = failed.json()
    assert problem["title"] == "Could not open the pull request"
    assert "FAKEGH" not in failed.text
    assert "refused by the test origin" not in failed.text
    assert str(hub_world.bare) not in failed.text
    assert hub_world.branches() == {"main"}
    assert list(hub_world.temp.iterdir()) == []
    assert _decisions(world_app) == []
    assert hub_world.snapshot() == checkout_before
    logged = caplog.text + "".join(json.dumps(r.__dict__, default=str) for r in caplog.records)
    assert "FAKEGH" not in logged
    assert "refused by the test origin" not in logged

    hub_world.fail_gh(on=False)
    hub_world.reject_pushes(on=False)
    retried = _accept(world_app, learning_id)

    assert retried.status_code == 201, retried.text
    assert retried.json()["state"] == "accepted_pr_open"
    assert len(_decisions(world_app)) == 1


def test_refuses_actions_when_hub_read_only(
    open_composed: Any, propose: Any, hub_world: Any
) -> None:
    app = open_composed(brain_changes=hub_world.changes(AGENT_HUB_IN_CONTAINER="1"))
    assert (
        app.client.post(
            "/api/v1/hubs",
            json={"path": str(hub_world.hub)},
            headers={"Origin": "http://127.0.0.1:7420"},
        ).status_code
        == 201
    )
    learning_id = propose(app, "gate-first.md", NOTE)

    listed = app.client.get("/api/v1/learnings").json()["items"]
    detail = app.client.get(f"/api/v1/learnings/{learning_id}").json()
    accepted = _accept(app, learning_id)
    rejected = _reject(app, learning_id, "Not needed")

    assert [item["actions_unavailable"] for item in listed] == ["Hub is read-only here"]
    assert detail["actions_unavailable"] == "Hub is read-only here"
    assert detail["note"] is not None
    for response in (accepted, rejected):
        assert response.status_code == 409, response.text
        assert response.json()["reason"] == "Hub is read-only here"
    assert hub_world.branches() == {"main"}
    assert hub_world.gh_calls() == []
    assert _decisions(app) == []


def test_applies_redaction_to_reason_and_pull_request_when_note_holds_secret(
    world_app: Any,
    propose: Any,
    *,
    hub_world: Any,
    caplog: pytest.LogCaptureFixture,
    capfd: pytest.CaptureFixture[str],
) -> None:
    caplog.set_level(logging.DEBUG)
    note = f"# Token {LEAK_SAMPLE} leaked\n\nRotate {LEAK_SAMPLE} after the demo, then rerun.\n"
    learning_id = propose(world_app, "token.md", note)

    response = _reject(world_app, learning_id, f"Contains {LEAK_SAMPLE}, rotate it")

    assert response.status_code == 201, response.text
    (pull,) = hub_world.pulls()
    (event,) = _decisions(world_app)
    stored = json.dumps([e.model_dump(mode="json") for e in world_app.rows()])
    served = world_app.client.get(f"/api/v1/learnings/{learning_id}").json()
    captured = capfd.readouterr()
    logged = caplog.text + "".join(json.dumps(r.__dict__, default=str) for r in caplog.records)
    logged += captured.out + captured.err
    for text in (pull["title"], pull["body"], stored, logged, response.text):
        assert LEAK_SAMPLE not in text
        assert LEAK_SAMPLE[:12] not in text
    assert "[redacted: " in pull["title"]
    assert "[redacted: " in pull["body"]
    assert "[redacted: " in str(event.payload["reason"])
    assert "[redacted: " in served["rejection_reason"]
    assert "FAKEGH" not in logged
    assert str(hub_world.bare) not in logged
