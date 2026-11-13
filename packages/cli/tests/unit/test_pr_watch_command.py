"""``hub pr-watch``: when the watch of one pull request ends and what it prints.

``gh`` is a fake that answers each ``gh api <path>`` from a list of reads, and the clock's
``sleep`` only moves it on: no test waits or reaches the network.
"""

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from click import unstyle
from click.testing import Result
from typer.testing import CliRunner

from agent_hub.cli import pr_watch_command
from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.main import app
from agent_hub.cli.pr_watch_command import WatchEnd, WatchRequest, parse_since, watch
from agent_hub.core.testing.workflow_fakes import START, FakeClock

REPO = "acme/demo-api"
HEAD = "a" * 40
PULL = "repos/acme/demo-api/pulls/7"
CHECKS = f"repos/acme/demo-api/commits/{HEAD}/check-runs?per_page=100"
REVIEWS = f"{PULL}/reviews?per_page=100"
# One read: these three calls, in this order.
ONE_READ = [("gh", "api", path) for path in (PULL, CHECKS, REVIEWS)]
# Text of a pull request and of a review, which the command never keeps or prints.
TITLE = "feat(api): a title that is never printed"
BODY = "A body that is never printed."
# What the command keeps of ``a_pull()`` with one successful check run and no review.
SNAPSHOT = {
    "merged": False,
    "state": "open",
    "head": HEAD,
    "mergeable_state": "clean",
    "checks": {"success": 1},
    "comments": 0,
    "review_comments": 0,
    "reviews": 0,
}
EVERY = timedelta(seconds=300)
# The command-line tests start their watch at the fake clock's ``START``.
SINCE = "2026-10-15T09:00:00Z"
# ``gh``'s error output for a pull request it cannot find: two lines, the last one long and
# with a terminal escape.
NOT_FOUND = ChildResult(
    1,
    b"",
    ("warning: first line\ngh: Not Found (HTTP 404) \x1b[31m" + "x" * 400 + "\n").encode(),
)


def a_pull(**changed: object) -> dict[str, object]:
    """An open pull request as GitHub's REST API answers it; ``changed`` replaces fields."""
    pull: dict[str, object] = {
        "number": 7,
        "title": TITLE,
        "body": BODY,
        "state": "open",
        "merged": False,
        "mergeable_state": "clean",
        "head": {"ref": "feature", "sha": HEAD},
        "comments": 0,
        "review_comments": 0,
    }
    return {**pull, **changed}


def a_check_run(status: str = "completed", conclusion: str | None = "success") -> dict[str, object]:
    return {"name": "check", "status": status, "conclusion": conclusion}


def check_runs(*runs: dict[str, object]) -> dict[str, object]:
    """The first page of a commit's check runs."""
    return {"total_count": len(runs), "check_runs": list(runs)}


@dataclass(frozen=True)
class Read:
    """One read's three replies: each a JSON value, a ``ChildResult`` or an exception to raise."""

    pull: Any = field(default_factory=a_pull)
    checks: Any = field(default_factory=lambda: check_runs(a_check_run()))
    reviews: Any = field(default_factory=list)


class FakeGh:
    """Answers ``gh api <path>`` from ``reads``, in order; the last read repeats.

    A call to the pull request's path starts the next read. Every argv is recorded.
    """

    def __init__(self, *reads: Read) -> None:
        self.reads = reads
        self.calls: list[tuple[str, ...]] = []
        self._started = 0

    def __call__(self, argv: Sequence[str]) -> ChildResult:
        # No test makes 100 reads: a watch that never ends fails here instead of hanging.
        assert len(self.calls) < 300, "the watch does not end"
        self.calls.append(tuple(argv))
        path = argv[-1]
        if path == PULL:
            self._started += 1
        read = self.reads[max(min(self._started, len(self.reads)), 1) - 1]
        if path == PULL:
            reply = read.pull
        elif path.endswith("/check-runs?per_page=100"):
            reply = read.checks
        elif path == REVIEWS:
            reply = read.reviews
        else:
            raise AssertionError(f"no reply for {list(argv)}")
        if isinstance(reply, Exception):
            raise reply
        if isinstance(reply, ChildResult):
            return reply
        return ChildResult(0, json.dumps(reply).encode(), b"")


