"""``make playground-export``: the playground's validated changes, as a delivery's input.

Exports the commits from the last export (tag ``playground-export/*``, else ``SINCE``, else the
merge base with ``origin/main``) to ``HEAD``, but those already on another pushed branch, into
``.playground/exports/<UTC stamp>/``: ``export.json`` (the changes grouped by screen or package,
each with the owner's requests that made it), ``brief.md`` (the requests in the owner's words,
then each group's commits, files and screens), ``reference.patch`` (the validated code),
``screens/`` (each touched screen rendered by the ``HEAD`` code on synthetic data, the delivery's
visual baseline) and ``hub/`` (what the sessions left in the project's hub). Then it tags
``HEAD``. Uncommitted changes are left out and listed. The contract is
docs/design/playground-export.md. Exits 0 when exported (or nothing to export), 1 on a failure.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT / "apps" / "web"
ROUTES_FILE = "apps/web/src/routes.tsx"
EXPORTS = ROOT / ".playground" / "exports"
TAG_PREFIX = "playground-export/"
CONDUCTOR = "http://127.0.0.1:7420"
PROJECT = "agent-hub"
# The owner's requests sit just before the commits that answer them.
REQUEST_LEAD = timedelta(hours=1)
WAIT_SECONDS = 90
EVENTS_PAGE = 500


@dataclass(frozen=True)
class Route:
    """A route to capture: the PNG's slug, the path, and the link prefix to follow from it."""

    slug: str
    path: str
    follow: str | None = None


# Each screen folder of apps/web/src/screens, to the routes.tsx routes showing it on the demo data.
SCREEN_ROUTES: Mapping[str, tuple[Route, ...]] = {
    "agent-session": (Route("sessions", "/sessions", follow="/agent-sessions/"),),
    "approvals": (Route("approvals", "/approvals"),),
    "brain": (Route("brain", "/knowledge/brain", follow="/projects/"),),
    "feature-detail": (Route("feature", "/features", follow="/features/"),),
    "features": (Route("features", "/features"),),
    "health": (Route("health", "/health"),),
    "knowledge-phase3": (Route("knowledge", "/knowledge/decisions"),),
    "learnings": (Route("learnings", "/knowledge/learnings"),),
    "live-sessions": (Route("live", "/live"),),
    "portfolio": (Route("portfolio", "/"),),
    "project-overview": (Route("project", "/projects/demo"),),
    "run-detail": (Route("run", "/runs", follow="/runs/"),),
    "runs-list": (Route("runs", "/runs"),),
    "session-detail": (Route("session", "/sessions", follow="/sessions/"),),
    "sessions-list": (Route("sessions", "/sessions"),),
    "settings": (Route("settings", "/settings/appearance"),),
    "skills": (Route("skills", "/projects/demo/skills"),),
    "welcome": (Route("welcome", "/welcome"),),
    "workflows": (Route("workflows", "/workflows"),),
}
# The shell (layout, shared components and lib) shows on every screen: a few representative ones.
SHELL_ROUTES = (
    Route("portfolio", "/"),
    Route("sessions", "/sessions"),
    Route("features", "/features"),
)
SCREEN = re.compile(r"apps/web/src/screens/([^/]+)/")
SHELL = ("apps/web/src/shell/", "apps/web/src/components/", "apps/web/src/lib/")
PACKAGE = re.compile(r"packages/([^/]+)/")
ROUTE_PATH = re.compile(r"""\bpath:\s*["']([^"']+)["']""")


@dataclass(frozen=True)
class Commit:
    sha: str
    subject: str
    body: str
    date: datetime
    files: tuple[str, ...]


@dataclass
class Group:
    name: str
    commits: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    screens: list[str] = field(default_factory=list)
    # Routes of the group that HEAD no longer has: nothing to capture, the delivery removes them.
    removed_screens: list[str] = field(default_factory=list)
    # The titles of the owner's requests whose sessions made the group's commits.
    requests: list[str] = field(default_factory=list)


def area_of(path: str) -> str:
    """The group a changed file belongs to (the contract's first matching area)."""
    if screen := SCREEN.match(path):
        return screen.group(1)
    if path.startswith(SHELL):
        return "shell"
    if package := PACKAGE.match(path):
        return package.group(1)
    return "repo"


def routes_of(group: str) -> tuple[Route, ...]:
    """The routes that show a group: its screen's, the shell's, or none for a package."""
    if group == "shell":
        return SHELL_ROUTES
    return SCREEN_ROUTES.get(group, ())


