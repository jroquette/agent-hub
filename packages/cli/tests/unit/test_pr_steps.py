from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from agent_hub.cli import pr_steps
from agent_hub.cli.child_process import ChildResult
from agent_hub.cli.errors import PrStepError
from agent_hub.cli.pr_steps import (
    OpenedPr,
    PrTarget,
    StepTimeouts,
    TitledPr,
    error_tail,
    git_output,
    open_or_find_pr,
    pr_url_of,
    push_branch,
    refuse_risky_config,
    refuse_uncommitted,
    run_gate,
    titled_pr,
    unmatched_warning,
)
from agent_hub.cli.run_children import push_command
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_conventions_document

CALLER_ENV = {
    "PATH": "/bin",
    "LINEAR_API_KEY": "lin-fake",
    "GH_TOKEN": "gh-fake",
    "GITHUB_TOKEN": "github-fake",
}
TOKENS = ("LINEAR_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")
OK = ChildResult(0, b"", b"")
TARGET = PrTarget(github="acme/demo-api", base_branch="trunk", branch="jdoe/dem-7-x")
TIMEOUTS = StepTimeouts(gate=11.0, push=13.0, gh=17.0, git=19.0)
LIST = ("git", "config", "--list", "--show-scope", "--includes", "-z")
ORIGIN = ("git", "config", "--get-all", "remote.origin.url")
GITHUB_ORIGIN = ChildResult(0, b"https://github.com/acme/demo-api.git\n", b"")
CREATE = ("gh", "pr", "create")
VIEW = ("gh", "pr", "view")
PR_URL = "https://github.com/acme/demo-api/pull/7"
CREATE_FAILED = ChildResult(1, b"", b"a pull request for branch already exists\n")
CREATE_ARGV = (
    *("gh", "pr", "create", "--repo", "acme/demo-api", "--base", "trunk"),
    *("--head", "jdoe/dem-7-x", "--title", "feat: add x", "--body", "DEM-7"),
)


@dataclass(frozen=True)
class Call:
    argv: tuple[str, ...]
    env: dict[str, str]
    timeout: float
    cwd: Path | None


@dataclass
class FakeChild:
    """A ``ChildCall`` that records each call and answers from ``script``: the answer of the
    longest argv prefix it holds, else exit 0 with no output."""

    script: dict[tuple[str, ...], ChildResult] = field(default_factory=dict)
    calls: list[Call] = field(default_factory=list)

    def __call__(
        self,
        argv: Sequence[str],
        *,
        env: dict[str, str],
        timeout: float,
        output_limit: int = 0,
        cwd: Path | None = None,
    ) -> ChildResult:
        self.calls.append(Call(tuple(argv), dict(env), timeout, cwd))
        matches = [prefix for prefix in self.script if tuple(argv[: len(prefix)]) == prefix]
        return self.script[max(matches, key=len)] if matches else OK

    def argvs(self) -> list[tuple[str, ...]]:
        return [call.argv for call in self.calls]

    def names(self, index: int) -> set[str]:
        """The variable names of call ``index``'s environment."""
        return set(self.calls[index].env)


def test_keeps_last_chars_when_error_tail_long() -> None:
    data = b"a" * 10 + b"b" * 500

    assert pr_steps.MAX_ERROR_TAIL_CHARS == 500
    assert error_tail(data) == "b" * 500


def test_accepts_url_when_last_line_is_https() -> None:
    stdout = b"Creating pull request\nhttps://github.com/acme/demo-api/pull/7\n"

    assert pr_url_of(stdout) == "https://github.com/acme/demo-api/pull/7"
    assert pr_url_of(b"https://github.com/acme/demo-api/pull/7 extra\n") is None
    assert pr_url_of(b"http://github.com/acme/demo-api/pull/7\n") is None
    assert pr_url_of(b"") is None


