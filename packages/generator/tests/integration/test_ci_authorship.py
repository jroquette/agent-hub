"""The rendered CI step ``Authorship``, run the way Actions runs it (AGH-4, AGH-699 C-9).

On a pull request, the step fails when the PR's title, body or a commit message carries AI
attribution, or, when an author email is known (``AUTHOR_EMAIL``, else ``hub.json``'s
``project.author_email``), when a commit of the PR is authored or committed with another email
(GitHub's own committer, ``noreply@github.com``, is let through). The title and body come from the
event file Actions writes (``GITHUB_EVENT_PATH``), never from an expression in the run block.
Each case takes the step's ``run: |`` block by its fixed indentation and runs it on ``bash`` with
Actions' default flags in a git repository holding the demo ``hub.json``, the PR's commits made
with real git on top of a base commit.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

TIMEOUT = 30
CI = ".github/workflows/ci.yml"
STEP = "      - name: Authorship\n"
RUN_HEAD = "        run: |\n"
BLOCK_INDENT = " " * 10
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
AUTHOR = ("Jane Doe", "jane@example.com")
FOREIGN = ("Bot", "noreply@anthropic.com")
WEB_FLOW = ("GitHub", "noreply@github.com")
CLEAN_TITLE = "feat(api): add the login endpoint"
CLEAN_BODY = "## Summary\n\nThe endpoint checks the session.\n"
# Built from fragments, so this file holds no attribution line a reader could take for one.
FOOTER = "\U0001f916 Generated " + "with [Claude Code](https://claude.com/claude-code)"
TRAILER = "Co-Authored-" + "By: Claude <noreply@anthropic.com>"
# The footer and trailer a Claude Code cloud session adds, built from fragments too.
CLOUD_FOOTER = "_Generated " + "by [Claude Code](https://claude.ai/code/session_0123)_"
SESSION_TRAILER = "Claude-" + "Session: https://claude.ai/code/session_0123"
UNREADABLE_EVENT = "Authorship: cannot read the pull request from the event file\n"


def authorship_block(ci: str) -> str:
    """The step's ``run: |`` block as bash reads it: its lines at the block's indent, dedented."""
    step = ci[ci.index(STEP) :]
    body = step[step.index(RUN_HEAD) + len(RUN_HEAD) :]
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip() and not line.startswith(BLOCK_INDENT):
            break
        lines.append(line.removeprefix(BLOCK_INDENT))
    assert lines, ci
    return "".join(lines)


def demo_ci() -> str:
    config = HubConfig.model_validate(a_hub_document())
    return next(file for file in render_hub(config).files if file.path == CI).content.decode()


def real(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, f"the authorship step runs {name}: install it"
    return os.path.realpath(found)


class PullRequest:
    """A repository in ``tmp_path/ws`` with a base commit, and the PR's commits on top of it."""

    def __init__(self, tmp_path: Path, hub_json: dict[str, Any] | None) -> None:
        self.tmp_path = tmp_path
        self.workspace = tmp_path / "ws"
        self.workspace.mkdir()
        if hub_json is not None:
            (self.workspace / "hub.json").write_text(json.dumps(hub_json), encoding="utf-8")
        self.git("init", "-q")
        self.base = self.commit("chore: base", author=AUTHOR)

    def git(self, *arguments: str, env: dict[str, str] | None = None) -> str:
        completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
            [real("git"), *arguments],
            capture_output=True,
            text=True,
            check=True,
            cwd=self.workspace,
            env={
                "PATH": os.pathsep.join(SYSTEM_PATH),
                "HOME": str(self.tmp_path / "home"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
            }
            | (env or {}),
            timeout=TIMEOUT,
        )
        return completed.stdout.strip()

    def commit(
        self,
        message: str,
        *,
        author: tuple[str, str] = AUTHOR,
        committer: tuple[str, str] | None = None,
    ) -> str:
        by = committer or author
        self.git(
            "commit",
            "-q",
            "--allow-empty",
            "-m",
            message,
            env={
                "GIT_AUTHOR_NAME": author[0],
                "GIT_AUTHOR_EMAIL": author[1],
                "GIT_COMMITTER_NAME": by[0],
                "GIT_COMMITTER_EMAIL": by[1],
            },
        )
        return self.git("rev-parse", "HEAD")

    def run_step(
        self,
        *,
        title: str = CLEAN_TITLE,
        body: str | None = CLEAN_BODY,
        env: dict[str, str] | None = None,
        event: object = None,
    ) -> subprocess.CompletedProcess[str]:
        """Run the rendered block with an event of ``title`` and ``body`` (or ``event`` as given)
        over ``base..HEAD``, ``python3`` being this interpreter."""
        head = self.git("rev-parse", "HEAD")
        if event is None:
            event = {
                "action": "edited",
                "pull_request": {
                    "title": title,
                    "body": body,
                    "base": {"sha": self.base},
                    "head": {"sha": head},
                },
            }
        event_path = self.tmp_path / "event.json"
        event_path.write_text(json.dumps(event), encoding="utf-8")
        bin_dir = self.tmp_path / "bin"
        if not bin_dir.exists():
            bin_dir.mkdir()
            (bin_dir / "python3").symlink_to(os.path.realpath(sys.executable))
        return subprocess.run(  # noqa: S603 - absolute bash, the rendered block, no shell
            [real("bash"), *BASH_FLAGS, "-c", authorship_block(demo_ci())],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.workspace,
            env={
                "PATH": os.pathsep.join((str(bin_dir), *SYSTEM_PATH)),
                "HOME": str(self.tmp_path / "home"),
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GITHUB_EVENT_PATH": str(event_path),
            }
            | (env or {}),
            timeout=TIMEOUT,
        )


