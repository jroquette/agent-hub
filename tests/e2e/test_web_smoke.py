"""The web app against an installed ``hub web`` (AC-200.63, AC-200.57, AC-201.41), and its
bundle's hosts (AC-200.56).

The smoke starts ``hub web`` on a temp database and registry, registers two synthetic hubs,
ingests a synthetic scenario (two projects, one live session, one failed run, one guard denial,
one open guard ask, one 5,000-event session) through ``POST /events/hooks`` and ``hub collect``,
then runs ``apps/web/e2e/smoke.spec.ts`` with Playwright: nine pages, no console error, no
request to another host, axe without serious or critical violations, and Session detail of the
long session complete in under 2 s. Without Chromium the smoke is skipped, and fails under CI.

AGH-201 adds the control-plane clarity screens: the ``demo`` hub is a git checkout of
``acme/demo-hub``, whose ``origin`` a git config in the server's environment maps to a local
bare repository, with a fake ``gh`` on the server's ``PATH`` (as ``packages/hub_git/tests``
does), and a brain (an index linking a note, a feature folder with spec, plan, eval and
``features.json``, an inbox note an agent proposed). The live session runs ``/feature`` through
a Skill call, starts an ``Explore`` subagent through an Agent call, recovers from a failed
``make check-fast`` and proposes the inbox note; an idle session's failed ``make test`` needs
the owner. The pages then check Live (red only for needs-you), Session detail (actors, verbs,
"What went wrong"), Knowledge (read a proposal, accept it: a pull request link), Feature detail
(Spec and Plan tabs) and Brain (tree, note, an in-app link). Everything is synthetic.

AGH-136 gives the feature a ticket plan (``features.json`` ``tickets``, T2 blocked by T1, which is
DEM-7), an eval per delivery (``evals/dem-7.md``) and a review record (``reviews/DEM-7.md``).
``hub web`` runs without ``LINEAR_API_KEY`` (E4: the Linear read is proven in-process by
``packages/api/tests/integration/test_tickets_route.py``), so the Tickets tab shows the plan's
tickets, the planning view and the "Linear is not connected" notice, with the content security
policy unchanged and no request to another host. That check runs in its own test
(``-k tickets``).

AGH-164 gives the demo hub (already holding ``hub init``'s managed skills, agents and settings
hooks) a project skill ``plugin/demo/skills/demo-check``; the live session's Skill call is its
``/feature`` use. The Skills catalog and the ``/feature`` detail are checked in their own test
(``-k skills``, AC-164.30): the content security policy unchanged, no request to another host,
no console error.

AGH-165 (AC-165.47, E14): ``hub web`` (installed with the ``sessions`` extra) finds the stub
``claude`` first on ``PATH``. Its own test (``-k agent_session``) opens the printed token URL,
starts a session from the Sessions screen, reloads while the permission card waits, answers it,
sends one message through the composer, reloads again: the transcript and state survive, the CSP
is unchanged, no other host is requested and no console error is logged.

AGH-233 (AC-213.20): the demo hub holds a ``smoke`` workflow (a sign-off gate, then a shell node
that sleeps until cancelled). Its own test (``-k workflow_run_driven``) starts it from Workflow
runs (always live: ``hub web`` runs the installed hub as its child), approves the gate in Run
detail and cancels the resumed run there; the run ends cancelled and its gate approved, with no
console error and no serious axe violation.

The page smoke runs every other test of ``smoke.spec.ts``.
"""

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.claude_sessions.testing.scenarios import Scenario as StubScenario
from agent_hub.claude_sessions.testing.scenarios import permission_turn, simple_turn
from agent_hub.core.testing.builders import an_event, events_to_jsonl
from agent_hub.core.testing.hook_inputs import a_hook_input
from agent_hub.core.testing.run_lines import run_lines_failed_in_verify
from tests.e2e.conftest import REPO_ROOT, InstalledHub, RunningWeb, StubClaude

# The browser checks time budgets (a 5,000-event session under 2 s): run alone (make test-e2e).
pytestmark = pytest.mark.serial

