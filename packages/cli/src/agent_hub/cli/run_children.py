"""The children ``hub run`` starts: their argv, folders and environments, and the dry run's lines.

Every child gets the caller's environment minus ``LINEAR_API_KEY`` (D10) and git's location
variables, so the worktree's own repo is the one git reads. What runs code the implementing
session may have written (the session itself, the gate, and git's reads of its worktree) also
loses ``GH_TOKEN`` and ``GITHUB_TOKEN``; only the push and ``gh`` keep them, and the push runs
with every git hook off, so a hook the session planted cannot run with them. The session also
gets ``OTEL_RESOURCE_ATTRIBUTES``.
A dry run prints each child as ``would run: <argv>   (cwd <folder>)``, each argument shell-quoted,
or JSON-escaped when it holds a line break or another unprintable character, so tracker text
cannot write to the terminal.
"""

import json
import os
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
        return f"origin/{self.config.project.default_branch}"

    @property
    def worktree(self) -> Path:
        return self.workspace / self.repo / WORKTREES / self.slug

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
        """The push, every hook off: the session could have planted one in the repo."""
        hooks_off = ("-c", f"core.hooksPath={os.devnull}")
        return ["git", *hooks_off, "push", "--no-verify", "-u", "origin", self.branch]

    def pr_argv(self, *, title: str, body: str) -> list[str]:
        base = self.config.project.default_branch
        return [
            *("gh", "pr", "create", "--base", base, "--head", self.branch),
            *("--title", title, "--body", body),
        ]


def without(environ: Mapping[str, str], names: Iterable[str]) -> dict[str, str]:
    """A copy of ``environ`` without ``names``."""
    hidden = set(names)
    return {name: value for name, value in environ.items() if name not in hidden}


def child_env(environ: Mapping[str, str]) -> dict[str, str]:
    """The environment of the worktree steps, the push and ``gh``: no tracker key."""
    return git_env(without(environ, CHILD_HIDDEN), optional_locks=True)


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
