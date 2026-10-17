"""``make playground-export``: the playground's validated changes, as a delivery's input.

Exports what the owner asked and validated in the playground since the last export (tag
``playground-export/*``, else ``SINCE``, else the merge base with ``origin/main``), one request
per playground conversation, into ``.playground/exports/<UTC stamp>/``: ``brief.md`` (each
request's turns in the owner's words and answers, with the commits each turn made, its files,
screens and hub files), ``export.json`` (the same, as data), ``requests/<n>-<slug>.patch`` (each
request's commits, generated files left out), ``reference.patch`` (every exported commit),
``in-progress.patch`` (what is not committed yet), ``screens/`` (each touched screen rendered by
the ``HEAD`` code on synthetic data, the delivery's visual baseline) and ``hub/`` (what the
sessions left in the project's hub). A commit ``origin/main`` already has is left out; one another
pushed branch has stays, marked. It commits the checkout as it is, uncommitted files included, on
the developer's local branch ``<prefix>/playground-snapshot/<stamp>``, to go back to; then it tags
``HEAD``, only when nothing was missed. The contract
is docs/design/playground-export.md. Exits 0 when exported (or nothing to export), 1 on a failure:
the owner's requests unreadable is one.
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
MAIN = "origin/main"
CONDUCTOR = "http://127.0.0.1:7420"
CONDUCTOR_LOG = "agent-hub-conductor.log"
PROJECT = "agent-hub"
# Each export's snapshot: the checkout as it was, on a branch of the developer's (prefix/...).
SNAPSHOT_PREFIX = "playground-snapshot/"
# The owner's requests sit just before the commits that answer them.
REQUEST_LEAD = timedelta(hours=1)
# Listing the sessions reads every one's state: slow on a busy conductor.
CONDUCTOR_TIMEOUT = 120
WAIT_SECONDS = 90
EVENTS_PAGE = 500
# Generated files (.gitattributes) stay out of the patches: a delivery regenerates them.
SOURCES_ONLY = (".", ":(exclude,attr:linguist-generated)")
# Personal files by Claude Code's convention (CLAUDE.local.md, settings.local.json), never work.
LOCAL_FILE = re.compile(r"(^|/)[^/]*\.local\.[^/]+$")
NO_SESSION = "Not made by a playground session"
UNTITLED = "Untitled session"
# The Studio's publish reply: one line per file written in the hub (apps/web/.../skills/draft.ts).
PUBLISHED = re.compile(r"^PUBLISHED\s+(\S+)", re.MULTILINE)
WRITING_TOOLS = ("Write", "Edit", "MultiEdit", "NotebookEdit")


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
    "knowledge-index": (Route("skills", "/knowledge/skills"), Route("brain", "/knowledge/brain")),
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
class Turn:
    """One message of the owner, what they answered while Claude worked on it, and the commits
    that work made."""

    at: str
    message: str
    screenshot: bool = False
    answers: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)


@dataclass
class Session:
    """A playground conversation as the conductor logged it."""

    id: str
    title: str
    folder: str | None
    created_at: datetime
    turns: list[Turn]
    # The paths its Write and Edit calls wrote, absolute or as given.
    written: list[str] = field(default_factory=list)
    # The hub paths a Studio publish reply listed.
    published: list[str] = field(default_factory=list)


@dataclass
class Request:
    """What the owner asked in one conversation (sessions of the same title and folder are one),
    and everything it made: the delivery's unit."""

    title: str
    folder: str | None = None
    started_at: str = ""
    sessions: list[str] = field(default_factory=list)
    turns: list[Turn] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    files: list[str] = field(default_factory=list)
    screens: list[str] = field(default_factory=list)
    # Routes it touches that HEAD no longer has: nothing to capture, the delivery removes them.
    removed_screens: list[str] = field(default_factory=list)
    hub_files: list[str] = field(default_factory=list)
    in_progress: list[str] = field(default_factory=list)
    # Its commits another pushed branch also has (that branch's PR delivers them too).
    also_on: dict[str, str] = field(default_factory=dict)
    patch: str | None = None