WEB_DIR = REPO_ROOT / "apps" / "web"
WEB_DIST = REPO_ROOT / "packages" / "api" / "src" / "agent_hub" / "api" / "web_dist"
PLAYWRIGHT_SECONDS = 300
REQUEST_SECONDS = 10
LONG_SESSION_EVENTS = 5_000
LIVE_SESSION = "live-7f3a"
ASK_SESSION = "ask-2c9e"
STUCK_SESSION = "stuck-4b1d"
LONG_SESSION = "long-81d0"
FAILED_RUN = "5e6f7a8b"
# The hub-init spec's flags, so git is never asked; one hub per project.
HUB_FLAGS = (
    "--tracker",
    "linear:DEM",
    "--branch-prefix",
    "jdoe/",
    "--author-name",
    "Jane Doe",
    "--author-email",
    "jane@example.com",
)
FEATURE = "export-button"
FEATURE_SPEC = "---\ntype: spec\nprocess_size: bounded\nrepos: [demo-api]\nlinear: [DEM-7]\n---\n"
# The demo hub's GitHub remote, mapped to a local bare repository by the git config the server
# runs with (``url.<bare>.insteadOf``), so nothing reaches the network.
DEMO_HUB_URL = "https://github.com/acme/demo-hub.git"
# The live session works in a worktree named after the issue (label "DEM-7 · /feature").
LIVE_CWD = "/work/demo-api/.claude/worktrees/dem-7-export-button"
INBOX_NOTE = "brain/_inbox/rerun-flaky-tests.md"
INBOX_TEXT = (
    "---\nkind: team\nprovenance: agent\n---\n"
    "# Rerun a flaky test once before calling it a failure\n\n"
    "The CSV export test failed once on a slow runner and passed when run again. Rerun a test "
    "that fails without a code change once before reporting it.\n"
)
BRAIN_INDEX = (
    "# Demo brain\n\n"
    "Start with [what we focus on now](now.md), then the "
    "[export button spec](features/export-button/spec.md).\n"
)
BRAIN_NOW = "# Now\n\nShip the CSV export button (DEM-7).\n"
# The ticket plan: T1 is DEM-7 in Linear; T2 is not created yet and waits on T1.
FEATURE_TICKETS = (
    {"key": "T1", "id": "DEM-7", "title": "Add the export route", "repo": "demo-api", "order": 1},
    {"key": "T2", "title": "Add the button", "repo": "demo-api", "blocked_by": ["T1"], "order": 2},
)
AC_TICKETS = {1: "T2", 2: "T2", 3: "T1"}
FEATURE_EVAL = (
    "---\ntype: eval\ndelivery: dem-7\nverdict: SHIP-WITH-OWNER-STEPS\ntickets: [DEM-7]\n"
    "acs: [AC-7.3]\nprs: [demo-api#3]\ncommit: 9c1e2d4\nevaluated_at: 2026-10-10T09:00:00Z\n---\n"
    "# Eval DEM-7\n\nOwner step: time the export on the owner's machine.\n"
)
FEATURE_REVIEW = (
    "---\ntype: review\nticket: DEM-7\noutcome: approved\npr: demo-api#3\n"
    "reviewed_at: 2026-10-10\n---\n# Review DEM-7\n\nBoth reviewers passed.\n"
)
# What ``hub web`` answers for the plan's tickets without a key (E4, AC-136.7).
NOT_CONNECTED_TYPE = "urn:agent-hub:problem:tracker-not_connected"
NOT_CONNECTED_TEXT = "Linear is not connected for hub web"
# The policy as v0.9.0 serves it (packages/api/tests/integration/test_local_security.py):
# reading Linear happens on the server, so the page still connects to its own origin only.
EXPECTED_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; font-src 'self'; "
    "img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; "
    "form-action 'self'; frame-ancestors 'none'"
)
# The Playwright test of smoke.spec.ts that opens the Tickets tab.
TICKETS_SPEC = "Tickets tab"
# The Playwright test of smoke.spec.ts that drives an agent session, and the prompt it sends.
AGENT_SESSION_SPEC = "Agent session"
AGENT_PROMPT = "Run the build."
AGENT_FOLLOW_UP = "Now run the tests."
# The Playwright test of smoke.spec.ts that opens the Skills catalog and a skill's detail.
SKILLS_SPEC = "Skills"
# The Playwright test of smoke.spec.ts that drives a workflow run from the web (AC-213.20), and
# the demo hub's workflow it runs: a sign-off gate, then a shell node that works until cancelled
# (no longer than the test's budget, so a failed run never outlives the test by much).
WORKFLOWS_SPEC = "Web-driven workflow run"
SMOKE_WORKFLOW = "workflows/smoke/smoke.yaml"
SMOKE_WORKFLOW_TEXT = """\
version: 1
name: smoke
revision: 1
description: Waits for a sign-off, then works until it is cancelled.
inputs:
  note:
    type: string
    description: A note for the run.
nodes:
  - id: sign-off
    type: approval
    message: Go on?
  - id: work
    type: shell
    command: [sleep, "120"]
    depends_on: [sign-off]
"""
# The demo hub's own skill (AGH-164), beside the managed ones ``hub init`` writes.
DEMO_SKILL = "plugin/demo/skills/demo-check/SKILL.md"
DEMO_SKILL_TEXT = (
    "---\nname: demo-check\ndescription: Checks the demo export before a release.\n"
    'argument-hint: "<issue id>"\n---\n# Demo check\n\n'
    "1. **Test**: run `make check` in demo-api.\n"
    "2. **Review**: ask the `evaluator` agent to read the diff.\n"
)
# A fake ``gh``: ``auth token`` succeeds; ``pr create`` checks the head branch is on the bare
# ``origin`` and prints the next pull request url of ``--repo``. Synthetic: no account, no token.
FAKE_GH = """\
import os, subprocess, sys

args = sys.argv[1:]
if args[:2] == ["auth", "token"]:
    print("gho_not-a-real-token")
    sys.exit(0)
if args[:2] != ["pr", "create"]:
    sys.exit(2)
opts = dict(arg[2:].split("=", 1) for arg in args[2:] if arg.startswith("--") and "=" in arg)
head = subprocess.run(
    ["git", "--git-dir", os.environ["FAKE_GH_ORIGIN"], "rev-parse", "--verify", "--quiet",
     "refs/heads/" + opts["head"]],
    stdout=subprocess.DEVNULL,
)
if head.returncode != 0:
    sys.exit(1)
pulls = os.path.join(os.environ["FAKE_GH_DIR"], "pulls")
with open(pulls, "a") as out:
    out.write(opts["head"] + "\\n")
count = sum(1 for _ in open(pulls))
print("https://github.com/" + opts["repo"] + "/pull/" + str(count))
"""

