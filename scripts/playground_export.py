"""``make playground-export``: the playground's validated changes, as a delivery's input.

Exports the commits from the last export (tag ``playground-export/*``, else ``SINCE``, else the
merge base with ``origin/main``) to ``HEAD`` into ``.playground/exports/<UTC stamp>/``:
``export.json`` (the changes grouped by screen or package), ``brief.md`` (the owner's requests in
the playground's sessions, then each group's commits and files), ``reference.patch`` (the
validated code) and ``screens/`` (each touched screen rendered by the ``HEAD`` code on synthetic
data, the delivery's visual baseline). Then it tags ``HEAD``. The contract is
docs/design/playground-export.md. Exits 0 when exported (or nothing to export), 2 when the tree
is dirty, 1 on another failure.
"""

import argparse
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
EXPORTS = ROOT / ".playground" / "exports"
TAG_PREFIX = "playground-export/"
CONDUCTOR = "http://127.0.0.1:7420"
PROJECT = "agent-hub"
# The owner's requests sit just before the commits that answer them.
REQUEST_LEAD = timedelta(hours=1)
WAIT_SECONDS = 90


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


def group_commits(commits: Sequence[Commit]) -> list[Group]:
    """The commits by group, groups by name; a commit joins every group its files touch."""
    groups: dict[str, Group] = {}
    for commit in commits:
        for path in commit.files:
            group = groups.setdefault(area_of(path), Group(area_of(path)))
            if commit.sha not in group.commits:
                group.commits.append(commit.sha)
            if path not in group.files:
                group.files.append(path)
    for group in groups.values():
        group.screens = [f"{group.name}/{route.slug}" for route in routes_of(group.name)]
    return [groups[name] for name in sorted(groups)]


def git(*args: str) -> str:
    return subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def resolve_base(since: str | None) -> str:
    """``since``, else the newest export tag reachable from HEAD, else the merge base with main."""
    if since:
        return git("rev-parse", since).strip()
    tags = git("tag", "--merged", "HEAD", "--sort=-creatordate", "--list", f"{TAG_PREFIX}*").split()
    if tags:
        return git("rev-parse", tags[0]).strip()
    return git("merge-base", "HEAD", "origin/main").strip()


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


def conductor_token(log: Path) -> str | None:
    """The conductor's launch token, from the log make playground writes."""
    try:
        found = re.findall(r"\?token=([A-Za-z0-9_-]+)", log.read_text("utf-8", errors="replace"))
    except OSError:
        return None
    return found[-1] if found else None


def owner_requests(start: datetime, end: datetime, log: Path) -> list[dict[str, Any]]:
    """The playground sessions created in [start - lead, end]: their title and first prompt."""
    token = conductor_token(log)
    if token is None:
        return []
    try:
        with httpx.Client(base_url=CONDUCTOR, timeout=10) as client:
            client.get("/", params={"token": token})
            reply = client.get("/api/v1/agent-sessions", params={"project": PROJECT})
            reply.raise_for_status()
            items = reply.json().get("items", [])
    except httpx.HTTPError, ValueError:
        return []
    picked = []
    for item in items:
        created = datetime.fromisoformat(str(item.get("created_at", "")).replace("Z", "+00:00"))
        if start - REQUEST_LEAD <= created <= end:
            picked.append({"created_at": created.isoformat(), "title": item.get("title")})
    return sorted(picked, key=lambda item: item["created_at"])


