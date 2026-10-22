"""``GhEventSource`` (AGH-481): GitHub events read through ``gh api``, over an injected launch."""

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.schedules.scheduled_starts import EventPollError, EventQuery, EventRef
from agent_hub.hub_git.git_runner import OUTPUT_LIMIT, ProcessResult
from agent_hub.hub_git.github_events import GhEventSource

SHA_A, SHA_B = "a" * 40, "b" * 40
MERGES = EventQuery("merge", "acme/demo", "main")
PULLS = EventQuery("pr_opened", "acme/demo", "main")
RED_RUNS = EventQuery("ci_red", "acme/demo", "release")


class CannedLaunch:
    """Answers every child with ``answer`` (JSON data, bytes or an exception), recording it."""

    def __init__(self, answer: Any, *, returncode: int = 0) -> None:
        self.answer = answer
        self.returncode = returncode
        self.calls: list[dict[str, Any]] = []

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        env: Mapping[str, str],
        timeout: float,
        keep_stdout: bool,
    ) -> ProcessResult:
        self.calls.append(
            {
                "argv": list(argv),
                "cwd": cwd,
                "env": dict(env),
                "timeout": timeout,
                "keep": keep_stdout,
            }
        )
        if isinstance(self.answer, BaseException):
            raise self.answer
        stdout = self.answer if isinstance(self.answer, bytes) else json.dumps(self.answer).encode()
        return ProcessResult(returncode=self.returncode, stdout=stdout)


@pytest.fixture
def gh_path(tmp_path: Path) -> str:
    tool = tmp_path / "bin" / "gh"
    tool.parent.mkdir()
    tool.write_text("#!/bin/sh\n")
    tool.chmod(0o755)
    return str(tool.parent)


def a_source(gh_path: str, launch: CannedLaunch, **environ: str) -> GhEventSource:
    return GhEventSource(environ={"PATH": gh_path, **environ}, launch=launch, timeout=30.0)


def test_reads_merge_shas_newest_first_when_gh_lists_commits(gh_path: str) -> None:
    launch = CannedLaunch([{"sha": SHA_B, "commit": {}}, {"sha": SHA_A}])

    refs = a_source(gh_path, launch).poll(MERGES)

    assert refs == (EventRef(SHA_B, {"sha": SHA_B}), EventRef(SHA_A, {"sha": SHA_A}))
    [call] = launch.calls
    assert call["argv"][1:] == [
        "api", "-X", "GET", "repos/acme/demo/commits", "-f", "sha=main", "-f", "per_page=20",
    ]  # fmt: skip
    assert (call["timeout"], call["keep"]) == (30.0, True)


def test_reads_pr_number_and_head_sha_when_gh_lists_open_pulls(gh_path: str) -> None:
    launch = CannedLaunch([{"number": 12, "head": {"sha": SHA_A}}])

    refs = a_source(gh_path, launch).poll(PULLS)

    assert refs == (EventRef("12", {"pr": 12, "sha": SHA_A}),)
    assert launch.calls[0]["argv"][4:] == [
        "repos/acme/demo/pulls", "-f", "state=open", "-f", "sort=created",
        "-f", "direction=desc", "-f", "per_page=20",
    ]  # fmt: skip


def test_reads_failed_run_ids_when_gh_lists_red_runs(gh_path: str) -> None:
    launch = CannedLaunch({"total_count": 1, "workflow_runs": [{"id": 9001, "head_sha": SHA_B}]})

    refs = a_source(gh_path, launch).poll(RED_RUNS)

    assert refs == (EventRef("9001", {"ci_run": 9001, "sha": SHA_B}),)
    assert launch.calls[0]["argv"][4:] == [
        "repos/acme/demo/actions/runs", "-f", "branch=release", "-f", "status=failure",
        "-f", "per_page=20",
    ]  # fmt: skip


