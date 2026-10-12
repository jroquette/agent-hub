"""Fixtures of the api integration tests: the app as ``hub web`` composes it (``build_app``) on
a temp event database, a temp hub registry and a temp ``~/.claude/projects``, and synthetic
hubs written by ``hub init --config``.

``hub_world`` makes such a hub a git checkout of ``acme/demo-hub`` whose ``origin`` is a local
bare repository: a test-only global git config rewrites the GitHub url to it (``insteadOf``),
and a fake ``gh`` (a stdlib script on ``PATH``) records each pull request it is asked to open,
as ``packages/hub_git/tests/conftest.py`` does. Nothing reaches the network; every name, url and
token is synthetic.
"""

import json
import os
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agent_hub.api.composition import build_app
from agent_hub.api.settings import ApiSettings
from agent_hub.cli.main import app as hub_cli
from agent_hub.core.events.event import Event
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.hub_git.brain_change_requests import GitBrainChangeRequests
from agent_hub.hub_git.git_runner import GitRunner
from agent_hub.storage.event_store import SqliteEventStore, open_event_store

COMPOSED_PORT = 7420
COMPOSED_URL = f"http://127.0.0.1:{COMPOSED_PORT}"
COMPOSED_NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
# The pin a synthetic hub carries and the version the composed app runs: the CLI's, so the
# doctor rules that compare them agree with ``hub doctor``.
RUNNING_VERSION = version("agent-hub-cli")


@dataclass
class Composed:
    """The composed app's client and what it reads and writes, for a test to inspect."""

    client: TestClient
    settings: ApiSettings
    projects: Path
    store: SqliteEventStore

    def rows(self) -> list[Event]:
        """Every stored event, in append order."""
        return self.store.read_all()


@pytest.fixture
def projects_root(tmp_path: Path) -> Path:
    """A temp ``~/.claude/projects`` with one project folder."""
    root = tmp_path / "home" / ".claude" / "projects"
    (root / "-work-demo-api").mkdir(parents=True)
    return root


@pytest.fixture
def composed_settings(tmp_path: Path) -> ApiSettings:
    return ApiSettings(
        db_path=tmp_path / "data" / "agent-hub.db",
        registry_path=tmp_path / "config" / "agent-hub" / "hubs.json",
        port=COMPOSED_PORT,
        running_version=RUNNING_VERSION,
        clock=lambda: COMPOSED_NOW,
    )


type ComposedOpener = Callable[..., Any]