def render_brief(
    base: str,
    head: str,
    *,
    groups: Sequence[Group],
    commits: Sequence[Commit],
    requests: Sequence[Mapping[str, Any]],
) -> str:
    by_sha = {commit.sha: commit for commit in commits}
    lines = [f"# Playground export {base[:8]}..{head[:8]}", "", "## The owner's requests", ""]
    lines += [f"- {item['created_at']}: {item['title']}" for item in requests] or ["- (none found)"]
    for group in groups:
        lines += ["", f"## {group.name}", "", "Commits:", ""]
        for sha in group.commits:
            commit = by_sha[sha]
            lines.append(f"- `{sha[:8]}` {commit.subject}")
            lines += [f"  {line}" for line in commit.body.splitlines() if line.strip()]
        lines += ["", "Files:", "", *[f"- `{path}`" for path in group.files]]
        if group.screens:
            lines += [
                "",
                "Screens:",
                "",
                *[f"- `screens/{screen}.png`" for screen in group.screens],
            ]
    return "\n".join(lines) + "\n"


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
        env = {
            **os.environ,
            "XDG_CONFIG_HOME": str(work / "config"),
            "AGENT_HUB_DB": str(work / "agent-hub.db"),
            "AGENT_HUB_CLAUDE_PROJECTS": str(work / "projects"),
        }
        built = subprocess.run(  # noqa: S603
            [
                npm,
                "--prefix",
                str(WEB_DIR),
                "run",
                "build",
                "--",
                "--outDir",
                str(work / "web"),
                "--emptyOutDir",
            ],
            cwd=ROOT,
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
            str(WEB_DIR),
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
            background(server, env=env, cwd=ROOT, log=work / "api.log"),
            background(preview, env=preview_env, cwd=WEB_DIR, log=work / "preview.log"),
        ):
            wait_until_up(f"{api_url}/api/v1/hubs")
            seeded = subprocess.run(  # noqa: S603
                [sys.executable, "-m", "scripts.seed_demo", "--url", api_url, "--via", "local"],
                cwd=ROOT,
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
                    str(WEB_DIR),
                    "exec",
                    "--",
                    "playwright",
                    "test",
                    "--config",
                    str(WEB_DIR / "playwright.config.ts"),
                    "e2e/capture.spec.ts",
                ],
                cwd=WEB_DIR,
                capture_output=True,
                text=True,
                check=False,
                env={
                    **env,
                    "AGENT_HUB_WEB_URL": web_url,
                    "AH_CAPTURE": json.dumps(routes),
                    "AH_CAPTURE_DIR": str(out),
                },
            )
        if captured.returncode != 0:
            return f"Playwright failed (is Chromium installed?): {captured.stdout.strip()[-400:]}"
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
        default=Path(tempfile.gettempdir()) / "agent-hub-conductor.log",
        help="the conductor's log, to read the owner's requests (make playground writes it)",
    )
    args = parser.parse_args(argv)

    if git("status", "--porcelain", "--untracked-files=no").strip():
        print(
            "the checkout has uncommitted changes: commit the playground's step first",
            file=sys.stderr,
        )
        return 2
    head = git("rev-parse", "HEAD").strip()
    try:
        base = resolve_base(args.since)
    except subprocess.CalledProcessError as error:
        print(f"cannot find where to start: {error.stderr.strip()}", file=sys.stderr)
        return 1
    commits = commits_between(base, head)
    if not commits:
        print("nothing to export")
        return 0

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = EXPORTS / stamp
    out.mkdir(parents=True)
    groups = group_commits(commits)
    requests = owner_requests(commits[0].date, commits[-1].date, args.conductor_log)
    (out / "reference.patch").write_text(git("diff", f"{base}..{head}"), "utf-8")
    (out / "brief.md").write_text(
        render_brief(base, head, groups=groups, commits=commits, requests=requests), "utf-8"
    )
    skipped = "--no-screens" if args.no_screens else capture_screens(groups, out / "screens")
    document = {
        "base": base,
        "head": head,
        "created_at": stamp,
        "groups": [asdict(group) for group in groups],
        "requests": list(requests),
        "screens_skipped": skipped,
    }
    (out / "export.json").write_text(json.dumps(document, indent=2) + "\n", "utf-8")
    git("tag", f"{TAG_PREFIX}{stamp}", head)
    print(f"exported {len(commits)} commit(s) in {len(groups)} group(s) to {out.relative_to(ROOT)}")
    if skipped:
        print(f"screens skipped: {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
