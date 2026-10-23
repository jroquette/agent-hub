# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Find orphan, stale, duplicate and cyclic issues among those ``read.py`` printed, as JSON.

``hygiene.py [--stale-days N] [--today YYYY-MM-DD]``, cwd the hub, ``read.py``'s output on stdin.
Each finding names its evidence (the field and its value):

- orphan: the state's type is ``started`` (or, with no type, the name is In Progress or In
  Review, any case), no link to a GitHub pull request or branch, and no branch ref in any repo
  (``git for-each-ref`` in ``../<dir>``, refs as last fetched) named for the issue
  (``(^|/)<id>(-|$)``, lower case) or its ``branch_name``; ``links: null`` says the PR links
  were not read;
- stale: no update for ``N`` days (14 by default) before ``--today`` (by default the clock's
  UTC date);
- duplicates: equal titles once case, a leading ``type(scope):``, punctuation and repeated
  spaces are dropped;
- cycles: groups of more than one issue that block each other through ``blocked_by`` and
  ``blocks``, among the issues read.

Prints ``{"orphans", "stale", "duplicates", "cycles", "unreadable", "summary"}``; a repo whose refs
cannot be read (``MAX_REFS`` at most, ``GIT_TIMEOUT`` seconds) is in ``unreadable`` and in each
orphan's evidence. ``summary`` is the report's text, at most ``SUMMARY_CHARS``. Bad stdin or
arguments exit 2 with ``hygiene.py: <reason>`` on stderr.
"""

import argparse
import json
import re
import subprocess
import sys
import unicodedata
from datetime import UTC, date, datetime
from pathlib import Path

MAX_REFS = 20_000
GIT_TIMEOUT = 30
SUMMARY_CHARS = 16_000
STARTED_NAMES = frozenset({"in progress", "in review"})
GITHUB_LINK = re.compile(r"https://github\.com/[^/\s]+/[^/\s]+/(pull|tree)/\S+")
CHANGE_PREFIX = re.compile(r"\s*[\w-]+(\([^)]*\))?!?:\s*")
CUT = "\n(cut)"

Issue = dict[str, object]
Finding = dict[str, object]


class BadInputError(Exception):
    """Stdin or an argument cannot be read: the run fails at this node."""


class RefsUnreadableError(Exception):
    """A repo's branch refs cannot be read; the reason is the message."""


def text(issue: Issue, key: str) -> str:
    value = issue.get(key)
    return value if isinstance(value, str) else ""


def state_of(issue: Issue) -> tuple[str, str]:
    state = issue.get("state")
    if not isinstance(state, dict):
        return "", ""
    name, kind = state.get("name"), state.get("type")
    return (name if isinstance(name, str) else ""), (kind if isinstance(kind, str) else "")


def ids_of(issue: Issue, key: str) -> list[str]:
    value = issue.get(key)
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def issue_key(issue_id: str) -> tuple[str, int]:
    """Sort ``DEM-2`` before ``DEM-10``."""
    team, _, number = issue_id.rpartition("-")
    return team, int(number) if number.isdecimal() else 0


