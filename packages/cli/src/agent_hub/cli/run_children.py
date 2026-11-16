"""The children ``hub run`` starts: their argv, folders and environments, and the dry run's lines.

Every child gets the caller's environment minus ``LINEAR_API_KEY`` (D10) and git's location
variables, so the worktree's own repo is the one git reads. What runs code the implementing
session may have written (the session itself, the gate, git's reads of its worktree, the
worktree add and the repo's setup script) also loses ``GH_TOKEN`` and ``GITHUB_TOKEN``. Only the
fetch, the push and ``gh`` keep them (``push_env``), git's hooks and fsmonitor off for each (as
config, and as ``-c`` on the fetch and the push), so a hook planted in the repo cannot run with
them. The session also gets ``OTEL_RESOURCE_ATTRIBUTES`` and the run variables the hook sensor
reads (``AGENT_HUB_RUN_ID``, ``AGENT_HUB_STEP``, ``AGENT_HUB_ATTEMPT``), and the setup script the
task's six ``HUB_*`` variables (``worktree_steps.script_env``).
A dry run prints each child as ``would run: <argv>   (cwd <folder>)``, each argument shell-quoted,
or JSON-escaped when it holds a line break or another unprintable character, so tracker text
cannot write to the terminal; what a child would read on stdin (a PR's body) follows its argv as
``<<< <text>``, quoted the same way. ``gh`` reaches GitHub through its REST API only (``gh api``):
a cloud session's proxy refuses ``gh pr``, which is GraphQL.
The hidden names and ``without`` are defined in ``hidden_env`` and re-exported here.
"""

import functools
import json
import os
import re
import shlex
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import git_env
from agent_hub.cli.hidden_env import CHILD_HIDDEN as CHILD_HIDDEN
from agent_hub.cli.hidden_env import KEY_VARIABLE as KEY_VARIABLE
from agent_hub.cli.hidden_env import SESSION_HIDDEN as SESSION_HIDDEN
from agent_hub.cli.hidden_env import without as without
from agent_hub.cli.init_report import shown_path
from agent_hub.cli.session_settings import session_settings_path
from agent_hub.core.hub_config.conventions import EffectiveConventions
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.team_keys import team_of
from agent_hub.core.runner.session_prompt import (
    IMPLEMENTING_TOOLS,
    TRACKER_MCP_SERVERS,
    gate_tools,
    implementing_argv,
    implementing_prompt,
)
from agent_hub.core.scenarios.credentials import (
    NO_CREDENTIALS,
    CredentialNames,
    hidden_environment,
)
from agent_hub.core.tracker.tracker_client import Issue
from agent_hub.core.workspace.worktree_name import worktree_branch

WORKTREES: Final = Path(".claude", "worktrees")
OTEL_VARIABLE: Final = "OTEL_RESOURCE_ATTRIBUTES"
# Read by the hook sensor: the run, step and attempt its session belongs to (D6).
RUN_ID_VARIABLE: Final = "AGENT_HUB_RUN_ID"
STEP_VARIABLE: Final = "AGENT_HUB_STEP"
ATTEMPT_VARIABLE: Final = "AGENT_HUB_ATTEMPT"
# The environment a process workflow runs in, for the guard's endpoint check (best effort).
RUN_ENVIRONMENT_VARIABLE: Final = "HUB_RUN_ENVIRONMENT"
IMPLEMENT_STEP: Final = "implement"
# Set for the push and gh, above any repo config: no fsmonitor, signing or hook runs there.
PUSH_OVERRIDES: Final = (
    ("core.fsmonitor", "false"),
    ("push.gpgSign", "false"),
    ("core.hooksPath", os.devnull),
)
_CONFIG_COUNT: Final = "GIT_CONFIG_COUNT"
_CONFIG_ENTRY: Final = re.compile(r"GIT_CONFIG_(?:KEY|VALUE)_[0-9]+")
# What the open-PR lookup keeps of each PR GitHub lists.
OPEN_PULLS_JQ: Final = "[.[] | {html_url, state}]"
_PULL_URL: Final = re.compile(
    r"https://github\.com/(?P<owner>[A-Za-z0-9._-]+)/(?P<name>[A-Za-z0-9._-]+)"
    r"/pull/(?P<number>[1-9][0-9]*)"
)


