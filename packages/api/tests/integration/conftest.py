"""Fixtures of the api integration tests: the app as ``hub web`` composes it (``build_app``) on
a temp event database, a temp hub registry and a temp ``~/.claude/projects``, and synthetic
hubs written by ``hub init --config``.

``hub_world`` makes such a hub a git checkout of ``acme/demo-hub`` whose ``origin`` is a local
bare repository: a test-only global git config rewrites the GitHub url to it (``insteadOf``),
and a fake ``gh`` (a stdlib script on ``PATH``) records each pull request it is asked to open,
as ``packages/hub_git/tests/conftest.py`` does. Nothing reaches the network; every name, url and
token is synthetic.
"""

import asyncio
import json
import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import AsyncIterator, Callable, Iterator, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from importlib.metadata import version
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agent_hub.api.app import create_app
from agent_hub.api.composition import build_app
from agent_hub.api.dependencies import ApiPorts
from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.cli.main import app as hub_cli
from agent_hub.core.agent_sessions.agent_session import (
    AgentSession,
    AgentSessionList,
    AgentSessionStatus,
    CloudMessage,
    CloudSession,
    CloudSessionList,
    CreateAgentSession,
    MessageAccepted,
    PermissionDecision,
    ResumableList,
    SendMessage,
    SessionSettings,
    StartCloud,
    WorkdirList,
)
from agent_hub.core.agent_sessions.cloud import CloudReply, CloudSessions
from agent_hub.core.agent_sessions.driver import DriverCapabilities
from agent_hub.core.agent_sessions.links import AgentSessionLinks
from agent_hub.core.agent_sessions.records import LogRecordPage, StreamItem, StreamPosition
from agent_hub.core.events.event import Event
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.agent_session_rig import Rig, build_rig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.read_model_builders import (
    a_cloud_session,
    a_log_record,
    a_workdir,
    an_agent_session,
)
from agent_hub.core.testing.session_driver_fakes import InMemorySessionDriver
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
    registered = composed.client.post(
        "/api/v1/hubs",
        json={"path": str(hub_world.hub)},
        headers={"Origin": "http://127.0.0.1:7420"},
    )
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


# AGH-136: the tickets route end to end, Linear faked at the HTTP transport (``linear_post``).
# A synthetic key, built at run time so no key-shaped literal sits in the source.
SYNTHETIC_LINEAR_KEY = "lin_api_" + "x" * 40
LINEAR_URL = "https://api.linear.app/graphql"
TICKETS_SLUG = "ticket-planning"
TICKETS_PATH = f"/api/v1/features/demo/{TICKETS_SLUG}/tickets"
_ISSUE_ID = re.compile(r"^([A-Z][A-Z0-9]*)-([1-9][0-9]*)$")