@pytest.fixture
def pull_request(tmp_path: Path) -> PullRequest:
    """The demo ``hub.json`` (author ``jane@example.com``) and a base commit by that author."""
    return PullRequest(tmp_path, a_hub_document())


def test_fails_when_body_carries_footer_then_passes_when_edited(
    pull_request: PullRequest,
) -> None:
    pull_request.commit("feat(api): add the login endpoint")

    footer = pull_request.run_step(body=f"{CLEAN_BODY}\n{FOOTER}\n")
    edited = pull_request.run_step(body=CLEAN_BODY)

    assert footer.returncode == 1
    assert footer.stderr == "Authorship: the pull request body carries AI attribution\n"
    assert edited.returncode == 0, edited.stderr
    assert edited.stdout == "Authorship: the title, the body and 1 commit(s) are clean\n"


def test_fails_when_body_carries_cloud_session_footer(pull_request: PullRequest) -> None:
    pull_request.commit("feat(api): add the login endpoint")

    completed = pull_request.run_step(body=f"{CLEAN_BODY}\n---\n{CLOUD_FOOTER}\n")

    assert completed.returncode == 1
    assert completed.stderr == "Authorship: the pull request body carries AI attribution\n"


def test_fails_when_commit_carries_session_trailer(pull_request: PullRequest) -> None:
    sha = pull_request.commit(f"feat(api): add the login endpoint\n\n{SESSION_TRAILER}")

    completed = pull_request.run_step()

    assert completed.returncode == 1
    assert (
        completed.stderr == f"Authorship: commit {sha[:12]}: the message carries AI attribution\n"
    )


@pytest.mark.parametrize("title", [f"feat: login {FOOTER[0]}", f"feat: login ({TRAILER})"])
def test_fails_when_title_carries_attribution(title: str, pull_request: PullRequest) -> None:
    pull_request.commit("feat(api): add the login endpoint")

    completed = pull_request.run_step(title=title)

    assert completed.returncode == 1
    assert completed.stderr == "Authorship: the pull request title carries AI attribution\n"


@pytest.mark.parametrize(
    ("author", "committer", "role"),
    [(FOREIGN, AUTHOR, "author"), (AUTHOR, FOREIGN, "committer")],
    ids=["author", "committer"],
)
def test_fails_when_commit_identity_foreign(
    *, author: tuple[str, str], committer: tuple[str, str], role: str, pull_request: PullRequest
) -> None:
    pull_request.commit("feat(api): add the login endpoint")
    sha = pull_request.commit("fix(api): check the token", author=author, committer=committer)

    completed = pull_request.run_step()

    assert completed.returncode == 1
    assert completed.stderr == (
        f"Authorship: commit {sha[:12]}: the {role} email noreply@anthropic.com is not"
        " jane@example.com\n"
    )


def test_fails_when_commit_message_carries_trailer(pull_request: PullRequest) -> None:
    sha = pull_request.commit(f"feat(api): add the login endpoint\n\n{TRAILER}\n")

    completed = pull_request.run_step()

    assert completed.returncode == 1
    assert (
        completed.stderr == f"Authorship: commit {sha[:12]}: the message carries AI attribution\n"
    )