# Absolute URLs the built bundle may contain, each exact. None is ever requested: React's and
# React Router's error texts name their docs, the XML namespaces are identifiers, and
# ``http://localhost`` is React Router's base for parsing relative URLs, as
# ``https://same-origin.invalid/app`` (a reserved TLD that never resolves) is ``safeHref``'s.
# Any other absolute URL, such as a font, script or API on another host, fails the check.
INERT_BUNDLE_URLS = frozenset(
    {
        "https://reactjs.org/docs/error-decoder.html",
        "https://reactrouter.com/en/main/routers/picking-a-router",
        "https://github.com/ungap/url-search-params",
        "http://www.w3.org/1999/xhtml",
        "http://www.w3.org/1999/xlink",
        "http://www.w3.org/2000/svg",
        "http://www.w3.org/1998/Math/MathML",
        "http://www.w3.org/XML/1998/namespace",
        "http://localhost",
        "https://same-origin.invalid/app",
        # AGH-136: the origin ``linearHref`` checks a Linear issue link against before rendering
        # it as a link the owner opens; the page never requests it (CSP connect-src 'self').
        "https://linear.app",
        # AGH-165: the origin and prefix ``claudeCodeHref`` checks a cloud session link against
        # (a link the owner opens in claude.ai); never requested.
        "https://claude.ai",
        "https://claude.ai/code",
        # AGH-252: text of highlight.js's console warnings in the lazy highlight chunk; never
        # requested.
        "https://github.com/highlightjs/highlight.js/issues/2277",
        "https://github.com/highlightjs/highlight.js/wiki/security",
    }
)
_ABSOLUTE_URL = re.compile(r"https?://[A-Za-z0-9.\-\[\]:]+(?:/[A-Za-z0-9._~/\-]*)?")


def bundle_urls(dist: Path) -> set[str]:
    """Every absolute URL in the built JS, CSS and HTML, up to its path (query cut, dot trimmed)."""
    found: set[str] = set()
    for path in sorted(dist.rglob("*")):
        if path.suffix in {".js", ".css", ".html"}:
            text = path.read_text(encoding="utf-8")
            found.update(match.rstrip("./") for match in _ABSOLUTE_URL.findall(text))
    return found


def test_bundle_names_no_other_host_when_web_app_built() -> None:
    """AC-200.56 on the committed build (``make web-dist-check`` proves it is the fresh build)."""
    urls = bundle_urls(WEB_DIST)

    assert urls - INERT_BUNDLE_URLS == set()
    assert "https://reactjs.org/docs/error-decoder.html" in urls


def test_bundle_check_fails_when_bundle_loads_external_font_or_script(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<script src="https://cdn.example.com/app.js"></script>', encoding="utf-8"
    )
    (tmp_path / "app.css").write_text(
        "@font-face{src:url(https://fonts.example.org/geist.woff2)}", encoding="utf-8"
    )
    (tmp_path / "app.js").write_text(
        'fetch("https://reactjs.org/api");x="http://www.w3.org/2000/svg"', encoding="utf-8"
    )

    assert bundle_urls(tmp_path) - INERT_BUNDLE_URLS == {
        "https://cdn.example.com/app.js",
        "https://fonts.example.org/geist.woff2",
        "https://reactjs.org/api",
    }


@dataclass(frozen=True)
class Scenario:
    """What the smoke pages open: ids the synthetic scenario stored."""

    live_session: str
    stuck_session: str
    long_session: str
    run_id: str
    project: str


