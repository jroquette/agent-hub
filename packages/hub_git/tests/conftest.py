"""A real hub ``origin`` for the hub git adapter's tests: a bare repository in ``tmp_path``, the
user's hub checkout cloned from it, and a fake ``gh`` on ``PATH``.

The hub's ``origin`` is ``https://github.com/acme/demo-hub.git``, as a real hub's is; a global
git config in the test's own ``HOME`` rewrites that url to the bare repository
(``url.<bare>.insteadOf``), so git never reaches the network. The fake ``gh`` is a stdlib
script: ``gh auth token`` succeeds unless the ``logged-out`` switch is on, and ``gh pr create``
records the pull request (failing unless the head branch is on ``origin``) and prints its url,
or fails (``fail`` switch) or prints something else (``garbage`` switch); ``gh pr list --head
<branch> --state open --json url`` prints the recorded pull requests of that head as JSON (every
recorded one is open), or fails (``list-fail`` switch). Everything here is
synthetic: no real repository, account or token.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path

import pytest

from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.brain_change_requests_contract import OpenedPullRequest, OriginCommit
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.hub_git.brain_change_requests import GitBrainChangeRequests
from agent_hub.hub_git.git_runner import GitRunner

HUB_REPO = "acme/demo-hub"
HUB_URL = f"https://github.com/{HUB_REPO}.git"
DEFAULT_BRANCH = "main"

_FAKE_GH = """\
import json, os, subprocess, sys

state = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]


def switch(name):
    return os.path.exists(os.path.join(state, name))


with open(os.path.join(state, "calls.jsonl"), "a") as calls:
    calls.write(json.dumps({"argv": args, "cwd": os.getcwd()}) + "\\n")
if args[:2] == ["auth", "token"]:
    if switch("logged-out"):
        sys.exit(1)
    print("gho_not-a-real-token")
    sys.exit(0)
pulls = os.path.join(state, "pulls.jsonl")
if args[:2] == ["pr", "list"]:
    if switch("list-fail"):
        sys.exit(1)
    flags = dict(zip(args[2::2], args[3::2]))
    known = [json.loads(line) for line in open(pulls)] if os.path.exists(pulls) else []
    open_pulls = [
        {"url": pull["url"]}
        for pull in known
        if pull["head"] == flags.get("--head") and flags.get("--state") == "open"
    ]
    print(json.dumps(open_pulls))
    sys.exit(0)
if args[:2] != ["pr", "create"]:
    sys.exit(2)
opts = dict(arg[2:].split("=", 1) for arg in args[2:] if arg.startswith("--") and "=" in arg)
if switch("fail"):
    sys.exit(1)
if switch("garbage"):
    print("Warning: something went sideways")
    sys.exit(0)
origin = os.environ["FAKE_GH_ORIGIN"]
head = subprocess.run(
    ["git", "--git-dir", origin, "rev-parse", "--verify", "--quiet", "refs/heads/" + opts["head"]],
    stdout=subprocess.DEVNULL,
)
if head.returncode != 0:
    sys.exit(1)
count = sum(1 for _ in open(pulls)) if os.path.exists(pulls) else 0
url = "https://github.com/" + opts["repo"] + "/pull/" + str(count + 1)
with open(opts["body-file"]) as body_file:
    body = body_file.read()
pull = {"url": url, "body": body}
pull.update({key: opts[key] for key in ("head", "base", "title")})
with open(pulls, "a") as out:
    out.write(json.dumps(pull) + "\\n")