def test_keeps_the_first_page_when_gh_lists_more_events_than_polled(gh_path: str) -> None:
    launch = CannedLaunch([{"sha": f"{index:040x}"} for index in range(25)])

    assert len(a_source(gh_path, launch).poll(MERGES)) == 20


def test_sends_only_relative_github_api_paths_when_events_polled(gh_path: str) -> None:
    calls = []
    for query, empty in ((MERGES, []), (PULLS, []), (RED_RUNS, {"workflow_runs": []})):
        launch = CannedLaunch(empty)
        assert a_source(gh_path, launch).poll(query) == ()
        calls += launch.calls

    for call in calls:
        argv = call["argv"]
        assert argv[0] == os.path.join(os.path.realpath(gh_path), "gh")
        assert argv[1:4] == ["api", "-X", "GET"]
        assert argv[4].startswith("repos/acme/demo/")
        assert "://" not in " ".join(argv)


def test_drops_linear_key_from_gh_env_when_events_polled(gh_path: str) -> None:
    launch = CannedLaunch([])

    a_source(gh_path, launch, LINEAR_API_KEY="lin_" + "x" * 12, GIT_DIR="/x").poll(MERGES)

    env = launch.calls[0]["env"]
    assert "LINEAR_API_KEY" not in env
    assert "GIT_DIR" not in env
    assert env["GH_PROMPT_DISABLED"] == "1"


def test_refuses_answer_when_gh_output_fills_the_cap(gh_path: str) -> None:
    launch = CannedLaunch(b"[" + b" " * (OUTPUT_LIMIT - 1))

    with pytest.raises(EventPollError, match="answer too large"):
        a_source(gh_path, launch).poll(MERGES)


def test_raises_poll_error_when_gh_answer_is_not_json(gh_path: str) -> None:
    with pytest.raises(EventPollError, match="answer not JSON"):
        a_source(gh_path, CannedLaunch(b"<html>")).poll(MERGES)


@pytest.mark.parametrize(
    ("query", "answer"),
    [
        (MERGES, [{"sha": "not-a-sha"}]),
        (MERGES, [{"sha": SHA_A.upper()}]),
        (MERGES, {"sha": SHA_A}),
        (PULLS, [{"number": "12", "head": {"sha": SHA_A}}]),
        (PULLS, [{"number": True, "head": {"sha": SHA_A}}]),
        (RED_RUNS, {"workflow_runs": [{"id": 0, "head_sha": SHA_A}]}),
        (RED_RUNS, {"workflow_runs": [{"id": 2**53 + 1, "head_sha": SHA_A}]}),
    ],
)
def test_raises_poll_error_when_an_item_has_no_valid_sha(
    gh_path: str, query: EventQuery, answer: Any
) -> None:
    with pytest.raises(EventPollError, match="unexpected answer"):
        a_source(gh_path, CannedLaunch(answer)).poll(query)


@pytest.mark.parametrize(
    "error", [TimeoutError(), subprocess.TimeoutExpired(["gh"], 30.0)], ids=["timeout", "expired"]
)
def test_raises_poll_error_when_gh_times_out(gh_path: str, error: Exception) -> None:
    with pytest.raises(EventPollError, match="gh timed out"):
        a_source(gh_path, CannedLaunch(error)).poll(MERGES)


def test_raises_poll_error_when_gh_is_missing(tmp_path: Path) -> None:
    launch = CannedLaunch([])

    with pytest.raises(EventPollError, match="gh not found"):
        a_source(str(tmp_path), launch).poll(MERGES)
    assert launch.calls == []


def test_raises_poll_error_when_gh_exits_non_zero(gh_path: str) -> None:
    secret_text = b'{"message": "Bad credentials"}'

    with pytest.raises(EventPollError, match="gh exited 1") as caught:
        a_source(gh_path, CannedLaunch(secret_text, returncode=1)).poll(MERGES)
    assert "Bad credentials" not in str(caught.value)
