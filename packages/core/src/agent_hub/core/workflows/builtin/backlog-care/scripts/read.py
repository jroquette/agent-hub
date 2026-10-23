# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read the issues file ``/triage --backlog`` wrote, bounded, and print it as one JSON object.

``read.py --file PATH --limit N``, cwd the hub. ``PATH`` is the absolute path of a regular file
(not a link) of at most 1 MiB: one UTF-8 JSON object ``{"version": 1, "read_at", "open_total",
"issues": [...]}`` (``TOP_FIELDS``), each issue with ``ISSUE_FIELDS``. Its text is
the tracker's, written by anyone: every field is cut and control characters are removed. An
entry without a well-formed ``id``, a ``title``, a ``state.name`` or ISO-8601 dates with an offset
is skipped and named in ``skipped``. The oldest ``N`` issues (1-100) are kept; ``open`` is
``open_total`` or the file's entry count, whichever is larger, and ``unread_line`` says how many
open issues were left unread. ``hub.json`` gives ``tracker.ready_label`` and ``repos[].dir``, so
later scripts read no config.

Prints ``{"ready_label", "repos", "read", "open", "unread", "unread_line",
"descriptions_dropped", "skipped", "issues"}``, at most ``OUTPUT_BUDGET`` bytes: past it,
descriptions are dropped from the newest issue first. A bad file, ``hub.json`` or limit, or an
output still over budget without descriptions, exits 2 with ``read.py: <reason>`` on stderr.
"""

import argparse
import json
import os
import re
import stat
import sys
import unicodedata
from datetime import datetime
from pathlib import Path

ISSUE_FIELDS = (
    "id",
    "title",
    "url",
    "state",
    "created_at",
    "updated_at",
    "labels",
    "blocked_by",
    "blocks",
    "links",
    "branch_name",
    "description",
)
TOP_FIELDS = ("version", "read_at", "open_total", "issues")
ISSUE_ID = re.compile(r"[A-Z][A-Z0-9]{0,9}-[1-9][0-9]{0,8}")
REPO_DIR = re.compile(r"[A-Za-z0-9_][A-Za-z0-9._-]{0,99}")
DEFAULT_READY_LABEL = "agent-ready"
MAX_FILE_BYTES = 1 << 20
MAX_ENTRIES = 500
MAX_LIMIT = 100
OUTPUT_BUDGET = 400 * 1024
TITLE_CHARS = 500
TEXT_CHARS = 500
NAME_CHARS = 100
DESCRIPTION_CHARS = 1000
MAX_LABELS = 20
MAX_RELATIONS = 25
MAX_LINKS = 10
# Kept in a description, which is several lines; removed everywhere else.
LINE_CONTROLS = frozenset("\n\t")


class BadInputError(Exception):
    """The file, hub.json or an argument cannot be read: the run fails at this node."""


def clean(value: object, limit: int, *, lines: bool = False) -> str:
    """``value`` as text without control characters, cut to ``limit``; not text reads empty."""
    if not isinstance(value, str):
        return ""
    keep = LINE_CONTROLS if lines else frozenset()
    kept = (c for c in value if c in keep or unicodedata.category(c) != "Cc")
    return "".join(kept)[:limit]


def texts(value: object, limit: int, count: int) -> list[str]:
    """The first ``count`` non-empty texts of a list, each cleaned; anything else reads empty."""
    if not isinstance(value, list):
        return []
    found = (clean(item, limit) for item in value)
    return [item for item in found if item][:count]


def relations(value: object) -> list[str]:
    """The well-formed issue ids of a relation list, in order, without repeats, at most 25."""
    found: list[str] = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str) and ISSUE_ID.fullmatch(item) and item not in found:
            found.append(item)
    return found[:MAX_RELATIONS]


def moment(value: object) -> datetime | None:
    """An ISO-8601 date and time with an offset, else None."""
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        found = datetime.fromisoformat(value)
    except ValueError:
        return None
    return found if found.tzinfo is not None else None


def problem(raw: dict[str, object]) -> str:
    """Why an entry cannot be read, or empty when it can."""
    state = raw.get("state")
    issue_id = raw.get("id")
    if not isinstance(issue_id, str) or not ISSUE_ID.fullmatch(issue_id):
        return "id missing or malformed"
    if not clean(raw.get("title"), TITLE_CHARS).strip():
        return "title missing"
    if not isinstance(state, dict) or not clean(state.get("name"), NAME_CHARS).strip():
        return "state.name missing"
    for key in ("created_at", "updated_at"):
        if moment(raw.get(key)) is None:
            return f"{key} missing or not ISO-8601 with an offset"
    return ""


def entry(raw: dict[str, object]) -> dict[str, object]:
    """A readable entry with every field cut and cleaned (``problem`` found none)."""
    found = raw.get("state")
    state = found if isinstance(found, dict) else {}
    links = raw.get("links", [])
    return {
        "id": raw["id"],
        "title": clean(raw["title"], TITLE_CHARS),
        "url": clean(raw.get("url"), TEXT_CHARS),
        "state": {
            "name": clean(state.get("name"), NAME_CHARS),
            "type": clean(state.get("type"), NAME_CHARS),
        },
        "created_at": clean(raw["created_at"], TEXT_CHARS),
        "updated_at": clean(raw["updated_at"], TEXT_CHARS),
        "labels": texts(raw.get("labels"), NAME_CHARS, MAX_LABELS),
        "blocked_by": relations(raw.get("blocked_by")),
        "blocks": relations(raw.get("blocks")),
        # null: the skill could not read the issue's links (hygiene says so).
        "links": None if links is None else texts(links, TEXT_CHARS, MAX_LINKS),
        "branch_name": clean(raw.get("branch_name"), TEXT_CHARS),
        "description": clean(raw.get("description"), DESCRIPTION_CHARS, lines=True),
    }


def bounded_issues(
    document: dict[str, object], limit: int
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """The oldest ``limit`` readable issues, and each entry skipped with its reason."""
    readable: list[tuple[datetime, str, dict[str, object]]] = []
    skipped: list[dict[str, object]] = []
    for index, item in enumerate(entries_of(document)):
        reason = problem(item) if isinstance(item, dict) else "not an object"
        when = moment(item.get("created_at")) if isinstance(item, dict) else None
        if reason or when is None or not isinstance(item, dict):
            skipped.append({"index": index, "reason": reason or "not an object"})
        else:
            readable.append((when, str(item["id"]), entry(item)))
    readable.sort(key=lambda found: found[:2])
    return [issue for _, _, issue in readable[:limit]], skipped


def entries_of(document: dict[str, object]) -> list[object]:
    found = document.get("issues")
    return found if isinstance(found, list) else []


def unread_line(read: int, open_total: int) -> str:
    """The report's line on how many open issues this run did not read."""
    unread = open_total - read
    if unread <= 0:
        return f"No open issue was left unread ({read} of {open_total} read)"
    noun = "open issue was" if unread == 1 else "open issues were"
    return f"{unread} {noun} left unread ({read} of {open_total} read, oldest first)"