def chromium_executable() -> str | None:
    """A Chromium headless shell for Playwright: the revision it expects, else the newest found.

    The browsers come from ``PLAYWRIGHT_BROWSERS_PATH`` (else Playwright's cache); nothing is
    ever downloaded here.
    """
    configured = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
    root = Path(configured) if configured else Path.home() / ".cache" / "ms-playwright"
    # The playwright-core under @playwright/test is the one `playwright install` runs; another
    # copy (from @axe-core/playwright) can sit at the top of node_modules with a newer revision.
    modules = WEB_DIR / "node_modules"
    nested = modules / "playwright" / "node_modules" / "playwright-core" / "browsers.json"
    browsers = nested if nested.is_file() else modules / "playwright-core" / "browsers.json"
    if browsers.is_file():
        listed = json.loads(browsers.read_text(encoding="utf-8"))["browsers"]
        revision = next(b["revision"] for b in listed if b["name"] == "chromium-headless-shell")
        expected = _headless_shells(root, revision)
        if expected:
            return str(expected[0])
    found = _headless_shells(root, "*")
    return str(found[-1]) if found else None


def _headless_shells(root: Path, revision: str) -> list[Path]:
    # Older Playwright builds ship chrome-linux/headless_shell; newer ones (1.5x+) ship
    # chrome-headless-shell-linux64/chrome-headless-shell.
    folder = f"chromium_headless_shell-{revision}"
    return sorted(
        [
            *root.glob(f"{folder}/chrome-*/headless_shell"),
            *root.glob(f"{folder}/chrome-headless-shell-*/chrome-headless-shell"),
        ]
    )


@dataclass(frozen=True)
class HubOrigin:
    """The demo hub's bare ``origin``, the fake ``gh`` and the environment git and gh run in."""

    bare: Path
    env: Mapping[str, str]

    def git(self, *args: str, cwd: Path) -> None:
        """Run git in ``cwd`` with the origin's environment; fails the test when git fails."""
        result = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env={**os.environ, **self.env},
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, f"git {' '.join(args)}: {result.stderr}"


@pytest.fixture
def hub_origin(tmp_path: Path) -> HubOrigin:
    """A bare ``origin`` for ``acme/demo-hub``, a git config mapping its GitHub url to it, and
    a fake ``gh`` in a folder for ``PATH``."""
    root = tmp_path / "hub-origin"
    bin_dir, gh_state = root / "bin", root / "gh"
    for folder in (bin_dir, gh_state):
        folder.mkdir(parents=True)
    bare = root / "origin.git"
    config = root / "gitconfig"
    config.write_text(
        "[user]\n\tname = Jane Doe\n\temail = jane@example.com\n"
        "[init]\n\tdefaultBranch = main\n"
        f'[url "{bare}"]\n\tinsteadOf = {DEMO_HUB_URL}\n',
        encoding="utf-8",
    )
    source = bin_dir / "fake_gh.py"
    source.write_text(FAKE_GH, encoding="utf-8")
    gh = bin_dir / "gh"
    gh.write_text(f'#!/bin/sh\nexec "{sys.executable}" -I "{source}" "$@"\n', encoding="utf-8")
    gh.chmod(0o755)
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "GIT_CONFIG_GLOBAL": str(config),
        "GIT_CONFIG_NOSYSTEM": "1",
        "FAKE_GH_DIR": str(gh_state),
        "FAKE_GH_ORIGIN": str(bare),
    }
    origin = HubOrigin(bare=bare, env=env)
    origin.git("init", "--quiet", "--bare", "--initial-branch=main", str(bare), cwd=root)
    return origin


@pytest.fixture
def web_extra_env(hub_origin: HubOrigin, stub_claude: StubClaude) -> Mapping[str, str]:
    """``hub web`` runs git and gh against the bare origin and the fake gh, with an empty
    ``LINEAR_API_KEY`` (E4), so a key in the caller's environment never reaches Linear, and
    finds the stub ``claude`` first on ``PATH`` (E14)."""
    path = f"{stub_claude.bin_dir}{os.pathsep}{hub_origin.env['PATH']}"
    return {**hub_origin.env, **stub_claude.env, "PATH": path, "LINEAR_API_KEY": ""}


