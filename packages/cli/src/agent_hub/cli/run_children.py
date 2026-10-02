"""The children ``hub run`` starts: their argv, folders and environments, and the dry run's lines.

Every child gets the caller's environment minus ``LINEAR_API_KEY`` (D10) and git's location
variables, so the worktree's own repo is the one git reads. What runs code the implementing
session may have written (the session itself, the gate, git's reads of its worktree, the
worktree add and the repo's setup script) also loses ``GH_TOKEN`` and ``GITHUB_TOKEN``. Only the
fetch, the push and ``gh`` keep them (``push_env``), git's hooks and fsmonitor off for each (as
config, and as ``-c`` on the fetch and the push), so a hook planted in the repo cannot run with
them. The session also gets ``OTEL_RESOURCE_ATTRIBUTES``.
A dry run prints each child as ``would run: <argv>   (cwd <folder>)``, each argument shell-quoted,
or JSON-escaped when it holds a line break or another unprintable character, so tracker text
cannot write to the terminal.
"""

import json
import os
import re
import shlex
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import git_env
from agent_hub.cli.init_report import shown_path
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.runner.session_prompt import (
    IMPLEMENTING_TOOLS,
    TRACKER_MCP_SERVERS,
    gate_tools,
    implementing_argv,
    implementing_prompt,
)
from agent_hub.core.tracker.tracker_client import Issue
from agent_hub.tracker_linear.mcp_protocol import LINEAR_TOOL_PREFIX, LINEAR_TOOLS

WORKTREES: Final = Path(".claude", "worktrees")
KEY_VARIABLE: Final = "LINEAR_API_KEY"
# Hidden from every child; the implementing session also loses the GitHub tokens.
CHILD_HIDDEN: Final = (KEY_VARIABLE,)
SESSION_HIDDEN: Final = (KEY_VARIABLE, "GH_TOKEN", "GITHUB_TOKEN")
OTEL_VARIABLE: Final = "OTEL_RESOURCE_ATTRIBUTES"
# Set for the push and gh, above any repo config: no fsmonitor, signing or hook runs there.
PUSH_OVERRIDES: Final = (
    ("core.fsmonitor", "false"),
    ("push.gpgSign", "false"),
    ("core.hooksPath", os.devnull),
)
_CONFIG_COUNT: Final = "GIT_CONFIG_COUNT"
_CONFIG_ENTRY: Final = re.compile(r"GIT_CONFIG_(?:KEY|VALUE)_[0-9]+")
# Denied to the implementing session: both Linear servers as a whole, and, should a client
# read only tool names, each tool of the snapshot under both server prefixes.
SESSION_DENIED_TOOLS: Final = (
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
    """Where and how one run's children run: the hub, the repo's worktree and its branch."""

    config: HubConfig
    hub: Path
    repo: str
    issue_id: str

    @property
    def workspace(self) -> Path:
        return self.hub.parent

    @property
    def slug(self) -> str:
        """The worktree name: the issue id lowercased (``dem-1``)."""
        return self.issue_id.lower()

    @property
    def branch(self) -> str:
        return f"{self.config.project.branch_prefix}{self.slug}"

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
            prefix=f"{self.config.tracker.team}-",
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
            denied_tools=SESSION_DENIED_TOOLS,
        )

    @property
    def repo_path(self) -> Path:
        return self.workspace / self.repo

    def gate_argv(self) -> list[str]:
        return ["bash", "-c", self.gate]

    def push_argv(self) -> list[str]:
        """The push with ``PUSH_OVERRIDES`` as its own ``-c`` options (hooks, fsmonitor and
        signing off): a caller's ``GIT_CONFIG_PARAMETERS`` outranks ``push_env``'s
        ``GIT_CONFIG_COUNT``, and these come after it."""
        overrides = [part for key, value in PUSH_OVERRIDES for part in ("-c", f"{key}={value}")]
        return ["git", *overrides, "push", "--no-verify", "-u", "origin", self.branch]

    def pr_argv(self, *, title: str, body: str) -> list[str]:
        return [
            *("gh", "pr", "create", "--repo", self.github, "--base", self.default_branch),
            *("--head", self.branch, "--title", title, "--body", body),
        ]

    def pr_view_argv(self) -> list[str]:
        """The lookup of the branch's PR, by its repo from ``hub.json``, not the worktree's."""
        return ["gh", "pr", "view", self.branch, "--repo", self.github, "--json", "url,state"]


def without(environ: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """A copy of ``environ`` without ``names``."""
    hidden = set(names)
    return {name: value for name, value in environ.items() if name not in hidden}


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


def untrusted_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of what may run the session's code (the gate, git's reads of the
    worktree): no tracker key and no GitHub token."""
    return git_env(without(environ, SESSION_HIDDEN), optional_locks=True)


def session_env(
    environ: Mapping[str, str], *, repo: str, issue_id: str, run_id: str
) -> dict[str, str]:
    """The implementing session's environment: ``untrusted_env`` and its telemetry tags."""
    env = untrusted_env(environ)
    env[OTEL_VARIABLE] = f"repo={repo},issue={issue_id},agent_run={run_id}"
    return env


def shown_command(argv: Sequence[str]) -> str:
    """``argv`` as one printable line: each argument shell-quoted, or JSON when unprintable."""
    return " ".join(
        shlex.quote(argument) if argument.isprintable() else json.dumps(argument)
        for argument in argv
    )


def would_run_line(argv: Sequence[str], *, cwd: Path) -> str:
    return f"would run: {shown_command(argv)}   (cwd {shown_path(str(cwd))})"