class MovableClock:
    """The composed app's clock (``ApiSettings.clock``), moved by the test."""

    def __init__(self, now: datetime = COMPOSED_NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


@dataclass
class LinearIssue:
    """One synthetic Linear issue the fake serves; ``blocked_by`` are issue ids."""

    title: str
    state: tuple[str, str] = ("Todo", "unstarted")
    assignee: str | None = None
    priority: int = 0
    estimate: float | None = None
    blocked_by: tuple[str, ...] = ()


class FakeLinear:
    """A ``Post`` answering ``ReadIssueSummaries`` from ``issues`` in Linear's public shape.

    ``fail`` replaces the answer: an HTTP status (with ``fail_body``), ``"timeout"`` (raises
    ``TimeoutError`` as ``urllib_post`` does) or ``"malformed"`` (200, not JSON). ``gate``,
    when set, holds each request until it is set. Every request is recorded in ``requests``.
    """

    def __init__(self, issues: dict[str, LinearIssue] | None = None) -> None:
        self.issues: dict[str, LinearIssue] = dict(issues or {})
        self.fail: int | str | None = None
        self.fail_body: bytes = b'{"errors": [{"message": "failed"}]}'
        self.gate: threading.Event | None = None
        self.entered = threading.Event()
        self.requests: list[tuple[str, dict[str, str], dict[str, Any]]] = []
        self.timeouts: list[float] = []
        self._lock = threading.Lock()

    @property
    def count(self) -> int:
        return len(self.requests)

    def __call__(
        self, url: str, headers: Mapping[str, str], body: bytes, *, timeout_s: float
    ) -> tuple[int, bytes]:
        document = json.loads(body)
        with self._lock:
            self.requests.append((url, dict(headers), document))
            self.timeouts.append(timeout_s)
        self.entered.set()
        if self.gate is not None:
            assert self.gate.wait(timeout=10), "the test never released the fake Linear"
        assert url == LINEAR_URL
        assert document["operationName"] == "ReadIssueSummaries"
        if self.fail == "timeout":
            raise TimeoutError(f"no answer within {timeout_s:g} s")
        if self.fail == "malformed":
            return 200, b"<html>not json</html>"
        if isinstance(self.fail, int):
            return self.fail, self.fail_body
        return 200, json.dumps({"data": self._answer(document["variables"])}).encode()

    def _answer(self, variables: dict[str, Any]) -> dict[str, Any]:
        team = variables["filter"]["team"]["key"]["eq"]
        asked = [f"{team}-{number}" for number in variables["filter"]["number"]["in"]]
        nodes = [self._node(issue_id) for issue_id in asked if issue_id in self.issues]
        return {"issues": {"nodes": nodes, "pageInfo": {"hasNextPage": False, "endCursor": None}}}

    def _summary(self, issue_id: str) -> dict[str, Any]:
        issue = self.issues[issue_id]
        match = _ISSUE_ID.fullmatch(issue_id)
        assert match is not None
        return {
            "identifier": issue_id,
            "title": issue.title,
            "url": f"https://linear.app/demo/issue/{issue_id}",
            "priority": float(issue.priority),
            "estimate": issue.estimate,
            "state": {"name": issue.state[0], "type": issue.state[1]},
            "assignee": None if issue.assignee is None else {"displayName": issue.assignee},
        }

    def _related(self, issue_id: str) -> dict[str, Any]:
        # A related issue is selected only for what an external blocker shows.
        summary = self._summary(issue_id)
        return {name: summary[name] for name in ("identifier", "title", "url", "state")}

    def _node(self, issue_id: str) -> dict[str, Any]:
        blocks = [other for other, issue in self.issues.items() if issue_id in issue.blocked_by]
        return self._summary(issue_id) | {
            "parent": None,
            "relations": {
                "nodes": [{"type": "blocks", "relatedIssue": self._related(o)} for o in blocks],
                "pageInfo": {"hasNextPage": False},
            },
            "inverseRelations": {
                "nodes": [
                    {"type": "blocks", "issue": self._related(blocker)}
                    for blocker in self.issues[issue_id].blocked_by
                ],
                "pageInfo": {"hasNextPage": False},
            },
        }


def a_ticket_record(tickets: list[dict[str, Any]], acs: list[dict[str, Any]] | None = None) -> str:
    """A ``features.json`` with the ticket plan ``tickets`` and ``acs`` (default: one each)."""
    default_acs = [
        {
            "id": f"AC-9.{index}",
            "description": f"Criterion {index}",
            "repo": "demo-api",
            "verification": "make check",
            "passes": False,
            "evidence": None,
            "ticket": ticket["key"],
        }
        for index, ticket in enumerate(tickets, start=1)
    ]
    record = {
        "feature": TICKETS_SLUG,
        "tickets": tickets,
        "acs": default_acs if acs is None else acs,
    }
    return json.dumps(record, indent=2)


def write_feature(hub: Path, record: str, *, slug: str = TICKETS_SLUG) -> Path:
    """A feature folder with a spec, research, plan and ``features.json`` ``record``."""
    folder = hub / "brain" / "features" / slug
    folder.mkdir(parents=True)
    spec = "---\ntype: spec\nprocess_size: bounded\nrepos: [demo-api]\n---\n# Spec\n"
    files = {"spec.md": spec, "research.md": "# Research\n", "plan.md": "# Plan\n"}
    for name, text in (files | {"features.json": record}).items():
        (folder / name).write_text(text, encoding="utf-8")
    return folder


# The default plan: DEM-2 waits on DEM-1 (plan and Linear) and on OPS-9 (Linear only, outside
# the feature); "docs" is not created in Linear yet.
PLANNED_TICKETS: list[dict[str, Any]] = [
    {"key": "api", "id": "DEM-1", "title": "Planned api work", "repo": "demo-api", "order": 1},
    {"key": "web", "id": "DEM-2", "title": "Planned web work", "blocked_by": ["api"], "order": 2},
    {"key": "docs", "title": "Planned docs", "blocked_by": ["web"], "order": 3},
]


def linear_issues() -> dict[str, LinearIssue]:
    """The Linear side of ``PLANNED_TICKETS``."""
    return {
        "DEM-1": LinearIssue("Build the api", state=("In Progress", "started"), assignee="Ada"),
        "DEM-2": LinearIssue(
            "Build the web", priority=2, estimate=3, blocked_by=("DEM-1", "OPS-9")
        ),
        "OPS-9": LinearIssue("Open the firewall", state=("Done", "completed")),
    }


@dataclass
class TicketsWorld:
    """The composed app over a registered hub with one planned feature, and its fake Linear."""

    app: Composed
    hub: Path
    linear: FakeLinear
    clock: MovableClock
    environ: dict[str, str]

    def tickets(self) -> Any:
        return self.app.client.get(TICKETS_PATH)


type TicketsOpener = Callable[..., TicketsWorld]


@pytest.fixture
def open_tickets(
    open_composed: Callable[..., Composed], composed_settings: ApiSettings, make_hub: HubFactory
) -> TicketsOpener:
    """Opens ``TicketsWorld``: ``record`` (default ``PLANNED_TICKETS``), ``issues`` (default
    ``linear_issues()``) and ``environ`` (default the synthetic key) may be overridden."""

    def opened(
        *,
        record: str | None = None,
        issues: dict[str, LinearIssue] | None = None,
        environ: dict[str, str] | None = None,
    ) -> TicketsWorld:
        hub = make_hub()
        write_feature(hub, a_ticket_record(PLANNED_TICKETS) if record is None else record)
        clock = MovableClock()
        linear = FakeLinear(linear_issues() if issues is None else issues)
        env = {"LINEAR_API_KEY": SYNTHETIC_LINEAR_KEY} if environ is None else environ
        app = open_composed(
            replace(composed_settings, clock=clock), environ=env, linear_post=linear
        )
        registered = app.client.post(
            "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": "http://127.0.0.1:7420"}
        )
        assert registered.status_code == 201, registered.text
        return TicketsWorld(app=app, hub=hub, linear=linear, clock=clock, environ=env)

    return opened