def _make_hub(installed_hub: InstalledHub, root: Path, *, project: str, repo: str) -> Path:
    hub = root / f"{project}-hub"
    command = [
        str(installed_hub.executable),
        "init",
        project,
        "--repos",
        f"acme/{repo}",
        "--hub-repo",
        f"acme/{project}-hub",
        *HUB_FLAGS,
        "--dir",
        str(hub),
    ]
    result = subprocess.run(
        command, cwd=root, env=installed_hub.env, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
    return hub


def _write_feature(hub: Path) -> None:
    """The feature folder: spec, plan, a scoped legacy ``eval.md``, ``features.json`` with its
    ticket plan, an eval per delivery and a review record."""
    folder = hub / "brain" / "features" / FEATURE
    (folder / "evals").mkdir(parents=True)
    (folder / "reviews").mkdir()
    acs = [
        {
            "id": f"AC-7.{index}",
            "description": f"Criterion {index}",
            "repo": "demo-api",
            "verification": "make check",
            "passes": index < 3,
            "evidence": "test run" if index < 3 else None,
            "ticket": AC_TICKETS[index],
        }
        for index in (1, 2, 3)
    ]
    record = {
        "feature": FEATURE,
        "linear": ["DEM-7"],
        "tickets": list(FEATURE_TICKETS),
        "acs": acs,
    }
    (folder / "features.json").write_text(json.dumps(record), encoding="utf-8")
    criteria = "".join(f"- AC-7.{index} Criterion {index}\n" for index in (1, 2, 3))
    (folder / "spec.md").write_text(
        f"{FEATURE_SPEC}# Export button\n\n{criteria}", encoding="utf-8"
    )
    (folder / "plan.md").write_text(
        "# Plan\n\n1. Add the export route.\n2. Add the button.\n", encoding="utf-8"
    )
    (folder / "eval.md").write_text(
        "---\ntype: eval\nacs: [AC-7.1, AC-7.2]\n---\n"
        "# Eval\n\n**Verdict: SHIP**\n\nAll criteria verified.\n",
        encoding="utf-8",
    )
    (folder / "evals" / "dem-7.md").write_text(FEATURE_EVAL, encoding="utf-8")
    (folder / "reviews" / "DEM-7.md").write_text(FEATURE_REVIEW, encoding="utf-8")


def _write_brain(hub: Path) -> None:
    """The brain's index (linking two notes), ``now.md`` and an inbox note an agent proposed."""
    brain = hub / "brain"
    (brain / "index.md").write_text(BRAIN_INDEX, encoding="utf-8")
    (brain / "now.md").write_text(BRAIN_NOW, encoding="utf-8")
    note = hub / INBOX_NOTE
    note.parent.mkdir(parents=True, exist_ok=True)
    note.write_text(INBOX_TEXT, encoding="utf-8")


def _write_skill(hub: Path) -> None:
    """The project's own skill, next to the managed ones (AGH-164)."""
    skill = hub / DEMO_SKILL
    skill.parent.mkdir(parents=True, exist_ok=True)
    skill.write_text(DEMO_SKILL_TEXT, encoding="utf-8")


def _write_workflow(hub: Path) -> None:
    """The demo hub's own workflow, which the web starts, approves and cancels (AC-213.20)."""
    workflow = hub / SMOKE_WORKFLOW
    workflow.parent.mkdir(parents=True, exist_ok=True)
    workflow.write_text(SMOKE_WORKFLOW_TEXT, encoding="utf-8")


def _publish_hub(hub: Path, origin: HubOrigin) -> None:
    """Make ``hub`` a checkout of ``acme/demo-hub`` whose ``main`` is on the bare origin."""
    origin.git("init", "--quiet", "--initial-branch=main", cwd=hub)
    origin.git("remote", "add", "origin", DEMO_HUB_URL, cwd=hub)
    origin.git("add", "--all", cwd=hub)
    origin.git("commit", "--quiet", "--no-verify", "-m", "chore: start the hub", cwd=hub)
    origin.git("push", "--quiet", "--set-upstream", "origin", "main", cwd=hub)


def _envelope(
    project: str, repo: str, hook: dict[str, Any], *, at: datetime, **extra: Any
) -> dict[str, Any]:
    return {
        "v": 1,
        "project": project,
        "repo": repo,
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": at.isoformat(),
        "hook": hook,
    } | extra


def _tool(name: str, tool_input: dict[str, Any], tool_use_id: str) -> dict[str, Any]:
    return {"tool_name": name, "tool_input": tool_input, "tool_use_id": tool_use_id}


def _live_hooks() -> list[tuple[str, dict[str, Any], dict[str, Any]]]:
    """The live session, in order: ``/feature`` through a Skill call, an ``Explore`` subagent
    started by an Agent call, a failed ``make check-fast`` the agent recovered from, an inbox
    note proposed, then a push the guard denied (the agent is still on it)."""
    explore = {"agent_id": "agent-7", "agent_type": "Explore"}
    skill = _tool("Skill", {"skill": "feature"}, "toolu_skill")
    agent = _tool(
        "Agent",
        {
            "subagent_type": "Explore",
            "description": "Find the export code",
            "prompt": "Where is the export route?",
        },
        "toolu_agent",
    )
    grep = _tool("Grep", {"pattern": "def export", "path": "src"}, "toolu_grep")
    check = {"command": "make check-fast", "description": "Run the fast gate"}
    failed = _tool("Bash", check, "toolu_check_1")
    passed = _tool("Bash", check, "toolu_check_2")
    note = _tool(
        "Write", {"file_path": f"/work/demo-hub/{INBOX_NOTE}", "content": INBOX_TEXT}, "toolu_note"
    )
    push = _tool("Bash", {"command": "git push origin main"}, "toolu_push")
    error = "Exit code 2\nFAILED tests/test_export.py::test_csv_header - KeyError: 'name'"
    deny = {"by": "guard", "kind": "deny", "rule": "push-to-main"}
    return [
        ("SessionStart", {}, {}),
        ("UserPromptSubmit", {}, {}),
        ("PreToolUse", skill, {}),
        ("PostToolUse", skill, {}),
        ("PreToolUse", agent, {}),
        ("SubagentStart", explore, {}),
        ("PreToolUse", grep | explore, {}),
        ("PostToolUse", grep | explore, {}),
        ("SubagentStop", explore, {}),
        ("PostToolUse", agent, {}),
        ("PreToolUse", failed, {}),
        ("PostToolUseFailure", failed | {"error": error}, {}),
        ("PreToolUse", passed, {}),
        ("PostToolUse", passed, {}),
        ("PreToolUse", note, {}),
        ("PostToolUse", note, {}),
        ("PreToolUse", push, {"decision": deny}),
    ]


def _hooks(now: datetime) -> list[dict[str, Any]]:
    """The live ``demo`` session, an idle one whose failed ``make test`` needs the owner, and
    one in ``ops`` waiting on a guard ask."""
    live = {"session_id": LIVE_SESSION, "cwd": LIVE_CWD}
    stuck = {"session_id": STUCK_SESSION, "cwd": "/work/demo-api"}
    ask = {"session_id": ASK_SESSION, "cwd": "/work/ops-api"}
    edit = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": "/work/ops-api/docs/adr/0009.md",
            "old_string": "a",
            "new_string": "b",
        },
        "tool_use_id": "toolu_adr",
    }
    ask_decision = {"by": "guard", "kind": "ask", "rule": "ask_before_edit"}
    steps = _live_hooks()
    live_envelopes = [
        _envelope(
            "demo",
            "demo-api",
            a_hook_input(name, **fields) | live,
            at=now - timedelta(seconds=5 * (len(steps) - index)),
            **extra,
        )
        for index, (name, fields, extra) in enumerate(steps)
    ]
    test = _tool("Bash", {"command": "make test"}, "toolu_test")
    error = "Exit code 1\nAssertionError: expected 3 rows, got 2"
    stuck_envelopes = [
        _envelope(
            "demo", "demo-api", a_hook_input("SessionStart") | stuck, at=now - timedelta(minutes=12)
        ),
        _envelope(
            "demo",
            "demo-api",
            a_hook_input("PreToolUse", **test) | stuck,
            at=now - timedelta(minutes=11),
        ),
        _envelope(
            "demo",
            "demo-api",
            a_hook_input("PostToolUseFailure", **test, error=error) | stuck,
            at=now - timedelta(minutes=10),
        ),
    ]
    at = now - timedelta(seconds=60)
    return [
        *live_envelopes,
        *stuck_envelopes,
        _envelope("ops", "ops-api", a_hook_input("SessionStart") | ask, at=at),
        _envelope(
            "ops",
            "ops-api",
            a_hook_input("PreToolUse", **edit) | ask,
            at=now - timedelta(seconds=40),
            decision=ask_decision,
        ),
    ]