print(url)
"""


@dataclass(frozen=True, kw_only=True)
class GitWorld:
    """The bare ``origin``, the user's hub checkout, the fake gh's state and the environment."""

    root: Path
    bare: Path
    hub: Path
    seed: Path
    gh_state: Path
    bin: Path
    environ: dict[str, str]

    def git(self, *args: str, cwd: Path | None = None, check: bool = True) -> str:
        """Run git in ``cwd`` (default: the hub) with the world's environment; its stdout."""
        done = subprocess.run(  # noqa: S603 - the test's own git, an argv list
            ["git", *args],  # noqa: S607 - git from the test PATH
            cwd=cwd or self.hub,
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )
        if check and done.returncode != 0:
            raise AssertionError(f"git {' '.join(args)} failed: {done.stderr}")
        return done.stdout

    def origin_git(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run git against the bare ``origin``."""
        return subprocess.run(  # noqa: S603 - the test's own git, an argv list
            ["git", "--git-dir", str(self.bare), *args],  # noqa: S607 - git from the test PATH
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )

    def switch(self, name: str, *, on: bool = True) -> None:
        """Turn a fake gh switch (``fail``, ``garbage``, ``logged-out``) on or off."""
        path = self.gh_state / name
        if on:
            path.touch()
        else:
            path.unlink(missing_ok=True)

    def gh_calls(self) -> list[list[str]]:
        """The argv of every fake gh call so far."""
        calls = self.gh_state / "calls.jsonl"
        if not calls.exists():
            return []
        return [json.loads(line)["argv"] for line in calls.read_text().splitlines()]

    def runner(self) -> GitRunner:
        """A runner over the world's environment."""
        return GitRunner(environ=self.environ)

    def logging_runner(self, *, before_push: str = "") -> GitRunner:
        """A runner whose git logs each argv to ``root/git-calls`` (``git_calls``) and runs
        ``before_push`` (shell) just before a push that is not a delete."""
        log = self.root / "git-calls"
        wrapper = self.root / "git-logged"
        wrapper.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\n'
            f'case " $* " in *" --delete "*) ;; *" push "*) {before_push}:;; esac\n'
            'exec git "$@"\n'
        )
        wrapper.chmod(0o755)
        return GitRunner(git=str(wrapper), environ=self.environ)

    def git_calls(self) -> list[str]:
        """The argv, joined, of every git call a ``logging_runner`` made so far."""
        log = self.root / "git-calls"
        return log.read_text().splitlines() if log.exists() else []

    def reject_pushes(self) -> None:
        """Make ``origin`` refuse every push (a ``pre-receive`` hook that fails)."""
        hook = self.bare / "hooks" / "pre-receive"
        hook.write_text("#!/bin/sh\nexit 1\n")
        hook.chmod(0o755)

    def adapter(self, runner: GitRunner | None = None) -> GitBrainChangeRequests:
        """The adapter under test over ``runner`` (default: ``runner()``), with its temporary
        folders under the world's root."""
        temp = self.root / "temp"
        temp.mkdir(exist_ok=True)
        return GitBrainChangeRequests(runner or self.runner(), temp_root=temp)

    def snapshot(self) -> tuple[str, ...]:
        """What the user's checkout looks like to git: HEAD, status, refs, worktrees, index."""
        return (
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain", "--ignored"),
            self.git("for-each-ref"),
            self.git("worktree", "list", "--porcelain"),
            self.git("stash", "list"),
            self.git("ls-files", "--stage"),
            self.git("config", "--list", "--local"),
        )


def _fake_gh(bin_dir: Path) -> None:
    source = bin_dir / "fake_gh.py"
    source.write_text(_FAKE_GH)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{source}" "$@"\n')
    gh.chmod(0o755)


def _gitconfig(home: Path, bare: Path) -> Path:
    config = home / ".gitconfig"
    config.write_text(
        "[user]\n\tname = Seed Owner\n\temail = seed@example.com\n"
        "[init]\n\tdefaultBranch = main\n"
        f'[url "{bare}"]\n\tinsteadOf = {HUB_URL}\n'
    )
    return config


@pytest.fixture
def git_world(tmp_path: Path) -> GitWorld:
    """A hub checkout of ``acme/demo-hub`` whose ``origin`` is a local bare repository."""
    root = tmp_path / "world"
    home, bin_dir, gh_state = root / "home", root / "bin", root / "gh"
    for folder in (home, bin_dir, gh_state):
        folder.mkdir(parents=True)
    bare = root / "origin.git"
    _fake_gh(bin_dir)
    environ = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOME": str(home),
        "GIT_CONFIG_GLOBAL": str(_gitconfig(home, bare)),
        "GIT_CONFIG_NOSYSTEM": "1",
        "LC_ALL": "C",
        "FAKE_GH_DIR": str(gh_state),
        "FAKE_GH_ORIGIN": str(bare),
    }
    world = GitWorld(
        root=root,
        bare=bare,
        hub=root / "demo-hub",
        seed=root / "seed",
        gh_state=gh_state,
        bin=bin_dir,
        environ=environ,
    )
    world.git("init", "--quiet", "--bare", "--initial-branch=main", str(bare), cwd=root)
    world.git("clone", "--quiet", HUB_URL, str(world.seed), cwd=root)
    (world.seed / "README.md").write_text("# Demo hub\n")
    world.git("add", "README.md", cwd=world.seed)
    world.git("commit", "--quiet", "-m", "chore: start the hub", cwd=world.seed)
    world.git("push", "--quiet", "origin", "main", cwd=world.seed)
    world.git("clone", "--quiet", HUB_URL, str(world.hub), cwd=root)
    return world