def run_watch(
    gh: FakeGh, *, since: datetime = START, every: int = 300, window: int = 100
) -> tuple[WatchEnd, FakeClock]:
    """Watch pull request 7 from ``START``: ``every`` in seconds, ``window`` in minutes."""
    clock = FakeClock()
    request = WatchRequest(
        github=REPO,
        number=7,
        since=since,
        every=timedelta(seconds=every),
        window=timedelta(minutes=window),
    )
    return watch(request, gh=gh, clock=clock), clock


def reported(end: WatchEnd) -> dict[str, Any]:
    """The JSON line of ``end``, parsed."""
    report: dict[str, Any] = json.loads(end.line())
    return report


def padded(value: object, size: int) -> ChildResult:
    """A reply of exactly ``size`` bytes: ``value`` as JSON, then blanks."""
    return ChildResult(0, json.dumps(value).encode().ljust(size), b"")


@dataclass
class CommandLine:
    """``hub pr-watch`` run in this process, with ``gh`` as its child and a clock that never
    sleeps; ``children`` holds each child's argv and options."""

    gh: FakeGh
    clock: FakeClock = field(default_factory=FakeClock)
    children: list[dict[str, Any]] = field(default_factory=list)

    def run(self, *args: str) -> Result:
        # Wide enough that an error message stays on one line.
        return CliRunner().invoke(app, ["pr-watch", *args], env={"COLUMNS": "200"})


def a_command_line(monkeypatch: pytest.MonkeyPatch, *reads: Read) -> CommandLine:
    command = CommandLine(FakeGh(*reads))

    def run_child(argv: Sequence[str], **options: Any) -> ChildResult:
        command.children.append({"argv": list(argv), **options})
        return command.gh(argv)

    monkeypatch.setattr(pr_watch_command, "run_child", run_child)
    monkeypatch.setattr(pr_watch_command, "SystemClock", lambda: command.clock)
    return command


def shown(result: Result) -> str:
    """Everything the command printed, without styles, its blanks joined."""
    return " ".join(unstyle(result.output).split())


def refuses(result: Result, name: str) -> bool:
    """Whether the command's error says that the value of ``name`` is refused."""
    return re.search(rf"Invalid value for '?{re.escape(name)}'?:", shown(result)) is not None


MERGED = Read(pull=a_pull(merged=True, state="closed"))


def test_exits_at_once_when_pr_already_merged() -> None:
    gh = FakeGh(MERGED)

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("merged", 0)
    assert end.line() == (
        '{"event": "merged", "pr": {"merged": true, "state": "closed", '
        f'"head": "{HEAD}", "mergeable_state": "clean", "checks": {{"success": 1}}, '
        '"comments": 0, "review_comments": 0, "reviews": 0}, "elapsed_minutes": 0}'
    )
    assert list(reported(end)["pr"]) == list(SNAPSHOT)
    assert TITLE not in end.line()
    assert BODY not in end.line()
    assert gh.calls == ONE_READ
    assert clock.sleeps == []


def test_exits_at_once_when_pr_already_closed() -> None:
    gh = FakeGh(Read(pull=a_pull(state="closed")))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("closed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, "state": "closed"}
    assert gh.calls == ONE_READ
    assert clock.sleeps == []


def test_exits_expired_when_total_limit_passed() -> None:
    gh = FakeGh(MERGED)

    end, clock = run_watch(gh, since=START - timedelta(hours=24))

    assert (end.event, end.exit_code) == ("expired", 0)
    assert end.line() == '{"event": "expired", "pr": null, "elapsed_minutes": 1440}'
    assert gh.calls == []
    assert clock.sleeps == []
    # One second before the limit, the pull request is still read.
    early, _ = run_watch(gh, since=START - timedelta(hours=24) + timedelta(seconds=1))
    assert early.event == "merged"
    assert gh.calls == ONE_READ


def test_exits_changed_when_pr_merged() -> None:
    gh = FakeGh(Read(), Read(pull=a_pull(merged=True)))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert end.line() == json.dumps(
        {"event": "changed", "pr": {**SNAPSHOT, "merged": True}, "elapsed_minutes": 5}
    )
    assert clock.sleeps == [EVERY]
    assert gh.calls == ONE_READ * 2


def test_exits_changed_when_mergeable_state_turns_dirty() -> None:
    gh = FakeGh(Read(), Read(pull=a_pull(mergeable_state="dirty")))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, "mergeable_state": "dirty"}
    assert clock.sleeps == [EVERY]


