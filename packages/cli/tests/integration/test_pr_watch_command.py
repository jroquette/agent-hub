"""``hub pr-watch``: the real command, run in process against a fake ``gh`` on ``PATH``.

The pull request is already merged, so the command ends on its first read: the test waits no
interval. ``brief_workspace`` puts its rule-driven fake ``gh`` first on a ``PATH`` built from
scratch, so no real ``gh`` can run.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from typer.testing import Result

pytestmark = pytest.mark.disable_socket

# The conftest's in-process run and workspace (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

HEAD = "5f" * 20
PULL = "repos/acme/api/pulls/7"
CHECKS = f"repos/acme/api/commits/{HEAD}/check-runs?per_page=100"
REVIEWS = f"{PULL}/reviews?per_page=100"
# A merged pull request as GitHub's REST API answers it; its title and body are never printed.
PULL_REPLY = {
    "number": 7,
    "title": "feat(api): a title that is never printed",
    "body": "A body that is never printed.",
    "state": "closed",
    "merged": True,
    "mergeable_state": "unknown",
    "head": {"ref": "feature", "sha": HEAD},
    "comments": 2,
    "review_comments": 1,
}
CHECKS_REPLY = {
    "total_count": 1,
    "check_runs": [{"name": "check", "status": "completed", "conclusion": "success"}],
}
REVIEWS_REPLY = [{"id": 1, "state": "APPROVED", "body": "A review that is never printed."}]
MERGED_LINE = (
    '{"event": "merged", "pr": {"merged": true, "state": "closed", "head": "' + HEAD + '",'
    ' "mergeable_state": "unknown", "checks": {"success": 1}, "comments": 2,'
    ' "review_comments": 1, "reviews": 1}, "elapsed_minutes": 0}\n'
)


def test_prints_one_json_line_when_pr_already_merged(
    brief_workspace: Workspace, run_command: CommandRunner
) -> None:
    brief_workspace.answer(
        [
            {"argv_has": ["api", PULL], "stdout": json.dumps(PULL_REPLY)},
            {"argv_has": ["api", CHECKS], "stdout": json.dumps(CHECKS_REPLY)},
            {"argv_has": ["api", REVIEWS], "stdout": json.dumps(REVIEWS_REPLY)},
        ]
    )
    since = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

    result = run_command(brief_workspace.hub, "pr-watch", "acme/api", "7", "--since", since)

    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    assert result.stdout == MERGED_LINE
    calls = [json.loads(line)["argv"][1:] for line in brief_workspace.calls().splitlines()]
    assert calls == [["api", PULL], ["api", CHECKS], ["api", REVIEWS]]