class RequestsUnavailableError(Exception):
    """The conductor could not say what the owner asked: exporting without it would lose it."""


def area_of(path: str) -> str:
    """The area a changed file belongs to (the contract's first matching one)."""
    if screen := SCREEN.match(path):
        return screen.group(1)
    if path.startswith(SHELL):
        return "shell"
    if package := PACKAGE.match(path):
        return package.group(1)
    return "repo"


def routes_of(area: str) -> tuple[Route, ...]:
    """The routes that show an area: its screen's, the shell's, or none for a package."""
    if area == "shell":
        return SHELL_ROUTES
    return SCREEN_ROUTES.get(area, ())


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


def screens_of(
    files: Sequence[str], patterns: Sequence[re.Pattern[str]] | None = None
) -> tuple[list[str], list[str]]:
    """The screens (``<area>/<route slug>``) the files show, and the routes among them HEAD no
    longer has (with ``patterns``, HEAD's routes)."""
    screens: list[str] = []
    removed: list[str] = []
    for area in sorted({area_of(path) for path in files}):
        for route in routes_of(area):
            if patterns is None or route_shown(route, patterns):
                screens.append(f"{area}/{route.slug}")
            elif route.path not in removed:
                removed.append(route.path)
    return screens, removed


def git(*args: str, cwd: Path = ROOT, env: Mapping[str, str] | None = None) -> str:
    return subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        ["git", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env=dict(env) if env is not None else None,
    ).stdout


def snapshot_branch(current: str, email: str, stamp: str) -> str:
    """The developer's own branch for a snapshot: the current branch's prefix (``roquettejh/``),
    else their email's local part."""
    prefix = current.split("/", 1)[0] if "/" in current else email.split("@", 1)[0]
    return f"{prefix + '/' if prefix else ''}{SNAPSHOT_PREFIX}{stamp}"


def snapshot(
    branch: str, *, message: str, in_progress: Sequence[str] = (), cwd: Path = ROOT
) -> str:
    """Commits the checkout as it is (HEAD and its uncommitted files) on ``branch``, with HEAD's
    author, without touching the checkout's files, index or branch. Returns the commit. The
    hub's files stay out: project material never goes into the platform's repo."""
    name, email = git("log", "-1", "--format=%an%x1f%ae", cwd=cwd).strip().split("\x1f")
    with tempfile.TemporaryDirectory(prefix="playground-snapshot-") as scratch:
        env = {
            **os.environ,
            "GIT_INDEX_FILE": str(Path(scratch) / "index"),
            "GIT_AUTHOR_NAME": name,
            "GIT_AUTHOR_EMAIL": email,
            "GIT_COMMITTER_NAME": name,
            "GIT_COMMITTER_EMAIL": email,
        }
        git("read-tree", "HEAD", cwd=cwd, env=env)
        if in_progress:
            git("add", "-A", "--", *in_progress, cwd=cwd, env=env)
        tree = git("write-tree", cwd=cwd, env=env).strip()
        commit = git("commit-tree", tree, "-p", "HEAD", "-m", message, cwd=cwd, env=env).strip()
    git("branch", branch, commit, cwd=cwd)
    return commit


def resolve_base(since: str | None) -> str:
    """``since``, else the newest export tag reachable from HEAD, else the merge base with main."""
    if since:
        return git("rev-parse", since).strip()
    tags = git("tag", "--merged", "HEAD", "--sort=-creatordate", "--list", f"{TAG_PREFIX}*").split()
    if tags:
        return git("rev-parse", tags[0]).strip()
    return git("merge-base", "HEAD", MAIN).strip()