def test_exits_changed_when_a_check_completes() -> None:
    queued = Read(checks=check_runs(a_check_run("queued", None)))
    in_progress = Read(checks=check_runs(a_check_run("in_progress", None)))
    gh = FakeGh(queued, in_progress, Read())

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == SNAPSHOT
    # A run with no conclusion counts under "pending" whatever its status: the second read
    # is no change.
    assert clock.sleeps == [EVERY, EVERY]
    still, _ = run_watch(FakeGh(queued, in_progress), window=5)
    assert still.event == "quiet"
    assert reported(still)["pr"]["checks"] == {"pending": 1}


def test_exits_changed_when_review_count_grows() -> None:
    review = {"id": 1, "state": "COMMENTED", "body": BODY}
    gh = FakeGh(Read(), Read(reviews=[review]))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, "reviews": 1}
    assert BODY not in end.line()
    assert clock.sleeps == [EVERY]


def test_exits_changed_when_head_moves() -> None:
    moved = "b" * 40
    gh = FakeGh(Read(), Read(pull=a_pull(head={"ref": "feature", "sha": moved})))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, "head": moved}
    # The check runs read are those of the commit the pull request now ends at.
    moved_checks = f"repos/acme/demo-api/commits/{moved}/check-runs?per_page=100"
    assert gh.calls == [*ONE_READ, ("gh", "api", PULL), ("gh", "api", moved_checks), ONE_READ[2]]
    assert clock.sleeps == [EVERY]


@pytest.mark.parametrize(
    ("name", "value"),
    [("state", "closed"), ("comments", 1), ("review_comments", 1)],
)
def test_exits_changed_when_state_or_comment_counts_differ(name: str, value: object) -> None:
    gh = FakeGh(Read(), Read(pull=a_pull(**{name: value})))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, name: value}
    assert clock.sleeps == [EVERY]


def test_reads_only_through_get_when_polling() -> None:
    # The baseline, a read that shows no change, then one more successful check run.
    gh = FakeGh(Read(), Read(), Read(checks=check_runs(a_check_run(), a_check_run())))

    end, _ = run_watch(gh)

    assert end.event == "changed"
    assert reported(end)["pr"]["checks"] == {"success": 2}
    # Each call is `gh api <path>` and nothing more: with no method and no field, gh sends a GET.
    assert gh.calls == ONE_READ * 3
    for call in gh.calls:
        assert not {"-X", "--method", "-f", "-F", "--input"} & set(call)


def test_exits_quiet_when_window_ends() -> None:
    gh = FakeGh(Read())

    end, clock = run_watch(gh, since=START - timedelta(minutes=60), window=7)

    assert (end.event, end.exit_code) == ("quiet", 0)
    assert end.line() == json.dumps({"event": "quiet", "pr": SNAPSHOT, "elapsed_minutes": 67})
    # The last wait is cut to what is left of the window.
    assert clock.sleeps == [EVERY, timedelta(seconds=120)]
    assert gh.calls == ONE_READ * 3


def test_exits_expired_when_limit_passes_during_window() -> None:
    gh = FakeGh(Read())

    end, clock = run_watch(gh, since=START - (timedelta(hours=24) - timedelta(minutes=2)))

    assert (end.event, end.exit_code) == ("expired", 0)
    assert end.line() == json.dumps({"event": "expired", "pr": SNAPSHOT, "elapsed_minutes": 1440})
    # The wait is cut to what is left of the 24 hours.
    assert clock.sleeps == [timedelta(seconds=120)]
    assert gh.calls == ONE_READ * 2


def test_refuses_window_when_over_110_minutes(monkeypatch: pytest.MonkeyPatch) -> None:
    command = a_command_line(monkeypatch, MERGED)

    for minutes in ("111", "0"):
        result = command.run(REPO, "7", "--since", SINCE, "--for", minutes)
        assert result.exit_code == 2, shown(result)
        assert refuses(result, "--for"), shown(result)
    assert command.children == []
    for minutes in ("110", "1"):
        result = command.run(REPO, "7", "--since", SINCE, "--for", minutes)
        assert result.exit_code == 0, shown(result)


