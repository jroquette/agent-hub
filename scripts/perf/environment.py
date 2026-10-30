"""``make perf``'s environment: the temp root, the child environment, the tool bin and the temp hub.

Every child the suite starts runs with ``child_env``: built from scratch, never from
``os.environ``, so no proxy, tracker token or Claude Code variable reaches it, ``HOME`` and the
XDG folders sit under the temp root, and ``PATH`` is the root's ``bin/`` only. That bin
(``make_tool_bin``) holds links to ``git``, ``python3`` and ``sh`` (``npm exec`` runs its command
through ``sh``) and a ``uvx`` stand-in that runs the worktree's ``hub``, so ``./hub`` and
``session_start`` do real work offline. ``create_hub`` makes a ``hub init`` hub under the root
with the fixture's feature folder, a brain of six folders of a hundred synthetic notes
(``brain/tree-<n>/``), a synthetic transcript, a release commit in its ``hub.lock`` (ADR 0054, so
``./hub`` takes the one-call commit path that a synced hub takes; the stand-in ignores
``--from``), and one commit by a made-up author.
"""

import json
import shlex
import shutil
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from types import TracebackType
from typing import Protocol, Self

from agent_hub.core.hub_config.platform_repository import DEFAULT_PLATFORM_REPOSITORY
from scripts.perf.fixture import (
    BRAIN_FOLDERS,
    BRANCH_PREFIX,
    CWD,
    FEATURE_ISSUE,
    FEATURE_SLUG,
    NOTES_PER_FOLDER,
    PAGE_SESSION,
    PROJECT,
    REPO,
)

LOOPBACK = "127.0.0.1"
HUB_DIR = "hub"
ISSUE = f"AGH-{FEATURE_ISSUE}"
AUTHOR_NAME = "Perf Author"
AUTHOR_EMAIL = "perf@example.com"
# The hub-init flags, so git is never asked; all values are made up.
HUB_FLAGS = (
    "--repos",
    f"acme/{REPO}",
    "--tracker",
    "linear:AGH",
    "--branch-prefix",
    BRANCH_PREFIX,
    "--hub-repo",
    "acme/perf-hub",
    "--author-name",
    AUTHOR_NAME,
    "--author-email",
    AUTHOR_EMAIL,
)
# The made-up release commit the temp hub's lock records: 40 lowercase hex, never fetched.
RELEASE_COMMIT = "0123456789abcdef0123456789abcdef01234567"
# Git reads no config of the developer's: no global file, no system file.
GIT_ISOLATION = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1"}


class Runner(Protocol):
    """Runs ``argv`` in ``cwd`` with exactly ``env``; the real one wraps ``subprocess.run``."""

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> object: ...


class PerfRoot:
    """A temp folder from ``tempfile.mkdtemp`` (under ``TMPDIR``), removed on exit."""

    def __init__(self) -> None:
        self.path = Path(tempfile.mkdtemp(prefix="agent-hub-perf-"))

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        shutil.rmtree(self.path, ignore_errors=True)


def claude_projects(root: Path) -> Path:
    """The transcripts root ``hub web`` reads (``AGENT_HUB_CLAUDE_PROJECTS``)."""
    return root / "claude" / "projects"


def child_env(root: Path, *, db: Path, tool_bin: Path, sensor_url: str) -> dict[str, str]:
    """The environment of every child: only these variables, each under ``root`` or given.

    The home, XDG, temp and transcripts folders are made, so a child can write to them."""
    home = root / "home"
    folders = {
        "HOME": home,
        "XDG_DATA_HOME": home / ".local" / "share",
        "XDG_CONFIG_HOME": home / ".config",
        "XDG_CACHE_HOME": home / ".cache",
        "TMPDIR": root / "tmp",
        "UV_CACHE_DIR": root / "uv-cache",
        "AGENT_HUB_CLAUDE_PROJECTS": claude_projects(root),
    }
    for folder in folders.values():
        folder.mkdir(parents=True, exist_ok=True)
    return {
        **{name: str(folder) for name, folder in folders.items()},
        "PATH": str(tool_bin),
        "LANG": "C.UTF-8",
        "AGENT_HUB_DB": str(db),
        "AGENT_HUB_WEB_URL": sensor_url,
    }


def _uvx_text(hub_bin: Path) -> str:
    return (
        "#!/bin/sh\n"
        "# make perf's uvx stand-in: runs the worktree's hub, never a release.\n"
        'if [ "$1" = "--from" ]; then shift 2; fi\n'
        'if [ "$1" != "hub" ]; then echo "uvx stand-in: expected hub, got $1" >&2; exit 2; fi\n'
        "shift\n"
        f'exec {shlex.quote(str(hub_bin))} "$@"\n'
    )