def _long_session(now: datetime) -> list[Any]:
    """An ended ``demo`` session of 5,000 events: a start, tool calls and results, an end."""
    start = now - timedelta(hours=2)

    def event(index: int, kind: str, payload: dict[str, Any]) -> Any:
        return an_event(
            session=LONG_SESSION,
            type=kind,
            timestamp=start + timedelta(milliseconds=500 * index),
            source="claude_code",
            source_id=f"{LONG_SESSION}:{index}",
            repo="demo-api",
            agent="main",
            payload=payload,
        )

    events = [event(0, "session.start", {"trigger": "startup", "cwd": "/work/demo-api"})]
    pairs = (LONG_SESSION_EVENTS - 2) // 2
    for pair in range(pairs):
        tool_use_id = f"toolu_{pair:05d}"
        call = {"tool": "Bash", "tool_use_id": tool_use_id, "command": f"make test-{pair % 7}"}
        events.append(event(2 * pair + 1, "tool.call", call))
        result = {"tool": "Bash", "tool_use_id": tool_use_id, "status": "ok", "duration_ms": 40}
        events.append(event(2 * pair + 2, "tool.result", result))
    events.append(
        event(len(events), "session.end", {"end_reason": "prompt_input_exit", "outcome": "stopped"})
    )
    return events


