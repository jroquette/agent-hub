"""The workflow engine's ``CheckoutProbe``: ``git status`` of the hub and its repos (ADR 0032).

A node that declares ``mutates_checkout: false`` is checked around each attempt: the engine reads
``status`` before and after, and a change fails the node ``config``. ``status`` runs ``git status
--porcelain=v1 -z --untracked-files=all`` in each checkout with no optional lock, so it never
contends with the user's own git or with a node running beside it, and without the tracker key
or a GitHub token. A checkout git cannot read fails the node ``config``.

Limit: git status names the paths that differ from ``HEAD``, not their content, so a node that
edits a file already changed before it ran leaves the status as it was.
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.cli.child_process import ChildResult, git_env, run_child
from agent_hub.cli.errors import ChildTimedOutError
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.workflows.failures import NodeFailedError

STATUS_ARGV: Final = ("git", "status", "--porcelain=v1", "-z", "--untracked-files=all")
STATUS_TIMEOUT: Final = 60.0
# The end of git's stderr kept in a failure's detail (the run's record, never events).
MAX_DETAIL: Final = 300

type ChildRunner = Callable[..., ChildResult]


@dataclass(frozen=True, kw_only=True)
class GitCheckoutProbe:
    """``roots`` are the checkouts a run's nodes may change: the hub and its repos."""

    roots: tuple[Path, ...]
    environ: Mapping[str, str]
    child: ChildRunner = field(default=run_child)

    def status(self) -> str:
        env = git_env(without(self.environ, SESSION_HIDDEN), optional_locks=False)
        parts: list[str] = []
        for root in self.roots:
            try:
                result = self.child(STATUS_ARGV, cwd=root, env=env, timeout=STATUS_TIMEOUT)
            except (OSError, ChildTimedOutError) as error:
                detail = f"git status cannot run in {root.name}: {type(error).__name__}"
                raise NodeFailedError("config", detail) from None
            if result.returncode != 0:
                said = " ".join(result.stderr.decode(errors="replace").split())[-MAX_DETAIL:]
                raise NodeFailedError("config", f"git status failed in {root.name}: {said}")
            parts.append(f"{root}\0{result.stdout.decode(errors='replace')}")
        return "\0\0".join(parts)
