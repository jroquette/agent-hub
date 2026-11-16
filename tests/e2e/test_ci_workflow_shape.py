"""ci.yml's authorship job (AGH-4, AGH-699 C-9), parsed as YAML.

The job runs the same ``Authorship`` step as the hub CI the generator renders, byte for byte (the
generator's ``test_ci_authorship.py`` runs that step), with the owner's email in its environment
since this repo has no ``hub.json``; it runs again when a pull request is edited, and the required
``check`` job needs it.
"""

import re
from typing import Any

import pytest
import yaml

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub
from tests.e2e.conftest import REPO_ROOT

CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
OWNER_EMAIL = "roquettejh@gmail.com"
PULL_REQUEST_ONLY = "github.event_name == 'pull_request'"
# An action pinned by its 40-hex commit SHA, the release named in a comment (as the hub CI's).
PINNED_CHECKOUT = re.compile(r"^      - uses: actions/checkout@[0-9a-f]{40}  # v\d+\.\d+\.\d+$")


def load(text: str) -> dict[Any, Any]:
    document = yaml.safe_load(text)
    assert isinstance(document, dict)
    return document


@pytest.fixture
def workflow() -> dict[Any, Any]:
    return load(CI_WORKFLOW.read_text(encoding="utf-8"))


def hub_authorship_step() -> dict[str, Any]:
    config = HubConfig.model_validate(a_hub_document())
    ci = next(file for file in render_hub(config).files if file.path == ".github/workflows/ci.yml")
    steps = load(ci.content.decode("utf-8"))["jobs"]["check"]["steps"]
    found = [step for step in steps if step.get("name") == "Authorship"]
    assert len(found) == 1
    return dict(found[0])


def test_runs_hub_authorship_step_when_pull_request_checked(workflow: dict[Any, Any]) -> None:
    steps = workflow["jobs"]["authorship"]["steps"]
    hub_step = hub_authorship_step()

    assert [step.get("name", step.get("uses")) for step in steps][1:] == ["Authorship"]
    assert steps[1]["run"] == hub_step["run"]
    assert steps[1]["if"] == hub_step["if"] == PULL_REQUEST_ONLY
    assert steps[1]["env"] == {"AUTHOR_EMAIL": OWNER_EMAIL}
    assert "${{" not in steps[1]["run"]


def test_fetches_pull_request_history_when_authorship_checks_out(
    workflow: dict[Any, Any],
) -> None:
    checkout = workflow["jobs"]["authorship"]["steps"][0]
    lines = CI_WORKFLOW.read_text(encoding="utf-8").splitlines()
    job = lines[lines.index("  authorship:") :]

    assert checkout["if"] == PULL_REQUEST_ONLY
    assert checkout["with"] == {"persist-credentials": False, "fetch-depth": 0}
    assert PINNED_CHECKOUT.match(next(line for line in job if "uses:" in line))


def test_reruns_when_pull_request_edited(workflow: dict[Any, Any]) -> None:
    on = workflow.get("on", workflow.get(True))
    assert isinstance(on, dict)

    assert on["pull_request"] == {"types": ["opened", "synchronize", "reopened", "edited"]}
    assert on["push"] == {"branches": ["main"]}


def test_needs_authorship_when_check_job_read(workflow: dict[Any, Any]) -> None:
    assert "authorship" in workflow["jobs"]["check"]["needs"]