def route_patterns(routes_source: str) -> list[re.Pattern[str]]:
    """The paths routes.tsx declares, as patterns (``:param`` one segment, ``*`` the rest);
    the catch-all ``*`` is left out, since it matches a removed route too."""
    patterns = []
    for path in ROUTE_PATH.findall(routes_source):
        if path == "*":
            continue
        parts = [
            "[^/]+" if part.startswith(":") else ".*" if part == "*" else re.escape(part)
            for part in path.strip("/").split("/")
        ]
        patterns.append(re.compile("/".join(parts)))
    return patterns


def route_shown(route: Route, patterns: Sequence[re.Pattern[str]]) -> bool:
    """Whether HEAD still has the route: ``/`` (the index route) always does."""
    path = route.path.strip("/")
    return not path or any(pattern.fullmatch(path) for pattern in patterns)


def group_commits(
    commits: Sequence[Commit], patterns: Sequence[re.Pattern[str]] | None = None
) -> list[Group]:
    """The commits by group, groups by name; a commit joins every group its files touch.

    With ``patterns`` (HEAD's routes), a route HEAD no longer has goes to ``removed_screens``.
    """
    groups: dict[str, Group] = {}
    for commit in commits:
        for path in commit.files:
            group = groups.setdefault(area_of(path), Group(area_of(path)))
            if commit.sha not in group.commits:
                group.commits.append(commit.sha)
            if path not in group.files:
                group.files.append(path)
    for group in groups.values():
        for route in routes_of(group.name):
            if patterns is None or route_shown(route, patterns):
                group.screens.append(f"{group.name}/{route.slug}")
            else:
                group.removed_screens.append(route.path)
    return [groups[name] for name in sorted(groups)]


def git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout


def resolve_base(since: str | None) -> str:
    """``since``, else the newest export tag reachable from HEAD, else the merge base with main."""
    if since:
        return git("rev-parse", since).strip()
    tags = git("tag", "--merged", "HEAD", "--sort=-creatordate", "--list", f"{TAG_PREFIX}*").split()
    if tags:
        return git("rev-parse", tags[0]).strip()
    return git("merge-base", "HEAD", "origin/main").strip()


def delivering_branches(remote_refs: Sequence[str], current: str) -> list[str]:
    """The pushed branches but this checkout's own: a commit on one is that branch's delivery."""
    return [
        ref
        for ref in remote_refs
        if "/" in ref and not ref.endswith("/HEAD") and ref.split("/", 1)[1] != current
    ]


def commits_between(base: str, head: str) -> list[Commit]:
    """The range's commits, oldest first, with their files (merges left out)."""
    raw = git(
        "log", "--reverse", "--no-merges", "--format=%H%x1f%s%x1f%cI%x1f%b%x1e", f"{base}..{head}"
    )
    commits = []
    for entry in filter(None, (part.strip("\n") for part in raw.split("\x1e"))):
        sha, subject, date, body = entry.split("\x1f", 3)
        files = git("show", "--name-only", "--format=", sha).split()
        commits.append(
            Commit(sha, subject, body.strip(), datetime.fromisoformat(date), tuple(files))
        )
    return commits


def conductor_log(environ: Mapping[str, str]) -> Path:
    """Where ``make playground`` writes the conductor's log: its private folder under the temp dir
    (scripts/playground.sh, ``${TMPDIR:-/tmp}/agent-hub-playground-<uid>``)."""
    temp = Path(environ.get("TMPDIR") or "/tmp")  # noqa: S108 -- the folder playground.sh uses
    return temp / f"agent-hub-playground-{os.getuid()}" / "agent-hub-conductor.log"


def delivered_elsewhere(commits: Sequence[Commit], branches: Sequence[str]) -> list[dict[str, str]]:
    """The commits a pushed branch already has, each with that branch: its delivery, not this
    export's."""
    if not branches:
        return []
    head = git("rev-parse", "HEAD").strip()
    own = set(git("rev-list", head, "--not", *branches).split())
    left = []
    for commit in commits:
        if commit.sha in own:
            continue
        holders = git("branch", "-r", "--contains", commit.sha, "--format=%(refname:short)")
        branch = next((ref for ref in branches if ref in holders.split()), "")
        left.append({"sha": commit.sha, "subject": commit.subject, "branch": branch})
    return left