@pytest.fixture
def tickets_world(open_tickets: TicketsOpener) -> TicketsWorld:
    """``open_tickets`` with every default."""
    return open_tickets()


@pytest.fixture
def tickets_kit() -> SimpleNamespace:
    """The tickets helpers, for test modules (which cannot import this conftest)."""
    return SimpleNamespace(
        LinearIssue=LinearIssue,
        a_ticket_record=a_ticket_record,
        write_feature=write_feature,
        linear_issues=linear_issues,
        planned=PLANNED_TICKETS,
        key=SYNTHETIC_LINEAR_KEY,
        path=TICKETS_PATH,
        slug=TICKETS_SLUG,
    )


# The agent-session routes (RT) against recording command ports: what each route passes on,
# the problem each core error becomes, and the stream's wire form.


@dataclass
class RecordingAgentSessions:
    """``AgentSessionCommands`` that records each call as ``(method, arguments)`` and answers
    built models. ``failures[method]`` raises instead; ``subscribe`` answers ``stream``, one
    item after another, after waiting ``pause`` seconds before each."""

    session: AgentSession = field(default_factory=an_agent_session)
    stream: list[StreamItem] = field(default_factory=list)
    pause: float = 0.0
    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)
    closed: bool = False

    def _call(self, method: str, *arguments: object) -> None:
        self.calls.append((method, arguments))
        if method in self.failures:
            raise self.failures[method]

    def methods(self) -> list[str]:
        """The names of the methods called, in order."""
        return [method for method, _ in self.calls]

    async def workdirs(self, project: str) -> WorkdirList:
        self._call("workdirs", project)
        return WorkdirList(items=(a_workdir(),))

    async def capabilities(self) -> DriverCapabilities:
        self._call("capabilities")
        return DriverCapabilities(available=True, engine="in-memory")

    async def resumable(self, project: str, workdir_id: str) -> ResumableList:
        self._call("resumable", project, workdir_id)
        return ResumableList(items=())

    async def list_sessions(
        self, *, project: str | None, status: AgentSessionStatus | None
    ) -> AgentSessionList:
        self._call("list_sessions", project, status)
        return AgentSessionList(items=(self.session,))

    async def create(self, request: CreateAgentSession) -> AgentSession:
        self._call("create", request)
        return self.session

    async def snapshot(self, agent_session_id: str) -> AgentSession:
        self._call("snapshot", agent_session_id)
        return self.session

    async def delete(self, agent_session_id: str) -> None:
        self._call("delete", agent_session_id)

    async def events(self, agent_session_id: str, *, after: int, limit: int) -> LogRecordPage:
        self._call("events", agent_session_id, after, limit)
        return LogRecordPage(items=(a_log_record(seq=after + 1),), next_after=None)

    async def subscribe(
        self, agent_session_id: str, after: StreamPosition | None
    ) -> AsyncIterator[StreamItem]:
        self._call("subscribe", agent_session_id, after)
        return self._frames()

    async def _frames(self) -> AsyncIterator[StreamItem]:
        try:
            for item in self.stream:
                await asyncio.sleep(self.pause)
                yield item
        finally:
            self.closed = True

    async def send(self, agent_session_id: str, message: SendMessage) -> MessageAccepted:
        self._call("send", agent_session_id, message)
        return MessageAccepted(seq=self.session.last_seq + 1)

    async def interrupt(self, agent_session_id: str) -> AgentSession:
        self._call("interrupt", agent_session_id)
        return self.session

    async def answer(
        self, agent_session_id: str, request_id: str, decision: PermissionDecision
    ) -> AgentSession:
        self._call("answer", agent_session_id, request_id, decision)
        return self.session

    async def change_settings(
        self, agent_session_id: str, settings: SessionSettings
    ) -> AgentSession:
        self._call("change_settings", agent_session_id, settings)
        return self.session

    async def close(self, agent_session_id: str) -> AgentSession:
        self._call("close", agent_session_id)
        return self.session