def test_rejects_url_when_over_limit() -> None:
    prefix = "https://github.com/"
    longest = prefix + "a" * (2_048 - len(prefix))

    assert pr_steps.MAX_PR_URL_CHARS == 2_048
    assert pr_url_of(longest.encode()) == longest
    assert pr_url_of((longest + "a").encode()) is None


def test_imports_no_child_runner_when_module_loaded() -> None:
    """The steps run every child through the caller's ``child``, so that ``hub run``'s tests,
    which patch ``run_steps.run_child``, still see each one."""
    assert not hasattr(pr_steps, "run_child")


def test_refuses_when_tracked_change_left() -> None:
    child = FakeChild({("git", "status"): ChildResult(0, b" M src/x.py\n", b"")})

    with pytest.raises(PrStepError) as raised:
        refuse_uncommitted(child, environ=CALLER_ENV, timeout=5.0)

    assert raised.value.reason == "uncommitted changes in the worktree"
    assert child.argvs() == [("git", "status", "--porcelain", "--untracked-files=no")]


def test_passes_when_worktree_clean() -> None:
    child = FakeChild()

    refuse_uncommitted(child, environ=CALLER_ENV, timeout=5.0, cwd=Path("/w"))

    assert child.calls[0].cwd == Path("/w")


def test_hides_tokens_when_gate_runs() -> None:
    child = FakeChild({("bash",): ChildResult(1, b"out", b"err")})

    result = run_gate(child, gate="make check", environ=CALLER_ENV, timeout=5.0)

    assert result == ChildResult(1, b"out", b"err")
    assert child.argvs() == [("bash", "-c", "make check")]
    assert not set(TOKENS) & child.names(0)
    assert "PATH" in child.names(0)


def test_names_git_command_when_git_read_fails() -> None:
    child = FakeChild({("git", "log"): ChildResult(128, b"", b"fatal: bad revision\n")})

    with pytest.raises(PrStepError) as raised:
        git_output(child, "log", "-1", environ=CALLER_ENV, timeout=5.0)

    assert raised.value.reason == "git log failed: fatal: bad revision"
    assert not set(TOKENS) & child.names(0)


def test_returns_stdout_when_exit_code_accepted() -> None:
    child = FakeChild({("git", "config"): ChildResult(1, b"", b"")})

    assert git_output(child, "config", "--get", "x", environ={}, timeout=5.0, accept=(0, 1)) == ""


def test_passes_given_timeout_when_gate_runs() -> None:
    child = FakeChild()

    run_gate(child, gate="true", environ=CALLER_ENV, timeout=7.0)
    git_output(child, "status", environ=CALLER_ENV, timeout=3.0)

    assert [call.timeout for call in child.calls] == [7.0, 3.0]


def test_names_key_when_credential_helper_set() -> None:
    listed = b"local\0credential.helper\nsecret-store\0local\0core.bare\nfalse\0"
    child = FakeChild({LIST: ChildResult(0, listed, b""), ORIGIN: GITHUB_ORIGIN})

    with pytest.raises(PrStepError) as raised:
        push_branch(child, target=TARGET, environ=CALLER_ENV, timeouts=TIMEOUTS)

    assert raised.value.reason == (
        "git config holds keys a push would use (credential.helper); the branch was not pushed"
    )
    assert "secret-store" not in raised.value.reason
    assert child.argvs() == [LIST]


def test_refuses_when_origin_not_github() -> None:
    child = FakeChild({ORIGIN: ChildResult(0, b"https://example.com/acme/demo-api.git\n", b"")})

    with pytest.raises(PrStepError) as raised:
        refuse_risky_config(
            child,
            github="acme/demo-api",
            environ=CALLER_ENV,
            timeout=5.0,
            use="a fetch would use",
            outcome="nothing was fetched",
            cwd=Path("/repo"),
        )

    assert raised.value.reason == (
        "remote.origin.url is not the GitHub url of acme/demo-api; nothing was fetched"
    )
    assert [call.cwd for call in child.calls] == [Path("/repo"), Path("/repo")]