def branch_refs(repo_dir: Path) -> list[str]:
    """The repo's local and remote-tracking branch refs, as last fetched (no network)."""
    command = [
        "git",
        "for-each-ref",
        f"--count={MAX_REFS + 1}",
        "--format=%(refname)",
        "refs/heads",
        "refs/remotes",
    ]
    try:
        done = subprocess.run(  # noqa: S603 - fixed arguments, read-only, in a hub repo
            command,
            cwd=repo_dir,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RefsUnreadableError(f"git for-each-ref took over {GIT_TIMEOUT} s") from error
    except OSError as error:
        raise RefsUnreadableError(error.strerror or "git cannot run there") from error
    if done.returncode != 0:
        first = (done.stderr.strip().splitlines() or ["git for-each-ref failed"])[0]
        raise RefsUnreadableError(first[:200])
    refs = done.stdout.splitlines()
    if len(refs) > MAX_REFS:
        raise RefsUnreadableError(f"more than {MAX_REFS} refs")
    return refs


def repo_refs(repos: list[str]) -> tuple[list[str], list[Finding]]:
    """Every repo's refs together, and each repo whose refs could not be read."""
    refs: list[str] = []
    unreadable: list[Finding] = []
    for repo in repos:
        try:
            refs.extend(branch_refs(Path("..") / repo))
        except RefsUnreadableError as error:
            unreadable.append({"repo": repo, "reason": str(error)})
    return refs, unreadable


def is_started(issue: Issue) -> bool:
    name, kind = state_of(issue)
    return kind == "started" if kind else name.casefold() in STARTED_NAMES


def has_branch(issue: Issue, refs: list[str], pattern: re.Pattern[str]) -> bool:
    branch = text(issue, "branch_name")
    named = branch and any(ref.endswith(f"/{branch}") for ref in refs)
    return bool(named) or any(pattern.search(ref) for ref in refs)


def orphans(issues: list[Issue], refs: list[str], unreadable: list[Finding]) -> list[Finding]:
    found: list[Finding] = []
    not_read = ", ".join(str(entry["repo"]) for entry in unreadable)
    for issue in issues:
        links = issue.get("links")
        linked = isinstance(links, list) and any(
            isinstance(link, str) and GITHUB_LINK.match(link) for link in links
        )
        issue_id = text(issue, "id")
        shown = f"(^|/){issue_id.lower()}(-|$)"
        pattern = re.compile(f"(^|/){re.escape(issue_id.lower())}(-|$)")
        if not is_started(issue) or linked or has_branch(issue, refs, pattern):
            continue
        name, kind = state_of(issue)
        branch = text(issue, "branch_name")
        evidence = [
            f"state {name} ({kind or 'no type'})",
            "PR links not read" if links is None else "no PR link",
            f"no branch ref matching {shown}" + (f" or ending in /{branch}" if branch else ""),
        ]
        if not_read:
            evidence.append(f"refs not read: {not_read}")
        found.append({"id": issue_id, "state": name, "evidence": "; ".join(evidence)})
    return found


def stale(issues: list[Issue], today: date, days: int) -> list[Finding]:
    found: list[Finding] = []
    for issue in issues:
        updated = text(issue, "updated_at")
        try:
            when = datetime.fromisoformat(updated).astimezone(UTC).date()
        except ValueError:
            continue
        idle = (today - when).days
        if idle >= days:
            evidence = f"updated_at {updated}: {idle} days without an update (stale after {days})"
            found.append(
                {"id": text(issue, "id"), "updated_at": updated, "days": idle, "evidence": evidence}
            )
    return found


def normalized(title: str) -> str:
    """The title without case, a leading ``type(scope):``, punctuation or repeated spaces."""
    lowered = CHANGE_PREFIX.sub("", title.casefold(), count=1)
    kept = "".join(c for c in lowered if not unicodedata.category(c).startswith("P"))
    return " ".join(kept.split())


def duplicates(issues: list[Issue]) -> list[Finding]:
    groups: dict[str, list[Issue]] = {}
    for issue in issues:
        title = normalized(text(issue, "title"))
        if title:
            groups.setdefault(title, []).append(issue)
    found: list[Finding] = []
    for title, group in groups.items():
        if len(group) > 1:
            group.sort(key=lambda issue: issue_key(text(issue, "id")))
            titles = ", ".join(f"{text(i, 'id')} {text(i, 'title')!r}" for i in group)
            found.append(
                {
                    "ids": [text(issue, "id") for issue in group],
                    "title": title,
                    "evidence": f"titles {titles} all read as {title!r}",
                }
            )
    return found


class _Tarjan:
    """Strongly connected groups of a graph, without recursion (a backlog may be long)."""

    def __init__(self, graph: dict[str, list[str]]) -> None:
        self.graph = graph
        self.index: dict[str, int] = {}
        self.low: dict[str, int] = {}
        self.stack: list[str] = []
        self.on_stack: set[str] = set()
        self.groups: list[list[str]] = []

    def visit(self, node: str) -> None:
        self.index[node] = self.low[node] = len(self.index)
        self.stack.append(node)
        self.on_stack.add(node)

    def close(self, node: str) -> None:
        if self.low[node] != self.index[node]:
            return
        group: list[str] = []
        while not group or group[-1] != node:
            group.append(self.stack.pop())
            self.on_stack.discard(group[-1])
        self.groups.append(group)

    def walk(self, root: str) -> None:
        self.visit(root)
        work = [(root, iter(self.graph[root]))]
        while work:
            node, children = work[-1]
            child = next(children, None)
            if child is None:
                work.pop()
                if work:
                    parent = work[-1][0]
                    self.low[parent] = min(self.low[parent], self.low[node])
                self.close(node)
            elif child not in self.index:
                self.visit(child)
                work.append((child, iter(self.graph[child])))
            elif child in self.on_stack:
                self.low[node] = min(self.low[node], self.index[child])


def cycles_of(graph: dict[str, list[str]]) -> list[list[str]]:
    """Each group of more than one node that reach each other, its ids sorted."""
    tarjan = _Tarjan(graph)
    for node in graph:
        if node not in tarjan.index:
            tarjan.walk(node)
    found = [sorted(group, key=issue_key) for group in tarjan.groups if len(group) > 1]
    return sorted(found, key=lambda group: issue_key(group[0]))


def blocked_graph(issues: list[Issue]) -> dict[str, list[str]]:
    """Issue → the issues it waits for, from ``blocked_by`` and ``blocks``, among those read."""
    graph: dict[str, list[str]] = {text(issue, "id"): [] for issue in issues}
    for issue in issues:
        issue_id = text(issue, "id")
        edges = [(issue_id, other) for other in ids_of(issue, "blocked_by")]
        edges += [(other, issue_id) for other in ids_of(issue, "blocks")]
        for waits, on in edges:
            if waits in graph and on in graph and waits != on and on not in graph[waits]:
                graph[waits].append(on)
    return graph


def cycles(issues: list[Issue]) -> list[Finding]:
    graph = blocked_graph(issues)
    found: list[Finding] = []
    for group in cycles_of(graph):
        edges = [
            f"{waits} blocked by {on}"
            for waits in group
            for on in sorted(graph[waits], key=issue_key)
            if on in group
        ]
        found.append({"ids": group, "evidence": "; ".join(edges)})
    return found


def plural(count: int, noun: str) -> str:
    return f"{count} {noun}" + ("" if count == 1 or noun == "stale" else "s")


def summary_of(read: int, result: dict[str, list[Finding]], titles: dict[str, str]) -> str:
    counts = [
        plural(len(result["orphans"]), "orphan"),
        plural(len(result["stale"]), "stale"),
        plural(len(result["duplicates"]), "duplicate group"),
        plural(len(result["cycles"]), "cycle"),
    ]
    lines = [f"Hygiene of {plural(read, 'issue')} read: {', '.join(counts)}."]
    for kind in ("orphans", "stale"):
        for item in result[kind]:
            issue_id = str(item["id"])
            lines.append(f"- {kind} {issue_id} {titles.get(issue_id, '')!r}: {item['evidence']}")
    for kind in ("duplicates", "cycles"):
        for item in result[kind]:
            ids = item["ids"]
            shown = ", ".join(ids) if isinstance(ids, list) else ""
            lines.append(f"- {kind} {shown}: {item['evidence']}")
    lines += [f"- refs not read in {e['repo']}: {e['reason']}" for e in result["unreadable"]]
    joined = "\n".join(lines)
    return joined if len(joined) <= SUMMARY_CHARS else joined[: SUMMARY_CHARS - len(CUT)] + CUT


def read_input(stdin: str) -> tuple[list[Issue], list[str], int]:
    try:
        read = json.loads(stdin)
    except ValueError as error:
        raise BadInputError("stdin is not JSON") from error
    if not isinstance(read, dict):
        raise BadInputError("stdin is not a JSON object")
    issues, repos = read.get("issues"), read.get("repos")
    if not isinstance(issues, list) or not isinstance(repos, list):
        raise BadInputError("stdin has no issues or repos list")
    kept = [issue for issue in issues if isinstance(issue, dict)]
    return kept, [repo for repo in repos if isinstance(repo, str)], len(kept)


def arguments(argv: list[str]) -> tuple[int, date]:
    parser = argparse.ArgumentParser(prog="hygiene.py")
    parser.add_argument("--stale-days", default="14")
    parser.add_argument("--today", default="")
    given = parser.parse_args(argv)
    days = given.stale_days
    if not (days.isascii() and days.isdecimal()) or not 1 <= int(days) <= 3650:
        raise BadInputError(f"--stale-days is not a whole number from 1 to 3650: {days!r}")
    try:
        today = date.fromisoformat(given.today) if given.today else datetime.now(UTC).date()
    except ValueError as error:
        raise BadInputError(f"--today is not YYYY-MM-DD: {given.today!r}") from error
    return int(days), today


def main(argv: list[str]) -> int:
    try:
        days, today = arguments(argv)
        issues, repos, read = read_input(sys.stdin.read())
    except BadInputError as error:
        print(f"hygiene.py: {error}", file=sys.stderr)
        return 2
    refs, unreadable = repo_refs(repos)
    result: dict[str, list[Finding]] = {
        "orphans": orphans(issues, refs, unreadable),
        "stale": stale(issues, today, days),
        "duplicates": duplicates(issues),
        "cycles": cycles(issues),
        "unreadable": unreadable,
    }
    titles = {text(issue, "id"): text(issue, "title") for issue in issues}
    print(json.dumps({**result, "summary": summary_of(read, result, titles)}))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