class GitBrainOrigin:
    """A ``BrainOrigin`` probe over a ``GitWorld``: seeds the bare ``origin`` through a scratch
    clone and reads its branches, commits and the fake gh's pull requests."""

    def __init__(self, world: GitWorld) -> None:
        self.world = world

    @property
    def hub_path(self) -> str:
        """The user's hub checkout."""
        return str(self.world.hub)

    @property
    def hub_repo(self) -> str:
        """The hub's GitHub ``owner/name``."""
        return HUB_REPO

    @property
    def default_branch(self) -> str:
        """``main``."""
        return DEFAULT_BRANCH

    def put_on_default(self, path: str, text: str) -> None:
        """Commit ``text`` at ``path`` on ``main`` and push it to the origin."""
        target = self.world.seed / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
        seed = self.world.seed
        self.world.git("add", "--", path, cwd=seed)
        self.world.git("commit", "--quiet", "-m", f"docs: add {path}", cwd=seed)
        self.world.git("push", "--quiet", "origin", DEFAULT_BRANCH, cwd=seed)

    def file_on(self, branch: str, path: str) -> str | None:
        """The text at ``path`` on the origin's ``branch``."""
        shown = self.world.origin_git("show", f"refs/heads/{branch}:{path}")
        return shown.stdout if shown.returncode == 0 else None

    def branch_names(self) -> frozenset[str]:
        """The origin's branches."""
        listed = self.world.origin_git("for-each-ref", "--format=%(refname:short)", "refs/heads")
        return frozenset(listed.stdout.split())

    def head_commit(self, branch: str) -> OriginCommit | None:
        """The head commit of the origin's ``branch``."""
        shown = self.world.origin_git(
            "log", "-1", "--format=%an%x00%ae%x00%B", f"refs/heads/{branch}", "--"
        )
        if shown.returncode != 0:
            return None
        name, email, message = shown.stdout.split("\0", 2)
        return OriginCommit(author_name=name, author_email=email, message=message)

    def pull_requests(self) -> tuple[OpenedPullRequest, ...]:
        """The pull requests the fake gh opened, in order."""
        pulls = self.world.gh_state / "pulls.jsonl"
        if not pulls.exists():
            return ()
        lines = pulls.read_text().splitlines()
        return tuple(OpenedPullRequest(**json.loads(line)) for line in lines)


@pytest.fixture
def brain_origin(git_world: GitWorld) -> GitBrainOrigin:
    """The contract suite's view of the bare ``origin``."""
    return GitBrainOrigin(git_world)


@pytest.fixture
def brain_change_requests(git_world: GitWorld) -> GitBrainChangeRequests:
    """The adapter acting on the world's hub."""
    return git_world.adapter()


# The knowledge checkout's hub (AGH-391, moved with its tests from ``cli``, AGH-393): adapted from
# ``packages/cli/tests/integration/conftest.py``'s ``knowledge_hub`` (a conftest cannot be shared
# across packages).
type KnowledgeHubFactory = Callable[..., Path]


def _commit_all(root: Path, *, git: str, env: Mapping[str, str]) -> None:
    """Make ``root`` a git repo whose one commit holds a README, ``AGENTS.md`` and its files."""
    (root / "README.md").write_bytes(f"# {root.name}\n".encode())
    (root / "AGENTS.md").write_bytes(f"# {root.name}\n".encode())
    author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    for args in (
        ["-c", "init.defaultBranch=main", "init", "-q"],
        ["add", "-A"],
        [*author, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
    ):
        subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
            [git, *args], cwd=root, env=dict(env), check=True, capture_output=True
        )


def _write_files(files: Mapping[str, bytes], *, hub: Path, repos: tuple[str, ...]) -> None:
    """Each file at its hub-relative path: in its repo beside the hub, else in the hub."""
    for path, data in files.items():
        first = path.split("/", 1)[0]
        target = (hub.parent if first in repos else hub) / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


@pytest.fixture
def knowledge_hub(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> KnowledgeHubFactory:
    """``knowledge_hub(files, *, repos=("demo-api",), commit=True)``: a hub checkout at
    ``tmp_path / "hub"`` holding a synthetic ``hub.json``, and each of ``repos`` checked out
    beside it, all synthetic git repos with a committed README and ``AGENTS.md``.

    ``files`` maps a hub-relative path, as the knowledge index names it, to its bytes: a path
    whose first segment is one of ``repos`` is written in that repo (``demo-api/docs/x.md``),
    any other in the hub (``brain/x.md``). With ``commit`` the files are committed, else they
    are left untracked. Git reads the test's own ``HOME`` and config only, and never looks for a
    repository above ``tmp_path``.
    """
    git = shutil.which("git")
    assert git is not None, "git is needed for a synthetic checkout"
    home = tmp_path / "checkout-home"
    home.mkdir()
    env = {
        "HOME": str(home),
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CEILING_DIRECTORIES": str(tmp_path),
    }
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    def build(
        files: Mapping[str, bytes], *, repos: tuple[str, ...] = ("demo-api",), commit: bool = True
    ) -> Path:
        hub = tmp_path / "hub"
        hub.mkdir()
        (hub / "hub.json").write_bytes(dump_json(a_hub_document()))
        for name in repos:
            (tmp_path / name).mkdir()
        if commit:
            _write_files(files, hub=hub, repos=repos)
        for name in ("hub", *repos):
            _commit_all(tmp_path / name, git=git, env=env)
        if not commit:
            _write_files(files, hub=hub, repos=repos)
        return hub

    return build