@functools.cache
def session_denied_tools() -> tuple[str, ...]:
    """Denied to the implementing session: both Linear servers as a whole, and, should a client
    read only tool names, each tool of the snapshot under both server prefixes."""
    from agent_hub.tracker_linear.mcp_protocol import (  # noqa: PLC0415 - only a session loads the tracker
        LINEAR_TOOL_PREFIX,
        LINEAR_TOOLS,
    )

    return (
        *TRACKER_MCP_SERVERS,
        *(
            f"{server}__{tool.removeprefix(LINEAR_TOOL_PREFIX)}"
            for server in TRACKER_MCP_SERVERS
            for tool in LINEAR_TOOLS
        ),
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class RunOptions:
    """The run's options, checked: ``start`` is ``implement`` or ``verify``."""

    live: bool
    max_turns: int
    budget: float
    model: str
    start: str
    effort: str


@dataclass(frozen=True, kw_only=True, slots=True)
class RunChildren:
    """Where and how one run's children run: the hub, the repo's worktree and its branch.

    ``branch_prefix`` is the developer's, resolved by the command (``effective_config``).
    """

    config: HubConfig
    hub: Path
    repo: str
    issue_id: str
    branch_prefix: str

    @property
    def workspace(self) -> Path:
        return self.hub.parent

    @property
    def slug(self) -> str:
        """The worktree name: the issue id lowercased (``dem-1``)."""
        return self.issue_id.lower()

    @property
    def conventions(self) -> EffectiveConventions:
        """The repo's effective conventions: the one source of its branch and titles."""
        return self.config.conventions_for(self.repo)

    @property
    def branch(self) -> str:
        """The task branch, as ``hub worktree`` builds it: the slug rendered with the repo's
        effective ``conventions.branch``."""
        pattern = self.conventions.branch
        return worktree_branch(self.slug, prefix=self.branch_prefix, pattern=pattern)

    @property
    def base(self) -> str:
        """The repo's base, ``origin/<its default branch>``."""
        return f"origin/{self.default_branch}"

    @property
    def default_branch(self) -> str:
        """The repo's default branch from ``hub.json``: its own, else the project's."""
        return self.config.default_branch_for(self.repo)

    @property
    def worktree(self) -> Path:
        return self.workspace / self.repo / WORKTREES / self.slug

    @property
    def github(self) -> str:
        """The repo's GitHub ``owner/name`` from ``hub.json``, which the session cannot edit."""
        return next(entry.github for entry in self.config.repos if entry.dir == self.repo)

    @property
    def gate(self) -> str:
        """The repo's full gate, ``check`` (never empty: the model refuses one, E1)."""
        return next(entry.check for entry in self.config.repos if entry.dir == self.repo)

    @property
    def team(self) -> str:
        """The issue's team in the configured spelling (``hub run`` accepted the id against it).

        Raises ValueError when the id matches no configured team.
        """
        team = team_of(self.issue_id, self.config.tracker.team_keys)
        if team is None:
            raise ValueError(f"{self.issue_id} matches no team of hub.json")
        return team

    def worktree_line(self) -> str:
        """The dry run's line for the worktree step, which runs in process when live (D7)."""
        return f"would run: ./hub worktree {self.slug} --only {self.repo}"

    def session_argv(self, issue: Issue, options: RunOptions) -> list[str]:
        """The implementing session's ``claude -p`` argv (spec D-desc, D-run)."""
        repo = next(entry for entry in self.config.repos if entry.dir == self.repo)
        prompt = implementing_prompt(
            issue,
            repo=self.repo,
            branch=self.branch,
            hub=str(self.hub),
            hub_name=self.hub.name,
            sensitive=self.config.guard.ask_before_edit,
            fast_gate=repo.check_fast,
            full_gate=repo.check,
            prefix=f"{self.team}-",
            commit_title=self.conventions.commit_title,
        )
        others = (str(self.workspace / entry.dir) for entry in self.config.repos)
        return implementing_argv(
            prompt=prompt,
            max_turns=options.max_turns,
            budget=options.budget,
            model=options.model,
            effort=options.effort,
            add_dirs=(str(self.hub), *(path for path in others if path != str(self.repo_path))),
            tools=(*IMPLEMENTING_TOOLS, *gate_tools((repo.check_fast, repo.check))),
            denied_tools=session_denied_tools(),
            settings_file=str(session_settings_path(self.hub, options.effort)),
        )

    @property
    def repo_path(self) -> Path:
        return self.workspace / self.repo

    def gate_argv(self) -> list[str]:
        return gate_command(self.gate)

    def push_argv(self) -> list[str]:
        return push_command(self.branch)

    def pr_argv(self, *, title: str) -> list[str]:
        """The PR's creation; its body goes on stdin (``pr_create_command``)."""
        return pr_create_command(
            github=self.github,
            base=self.default_branch,
            branch=self.branch,
            title=title,
            draft=False,
        )


def gate_command(gate: str) -> list[str]:
    """The gate (a repo's ``check``), run by bash."""
    return ["bash", "-c", gate]


def push_command(branch: str) -> list[str]:
    """The push of ``branch`` with ``PUSH_OVERRIDES`` as its own ``-c`` options (hooks,
    fsmonitor and signing off): a caller's ``GIT_CONFIG_PARAMETERS`` outranks ``push_env``'s
    ``GIT_CONFIG_COUNT``, and these come after it."""
    overrides = [part for key, value in PUSH_OVERRIDES for part in ("-c", f"{key}={value}")]
    return ["git", *overrides, "push", "--no-verify", "-u", "origin", branch]


def pr_create_command(*, github: str, base: str, branch: str, title: str, draft: bool) -> list[str]:
    """The creation of ``branch``'s PR into ``base`` on ``github`` through GitHub's REST API
    (``gh api --method POST repos/<github>/pulls``; ``gh pr`` is GraphQL, which a cloud
    session's proxy refuses). The title, head and base are plain fields (``-f``: never typed or
    read from a file); the body is read from stdin (``-F body=@-``), so it never sits on the
    command line and its length is not argv's; ``-F draft=true`` comes last when asked."""
    argv = [
        *("gh", "api", "--method", "POST", f"repos/{github}/pulls"),
        *("-f", f"title={title}", "-f", f"head={branch}", "-f", f"base={base}"),
        *("-F", "body=@-"),
    ]
    return [*argv, "-F", "draft=true"] if draft else argv


def pr_view_command(*, github: str, branch: str) -> list[str]:
    """The lookup of ``branch``'s open PR through the REST API (``GET repos/<github>/pulls``,
    ``head=<owner>:<branch>``, ``state=open``), by its repo from ``hub.json``, not the
    worktree's. ``gh`` keeps only each PR's ``html_url`` and ``state`` (``--jq``, applied
    locally): the answer would carry every body otherwise."""
    owner = github.split("/", 1)[0]
    return [
        *("gh", "api", "--method", "GET", f"repos/{github}/pulls"),
        *("-f", f"head={owner}:{branch}", "-f", "state=open", "--jq", OPEN_PULLS_JQ),
    ]


def pull_request_path(url: str) -> str | None:
    """``repos/<owner>/<name>/pulls/<n>``, the REST path of the PR page ``url``
    (``https://github.com/<owner>/<name>/pull/<n>``), else None."""
    found = _PULL_URL.fullmatch(url)
    if found is None or {found["owner"], found["name"]} & {".", ".."}:
        return None
    return f"repos/{found['owner']}/{found['name']}/pulls/{found['number']}"


def pr_body_command(path: str) -> list[str]:
    """The read of the PR at the REST ``path`` (``pull_request_path``), its body among its
    fields."""
    return ["gh", "api", "--method", "GET", path]


def pr_edit_command(path: str, body_file: Path) -> list[str]:
    """The edit of the PR at the REST ``path``: its body replaced by the text of ``body_file``
    (``-F body=@<file>``: a body can be longer than one argv string may be)."""
    return ["gh", "api", "--method", "PATCH", path, "-F", f"body=@{body_file}"]


def pr_body_reset_command(path: str) -> list[str]:
    """The edit that sets the body of the PR at the REST ``path`` again, read from stdin
    (``-F body=@-``) as the create read it. A cloud session's create appends an attribution
    footer to the body; an edit with the same text removes it where the environment lets it
    (through ``gh`` a cloud session can add one again)."""
    return ["gh", "api", "--method", "PATCH", path, "-F", "body=@-"]


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of the worktree steps, the push and ``gh``: no tracker key."""
    return git_env(without(environ, CHILD_HIDDEN), optional_locks=True)


def push_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of the push and ``gh``: ``child_env`` (the GitHub tokens kept) and
    ``PUSH_OVERRIDES`` as command-scope config after the caller's own ``GIT_CONFIG_*`` entries
    (dropped when their count is not a number). A caller's ``GIT_CONFIG_PARAMETERS`` (``-c``)
    still outranks these, so the push also passes them as ``-c``; ``gh`` takes no ``-c``."""
    env = child_env(environ)
    given = env.get(_CONFIG_COUNT, "0")
    # git reads ASCII digits only ("²" or "١" would pass str.isdigit or int()).
    is_count = given.isascii() and given.isdecimal()
    start = int(given) if is_count else 0
    if not is_count:
        # git refuses a bad count; its entries go with it (GIT_CONFIG_GLOBAL and the like stay).
        env = {name: value for name, value in env.items() if not _CONFIG_ENTRY.match(name)}
    for index, (key, value) in enumerate(PUSH_OVERRIDES, start=start):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    env[_CONFIG_COUNT] = str(start + len(PUSH_OVERRIDES))
    return env


def untrusted_env(
    environ: Mapping[str, str], *, hidden: CredentialNames = NO_CREDENTIALS
) -> dict[str, str]:
    """The environment of what may run the session's code (the gate, git's reads of the
    worktree): no tracker key and no GitHub token; nor, with ``hidden``, the hub's declared
    credential names and an ``AWS_PROFILE`` naming a declared profile (only an action's
    process gets those, docs/design/scenarios.md § Credentials)."""
    visible = hidden_environment(environ, hidden)
    return git_env(without(visible, SESSION_HIDDEN), optional_locks=True)


def session_env(
    environ: Mapping[str, str],
    *,
    repo: str,
    issue_id: str,
    run_id: str,
    attempt: int = 1,
    step: str = IMPLEMENT_STEP,
    hidden: CredentialNames = NO_CREDENTIALS,
    environment: str | None = None,
) -> dict[str, str]:
    """The implementing session's environment: ``untrusted_env``, its telemetry tags and the
    run variables the hook sensor attributes the session's events with (D6). A workflow's
    agent node passes its ``step`` (the node id as recorded) and run-wide ``attempt``, the
    hub's credential names as ``hidden``, and the run's ``environment`` when it declares one
    (``HUB_RUN_ENVIRONMENT``, read by the guard's ``environment_endpoint`` rule)."""
    env = untrusted_env(environ, hidden=hidden)
    env[OTEL_VARIABLE] = f"repo={repo},issue={issue_id},agent_run={run_id}"
    env[RUN_ID_VARIABLE] = run_id
    env[STEP_VARIABLE] = step
    env[ATTEMPT_VARIABLE] = str(attempt)
    if environment is not None:
        env[RUN_ENVIRONMENT_VARIABLE] = environment
    return env


def shown_command(argv: Sequence[str]) -> str:
    """``argv`` as one printable line: each argument shell-quoted, or JSON when unprintable."""
    return " ".join(
        shlex.quote(argument) if argument.isprintable() else json.dumps(argument)
        for argument in argv
    )


def would_run_line(argv: Sequence[str], *, cwd: Path, stdin: str | None = None) -> str:
    """The dry run's line for ``argv`` in ``cwd``; ``stdin``, the text the child would read
    there, follows as a here-string (``<<< <text>``), quoted as an argument is."""
    given = "" if stdin is None else f" <<< {shown_command([stdin])}"
    return f"would run: {shown_command(argv)}{given}   (cwd {shown_path(str(cwd))})"