def ingest_scenario(
    web: RunningWeb, installed_hub: InstalledHub, root: Path, *, origin: HubOrigin
) -> Scenario:
    """Registers the two hubs and stores the scenario in ``web``'s database."""
    demo = _make_hub(installed_hub, root, project="demo", repo="demo-api")
    ops = _make_hub(installed_hub, root, project="ops", repo="ops-api")
    _write_feature(demo)
    _write_brain(demo)
    _write_skill(demo)
    _write_workflow(demo)
    _publish_hub(demo, origin)
    now = datetime.now(UTC)
    with httpx.Client(base_url=web.url, timeout=REQUEST_SECONDS) as client:
        for hub in (demo, ops):
            response = client.post(
                "/api/v1/hubs", json={"path": str(hub)}, headers={"Origin": web.url}
            )
            assert response.status_code == 201, response.text
        for envelope in _hooks(now):
            response = client.post("/api/v1/events/hooks", json=envelope)
            assert response.status_code == 202, response.text
    long_file = root / "long.jsonl"
    long_file.write_text(events_to_jsonl(_long_session(now)), encoding="utf-8")
    runs = root / "runs.jsonl"
    records = run_lines_failed_in_verify(run_id=FAILED_RUN)
    runs.write_text("".join(json.dumps(record) + "\n" for record in records), encoding="utf-8")
    hub_exe = str(installed_hub.executable)
    db = ["--db", str(web.db_path)]
    for command in (
        [hub_exe, "collect", str(long_file), *db],
        [hub_exe, "collect", "--runs", str(runs), "--project", "demo", *db],
    ):
        result = subprocess.run(
            command, cwd=root, env=web.env, capture_output=True, text=True, check=False
        )
        assert result.returncode == 0, result.stderr
    with httpx.Client(base_url=web.url, timeout=REQUEST_SECONDS) as client:
        runs_page = client.get("/api/v1/workflow-runs").json()["items"]
    [run_id] = [item["id"] for item in runs_page]
    return Scenario(
        live_session=LIVE_SESSION,
        stuck_session=STUCK_SESSION,
        long_session=LONG_SESSION,
        run_id=run_id,
        project="demo",
    )


def _playwright(
    web: RunningWeb,
    installed_hub: InstalledHub,
    root: Path,
    *,
    origin: HubOrigin,
    run: Callable[..., subprocess.CompletedProcess[str]],
    selection: tuple[str, str],
) -> subprocess.CompletedProcess[str]:
    """Ingests the scenario into ``web``, then runs the smoke.spec.ts tests ``selection`` picks
    (``("--grep", text)`` or ``("--grep-invert", text)``); skipped without npm or Chromium,
    failed under CI."""
    npm = shutil.which("npm")
    executable = chromium_executable()
    if npm is None or executable is None:
        reason = "the smoke needs npm and a Playwright Chromium"
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    scenario = ingest_scenario(web, installed_hub, root, origin=origin)
    env = {
        **os.environ,
        "AGENT_HUB_WEB_URL": web.url,
        "AGENT_HUB_CHROMIUM": executable,
        "SMOKE_LIVE_SESSION": scenario.live_session,
        "SMOKE_STUCK_SESSION": scenario.stuck_session,
        "SMOKE_LONG_SESSION": scenario.long_session,
        "SMOKE_RUN": scenario.run_id,
        "SMOKE_TOKEN": web.token,
    }
    return run(
        [
            npm,
            "--prefix",
            str(WEB_DIR),
            "exec",
            "--",
            "playwright",
            "test",
            "--config",
            str(WEB_DIR / "playwright.config.ts"),
            *selection,
        ],
        env=env,
        cwd=WEB_DIR,
        timeout=PLAYWRIGHT_SECONDS,
    )


