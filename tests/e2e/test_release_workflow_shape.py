"""release.yml's shape (ADR 0047), parsed as YAML: which job runs on which event, in which order,
with which permissions, and that no input reaches a shell through an expression."""

from typing import Any

import pytest
import yaml

from tests.e2e.conftest import RELEASE_WORKFLOW

DISPATCH_FROM_MAIN = "github.event_name == 'workflow_dispatch' && github.ref == 'refs/heads/main'"
CHECK_AFTER_TAG = (
    "${{ !cancelled() && (github.event_name == 'push' || needs.release-tag.result == 'success') }}"
)
TAG_EXPRESSION = (
    "${{ github.event_name == 'workflow_dispatch' && format('v{0}', inputs.version)"
    " || github.ref_name }}"
)


@pytest.fixture
def workflow() -> dict[Any, Any]:
    document = yaml.safe_load(RELEASE_WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def triggers(workflow: dict[Any, Any]) -> dict[str, Any]:
    """The ``on:`` mapping; YAML 1.1 reads the bare key ``on`` as ``True``."""
    found = workflow.get("on", workflow.get(True))
    assert isinstance(found, dict)
    return found


def all_steps(workflow: dict[Any, Any]) -> list[dict[str, Any]]:
    return [step for job in workflow["jobs"].values() for step in job["steps"]]


def test_takes_version_sha_notes_when_dispatched(workflow: dict[Any, Any]) -> None:
    on = triggers(workflow)

    assert sorted(on["workflow_dispatch"]["inputs"]) == ["notes", "sha", "version"]
    assert on["push"] == {"tags": ["v*"]}


def test_names_version_and_sha_in_run_name_when_dispatched(workflow: dict[Any, Any]) -> None:
    run_name = workflow["run-name"]

    assert "format('release v{0} at {1}', inputs.version, inputs.sha)" in run_name


def test_runs_tag_job_only_when_dispatched_from_main(workflow: dict[Any, Any]) -> None:
    assert workflow["jobs"]["release-tag"]["if"] == DISPATCH_FROM_MAIN


def test_runs_check_after_tag_job_when_dispatched_or_alone_when_pushed(
    workflow: dict[Any, Any],
) -> None:
    check = workflow["jobs"]["release-check"]

    assert check["needs"] == "release-tag"
    assert check["if"] == CHECK_AFTER_TAG
    assert check["env"]["TAG"] == TAG_EXPRESSION


def test_writes_only_from_tag_job_when_permissions_read(workflow: dict[Any, Any]) -> None:
    jobs = workflow["jobs"]

    assert workflow["permissions"] == {"contents": "read"}
    assert jobs["release-tag"]["permissions"] == {"contents": "write"}
    assert "permissions" not in jobs["release-check"]


def test_keeps_credentials_out_of_checkouts_when_workflow_read(workflow: dict[Any, Any]) -> None:
    checkouts = [
        step
        for step in all_steps(workflow)
        if str(step.get("uses", "")).startswith("actions/checkout@")
    ]

    assert len(checkouts) == 2
    assert all(step["with"]["persist-credentials"] is False for step in checkouts)


def test_holds_token_only_in_steps_that_reach_remote_when_tag_job_read(
    workflow: dict[Any, Any],
) -> None:
    steps = workflow["jobs"]["release-tag"]["steps"]

    with_token = [step["name"] for step in steps if "GIT_CONFIG_KEY_0" in step.get("env", {})]

    assert with_token == ["Create and push the annotated tag, unless it exists"]


def test_keeps_expressions_out_of_run_when_workflow_read(workflow: dict[Any, Any]) -> None:
    """Inputs reach run: only through env (script injection), whatever the run: form."""
    runs = [str(step["run"]) for step in all_steps(workflow) if "run" in step]

    assert runs
    assert [run for run in runs if "${{" in run] == []