def test_lists_every_problem_when_several_found(pull_request: PullRequest) -> None:
    sha = pull_request.commit(f"feat: x\n\n{TRAILER}\n", author=FOREIGN, committer=AUTHOR)

    completed = pull_request.run_step(title=f"feat: x {FOOTER[0]}", body=FOOTER)

    assert completed.returncode == 1
    assert completed.stderr.splitlines() == [
        "Authorship: the pull request title carries AI attribution",
        "Authorship: the pull request body carries AI attribution",
        f"Authorship: commit {sha[:12]}: the message carries AI attribution",
        f"Authorship: commit {sha[:12]}: the author email noreply@anthropic.com is not"
        " jane@example.com",
    ]


def test_passes_when_pull_request_clean(pull_request: PullRequest) -> None:
    pull_request.commit("feat(api): add the login endpoint")
    # GitHub's own committer (a web edit, "Update branch") for a commit the author made.
    pull_request.commit("fix(api): check the token", committer=WEB_FLOW)

    completed = pull_request.run_step(body=None)

    assert completed.returncode == 0, completed.stderr
    assert (completed.stdout, completed.stderr) == (
        "Authorship: the title, the body and 2 commit(s) are clean\n",
        "",
    )


def test_reads_only_pull_request_commits_when_base_has_others(tmp_path: Path) -> None:
    pull_request = PullRequest(tmp_path, a_hub_document())
    # The base branch's history is not the PR's: an older foreign commit is not checked.
    pull_request.base = pull_request.commit("chore: older", author=FOREIGN)
    pull_request.commit("feat(api): add the login endpoint")

    completed = pull_request.run_step()

    assert completed.returncode == 0, completed.stderr


def test_checks_only_attribution_when_no_author_email_known(tmp_path: Path) -> None:
    document = a_hub_document()
    del document["project"]["author_email"]
    pull_request = PullRequest(tmp_path, document)
    pull_request.commit("feat(api): add the login endpoint", author=("Other", "other@example.com"))

    clean = pull_request.run_step()
    sha = pull_request.commit(f"fix: y\n\n{TRAILER}\n", author=("Other", "other@example.com"))
    attributed = pull_request.run_step()

    assert clean.returncode == 0, clean.stderr
    assert attributed.returncode == 1
    assert attributed.stderr == (
        f"Authorship: commit {sha[:12]}: the message carries AI attribution\n"
    )


def test_takes_author_email_from_variable_when_set(tmp_path: Path) -> None:
    # The platform's own CI has no hub.json: it names the author in the step's env.
    pull_request = PullRequest(tmp_path, None)
    sha = pull_request.commit("feat(api): add the login endpoint")

    named = pull_request.run_step(env={"AUTHOR_EMAIL": "jane@example.com"})
    other = pull_request.run_step(env={"AUTHOR_EMAIL": "owner@example.com"})

    assert named.returncode == 0, named.stderr
    assert other.returncode == 1
    assert other.stderr.splitlines() == [
        f"Authorship: commit {sha[:12]}: the author email jane@example.com is not"
        " owner@example.com",
        f"Authorship: commit {sha[:12]}: the committer email jane@example.com is not"
        " owner@example.com",
    ]


def test_runs_nothing_from_event_text_when_title_hostile(
    pull_request: PullRequest, tmp_path: Path
) -> None:
    pull_request.commit("feat(api): add the login endpoint")
    marker = tmp_path / "injected"
    hostile = f"$(touch {marker})`touch {marker}`'; touch {marker}; '\"; touch {marker}; \""

    completed = pull_request.run_step(title=hostile, body=hostile)

    assert completed.returncode == 0, completed.stderr
    assert not marker.exists()


@pytest.mark.parametrize(
    "event",
    [
        {"action": "opened"},
        {"pull_request": {"title": "x", "body": "", "base": {"sha": "main"}, "head": {}}},
        ["not", "an", "object"],
    ],
    ids=["no-pull-request", "bad-shas", "list"],
)
def test_exits_one_when_event_unreadable(event: object, pull_request: PullRequest) -> None:
    completed = pull_request.run_step(event=event)

    assert completed.returncode == 1
    assert (completed.stdout, completed.stderr) == ("", UNREADABLE_EVENT)


def test_names_no_expression_when_step_rendered() -> None:
    ci = demo_ci()
    start = ci.index(STEP)
    step = ci[start : ci.index("\n      - ", start) + 1]

    # The event's text reaches the step only as a file: no ${{ }} in the step at all.
    assert "${{" not in step
    assert "github.event.pull_request" not in ci
    assert re.search(r"^        if: github\.event_name == 'pull_request'$", step, re.MULTILINE)