def json_file(path: Path, limit: int, name: str) -> object:
    """A regular file of at most ``limit`` bytes, not a link, read as UTF-8 JSON."""
    try:
        found = os.lstat(path)
    except OSError as error:
        raise BadInputError(f"{name}: cannot be read ({error.strerror})") from error
    if stat.S_ISLNK(found.st_mode) or not stat.S_ISREG(found.st_mode):
        raise BadInputError(f"{name}: not a regular file")
    if found.st_size > limit:
        raise BadInputError(f"{name}: larger than {limit} bytes")
    try:
        return json.loads(path.read_bytes().decode("utf-8"))
    except (OSError, UnicodeDecodeError, ValueError, RecursionError) as error:
        raise BadInputError(f"{name}: not UTF-8 JSON") from error


def issues_file(given: str) -> dict[str, object]:
    """The skill's file, checked whole: its shape, its version and its entry count."""
    path = Path(given)
    if not path.is_absolute():
        raise BadInputError("the issues file is not an absolute path")
    document = json_file(path, MAX_FILE_BYTES, "the issues file")
    if not isinstance(document, dict):
        raise BadInputError("the issues file is not a JSON object")
    if document.get("version") != 1:
        raise BadInputError("the issues file's version is not 1")
    issues = document.get("issues")
    if not isinstance(issues, list):
        raise BadInputError("the issues file's issues is not a list")
    if len(issues) > MAX_ENTRIES:
        raise BadInputError(f"the issues file holds more than {MAX_ENTRIES} issues")
    return document


def hub_config() -> tuple[str, list[str]]:
    """``tracker.ready_label`` (its default when absent) and each ``repos[].dir`` of hub.json."""
    document = json_file(Path("hub.json"), MAX_FILE_BYTES, "hub.json")
    if not isinstance(document, dict):
        raise BadInputError("hub.json: not a JSON object")
    tracker = document.get("tracker", {})
    label = tracker.get("ready_label", DEFAULT_READY_LABEL) if isinstance(tracker, dict) else None
    if not isinstance(label, str) or not label:
        raise BadInputError("hub.json: tracker.ready_label is not text")
    repos = document.get("repos")
    if not isinstance(repos, list):
        raise BadInputError("hub.json: repos is not a list")
    dirs = [repo.get("dir") if isinstance(repo, dict) else None for repo in repos]
    if not all(isinstance(d, str) and REPO_DIR.fullmatch(d) and d != ".." for d in dirs):
        raise BadInputError("hub.json: a repos[].dir is not a folder name")
    return label, [str(d) for d in dirs]


def limit_of(given: str) -> int:
    if not (given.isascii() and given.isdecimal()) or not 1 <= int(given) <= MAX_LIMIT:
        raise BadInputError(f"--limit is not a whole number from 1 to {MAX_LIMIT}: {given!r}")
    return int(given)


def fit_budget(result: dict[str, object], issues: list[dict[str, object]]) -> int:
    """Drop descriptions, newest issue first, until ``result`` prints within the budget."""
    dropped = 0
    for issue in reversed(issues):
        if len(json.dumps(result)) <= OUTPUT_BUDGET:
            break
        if issue["description"]:
            issue["description"] = ""
            dropped += 1
    if len(json.dumps(result)) > OUTPUT_BUDGET:
        raise BadInputError(f"the issues read print over {OUTPUT_BUDGET} bytes")
    return dropped


def summary(document: dict[str, object], limit: int) -> dict[str, object]:
    label, repos = hub_config()
    issues, skipped = bounded_issues(document, limit)
    given = document.get("open_total")
    entries = entries_of(document)
    open_total = given if isinstance(given, int) and not isinstance(given, bool) else 0
    open_count = max(open_total, len(entries))
    result: dict[str, object] = {
        "ready_label": label,
        "repos": repos,
        "read": len(issues),
        "open": open_count,
        "unread": max(0, open_count - len(issues)),
        "unread_line": unread_line(len(issues), open_count),
        "descriptions_dropped": 0,
        "skipped": skipped,
        "issues": issues,
    }
    result["descriptions_dropped"] = fit_budget(result, issues)
    return result


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="read.py")
    parser.add_argument("--file", required=True)
    parser.add_argument("--limit", default="50")
    given = parser.parse_args(argv)
    try:
        result = summary(issues_file(given.file), limit_of(given.limit))
    except BadInputError as error:
        print(f"read.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