@dataclass
class RecordingCloudSessions:
    """``CloudSessionCommands`` that records each call; ``failures[method]`` raises instead."""

    failures: dict[str, Exception] = field(default_factory=dict)
    calls: list[tuple[str, tuple[object, ...]]] = field(default_factory=list)

    def _call(self, method: str, *arguments: object) -> None:
        self.calls.append((method, arguments))
        if method in self.failures:
            raise self.failures[method]

    async def list_cloud(self, project: str | None) -> CloudSessionList:
        self._call("list_cloud", project)
        return CloudSessionList(items=(a_cloud_session(),))

    async def start(self, request: StartCloud) -> CloudSession:
        self._call("start", request)
        return a_cloud_session()

    async def follow_up(self, cloud_id: str, message: CloudMessage) -> CloudSession:
        self._call("follow_up", cloud_id, message)
        return a_cloud_session(followups=1)


@dataclass
class RecordedApp:
    """``create_app`` over the recording ports, its client signed in and on this server's
    Origin (so writes pass the access middleware)."""

    client: TestClient
    control: RecordingAgentSessions
    cloud: RecordingCloudSessions


@pytest.fixture
def recorded_app(api_settings: ApiSettings, web_dist: Path) -> Iterator[RecordedApp]:
    """The agent-session routes over ``RecordingAgentSessions`` and ``RecordingCloudSessions``."""
    control, cloud = RecordingAgentSessions(), RecordingCloudSessions()
    ports = ApiPorts(agent_sessions=control, cloud_sessions=cloud)
    app = create_app(api_settings, ports=ports, web_dist=web_dist)
    origin = f"http://127.0.0.1:{api_settings.port}"
    with TestClient(
        app, base_url=origin, headers={"Origin": origin}, raise_server_exceptions=False
    ) as client:
        client.cookies.set(cookie_name(api_settings.port), str(api_settings.session_token))
        yield RecordedApp(client, control, cloud)