def make_tool_bin(root: Path, *, hub_bin: Path, git: Path, python3: Path, sh: Path) -> Path:
    """``root/bin`` with links to ``git``, ``python3`` and ``sh`` and the ``uvx`` stand-in."""
    bin_dir = root / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    for name, target in (("git", git), ("python3", python3), ("sh", sh)):
        (bin_dir / name).symlink_to(target)
    uvx = bin_dir / "uvx"
    uvx.write_text(_uvx_text(hub_bin), "utf-8")
    uvx.chmod(0o755)
    return bin_dir


def web_argv(hub_bin: Path, *, port: int, db: Path) -> list[str]:
    """``hub web`` on loopback only, over ``db``, without opening a browser."""
    return [
        str(hub_bin),
        "web",
        "--host",
        LOOPBACK,
        "--port",
        str(port),
        "--db",
        str(db),
        "--no-open",
    ]


def _feature_files(hub: Path) -> None:
    folder = hub / "brain" / "features" / FEATURE_SLUG
    folder.mkdir(parents=True, exist_ok=True)
    spec = (
        f"---\ntype: spec\nprocess_size: bounded\nrepos: [{REPO}]\nlinear: [{ISSUE}]\n---\n"
        "# Search index\n\nIndex the sessions so a query answers fast.\n"
    )
    (folder / "spec.md").write_text(spec, "utf-8")
    record = {"feature": FEATURE_SLUG, "linear": [ISSUE], "tickets": [ISSUE], "acs": []}
    (folder / "features.json").write_text(json.dumps(record, indent=2) + "\n", "utf-8")


def _brain_tree(hub: Path) -> None:
    """``BRAIN_FOLDERS`` folders of ``NOTES_PER_FOLDER`` notes, each a heading and one line."""
    for folder in range(1, BRAIN_FOLDERS + 1):
        directory = hub / "brain" / f"tree-{folder}"
        directory.mkdir(parents=True, exist_ok=True)
        for note in range(1, NOTES_PER_FOLDER + 1):
            text = f"# Note {folder}.{note:03d}\n\nA synthetic perf note in folder {folder}.\n"
            (directory / f"note-{note:03d}.md").write_text(text, "utf-8")


def transcript_path(env: Mapping[str, str]) -> Path:
    """The page session's synthetic transcript, in Claude Code's folder for the fixture's cwd."""
    return Path(env["AGENT_HUB_CLAUDE_PROJECTS"]) / CWD.replace("/", "-") / f"{PAGE_SESSION}.jsonl"


def _transcript(env: Mapping[str, str]) -> None:
    path = transcript_path(env)
    path.parent.mkdir(parents=True, exist_ok=True)
    common = {
        "sessionId": PAGE_SESSION,
        "cwd": CWD,
        "gitBranch": f"{BRANCH_PREFIX}agh-{FEATURE_ISSUE}-search",
    }
    lines = (
        {
            **common,
            "type": "user",
            "timestamp": "2026-07-01T09:00:00Z",
            "message": {"role": "user", "content": f"{ISSUE}: index the sessions"},
        },
        {
            **common,
            "type": "assistant",
            "timestamp": "2026-07-01T09:00:05Z",
            "message": {
                "role": "assistant",
                "content": [{"type": "text", "text": "Running make check-fast."}],
            },
        },
    )
    path.write_text("".join(json.dumps(line) + "\n" for line in lines), "utf-8")


def _release_commit(hub: Path) -> None:
    """Record ``RELEASE_COMMIT`` and the repository in use in ``hub.lock``, as a sync at a pin
    change would, so the shim and the hooks take the commit path; the rest of the lock is kept."""
    platform = json.loads((hub / "hub.json").read_text("utf-8")).get("platform", {})
    lock_path = hub / "hub.lock"
    lock = json.loads(lock_path.read_text("utf-8"))
    lock["platform_commit"] = RELEASE_COMMIT
    lock["platform_repository"] = platform.get("repository", DEFAULT_PLATFORM_REPOSITORY)
    lock_path.write_text(json.dumps(lock, indent=2, sort_keys=True) + "\n", "utf-8")


def create_hub(root: Path, *, runner: Runner, env: Mapping[str, str]) -> Path:
    """Make the temp hub under ``root`` and return its folder.

    ``hub init`` runs through the ``uvx`` stand-in on ``env``'s ``PATH``; then the lock gets its
    release commit, the feature folder, the brain notes and the transcript are written, and
    ``git init``, ``git add -A`` and one commit follow."""
    hub = root / HUB_DIR
    runner(["uvx", "hub", "init", PROJECT, *HUB_FLAGS, "--dir", str(hub)], cwd=root, env=env)
    _release_commit(hub)
    _feature_files(hub)
    _brain_tree(hub)
    _transcript(env)
    git_env = {**env, **GIT_ISOLATION}
    identity = ["-c", f"user.name={AUTHOR_NAME}", "-c", f"user.email={AUTHOR_EMAIL}"]
    for argv in (
        ["git", "init", "--quiet"],
        ["git", "add", "-A"],
        ["git", *identity, "commit", "--quiet", "-m", "perf hub"],
    ):
        runner(argv, cwd=hub, env=git_env)
    return hub