def delivering_branches(remote_refs: Sequence[str], current: str) -> list[str]:
    """The pushed branches but main and this checkout's own: a PR that may deliver a commit."""
    return [
        ref
        for ref in remote_refs
        if "/" in ref
        and not ref.endswith("/HEAD")
        and ref != MAIN
        and ref.split("/", 1)[1] != current
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


def equivalent_on(branch: str, base: str, head: str, *, cwd: Path = ROOT) -> set[str]:
    """The range's commits ``branch`` has, by sha or as the same change (a cherry-pick)."""
    in_range = set(git("rev-list", f"{base}..{head}", cwd=cwd).split())
    not_on = set(git("rev-list", f"{base}..{head}", "--not", branch, cwd=cwd).split())
    # git cherry lists only the commits branch lacks by sha, "-" when it has the same change.
    marks = git("cherry", branch, head, base, cwd=cwd).split("\n")
    return (in_range - not_on) | {line[2:] for line in marks if line.startswith("- ")}


def repeated_changes(base: str, head: str, *, cwd: Path = ROOT) -> dict[str, str]:
    """The range's commits that repeat an earlier one's change (a cherry-pick merged back),
    each to the first: applying both would apply the change twice."""
    log = git("log", "-p", "--reverse", "--no-merges", f"{base}..{head}", cwd=cwd)
    ids = subprocess.run(  # noqa: S603 -- a fixed argv, no shell
        ["git", "patch-id", "--stable"],
        cwd=cwd,
        input=log,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    first: dict[str, str] = {}
    repeated: dict[str, str] = {}
    for line in ids.splitlines():
        patch_id, sha = line.split()
        if patch_id in first:
            repeated[sha] = first[patch_id]
        else:
            first[patch_id] = sha
    return repeated


def conductor_logs(given: Path | None, environ: Mapping[str, str]) -> list[Path]:
    """Where make playground writes the conductor's log: ``given``, else ``$TMPDIR``, else the
    user's own temp folder on macOS (a sandbox may move ``$TMPDIR``)."""
    if given is not None:
        return [given]
    folders = [Path(environ.get("TMPDIR") or tempfile.gettempdir())]
    if sys.platform == "darwin":
        found = subprocess.run(
            ["getconf", "DARWIN_USER_TEMP_DIR"], capture_output=True, text=True, check=False
        ).stdout.strip()
        if found:
            folders.append(Path(found))
    return [folder / CONDUCTOR_LOG for folder in dict.fromkeys(folders)]


def conductor_token(log: Path) -> str | None:
    """The conductor's launch token, from the log make playground writes."""
    try:
        found = re.findall(r"\?token=([A-Za-z0-9_-]+)", log.read_text("utf-8", errors="replace"))
    except OSError:
        return None
    return found[-1] if found else None


def read_session(
    events: Sequence[Mapping[str, Any]], commits: Sequence[Commit]
) -> tuple[list[Turn], list[str], list[str]]:
    """A session's turns, the paths it wrote and the hub paths it published.

    A turn opens on each owner message and takes the answers they gave and the commits of
    ``commits`` made until the next one. A commit is the session's when its subject ends a line
    of the command that committed it (``-m "<subject>…"``, a heredoc): the session's log says
    what it did, so sessions running at the same time are told apart, which their times cannot.
    """
    turns: list[Turn] = []
    written: list[str] = []
    published: list[str] = []
    for event in events:
        kind, body = event.get("kind"), event.get("body") or {}
        if kind == "user.message":
            attachments = body.get("attachments") or ()
            turns.append(
                Turn(
                    at=str(event.get("at", "")),
                    message=str(body.get("text", "")),
                    screenshot=any(item.get("kind") == "screenshot" for item in attachments),
                )
            )
        elif kind == "permission.decision" and body.get("answers") and turns:
            turns[-1].answers += [
                f"{question} → {answer}" for question, answer in body["answers"].items()
            ]
        elif kind == "tool.call":
            tool, given = body.get("name"), body.get("input") or {}
            if tool in WRITING_TOOLS and given.get("file_path"):
                written.append(str(given["file_path"]))
            command = str(given.get("command", "")) if tool == "Bash" else ""
            if turns and re.search(r"\bgit\b.*\bcommit\b", command):
                turns[-1].commits += [
                    commit.sha
                    for commit in commits
                    if commit.sha not in turns[-1].commits
                    and re.search(re.escape(commit.subject) + r"""(?=["'\n\\]|$)""", command)
                ]
        elif kind == "text":
            published += PUBLISHED.findall(str(body.get("text", "")))
    return turns, written, published


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


def owner_sessions(
    start: datetime, *, commits: Sequence[Commit], logs: Sequence[Path]
) -> list[Session]:
    """The playground sessions active since ``start - lead``, or that made one of ``commits``.

    Raises RequestsUnavailableError when the conductor cannot be read.
    """
    token = next((found for log in logs if (found := conductor_token(log))), None)
    if token is None:
        tried = ", ".join(str(log) for log in logs)
        raise RequestsUnavailableError(
            f"no conductor token in {tried}: start the playground (make playground), or pass "
            "--conductor-log"
        )
    sessions = []
    try:
        with httpx.Client(base_url=CONDUCTOR, timeout=CONDUCTOR_TIMEOUT) as client:
            client.get("/", params={"token": token})
            reply = client.get("/api/v1/agent-sessions", params={"project": PROJECT})
            reply.raise_for_status()
            for item in reply.json().get("items", []):
                created = _instant(item.get("created_at"))
                updated = _instant(item.get("updated_at")) or created
                if created is None or updated is None or updated < start - REQUEST_LEAD:
                    continue
                turns, written, published = read_session(
                    _session_events(client, str(item["id"])), commits
                )
                if created < start - REQUEST_LEAD and not any(turn.commits for turn in turns):
                    continue
                sessions.append(
                    Session(
                        id=str(item["id"]),
                        title=str(item.get("title") or ""),
                        folder=item.get("workdir_label"),
                        created_at=created,
                        turns=turns,
                        written=written,
                        published=published,
                    )
                )
    except (httpx.HTTPError, ValueError, KeyError) as error:
        raise RequestsUnavailableError(f"the conductor at {CONDUCTOR} failed: {error!r}") from error
    return sorted(sessions, key=lambda session: session.created_at)


def _instant(value: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _wrote(session: Session, path: str, roots: Sequence[Path]) -> bool:
    """Whether the session wrote ``path`` (relative to one of ``roots``) or published it."""
    if path in session.published:
        return True
    targets = {str(root / path) for root in roots}
    return any(written in targets or written == path for written in session.written)


def build_requests(
    sessions: Sequence[Session],
    commits: Sequence[Commit],
    *,
    patterns: Sequence[re.Pattern[str]] | None = None,
    also_on: Mapping[str, str] | None = None,
    hub_files: Sequence[str] = (),
    hub_root: Path | None = None,
    in_progress: Sequence[str] = (),
    checkout: Path = ROOT,
    same_as: Mapping[str, str] | None = None,
) -> list[Request]:
    """One request per conversation (sessions sharing a title and folder are one), in the order
    the owner asked them, each with what it made: commits, files, screens, hub files and
    uncommitted files. What no session made is a last request, ``NO_SESSION``, so nothing of
    the range is dropped. A turn's commit that repeats an earlier change (``same_as``) counts as
    that earlier commit."""
    by_sha = {commit.sha: commit for commit in commits}
    also_on = also_on or {}
    for session in sessions:
        for turn in session.turns:
            turn.commits = list(dict.fromkeys((same_as or {}).get(s, s) for s in turn.commits))
    merged: dict[tuple[str | None, str], Request] = {}
    owners: dict[tuple[str | None, str], list[Session]] = {}
    for session in sessions:
        # An untitled session is its own request: only a title says two are one conversation.
        key = (session.folder, session.title or session.id)
        request = merged.setdefault(
            key,
            Request(session.title or UNTITLED, session.folder, _clock(session.created_at)),
        )
        owners.setdefault(key, []).append(session)
        request.sessions.append(session.id)
        request.turns += session.turns
    hub_roots = [hub_root] if hub_root else []
    for key, request in merged.items():
        made = {sha for turn in request.turns for sha in turn.commits}
        request.commits = [commit.sha for commit in commits if commit.sha in made]
        request.hub_files = [
            path
            for path in hub_files
            if any(_wrote(session, path, hub_roots) for session in owners[key])
        ]
        request.in_progress = [
            path
            for path in in_progress
            if any(_wrote(session, path, [checkout]) for session in owners[key])
        ]
    requests = list(merged.values())
    claimed = {sha for request in requests for sha in request.commits}
    leftover = Request(
        NO_SESSION,
        commits=[commit.sha for commit in commits if commit.sha not in claimed],
        hub_files=[p for p in hub_files if not any(p in r.hub_files for r in requests)],
        in_progress=[p for p in in_progress if not any(p in r.in_progress for r in requests)],
    )
    if leftover.commits or leftover.hub_files or leftover.in_progress:
        requests.append(leftover)
    for request in requests:
        files = [path for sha in request.commits for path in by_sha[sha].files]
        request.files = list(dict.fromkeys(files))
        request.screens, request.removed_screens = screens_of(
            [*request.files, *request.in_progress], patterns
        )
        request.also_on = {sha: also_on[sha] for sha in request.commits if sha in also_on}
    return requests


def _clock(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def slug_of(title: str) -> str:
    return (
        re.sub(r"[^a-z0-9]+", "-", title.lower().encode("ascii", "ignore").decode()).strip("-")[:48]
        or "request"
    )


def commit_patches(shas: Sequence[str], cwd: Path = ROOT) -> str:
    """Each commit as a mail patch, oldest first, generated files left out (so a commit that
    only regenerates files gives nothing)."""
    return "".join(
        git("format-patch", "--stdout", f"{sha}^!", "--", *SOURCES_ONLY, cwd=cwd) for sha in shas
    )


def uncommitted(cwd: Path = ROOT) -> list[str]:
    """The files changed but not committed, tracked then new; personal ``*.local.*`` ones left
    out."""
    tracked = git("diff", "--name-only", "HEAD", cwd=cwd).split("\n")
    new = git("ls-files", "--others", "--exclude-standard", cwd=cwd).split("\n")
    return [
        path for path in dict.fromkeys([*tracked, *new]) if path and not LOCAL_FILE.search(path)
    ]


def uncommitted_patch(paths: Sequence[str], cwd: Path = ROOT) -> str:
    """The uncommitted changes of ``paths``, new files included, without touching the index."""
    if not paths:
        return ""
    tracked = set(git("ls-files", "--", *paths, cwd=cwd).split("\n"))
    changed = [path for path in paths if path in tracked]
    patch = git("diff", "HEAD", "--", *changed, cwd=cwd) if changed else ""
    for path in paths:
        if path not in tracked and (cwd / path).is_file():
            patch += subprocess.run(  # noqa: S603 -- a fixed argv; exit 1 means "differs"
                ["git", "diff", "--no-index", "--", "/dev/null", path],
                cwd=cwd,
                capture_output=True,
                text=True,
                check=False,
            ).stdout
    return patch


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
    left = {path for path in changed if not synced(path)} | set(committed.split())
    return sorted(path for path in left if (hub / path).is_file())


def render_brief(
    base: str,
    head: str,
    *,
    requests: Sequence[Request],
    commits: Sequence[Commit],
    shipped: Sequence[Commit] = (),
    hub: str | None = None,
    missing: Sequence[str] = (),
    snapshot: str | None = None,
    repeated: Sequence[tuple[Commit, str]] = (),
) -> str:
    """The owner's requests in the order they asked them, each a delivery: its turns in their
    own words, then what it made."""
    by_sha = {commit.sha: commit for commit in [*commits, *shipped]}
    in_main = {commit.sha: MAIN for commit in shipped}
    lines = [f"# Playground export {base[:8]}..{head[:8]}", ""]
    lines.append(
        f"{len(requests)} request(s), {len(commits)} commit(s). Each request is one delivery: "
        "the owner's turns (what they asked, answered and validated), what each turn made, then "
        "its commits, files, screens and patch."
    )
    if snapshot:
        lines += [
            "",
            f"Snapshot: branch `{snapshot}`, the checkout as it was, uncommitted files included "
            f"(the hub's files are only in `hub/` here). Back to it: "
            f"`git switch -c <name> {snapshot}`.",
        ]
    if missing:
        lines += ["", "**Incomplete:**", "", *[f"- {reason}" for reason in missing]]
    for number, request in enumerate(requests, 1):
        lines += _request_lines(
            number, request, by_sha=by_sha, marks={**in_main, **request.also_on}, hub=hub
        )
    if shipped:
        lines += ["", f"## Already in {MAIN} (left out)", ""]
        lines += [f"- `{commit.sha[:8]}` {commit.subject}" for commit in shipped]
    if repeated:
        lines += ["", "## Repeated changes (left out, the same change as an exported commit)", ""]
        lines += [
            f"- `{commit.sha[:8]}` {commit.subject}: same as `{first[:8]}`"
            for commit, first in repeated
        ]
    return "\n".join(lines) + "\n"


def _request_lines(
    number: int,
    request: Request,
    *,
    by_sha: Mapping[str, Commit],
    marks: Mapping[str, str],
    hub: str | None,
) -> list[str]:
    facts = [
        f"in {request.folder}" if request.folder else "",
        f"{len(request.sessions)} session(s)" if request.sessions else "",
        f"asked {request.started_at}" if request.started_at else "",
        f"patch `{request.patch}`" if request.patch else "",
    ]
    lines = ["", f"## {number}. {request.title}", "", " · ".join(filter(None, facts))]
    lines += _turn_lines(request.turns, by_sha=by_sha, marks=marks)
    commits = [
        f"{_commit_ref(sha, by_sha, marks)}"
        + "".join(f"\n  {line}" for line in by_sha[sha].body.splitlines() if line.strip())
        for sha in request.commits
    ]
    lines += _section("Commits", commits)
    lines += _section("Files", [f"`{path}`" for path in request.files])
    lines += _section("Screens", [f"`screens/{shot}.png`" for shot in request.screens])
    lines += _section(
        "Removed screens (HEAD has no such route)",
        [f"`{path}`" for path in request.removed_screens],
    )
    lines += _section(
        f"Hub files ({hub or 'hub'}, copied under `hub/`)",
        [f"`{path}`" for path in request.hub_files],
    )
    lines += _section(
        "In progress (uncommitted, in `in-progress.patch`)",
        [f"`{path}`" for path in request.in_progress],
    )
    if not (request.commits or request.hub_files or request.in_progress):
        lines += ["", "Nothing made yet: discussed, abandoned, or made in another request."]
    return lines


def _turn_lines(
    turns: Sequence[Turn], *, by_sha: Mapping[str, Commit], marks: Mapping[str, str]
) -> list[str]:
    """Each turn: when, the owner's words, their answers and what it committed."""
    lines = ["", "### Turns"] if turns else []
    for index, turn in enumerate(turns, 1):
        when = _instant(turn.at)
        shot = " (with a screenshot)" if turn.screenshot else ""
        lines += ["", f"{index}. {_clock(when) if when else turn.at}{shot}"]
        lines += [f"   > {line}" for line in turn.message.splitlines() if line.strip()]
        lines += [f"   - Answered: {answer}" for answer in turn.answers]
        made = ", ".join(_commit_ref(sha, by_sha, marks) for sha in turn.commits)
        lines.append(f"   - Made: {made or 'nothing committed'}")
    return lines


def _section(title: str, items: Sequence[str]) -> list[str]:
    return ["", f"### {title}", "", *[f"- {item}" for item in items]] if items else []


def _commit_ref(sha: str, by_sha: Mapping[str, Commit], marks: Mapping[str, str]) -> str:
    """A commit's short sha and subject, with the branch that also has it."""
    commit = by_sha.get(sha)
    text = f"`{sha[:8]}` {commit.subject}" if commit else f"`{sha[:8]}`"
    return text + (f" (also on {marks[sha]})" if sha in marks else "")


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


def capture_routes(screens: Sequence[str]) -> list[dict[str, str]]:
    """The capture's routes for ``screens`` (``<area>/<route slug>``), each once."""
    routes = []
    for shot in dict.fromkeys(screens):
        area, slug = shot.split("/", 1)
        route = next(route for route in routes_of(area) if route.slug == slug)
        routes.append(
            {"file": shot, "path": route.path, **({"follow": route.follow} if route.follow else {})}
        )
    return routes


def capture_screens(screens: Sequence[str], out: Path) -> str | None:
    """Renders each screen from HEAD on synthetic data into ``out``.

    Returns why it could not, else None.
    """
    routes = capture_routes(screens)
    npm = shutil.which("npm")
    if not routes:
        return None
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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m scripts.playground_export", description=__doc__
    )
    parser.add_argument(
        "--since", default=None, help="the commit to export from (default: the last export)"
    )
    parser.add_argument(
        "--no-screens",
        action="store_true",
        help="skip the screen capture (the export is not marked)",
    )
    parser.add_argument(
        "--conductor-log",
        type=Path,
        default=None,
        help="the conductor's log, to read the owner's requests (default: where make playground "
        f"writes it, $TMPDIR/{CONDUCTOR_LOG})",
    )
    # make playground's hub, next to the main checkout (a worktree's common dir is the main one).
    main_checkout = Path(git("rev-parse", "--path-format=absolute", "--git-common-dir").strip())
    parser.add_argument(
        "--hub",
        type=Path,
        default=main_checkout.parent.parent / "agent-hub-hub",
        help="the project's hub, where Studio sessions write skills, agents and hooks",
    )
    return parser


def _also_on(base: str, head: str, shipped: set[str]) -> dict[str, str]:
    """The range's commits another pushed branch has, each with the first such branch."""
    current = git("branch", "--show-current").strip()
    remote_refs = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/").split()
    found: dict[str, str] = {}
    for branch in delivering_branches(remote_refs, current):
        for sha in equivalent_on(branch, base, head) - shipped:
            found.setdefault(sha, branch)
    return found


def _write_changes(
    out: Path,
    requests: Sequence[Request],
    commits: Sequence[Commit],
    *,
    hub: Path,
    hub_files: Sequence[str],
    in_progress: Sequence[str],
) -> None:
    """The patches (each request's, every commit's, the uncommitted) and the hub's files."""
    (out / "requests").mkdir(parents=True)
    for number, request in enumerate(requests, 1):
        if request.commits:
            request.patch = f"requests/{number:02d}-{slug_of(request.title)}.patch"
            (out / request.patch).write_text(commit_patches(request.commits), "utf-8")
    (out / "reference.patch").write_text(commit_patches([c.sha for c in commits]), "utf-8")
    if in_progress:
        (out / "in-progress.patch").write_text(uncommitted_patch(in_progress), "utf-8")
    for path in hub_files:
        target = out / "hub" / path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(hub / path, target)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    head = git("rev-parse", "HEAD").strip()
    try:
        base = resolve_base(args.since)
    except subprocess.CalledProcessError as error:
        print(f"cannot find where to start: {error.stderr.strip()}", file=sys.stderr)
        return 1
    everything = commits_between(base, head)
    shipped_shas = equivalent_on(MAIN, base, head) if everything else set()
    repeated = repeated_changes(base, head) if everything else {}
    shipped = [commit for commit in everything if commit.sha in shipped_shas]
    commits = [c for c in everything if c.sha not in shipped_shas and c.sha not in repeated]
    in_progress = uncommitted()
    if not commits and not in_progress:
        print("nothing to export")
        return 0
    # Without a commit, the sessions that wrote the uncommitted files are those since the base.
    start = (
        commits[0].date
        if commits
        else datetime.fromisoformat(git("show", "-s", "--format=%cI", base).strip())
    )
    try:
        sessions = owner_sessions(
            start, commits=everything, logs=conductor_logs(args.conductor_log, os.environ)
        )
    except RequestsUnavailableError as error:
        print(f"cannot read the owner's requests, nothing exported: {error}", file=sys.stderr)
        return 1
    also_on = _also_on(base, head, shipped_shas)
    hub_files = hub_changes(args.hub, start - REQUEST_LEAD)
    requests = build_requests(
        sessions,
        commits,
        patterns=route_patterns(git("show", f"{head}:{ROUTES_FILE}")),
        also_on=also_on,
        hub_files=hub_files,
        hub_root=args.hub,
        in_progress=in_progress,
        same_as=repeated,
    )

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = EXPORTS / stamp
    _write_changes(
        out, requests, commits, hub=args.hub, hub_files=hub_files, in_progress=in_progress
    )
    branch = snapshot_branch(
        git("branch", "--show-current").strip(), git("config", "user.email").strip(), stamp
    )
    snapshot(
        branch,
        message=f"chore(dev): playground snapshot {stamp}\n\nThe checkout as exported, "
        "uncommitted files included; not for merging.",
        in_progress=in_progress,
    )
    screens = [shot for request in requests for shot in request.screens]
    skipped = "--no-screens" if args.no_screens else capture_screens(screens, out / "screens")
    missing = [f"screens not captured: {skipped}"] if skipped else []
    brief = render_brief(
        base,
        head,
        requests=requests,
        commits=commits,
        shipped=shipped,
        hub=args.hub.name,
        missing=missing,
        snapshot=branch,
        repeated=[(c, repeated[c.sha]) for c in everything if c.sha in repeated],
    )
    (out / "brief.md").write_text(brief, "utf-8")
    document = {
        "base": base,
        "head": head,
        "created_at": stamp,
        "requests": [asdict(request) for request in requests],
        "shipped": [{"sha": c.sha, "subject": c.subject} for c in shipped],
        "repeated": [
            {"sha": c.sha, "subject": c.subject, "same_as": repeated[c.sha]}
            for c in everything
            if c.sha in repeated
        ],
        "hub": {"path": str(args.hub), "files": hub_files},
        "in_progress": in_progress,
        "screens_skipped": skipped,
        "complete": not missing,
        "snapshot": branch,
    }
    (out / "export.json").write_text(json.dumps(document, indent=2) + "\n", "utf-8")
    if not missing:
        git("tag", f"{TAG_PREFIX}{stamp}", head)
    print(
        "\n".join(
            [
                f"exported {len(requests)} request(s), {len(commits)} commit(s), "
                f"to {out.relative_to(ROOT)}",
                *([f"left out {len(shipped)} commit(s) {MAIN} already has"] if shipped else []),
                *([f"kept {len(also_on)} commit(s) another branch also has"] if also_on else []),
                *([f"copied {len(hub_files)} hub file(s)"] if hub_files else []),
                *([f"{len(in_progress)} uncommitted file(s)"] if in_progress else []),
                f"snapshot on branch {branch}",
                *(
                    [f"not marked, the next export starts here again: {'; '.join(missing)}"]
                    if missing
                    else []
                ),
            ]
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