def test_loads_pages_without_console_error_or_axe_violation_when_scenario_ingested(
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    hub_origin: HubOrigin,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = _playwright(
        hub_web,
        installed_hub,
        tmp_path,
        origin=hub_origin,
        run=run,
        selection=(
            "--grep-invert",
            f"{TICKETS_SPEC}|{SKILLS_SPEC}|{AGENT_SESSION_SPEC}|{WORKFLOWS_SPEC}",
        ),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    # Eight pages, the Live bookmark redirect (AC-234.2; it replaced the Live sessions page and
    # Live's red edge check, which the Sessions grid's covers), the long-session timing and six
    # control-plane clarity checks, none skipped.
    assert re.search(r"\b16 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout


def test_shows_plan_notice_when_feature_tickets_opened(
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    hub_origin: HubOrigin,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """AC-136.35 without a key (E4): Feature detail's Tickets tab shows the plan's tickets, the
    planning view and the not-connected notice; the CSP is unchanged, the browser requests no
    other host and logs no console error (smoke.spec.ts's ``watch``)."""
    result = _playwright(
        hub_web,
        installed_hub,
        tmp_path,
        origin=hub_origin,
        run=run,
        selection=("--grep", TICKETS_SPEC),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout
    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS) as client:
        page = client.get(f"/features/demo/{FEATURE}")
        tickets = client.get(f"/api/v1/features/demo/{FEATURE}/tickets")
    assert page.headers["content-security-policy"] == EXPECTED_CSP
    assert tickets.headers["content-security-policy"] == EXPECTED_CSP
    assert tickets.status_code == 200, tickets.text
    body = tickets.json()
    assert (body["source"], body["tracker_problem"]["type"]) == ("plan", NOT_CONNECTED_TYPE)
    assert NOT_CONNECTED_TEXT in body["notice"]
    assert [row["ref"] for row in body["tickets"]] == ["DEM-7", "T2"]
    assert body["planning"]["layers"] == [["DEM-7"], ["T2"]]


def test_shows_skills_catalog_and_detail_when_skills_opened(
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    hub_origin: HubOrigin,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    """AC-164.30: the Skills catalog of the demo hub and the ``/feature`` detail load with no
    console error and no request to another host (smoke.spec.ts's ``watch``), axe clean, and
    the pages and the skills routes keep the content security policy."""
    result = _playwright(
        hub_web,
        installed_hub,
        tmp_path,
        origin=hub_origin,
        run=run,
        selection=("--grep", SKILLS_SPEC),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout
    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS) as client:
        pages = [
            client.get("/projects/demo/skills"),
            client.get("/projects/demo/skills/skill/hub-workflow/feature"),
            client.get("/knowledge/skills"),
        ]
        catalog = client.get("/api/v1/projects/demo/skills")
        detail = client.get("/api/v1/projects/demo/skills/skill/hub-workflow/feature")
    for response in [*pages, catalog, detail]:
        assert response.status_code == 200, response.text
        assert response.headers["content-security-policy"] == EXPECTED_CSP
    ids = {item["id"] for item in catalog.json()["items"]}
    assert {"skill/hub-workflow/feature", "skill/demo/demo-check"} <= ids
    assert detail.json()["usage"]["count"] >= 1


def test_survives_reload_when_session_driven_agent_session(  # noqa: PLR0913 -- fixtures
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    hub_origin: HubOrigin,
    stub_claude: StubClaude,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    replies = {AGENT_PROMPT: permission_turn(), AGENT_FOLLOW_UP: simple_turn("The tests ran.")}
    stub_claude.play(StubScenario(replies=replies))

    result = _playwright(
        hub_web,
        installed_hub,
        tmp_path,
        origin=hub_origin,
        run=run,
        selection=("--grep", AGENT_SESSION_SPEC),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout
    cookie = {f"agent_hub_{hub_web.port}": hub_web.token}
    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS, cookies=cookie) as client:
        (session,) = client.get("/api/v1/agent-sessions").json()["items"]
        events = client.get(f"/api/v1/agent-sessions/{session['id']}/events").json()["items"]
        page = client.get(f"/agent-sessions/{session['id']}")
    assert (session["project"], session["status"]) == ("demo", "idle")
    kinds = [event["kind"] for event in events]
    assert kinds.index("permission.request") < kinds.index("permission.decision")
    messages = [event["body"]["text"] for event in events if event["kind"] == "user.message"]
    assert messages == [AGENT_PROMPT, AGENT_FOLLOW_UP]
    assert kinds.index("permission.decision") < kinds.index("user.message", 1)
    assert page.headers["content-security-policy"] == EXPECTED_CSP
    started = [record for record in stub_claude.records() if record.event == "start"]
    assert any("stream-json" in record.args for record in started)


def test_starts_approves_and_cancels_when_workflow_run_driven_from_web(
    hub_web: RunningWeb,
    *,
    installed_hub: InstalledHub,
    hub_origin: HubOrigin,
    tmp_path: Path,
    run: Callable[..., subprocess.CompletedProcess[str]],
) -> None:
    result = _playwright(
        hub_web,
        installed_hub,
        tmp_path,
        origin=hub_origin,
        run=run,
        selection=("--grep", WORKFLOWS_SPEC),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert re.search(r"\b1 passed\b", result.stdout), result.stdout
    assert "skipped" not in result.stdout, result.stdout
    with httpx.Client(base_url=hub_web.url, timeout=REQUEST_SECONDS) as client:
        listed = client.get("/api/v1/workflow-runs", params={"workflow": "smoke"})
        gates = client.get(
            "/api/v1/approvals",
            params={"project": "demo", "kind": "human_gate", "status": "all", "limit": 200},
        )
    listed.raise_for_status()
    gates.raise_for_status()
    approvals = gates.json()["items"]
    [smoke] = listed.json()["items"]
    assert smoke["status"] == "cancelled"
    # The resumed run reached its shell node before the cancel stopped it.
    assert "work" in {step["key"] for step in smoke["steps"]}
    [gate] = [item for item in approvals if item["session_id"] == f"run:{smoke['id']}"]
    assert (gate["gate_id"], gate["status"]) == (f"{smoke['id']}:sign-off:1", "approved")