def conductor_token(log: Path) -> str | None:
    """The conductor's launch token, from the log make playground writes."""
    try:
        found = re.findall(r"\?token=([A-Za-z0-9_-]+)", log.read_text("utf-8", errors="replace"))
    except OSError:
        return None
    return found[-1] if found else None


def link_session(
    events: Sequence[Mapping[str, Any]], commits: Sequence[Commit]
) -> tuple[str, list[str]]:
    """A session's first prompt, and the commits of ``commits`` its own ``git commit`` calls made.

    A commit is the session's when its subject ends a line of the command that committed it
    (``-m "<subject>…"``, a heredoc): the session's log says what it did, so sessions running at
    the same time are told apart, which their times cannot do.
    """
    prompt = next(
        (
            str(event["body"].get("text", ""))
            for event in events
            if event.get("kind") == "user.message"
        ),
        "",
    )
    commands = [
        str(event["body"].get("input", {}).get("command", ""))
        for event in events
        if event.get("kind") == "tool.call" and event["body"].get("name") == "Bash"
    ]
    committing = [command for command in commands if re.search(r"\bgit\b.*\bcommit\b", command)]
    linked = [
        commit.sha
        for commit in commits
        if any(
            re.search(re.escape(commit.subject) + r"""(?=["'\n\\]|$)""", command)
            for command in committing
        )
    ]
    return prompt, linked