def test_pushes_with_overrides_when_config_clean() -> None:
    child = FakeChild({ORIGIN: GITHUB_ORIGIN})

    push_branch(child, target=TARGET, environ=CALLER_ENV, timeouts=TIMEOUTS)

    assert child.argvs() == [LIST, ORIGIN, tuple(push_command("jdoe/dem-7-x"))]
    push = child.calls[2]
    assert push.argv[:7] == (
        *("git", "-c", "core.fsmonitor=false", "-c", "push.gpgSign=false"),
        *("-c", "core.hooksPath=/dev/null"),
    )
    assert push.argv[7:] == ("push", "--no-verify", "-u", "origin", "jdoe/dem-7-x")
    assert "GH_TOKEN" in child.names(2)
    assert "LINEAR_API_KEY" not in child.names(2)
    assert push.env["GIT_CONFIG_COUNT"] == "3"
    assert [call.timeout for call in child.calls] == [19.0, 19.0, 13.0]
    assert not {"GH_TOKEN", "GITHUB_TOKEN"} & (child.names(0) | child.names(1))


def test_names_tail_when_push_fails() -> None:
    rejected = ChildResult(1, b"", b"x" * 600 + b"! [rejected] (fetch first)\n")
    child = FakeChild({ORIGIN: GITHUB_ORIGIN, ("git", "-c"): rejected})

    with pytest.raises(PrStepError) as raised:
        push_branch(child, target=TARGET, environ=CALLER_ENV, timeouts=TIMEOUTS)

    assert raised.value.reason.startswith("push failed: xxx")
    assert raised.value.reason.endswith("! [rejected] (fetch first)\n")
    assert len(raised.value.reason) == len("push failed: ") + 500


def open_pr(child: FakeChild, *, draft: bool = False) -> OpenedPr:
    return open_or_find_pr(
        child,
        target=TARGET,
        title="feat: add x",
        body="DEM-7",
        draft=draft,
        environ=CALLER_ENV,
        timeout=17.0,
    )


def viewed(state: str) -> ChildResult:
    return ChildResult(0, f'{{"url": "{PR_URL}", "state": "{state}"}}'.encode(), b"")


def test_uses_open_pr_when_create_fails() -> None:
    child = FakeChild({CREATE: CREATE_FAILED, VIEW: viewed("OPEN")})

    assert open_pr(child) == OpenedPr(url=PR_URL, found=True)
    assert child.argvs()[1] == (
        *("gh", "pr", "view", "jdoe/dem-7-x", "--repo", "acme/demo-api"),
        *("--json", "url,state"),
    )
    assert "GH_TOKEN" in child.names(1)
    assert "LINEAR_API_KEY" not in child.names(1)
    assert [call.timeout for call in child.calls] == [17.0, 17.0]


def test_fails_when_found_pr_closed() -> None:
    child = FakeChild({CREATE: CREATE_FAILED, VIEW: viewed("CLOSED")})

    with pytest.raises(PrStepError) as raised:
        open_pr(child)

    assert raised.value.reason == "gh pr create failed: a pull request for branch already exists\n"
    assert [argv[:3] for argv in child.argvs()] == [CREATE, VIEW]


@pytest.mark.parametrize(
    "answer",
    [
        ChildResult(1, f'{{"url": "{PR_URL}", "state": "OPEN"}}'.encode(), b""),
        ChildResult(0, b"not json", b""),
        ChildResult(0, b"[]", b""),
        ChildResult(0, b'{"state": "OPEN", "url": "javascript:x"}', b""),
        ChildResult(0, b'{"state": "OPEN", "url": "https://a\\nb"}', b""),
        ChildResult(0, b'{"state": "OPEN", "url": 7}', b""),
    ],
    ids=["exit-1", "not-json", "not-object", "not-https", "line-break", "not-string"],
)
def test_fails_when_found_pr_url_refused(answer: ChildResult) -> None:
    child = FakeChild({CREATE: CREATE_FAILED, VIEW: answer})

    with pytest.raises(PrStepError) as raised:
        open_pr(child)

    assert raised.value.reason == "gh pr create failed: a pull request for branch already exists\n"
    assert [argv[:3] for argv in child.argvs()] == [CREATE, VIEW]