def test_refuses_interval_when_outside_60_to_1800_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = a_command_line(monkeypatch, MERGED)

    for seconds in ("59", "1801"):
        result = command.run(REPO, "7", "--since", SINCE, "--every", seconds)
        assert result.exit_code == 2, shown(result)
        assert refuses(result, "--every"), shown(result)
    assert command.children == []
    for seconds in ("60", "1800"):
        result = command.run(REPO, "7", "--since", SINCE, "--every", seconds)
        assert result.exit_code == 0, shown(result)


def test_refuses_since_when_not_an_iso_time(monkeypatch: pytest.MonkeyPatch) -> None:
    command = a_command_line(monkeypatch, MERGED)

    not_a_time = command.run(REPO, "7", "--since", "yesterday")
    missing = command.run(REPO, "7")

    assert not_a_time.exit_code == 2, shown(not_a_time)
    assert refuses(not_a_time, "--since"), shown(not_a_time)
    assert missing.exit_code == 2, shown(missing)
    assert "--since" in shown(missing)
    assert command.children == []


@pytest.mark.parametrize(
    ("github", "number", "refused"),
    [
        ("acme", "7", "GITHUB"),
        ("acme/demo-api/x", "7", "GITHUB"),
        (".acme/demo-api", "7", "GITHUB"),
        ("acme/..", "7", "GITHUB"),
        ("acme/demo-api?per_page=1", "7", "GITHUB"),
        (REPO, "0", "NUMBER"),
        (REPO, "x", "NUMBER"),
    ],
)
def test_refuses_target_when_repo_or_number_malformed(
    monkeypatch: pytest.MonkeyPatch, *, github: str, number: str, refused: str
) -> None:
    command = a_command_line(monkeypatch, MERGED)

    result = command.run(github, number, "--since", SINCE)

    assert result.exit_code == 2, shown(result)
    assert refuses(result, refused), shown(result)
    assert command.children == []


def test_reads_since_as_utc_when_offset_missing() -> None:
    expected = datetime(2026, 10, 14, 9, 0, tzinfo=UTC)

    assert parse_since("2026-10-14T09:00:00") == expected
    assert parse_since("2026-10-14T09:00:00Z") == expected
    assert parse_since("2026-10-14T11:00:00+02:00") == expected
    assert parse_since("yesterday") is None


def test_retries_at_next_interval_when_one_read_fails() -> None:
    failed = Read(pull=NOT_FOUND)
    gh = FakeGh(failed, Read(), failed, failed, Read(pull=a_pull(comments=1)))

    end, clock = run_watch(gh)

    # Two failed reads in a row do not end the watch, and a good read clears the count.
    assert (end.event, end.exit_code) == ("changed", 0)
    assert reported(end)["pr"] == {**SNAPSHOT, "comments": 1}
    assert clock.sleeps == [EVERY] * 4


@pytest.mark.parametrize(
    ("read", "path"),
    [
        pytest.param(Read(pull=NOT_FOUND), PULL, id="gh-exits-with-http-404"),
        pytest.param(
            Read(checks=ChildTimedOutError(program="gh", timeout=30.0)), CHECKS, id="gh-times-out"
        ),
        pytest.param(
            Read(pull=FileNotFoundError(2, "No such file or directory", "gh")),
            PULL,
            id="gh-cannot-start",
        ),
        pytest.param(
            Read(reviews=ChildResult(0, b"<html>Bad Gateway</html>", b"")),
            REVIEWS,
            id="reply-not-json",
        ),
        pytest.param(Read(pull=[a_pull()]), PULL, id="pull-is-a-list"),
        pytest.param(
            Read(pull=a_pull(head={"ref": "feature", "sha": "../../x"})),
            PULL,
            id="head-sha-not-hex",
        ),
        pytest.param(Read(checks={"total_count": 1}), CHECKS, id="no-check-runs-list"),
        pytest.param(Read(reviews={"message": "Not Found"}), REVIEWS, id="reviews-is-an-object"),
    ],
)
def test_reports_unreadable_when_three_reads_fail_in_a_row(read: Read, path: str) -> None:
    gh = FakeGh(read)

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("unreadable", 3)
    report = reported(end)
    assert set(report) == {"event", "pr", "elapsed_minutes", "reason"}
    assert (report["pr"], report["elapsed_minutes"]) == (None, 10)
    assert clock.sleeps == [EVERY, EVERY]
    # The reason names the call that failed, on one printable line of 300 characters at most.
    reason = report["reason"]
    assert reason.startswith(f"gh api {path}: ")
    assert "\n" not in reason
    assert reason.isprintable()
    assert len(reason) <= 300
    # No path is built from a head that is not a commit id.
    assert {call[-1] for call in gh.calls} <= {PULL, CHECKS, REVIEWS}