def _session_events(client: httpx.Client, session_id: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    after: int | None = 0
    while after is not None:
        page = client.get(
            f"/api/v1/agent-sessions/{session_id}/events",
            params={"after": after, "limit": EVENTS_PAGE},
        )
        page.raise_for_status()
        body = page.json()
        events += body.get("items", [])
        after = body.get("next_after")
    return events


def owner_requests(
    start: datetime, end: datetime, *, commits: Sequence[Commit], log: Path
) -> list[dict[str, Any]]:
    """The playground sessions active in [start - lead, end]: their title, first prompt, folder
    and the commits they made."""
    token = conductor_token(log)
    if token is None:
        return []
    picked = []
    try:
        with httpx.Client(base_url=CONDUCTOR, timeout=30) as client:
            client.get("/", params={"token": token})
            reply = client.get("/api/v1/agent-sessions", params={"project": PROJECT})
            reply.raise_for_status()
            for item in reply.json().get("items", []):
                created = _instant(item.get("created_at"))
                updated = _instant(item.get("updated_at")) or created
                if created is None or updated is None:
                    continue
                if created > end or updated < start - REQUEST_LEAD:
                    continue
                prompt, linked = link_session(_session_events(client, str(item["id"])), commits)
                if created < start - REQUEST_LEAD and not linked:
                    continue
                picked.append(
                    {
                        "created_at": created.isoformat(),
                        "title": item.get("title"),
                        "folder": item.get("workdir_label"),
                        "prompt": prompt,
                        "commits": linked,
                    }
                )
    except httpx.HTTPError, ValueError, KeyError:
        return []
    return sorted(picked, key=lambda request: request["created_at"])


def _instant(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def attach_requests(groups: Sequence[Group], requests: Sequence[Mapping[str, Any]]) -> None:
    """Each group takes the titles of the requests whose commits are in it."""
    for group in groups:
        group.requests = [
            str(request["title"])
            for request in requests
            if set(request.get("commits", ())) & set(group.commits)
        ]


def hub_changes(hub: Path, since: datetime) -> list[str]:
    """What the sessions left in the project's hub: the files its git sees as new or changed
    that ``hub sync`` did not write as they are (``hub.lock``), and those of its commits since
    ``since``."""
    if not (hub / "hub.json").is_file():
        return []
    lock_file = hub / "hub.lock"
    lock = json.loads(lock_file.read_text("utf-8")).get("files", {}) if lock_file.is_file() else {}

    def synced(path: str) -> bool:
        entry = lock.get(path)
        if entry is None:
            return False
        digest = entry.get("sha256")
        if digest is None:
            return True
        return bool(hashlib.sha256((hub / path).read_bytes()).hexdigest() == digest)

    loose = git("ls-files", "-z", "--others", "--modified", "--exclude-standard", cwd=hub)
    changed = {path for path in loose.split("\0") if path and path != "hub.lock"}
    try:
        committed = git("log", f"--since={since.isoformat()}", "--name-only", "--format=", cwd=hub)
    except subprocess.CalledProcessError:
        committed = ""  # a hub without a commit yet
    # A deleted file (git lists it as modified) has nothing to copy, nor to compare with the lock.
    present = {path for path in changed | set(committed.split()) if (hub / path).is_file()}
    return sorted(path for path in present if path not in changed or not synced(path))


def render_brief(
    base: str,
    head: str,
    *,
    groups: Sequence[Group],
    commits: Sequence[Commit],
    requests: Sequence[Mapping[str, Any]],
    left_out: Sequence[Mapping[str, str]] = (),
    in_progress: Sequence[str] = (),
    hub: str | None = None,
    hub_files: Sequence[str] = (),
) -> str:
    by_sha = {commit.sha: commit for commit in commits}
    lines = [f"# Playground export {base[:8]}..{head[:8]}", "", "## The owner's requests", ""]
    lines += _request_lines(requests, delivered={item["sha"] for item in left_out})
    for group in groups:
        lines += _group_lines(group, by_sha)
    if hub_files:
        lines += ["", f"## hub: {hub}", "", "Not in this checkout's git; copied under `hub/`:", ""]
        lines += [f"- `{path}`" for path in hub_files]
    if left_out:
        lines += ["", "## Delivered elsewhere (left out)", ""]
        lines += [
            f"- `{item['sha'][:8]}` {item['subject']}"
            + (f" ({item['branch']})" if item["branch"] else "")
            for item in left_out
        ]
    if in_progress:
        lines += ["", "## In progress (uncommitted, not exported)", ""]
        lines += [f"- `{path}`" for path in in_progress]
    return "\n".join(lines) + "\n"


def _request_lines(requests: Sequence[Mapping[str, Any]], *, delivered: set[str]) -> list[str]:
    """Each request: when, its title, its folder and commits (those another branch delivers
    marked), then the owner's first prompt."""
    lines = []
    for request in requests:
        where = f" (in {request['folder']})" if request.get("folder") else ""
        made = " ".join(
            f"`{sha[:8]}`" + (" (delivered elsewhere)" if sha in delivered else "")
            for sha in request.get("commits", ())
        )
        made = made or "no commit"
        lines.append(f"- {request['created_at']}: {request['title']}{where}: {made}")
        lines += [f"  > {line}" for line in str(request.get("prompt", "")).splitlines() if line]
    return lines or ["- (none found)"]


def _group_lines(group: Group, by_sha: Mapping[str, Commit]) -> list[str]:
    lines = ["", f"## {group.name}", ""]
    if group.requests:
        lines += ["Requests:", "", *[f"- {title}" for title in group.requests], ""]
    lines += ["Commits:", ""]
    for sha in group.commits:
        commit = by_sha[sha]
        lines.append(f"- `{sha[:8]}` {commit.subject}")
        lines += [f"  {line}" for line in commit.body.splitlines() if line.strip()]
    lines += ["", "Files:", "", *[f"- `{path}`" for path in group.files]]
    if group.screens:
        lines += ["", "Screens:", "", *[f"- `screens/{shot}.png`" for shot in group.screens]]
    if group.removed_screens:
        lines += ["", "Removed screens (HEAD has no such route):", ""]
        lines += [f"- `{path}`" for path in group.removed_screens]
    return lines


def chromium_executable(environ: Mapping[str, str]) -> str | None:
    """A Chromium headless shell when Playwright's own revision is missing: the newest found.

    The same rule as the web smoke (tests/e2e/test_web_smoke.py), also looking in macOS's cache;
    nothing is downloaded. None when Playwright's revision is there, or no shell is.
    """
    configured = environ.get("PLAYWRIGHT_BROWSERS_PATH")
    home = Path.home()
    roots = (
        [Path(configured)]
        if configured
        else [home / "Library" / "Caches" / "ms-playwright", home / ".cache" / "ms-playwright"]
    )
    modules = WEB_DIR / "node_modules"
    nested = modules / "playwright" / "node_modules" / "playwright-core" / "browsers.json"
    browsers = nested if nested.is_file() else modules / "playwright-core" / "browsers.json"
    if browsers.is_file():
        listed = json.loads(browsers.read_text("utf-8"))["browsers"]
        revision = next(b["revision"] for b in listed if b["name"] == "chromium-headless-shell")
        if any(_headless_shells(root, revision) for root in roots):
            return None
    found = sorted(shell for root in roots for shell in _headless_shells(root, "*"))
    return str(found[-1]) if found else None


def _headless_shells(root: Path, revision: str) -> list[Path]:
    folder = f"chromium_headless_shell-{revision}"
    return [
        *root.glob(f"{folder}/chrome-*/headless_shell"),
        *root.glob(f"{folder}/chrome-headless-shell-*/chrome-headless-shell"),
    ]


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


def wait_until_up(url: str) -> None:
    deadline = time.monotonic() + WAIT_SECONDS
    while time.monotonic() < deadline:
        try:
            if httpx.get(url, timeout=2).status_code < 500:
                return
        except httpx.HTTPError:
            pass
        time.sleep(1)
    raise TimeoutError(f"no answer from {url}")


@contextmanager
def background(
    command: Sequence[str], *, env: Mapping[str, str], cwd: Path, log: Path
) -> Iterator[None]:
    with log.open("w") as output:
        child = subprocess.Popen(
            command, cwd=cwd, env=dict(env), stdout=output, stderr=subprocess.STDOUT
        )  # noqa: S603
        try:
            yield
        finally:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()


@contextmanager
def head_checkout(scratch: Path) -> Iterator[Path]:
    """HEAD in a temporary worktree, as make playground copies it for the conductor: the capture
    renders the exported code, not the edits a session has in progress. It shares the
    checkout's node_modules."""
    tree = scratch / "head"
    git("worktree", "add", "--detach", str(tree), "HEAD")
    try:
        (tree / "apps" / "web" / "node_modules").symlink_to(WEB_DIR / "node_modules")
        yield tree
    finally:
        git("worktree", "remove", "--force", str(tree))


def capture_screens(groups: Sequence[Group], out: Path) -> str | None:
    """Renders each group's routes from HEAD on synthetic data into ``out``.

    Returns why it could not, else None.
    """
    routes = [
        {
            "file": f"{group.name}/{route.slug}",
            "path": route.path,
            **({"follow": route.follow} if route.follow else {}),
        }
        for group in groups
        for route in routes_of(group.name)
        if f"{group.name}/{route.slug}" in group.screens
    ]
    npm = shutil.which("npm")
    if not routes:
        return "no screen in this export"
    if npm is None:
        return "npm is not on PATH"
    with tempfile.TemporaryDirectory(prefix="playground-export-") as scratch:
        work = Path(scratch)
        (work / "config").mkdir()
        (work / "projects").mkdir()
        with head_checkout(work) as tree:
            web_dir = tree / "apps" / "web"
            # HEAD's packages ahead of the editable installs, which point at the checkout.
            sources = [str(path) for path in sorted((tree / "packages").glob("*/src"))]
            env = {
                **os.environ,
                "XDG_CONFIG_HOME": str(work / "config"),
                "AGENT_HUB_DB": str(work / "agent-hub.db"),
                "AGENT_HUB_CLAUDE_PROJECTS": str(work / "projects"),
                "PYTHONPATH": os.pathsep.join([*sources, str(tree)]),
            }
            built = subprocess.run(  # noqa: S603
                [
                    npm,
                    "--prefix",
                    str(web_dir),
                    "run",
                    "build",
                    "--",
                    "--outDir",
                    str(work / "web"),
                    "--emptyOutDir",
                ],
                cwd=tree,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            if built.returncode != 0:
                return f"the web app did not build: {built.stderr.strip()[-300:]}"
            api, web = free_port(), free_port()
            api_url, web_url = f"http://127.0.0.1:{api}", f"http://127.0.0.1:{web}"
            server = [sys.executable, "-m", "agent_hub.cli", "web", "--port", str(api)]
            preview = [
                npm,
                "--prefix",
                str(web_dir),
                "exec",
                "--",
                "vite",
                "preview",
                "--outDir",
                str(work / "web"),
                "--port",
                str(web),
                "--strictPort",
            ]
            preview_env = {**env, "AH_API_TARGET": api_url, "AH_SESSIONS_TARGET": api_url}
            with (
                background(server, env=env, cwd=tree, log=work / "api.log"),
                background(preview, env=preview_env, cwd=web_dir, log=work / "preview.log"),
            ):
                wait_until_up(f"{api_url}/api/v1/hubs")
                seeded = subprocess.run(  # noqa: S603
                    [sys.executable, "-m", "scripts.seed_demo", "--url", api_url, "--via", "local"],
                    cwd=tree,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if seeded.returncode != 0:
                    return f"the demo data did not load: {seeded.stdout.strip()[-300:]}"
                wait_until_up(web_url)
                captured = subprocess.run(  # noqa: S603
                    [
                        npm,
                        "--prefix",
                        str(web_dir),
                        "exec",
                        "--",
                        "playwright",
                        "test",
                        "--config",
                        str(web_dir / "playwright.config.ts"),
                        "e2e/capture.spec.ts",
                    ],
                    cwd=web_dir,
                    capture_output=True,
                    text=True,
                    check=False,
                    env={
                        **env,
                        "AGENT_HUB_WEB_URL": web_url,
                        "AH_CAPTURE": json.dumps(routes),
                        "AH_CAPTURE_DIR": str(out),
                        **(
                            {"AGENT_HUB_CHROMIUM": shell}
                            if (shell := chromium_executable(env))
                            else {}
                        ),
                    },
                )
        # The capture's own output, and the servers' when it failed, next to the screens.
        out.parent.joinpath("capture.log").write_text(captured.stdout + captured.stderr, "utf-8")
        if captured.returncode != 0:
            for name in ("api.log", "preview.log"):
                shutil.copy(work / name, out.parent / f"capture-{name}")
            return "Playwright failed on some screens: see capture.log"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.playground_export", description=__doc__
    )
    parser.add_argument(
        "--since", default=None, help="the commit to export from (default: the last export)"
    )
    parser.add_argument("--no-screens", action="store_true", help="skip the screen capture")
    parser.add_argument(
        "--conductor-log",
        type=Path,
        default=conductor_log(os.environ),
        help="the conductor's log, to read the owner's requests (make playground writes it)",
    )
    # make playground's hub, next to the main checkout (a worktree's common dir is the main one).
    main_checkout = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    parser.add_argument(
        "--hub",
        type=Path,
        default=main_checkout.parent.parent / "agent-hub-hub",
        help="the project's hub, where Studio sessions write skills, agents and hooks",
    )
    args = parser.parse_args(argv)

    head = git("rev-parse", "HEAD").strip()
    try:
        base = resolve_base(args.since)
    except subprocess.CalledProcessError as error:
        print(f"cannot find where to start: {error.stderr.strip()}", file=sys.stderr)
        return 1
    current = git("branch", "--show-current").strip()
    remote_refs = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/").split()
    branches = delivering_branches(remote_refs, current)
    everything = commits_between(base, head)
    left_out = delivered_elsewhere(everything, branches)
    delivered = {item["sha"] for item in left_out}
    commits = [commit for commit in everything if commit.sha not in delivered]
    if not commits:
        print("nothing to export")
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = EXPORTS / stamp
    out.mkdir(parents=True)
    groups = group_commits(commits, route_patterns(git("show", f"{head}:{ROUTES_FILE}")))
    requests = owner_requests(
        everything[0].date, everything[-1].date, commits=everything, log=args.conductor_log
    )
    attach_requests(groups, requests)
    in_progress = [line[3:] for line in git("status", "--porcelain").splitlines()]
    hub_files = hub_changes(args.hub, commits[0].date - REQUEST_LEAD)
    for path in hub_files:
        target = out / "hub" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(args.hub / path, target)
    (out / "reference.patch").write_text(git("diff", f"{base}..{head}"), "utf-8")
    (out / "brief.md").write_text(
        render_brief(
            base,
            head,
            groups=groups,
            commits=commits,
            requests=requests,
            left_out=left_out,
            in_progress=in_progress,
            hub=args.hub.name,
            hub_files=hub_files,
        ),
        "utf-8",
    )
    skipped = "--no-screens" if args.no_screens else capture_screens(groups, out / "screens")
    document = {
        "base": base,
        "head": head,
        "created_at": stamp,
        "groups": [asdict(group) for group in groups],
        "requests": list(requests),
        "hub": {"path": str(args.hub), "files": hub_files},
        "left_out": left_out,
        "in_progress": in_progress,
        "screens_skipped": skipped,
    }
    (out / "export.json").write_text(json.dumps(document, indent=2) + "\n", "utf-8")
    git("tag", f"{TAG_PREFIX}{stamp}", head)
    print(f"exported {len(commits)} commit(s) in {len(groups)} group(s) to {out.relative_to(ROOT)}")
    if left_out:
        print(f"left out {len(left_out)} commit(s) another pushed branch delivers")
    if hub_files:
        print(f"copied {len(hub_files)} file(s) from the hub {args.hub.name}")
    if in_progress:
        print(f"left out {len(in_progress)} uncommitted file(s): commit them for the next export")
    if skipped:
        print(f"screens skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