# The agent-session routes over the real use case (CP, AC-165.15-.35): ``AgentSessionControl``
# over ``InMemorySessionDriver`` and ``InMemoryAgentSessionStore`` (``agent_session_rig``), with
# ``CloudSessions`` and the links. No runtime: a test moves the rig's clock and sweeps itself.


class NoCloudLauncher:
    """A ``CloudLauncher`` no test reaches (follow-ups are off in the fake capabilities)."""

    async def follow_up(self, cloud_id: str, text: str, *, timeout_seconds: int) -> CloudReply:
        msg = f"no cloud launcher in this test ({cloud_id}, {len(text)}, {timeout_seconds})"
        raise AssertionError(msg)


@dataclass
class SessionApp:
    """The routes over the rig's control, its client signed in and on this server's Origin."""

    client: TestClient
    rig: Rig

    @property
    def driver(self) -> InMemorySessionDriver:
        return self.rig.driver

    def run(self, call: Callable[..., Any], *arguments: Any) -> Any:
        """Await ``call(*arguments)`` on the app's event loop (where the sessions live)."""
        portal = self.client.portal
        assert portal is not None
        return portal.call(call, *arguments)

    def sweep(self, seconds: float) -> None:
        """Move the clock ``seconds`` and apply time (no purge)."""
        self.run(lambda: self.rig.control.sweep(self.rig.clock.advance(seconds), purge=False))

    def get(self, agent_session_id: str) -> dict[str, Any]:
        response = self.client.get(f"/api/v1/agent-sessions/{agent_session_id}")
        assert response.status_code == 200, response.text
        body: dict[str, Any] = response.json()
        return body

    def until_status(self, agent_session_id: str, *statuses: str) -> dict[str, Any]:
        """The session once its status is one of ``statuses`` (5 s at most)."""
        deadline = time.monotonic() + 5
        while True:
            body = self.get(agent_session_id)
            if body["status"] in statuses or time.monotonic() > deadline:
                assert body["status"] in statuses, body
                return body
            time.sleep(0.005)

    def kinds(self, agent_session_id: str) -> list[str]:
        """The kinds of the persisted records, in seq order."""
        return self.rig.kinds(agent_session_id)


type SessionAppOpener = Callable[..., SessionApp]


@pytest.fixture
def open_agent_session_app(api_settings: ApiSettings, web_dist: Path) -> Iterator[SessionAppOpener]:
    """Opens the routes over a fresh rig; ``build_rig`` keywords (``replies``, ``limits``,
    ``past_sessions``, ``driver``) pass through."""
    opened_apps: list[SessionApp] = []

    def opened(**options: Any) -> SessionApp:
        rig = build_rig(**options)
        cloud = CloudSessions(
            launcher=NoCloudLauncher(),
            store=rig.store,
            capabilities=rig.driver.capabilities,
            clock=rig.clock,
        )
        ports = ApiPorts(
            agent_sessions=rig.control,
            cloud_sessions=cloud,
            agent_session_links=AgentSessionLinks(rig.control.live_link, rig.store),
        )
        app = create_app(api_settings, ports=ports, web_dist=web_dist)
        origin = f"http://127.0.0.1:{api_settings.port}"
        client = TestClient(
            app, base_url=origin, headers={"Origin": origin}, raise_server_exceptions=False
        )
        client.__enter__()
        client.cookies.set(cookie_name(api_settings.port), str(api_settings.session_token))
        session_app = SessionApp(client=client, rig=rig)
        opened_apps.append(session_app)
        return session_app

    yield opened
    for session_app in opened_apps:
        # End the live sessions on their loop before it closes (as the runtime does).
        session_app.run(session_app.rig.control.shutdown)
        session_app.client.__exit__(None, None, None)


@pytest.fixture
def agent_session_app(open_agent_session_app: SessionAppOpener) -> SessionApp:
    """The agent-session routes over the real ``AgentSessionControl`` (default rig)."""
    return open_agent_session_app()
