"""``hub worktree --stack-on``'s pull request reading (AGH-381), over a scripted ``gh``."""

import json
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import WorktreeError, WorktreeUsageError
from agent_hub.cli.stack_on import stack_base, stack_repo
from agent_hub.cli.worktree_steps import StackBase
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo

URL = "https://github.com/acme/demo-web/pull/12"


def two_repo_config() -> HubConfig:
    document = a_hub_document()
    document["repos"] = [*document["repos"], a_second_repo()]
    return HubConfig.model_validate(document)


class ScriptedGh:
    """A ``gh`` that answers every call with ``answer``, recording each argv."""

    def __init__(self, answer: ChildResult) -> None:
        self.answer = answer
        self.calls: list[list[str]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path | str,
        env: Mapping[str, str],
        timeout: float | None,
        own_session: bool | None = None,
    ) -> ChildResult:
        del cwd, env, timeout, own_session
        self.calls.append(list(argv))
        return self.answer


def viewed(*, head: object = "jdoe/dem-6-y", state: object = "OPEN", fork: object = False) -> bytes:
    return json.dumps({"headRefName": head, "state": state, "isCrossRepository": fork}).encode()


def read(answer: ChildResult) -> StackBase:
    return stack_base(
        two_repo_config(), URL, gh="gh", cwd=Path("/hub"), env={}, runner=ScriptedGh(answer)
    )


def test_names_the_repo_and_head_branch_when_the_pull_request_is_open() -> None:
    gh = ScriptedGh(ChildResult(0, viewed(), b""))

    found = stack_base(two_repo_config(), URL, gh="gh", cwd=Path("/hub"), env={}, runner=gh)

    assert found == StackBase(repo="demo-web", branch="jdoe/dem-6-y")
    assert gh.calls == [["gh", "pr", "view", URL, "--json", "headRefName,state,isCrossRepository"]]


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/ACME/Demo-Web/pull/12",
        "https://github.com/acme/demo-web/pull/12/",
    ],
)
def test_matches_the_hub_repo_when_case_or_trailing_slash_differs(url: str) -> None:
    assert stack_repo(two_repo_config(), url) == "demo-web"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/acme/demo-web/issues/12",
        "https://github.com/acme/demo-web/pull/12/files",
        "http://github.com/acme/demo-web/pull/12",
        "https://github.com/acme/demo-web/pull/0",
        "--json=x",
    ],
)
def test_refuses_usage_when_the_url_is_not_a_pull_request(url: str) -> None:
    with pytest.raises(WorktreeUsageError, match="takes a pull request URL"):
        stack_repo(two_repo_config(), url)


def test_refuses_usage_when_the_repo_is_not_in_hub_json() -> None:
    with pytest.raises(WorktreeUsageError, match="acme/other is not a repo of hub.json"):
        stack_repo(two_repo_config(), "https://github.com/acme/other/pull/1")


@pytest.mark.parametrize(
    "answer",
    [
        ChildResult(1, b"", b"gh: synthetic failure\n"),
        ChildResult(0, b"not json", b""),
        ChildResult(0, b"[]", b""),
        ChildResult(0, viewed(head=""), b""),
        ChildResult(0, viewed(head=None), b""),
        ChildResult(0, viewed(state=None), b""),
        ChildResult(0, viewed(fork="no"), b""),
    ],
)
def test_refuses_when_gh_answer_cannot_be_read(answer: ChildResult) -> None:
    with pytest.raises(WorktreeError, match="could not read"):
        read(answer)


def test_names_the_state_when_the_pull_request_is_not_open() -> None:
    with pytest.raises(WorktreeError, match="is merged, not open"):
        read(ChildResult(0, viewed(state="MERGED"), b""))


def test_refuses_when_the_pull_request_comes_from_a_fork() -> None:
    with pytest.raises(WorktreeError, match="comes from a fork"):
        read(ChildResult(0, viewed(fork=True), b""))