def test_counts_read_as_failed_when_reply_reaches_one_mib() -> None:
    merged = a_pull(merged=True, state="closed")
    # A reply as long as the cap was cut: only its end was kept.
    gh = FakeGh(Read(pull=padded(merged, 1 << 20)))

    cut, clock = run_watch(gh)

    assert (cut.event, cut.exit_code) == ("unreadable", 3)
    assert reported(cut)["reason"].startswith(f"gh api {PULL}: ")
    assert clock.sleeps == [EVERY, EVERY]
    whole, _ = run_watch(FakeGh(Read(pull=padded(merged, (1 << 20) - 1))))
    assert whole.event == "merged"


def test_keeps_last_snapshot_when_reads_fail_after_baseline() -> None:
    gh = FakeGh(Read(), Read(pull=NOT_FOUND))

    end, clock = run_watch(gh)

    assert (end.event, end.exit_code) == ("unreadable", 3)
    assert reported(end)["pr"] == SNAPSHOT
    assert reported(end)["elapsed_minutes"] == 15
    assert clock.sleeps == [EVERY] * 3


def test_reads_every_five_minutes_for_100_minutes_when_defaults_used(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    command = a_command_line(monkeypatch, Read())

    result = command.run(REPO, "7", "--since", SINCE)

    assert result.exit_code == 0, shown(result)
    assert json.loads(result.stdout) == {"event": "quiet", "pr": SNAPSHOT, "elapsed_minutes": 100}
    assert command.clock.sleeps == [EVERY] * 20
    assert len(command.gh.calls) == 63


def test_pins_limits_when_module_loaded() -> None:
    assert timedelta(hours=24) == pr_watch_command.TOTAL_LIMIT
    assert pr_watch_command.GH_TIMEOUT == 30.0
    assert pr_watch_command.MAX_FAILED_READS == 3
    assert pr_watch_command.UNREADABLE_EXIT == 3
    assert pr_watch_command.GH_API_OUTPUT_LIMIT == 1 << 20


@pytest.mark.parametrize(
    ("read", "event", "exit_code"),
    [
        pytest.param(MERGED, "merged", 0, id="merged-at-once"),
        pytest.param(
            Read(pull=NOT_FOUND, checks=NOT_FOUND, reviews=NOT_FOUND),
            "unreadable",
            3,
            id="every-call-fails",
        ),
    ],
)
def test_maps_event_to_exit_code_when_command_runs(
    monkeypatch: pytest.MonkeyPatch, *, read: Read, event: str, exit_code: int
) -> None:
    monkeypatch.setenv("LINEAR_API_KEY", "lin-fake")
    monkeypatch.setenv("GH_TOKEN", "gh-fake")
    command = a_command_line(monkeypatch, read)

    result = command.run(REPO, "7", "--since", SINCE)

    assert result.exit_code == exit_code, shown(result)
    # One JSON line, ended by a line break.
    assert result.stdout.endswith("\n")
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout)["event"] == event
    # gh is killed after 30 seconds, its reply is read up to 1 MiB, and it stays in the
    # caller's process group; it gets the GitHub token and not the tracker's key.
    first = command.children[0]
    assert first["argv"] == ["gh", "api", PULL]
    assert (first["timeout"], first["output_limit"], first["own_session"]) == (30.0, 1 << 20, False)
    assert "LINEAR_API_KEY" not in first["env"]
    assert "GH_TOKEN" in first["env"]