@pytest.fixture
def open_composed(
    composed_settings: ApiSettings, projects_root: Path, web_dist: Path
) -> Iterator[Callable[..., Composed]]:
    """Opens ``build_app`` on the temp paths; ``build_app`` keywords may be overridden."""
    clients: list[TestClient] = []

    def opened(settings: ApiSettings = composed_settings, **options: Any) -> Composed:
        app = build_app(
            settings,
            **({"projects_root": projects_root, "web_dist": web_dist} | options),
        )
        client = TestClient(app, base_url=COMPOSED_URL, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return Composed(
            client=client,
            settings=settings,
            projects=projects_root,
            store=open_event_store(settings.db_path),
        )

    yield opened
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def composed(open_composed: Callable[..., Composed]) -> Composed:
    """The composed app on the temp paths."""
    return open_composed()


type HubFactory = Callable[..., Path]


@pytest.fixture
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """``HOME`` under ``tmp_path`` and no git config from the machine or a caller."""
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    return home


@pytest.fixture
def make_hub(tmp_path: Path, isolated_home: Path) -> HubFactory:
    """Writes a synthetic hub with ``hub init --config`` in ``tmp_path / <folder>``.

    The document is ``a_hub_document`` without modules, pinned to the running CLI, named
    ``project``; ``change`` may edit it before it is written.
    """

    def make(
        project: str = "demo",
        *,
        folder: str | None = None,
        change: Callable[[dict[str, Any]], None] | None = None,
    ) -> Path:
        document = a_hub_document()
        del document["modules"]
        document["platform"]["version"] = RUNNING_VERSION
        document["project"]["name"] = project
        if change is not None:
            change(document)
        base = tmp_path / f"{folder or project}-config"
        base.mkdir()
        config = base / "hub.json"
        config.write_bytes(dump_json(document))
        root = tmp_path / (folder or f"{project}-hub")
        result = CliRunner().invoke(hub_cli, ["init", "--config", str(config), "--dir", str(root)])
        assert result.exit_code == 0, result.output
        return root

    return make


HUB_REPO = "acme/demo-hub"
HUB_URL = f"https://github.com/{HUB_REPO}.git"
DEFAULT_BRANCH = "main"
# Printed by the fake gh on stdout and stderr: the server must never log or answer it.
GH_OUTPUT_MARKER = "FAKEGH-OUTPUT-n4v8"

_FAKE_GH = f"""\\
import json, os, subprocess, sys

state = os.environ["FAKE_GH_DIR"]
args = sys.argv[1:]
sys.stderr.write("{GH_OUTPUT_MARKER} stderr\\n")


def switch(name):
    return os.path.exists(os.path.join(state, name))


with open(os.path.join(state, "calls.json-lines"), "a") as calls:
    calls.write(json.dumps(args) + "\\n")
if args[:2] == ["auth", "token"]:
    print("gho_not-a-real-token")
    sys.exit(0)
pulls = os.path.join(state, "pulls.json-lines")
if args[:2] == ["pr", "list"]:
    flags = dict(zip(args[2::2], args[3::2]))
    known = [json.loads(line) for line in open(pulls)] if os.path.exists(pulls) else []
    print(json.dumps([{{"url": pull["url"]}} for pull in known if pull["head"] == flags["--head"]]))
    sys.exit(0)
if args[:2] != ["pr", "create"]:
    sys.exit(2)
opts = dict(arg[2:].split("=", 1) for arg in args[2:] if arg.startswith("--") and "=" in arg)
if switch("fail"):
    print("{GH_OUTPUT_MARKER} failed")
    sys.exit(1)
head = subprocess.run(
    ["git", "--git-dir", os.environ["FAKE_GH_ORIGIN"], "rev-parse", "--verify", "--quiet",
     "refs/heads/" + opts["head"]],
    stdout=subprocess.DEVNULL,
)
if head.returncode != 0:
    sys.exit(1)
count = sum(1 for _ in open(pulls)) if os.path.exists(pulls) else 0
url = "https://github.com/" + opts["repo"] + "/pull/" + str(count + 1)
with open(opts["body-file"]) as body_file:
    body = body_file.read()
pull = {{"url": url, "body": body}}
pull.update({{key: opts[key] for key in ("head", "base", "title")}})
with open(pulls, "a") as out:
    out.write(json.dumps(pull) + "\\n")
print(url)
"""
_REJECT_PUSHES = "#!/bin/sh\necho 'push refused by the test origin' >&2\nexit 1\n"


@dataclass(frozen=True, kw_only=True)
class HubWorld:
    """A registered-to-be hub checkout, its bare ``origin``, the fake gh and their environment."""

    hub: Path
    bare: Path
    gh_state: Path
    temp: Path
    environ: dict[str, str]

    def git(self, *args: str, cwd: Path | None = None) -> str:
        """Run git in ``cwd`` (default: the hub checkout); its stdout."""
        done = subprocess.run(  # noqa: S603 - the test's own git, an argv list
            ["git", *args],  # noqa: S607 - git from the test PATH
            cwd=cwd or self.hub,
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )
        assert done.returncode == 0, f"git {' '.join(args)} failed: {done.stderr}"
        return done.stdout

    def origin(self, *args: str) -> subprocess.CompletedProcess[str]:
        """Run git against the bare ``origin``."""
        return subprocess.run(  # noqa: S603 - the test's own git, an argv list
            ["git", "--git-dir", str(self.bare), *args],  # noqa: S607 - git from the test PATH
            env=self.environ,
            capture_output=True,
            text=True,
            check=False,
        )

    def put_note(self, path: str, text: str, *, push: bool = True) -> None:
        """Write ``text`` at hub-relative ``path``, commit it and (by default) push it."""
        target = self.hub / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        self.git("add", "--", path)
        self.git("commit", "--quiet", "-m", f"docs: add {path}")
        if push:
            self.git("push", "--quiet", "origin", DEFAULT_BRANCH)

    def branches(self) -> set[str]:
        """The origin's branches."""
        listed = self.origin("for-each-ref", "--format=%(refname:short)", "refs/heads")
        return set(listed.stdout.split())

    def head(self, branch: str) -> str:
        """The origin's ``branch`` head commit."""
        return self.origin("rev-parse", f"refs/heads/{branch}").stdout.strip()

    def file_on(self, branch: str, path: str) -> str | None:
        """The text at ``path`` on the origin's ``branch``, or None."""
        shown = self.origin("show", f"refs/heads/{branch}:{path}")
        return shown.stdout if shown.returncode == 0 else None

    def pulls(self) -> list[dict[str, str]]:
        """The pull requests the fake gh opened, in order."""
        pulls = self.gh_state / "pulls.json-lines"
        if not pulls.exists():
            return []
        return [json.loads(line) for line in pulls.read_text().splitlines()]

    def gh_calls(self) -> list[list[str]]:
        """The argv of every fake gh call so far."""
        calls = self.gh_state / "calls.json-lines"
        if not calls.exists():
            return []
        return [json.loads(line) for line in calls.read_text().splitlines()]

    def fail_gh(self, *, on: bool = True) -> None:
        """Make ``gh pr create`` fail (printing ``GH_OUTPUT_MARKER``), or work again."""
        switch = self.gh_state / "fail"
        if on:
            switch.touch()
        else:
            switch.unlink(missing_ok=True)

    def reject_pushes(self, *, on: bool = True) -> None:
        """Make the origin refuse every push (a ``pre-receive`` hook), or accept them again."""
        hook = self.bare / "hooks" / "pre-receive"
        if on:
            hook.write_text(_REJECT_PUSHES)
            hook.chmod(0o755)
        else:
            hook.unlink(missing_ok=True)

    def snapshot(self) -> tuple[str, ...]:
        """The user's checkout as git sees it: HEAD, status, refs, worktrees, index."""
        return (
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain", "--ignored"),
            self.git("for-each-ref"),
            self.git("worktree", "list", "--porcelain"),
            self.git("ls-files", "--stage"),
        )

    def changes(self, **environ: str) -> GitBrainChangeRequests:
        """The ``hub_git`` adapter over this world (temporary clones under ``temp``)."""
        return GitBrainChangeRequests(
            GitRunner(environ=self.environ | environ), temp_root=self.temp
        )


def _write_fake_gh(bin_dir: Path) -> None:
    source = bin_dir / "fake_gh.py"
    source.write_text(_FAKE_GH)
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{source}" "$@"\n')
    gh.chmod(0o755)


@pytest.fixture
def hub_world(
    tmp_path: Path, make_hub: HubFactory, *, isolated_home: Path, monkeypatch: pytest.MonkeyPatch
) -> HubWorld:
    """``make_hub``'s hub as a git checkout of ``acme/demo-hub`` pushed to a bare ``origin``.

    The process environment gets the world's git config, ``PATH`` (fake gh first) and fake gh
    state, so every git the test or the app runs sees the same world.
    """
    root = tmp_path / "world"
    bin_dir, gh_state, temp = root / "bin", root / "gh", root / "temp"
    for folder in (bin_dir, gh_state, temp):
        folder.mkdir(parents=True)
    bare = root / "origin.git"
    _write_fake_gh(bin_dir)
    config = root / "gitconfig"
    config.write_text(
        "[user]\n\tname = Seed Owner\n\temail = seed@example.com\n"
        "[init]\n\tdefaultBranch = main\n"
        f'[url "{bare}"]\n\tinsteadOf = {HUB_URL}\n'
    )
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    monkeypatch.setenv("FAKE_GH_DIR", str(gh_state))
    monkeypatch.setenv("FAKE_GH_ORIGIN", str(bare))
    monkeypatch.setenv("LC_ALL", "C")
    monkeypatch.delenv("AGENT_HUB_IN_CONTAINER", raising=False)
    hub = make_hub()
    world = HubWorld(hub=hub, bare=bare, gh_state=gh_state, temp=temp, environ=dict(os.environ))
    world.git("init", "--quiet", "--bare", "--initial-branch=main", str(bare), cwd=root)
    world.git("init", "--quiet", "--initial-branch=main")
    world.git("remote", "add", "origin", HUB_URL)
    world.git("add", "-A")
    world.git("commit", "--quiet", "-m", "chore: start the hub")
    world.git("push", "--quiet", "--set-upstream", "origin", DEFAULT_BRANCH)
    return world


HOOKS = "/api/v1/events/hooks"
# When the composed app's synthetic sessions happen: shortly before its clock's "now".
HOOK_SENT_AT = "2026-10-11T11:58:00.000Z"


@pytest.fixture
def world_app(open_composed: Callable[..., Composed], hub_world: HubWorld) -> Composed:
    """The composed app acting on ``hub_world`` through ``hub_git``, with the hub registered."""
    composed = open_composed(brain_changes=hub_world.changes())
    registered = composed.client.post("/api/v1/hubs", json={"path": str(hub_world.hub)})
    assert registered.status_code == 201, registered.text
    return composed


type Propose = Callable[..., str]


@pytest.fixture
def propose(hub_world: HubWorld) -> Propose:
    """Proposes a learning the way a session does: the note in the hub's ``brain/_inbox/``
    (committed and pushed unless ``on_disk``/``push`` say otherwise) and the session's Write of
    it posted as a hook. Returns the learning's id (the Write's tool use id)."""

    def proposed(  # noqa: PLR0913 - one keyword per way a test bends the proposal
        composed: Composed,
        name: str,
        text: str,
        *,
        on_disk: bool = True,
        push: bool = True,
        project: str = "demo",
        session: str = "session-learn",
    ) -> str:
        path = f"brain/_inbox/{name}"
        if on_disk:
            hub_world.put_note(path, text, push=push)
        tool_use_id = f"toolu_learn_{name.replace('.', '_').replace('/', '_')}"
        write = {
            "tool_name": "Write",
            "tool_input": {"file_path": str(hub_world.hub / path), "content": text},
            "tool_use_id": tool_use_id,
            "session_id": session,
            "cwd": str(hub_world.hub),
        }
        hook = a_hook_input("PreToolUse", **write)
        envelope = an_envelope(hook, project=project, sent_at=HOOK_SENT_AT)
        posted = composed.client.post(HOOKS, json=envelope.model_dump(mode="json"))
        assert posted.status_code == 202, posted.text
        return tool_use_id

    return proposed