def test_fails_when_create_prints_no_url() -> None:
    child = FakeChild({CREATE: ChildResult(0, b"done\n", b"")})

    with pytest.raises(PrStepError) as raised:
        open_pr(child)

    assert raised.value.reason == "gh printed no PR url"
    assert child.argvs() == [CREATE_ARGV]


def test_adds_draft_when_draft_asked() -> None:
    created = ChildResult(0, f"{PR_URL}\n".encode(), b"")
    child = FakeChild({CREATE: created})

    assert open_pr(child, draft=True) == OpenedPr(url=PR_URL, found=False)
    assert open_pr(child, draft=False) == OpenedPr(url=PR_URL, found=False)
    assert child.argvs() == [(*CREATE_ARGV, "--draft"), CREATE_ARGV]
    assert "GH_TOKEN" in child.names(0)


def test_reports_unmatched_line_when_subject_off_pattern() -> None:
    conventions = HubConfig.model_validate(a_conventions_document()).conventions_for("demo-web")

    off = titled_pr("add x", conventions=conventions, issue_id="DEM-7", workspace="/ws")
    matched = titled_pr(
        "DEM-7: feat(cli): add x", conventions=conventions, issue_id="DEM-7", workspace="/ws"
    )

    assert off == TitledPr(title="add x", unmatched="add x")
    assert matched == TitledPr(title="DEM-7: feat(cli): add x", unmatched=None)
    assert unmatched_warning("hub ship", line="add x", commit_title=conventions.commit_title) == (
        "hub ship: warning: the commit subject `add x` does not match"
        " commit_title `{ISSUE}: {type}({scope}): {summary}`; the PR title is the subject"
    )
    assert unmatched_warning("hub run", line="", commit_title="{summary}").endswith(
        "; the PR title is the issue id"
    )


def test_runs_gate_in_given_folder_when_cwd_passed() -> None:
    child = FakeChild()

    run_gate(child, gate="true", environ=CALLER_ENV, timeout=5.0, cwd=Path("/w/demo-api"))

    assert [call.cwd for call in child.calls] == [Path("/w/demo-api")]


def test_pushes_from_given_folder_when_cwd_passed() -> None:
    child = FakeChild({ORIGIN: GITHUB_ORIGIN})

    push_branch(
        child, target=TARGET, environ=CALLER_ENV, timeouts=TIMEOUTS, cwd=Path("/w/demo-api")
    )

    assert [call.cwd for call in child.calls] == [Path("/w/demo-api")] * 3


def test_opens_pr_from_given_folder_when_cwd_passed() -> None:
    child = FakeChild({CREATE: CREATE_FAILED, VIEW: viewed("OPEN")})

    open_or_find_pr(
        child,
        target=TARGET,
        title="feat: add x",
        body="DEM-7",
        draft=False,
        environ=CALLER_ENV,
        timeout=17.0,
        cwd=Path("/w/demo-api"),
    )

    assert [call.cwd for call in child.calls] == [Path("/w/demo-api")] * 2


def test_runs_in_caller_folder_when_cwd_not_passed() -> None:
    child = FakeChild({ORIGIN: GITHUB_ORIGIN, CREATE: ChildResult(0, PR_URL.encode(), b"")})

    run_gate(child, gate="true", environ=CALLER_ENV, timeout=5.0)
    push_branch(child, target=TARGET, environ=CALLER_ENV, timeouts=TIMEOUTS)
    open_pr(child)

    assert [call.cwd for call in child.calls] == [None] * 5
