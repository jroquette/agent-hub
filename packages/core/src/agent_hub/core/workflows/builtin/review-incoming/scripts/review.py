# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Fold the lenses' findings, write the review file the owner edits, and read it back.

``review.py merge --spec <json> --quality <json> --security <json or "">`` prints
``{"findings", "coverage", "verdicts", "omitted"}``: each lens finding tagged ``<lens>:<id>``,
duplicates (the same path, line and text) merged into the first (``also``), blocking first, then
cut from the end, counted in ``omitted``, until the compact UTF-8 JSON holds ``BUDGET_BYTES``. A
blank lens did not run (``not run``). A lens that is not JSON exits 2.

``review.py compose --findings <json> --path <clone> --base <sha> --head <sha> --repo <dir>
--pr <n> < draft`` writes ``.agent-runs/review-incoming/<AGENT_HUB_RUN_ID>.md`` under the cwd (the
hub) and never overwrites it (exit 1). Every blocking finding is kept: one the draft cites in no
comment is appended. A comment whose line is not in the diff (``-U3``, head side) moves to "Not on
a changed line"; minor comments are held apart under their own heading while a blocking one is
left. Agent text loses control characters, backtick fences and AI attribution lines, and a line
that would read as a heading is escaped. It prints ``{"path", "blocking", "minor", "inline",
"suggested", "preview"}``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BUDGET_BYTES = 40960
DIFF_CAP = 8 * 1024 * 1024
PREVIEW_CHARS = 6000
PATH_CHARS = 300
LENSES = ("spec", "quality", "security")
FOLDER = Path(".agent-runs/review-incoming")
RUN_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
NUMBER = re.compile(r"[1-9][0-9]{0,8}")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
BACKTICKS = re.compile(r"`{3,}")
ATTRIBUTION = re.compile(r"co-authored-by|generated with|\U0001f916", re.IGNORECASE)
HUNK = re.compile(r"^@{2} -[0-9,]+ \+([0-9]+)(?:,([0-9]+))? @{2}")
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.quotePath=false")
SUMMARY = "# Summary"
BLOCKING = "# Blocking"
OPTIONAL = "# Optional (minor)"
HELD = "# Optional (minor), not posted while a blocking finding is left"
OFF_DIFF = "# Not on a changed line"
LABELS = {"blocking": "**Blocking.**", "minor": "**Optional.**"}
SECTIONS = {
    SUMMARY: "summary",
    BLOCKING: "blocking",
    OPTIONAL: "minor",
    HELD: "held",
    OFF_DIFF: "off",
}
BLOCK = re.compile(r"## (.+?)(?::([1-9][0-9]{0,8}))?")
LISTED = re.compile(r"\*\*(Blocking|Optional)\.\*\* `([^`]+)`: ?(.*)")
EVENTS = {"comment": "COMMENT", "request-changes": "REQUEST_CHANGES", "approve": "APPROVE"}
REVIEW_CAP = 65536
BODY_CAP = 65536
COMMENT_CAP = 8000
COMMENTS_MAX = 50


class InputError(ValueError):
    """Bad input: exit 2."""


class RefusedError(ValueError):
    """A refusal of what is there: exit 1."""


def compact(value: object) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def text_of(value: object) -> str:
    return value if isinstance(value, str) else ""


def clean(text: str) -> str:
    """Agent or owner text, safe in the file: no control characters, fences or attribution."""
    text = BACKTICKS.sub("`", CONTROL.sub("", text.replace("\r\n", "\n")))
    lines = [line for line in text.split("\n") if not ATTRIBUTION.search(line)]
    # A line that would read as a heading or a comment of the file is escaped.
    lines = ["\\" + line if line.startswith(("#", "<!--")) else line for line in lines]
    return "\n".join(lines).strip()


def one_line(text: str, limit: int = PATH_CHARS) -> str:
    return BACKTICKS.sub("`", CONTROL.sub("", text.replace("\n", " ").replace("\t", " ")))[:limit]


def parsed(text: str, what: str) -> dict[str, object] | None:
    if not text.strip():
        return None
    try:
        value = json.loads(text)
    except ValueError:
        value = None
    if not isinstance(value, dict):
        raise InputError(f"{what} is not a lens review")
    return value


def listed(value: object) -> list[dict[str, object]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def tagged(lens: str, review: dict[str, object] | None) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for item in listed(review.get("findings") if review else None):
        line = item.get("line")
        found.append(
            {
                "id": f"{lens}:{text_of(item.get('id'))}",
                "lens": lens,
                "kind": text_of(item.get("kind")),
                "severity": "blocking" if item.get("severity") == "blocking" else "minor",
                "path": one_line(text_of(item.get("path"))),
                "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
                "acs": [one_line(ac, 64) for ac in listed_text(item.get("acs"))][:10],
                "what": one_line(text_of(item.get("what")), 400),
                "expected": one_line(text_of(item.get("expected")), 400),
            }
        )
    return found


def merge_findings(
    spec: dict[str, object] | None,
    quality: dict[str, object] | None,
    security: dict[str, object] | None,
) -> dict[str, object]:
    """The three lenses as one list, duplicates merged, blocking first (not yet budgeted)."""
    reviews = {"spec": spec, "quality": quality, "security": security}
    merged: list[dict[str, object]] = []
    seen: dict[tuple[str, object, str], dict[str, object]] = {}
    for lens in LENSES:
        for finding in tagged(lens, reviews[lens]):
            key = (
                str(finding["path"]),
                finding["line"],
                " ".join(str(finding["what"]).split()).casefold(),
            )
            first = seen.get(key)
            if first is None:
                seen[key] = finding
                merged.append(finding)
                continue
            also = first.setdefault("also", [])
            if isinstance(also, list):
                also.append(finding["id"])
            if finding["severity"] == "blocking":
                first["severity"] = "blocking"
    merged.sort(key=lambda finding: finding["severity"] != "blocking")
    verdicts = {
        lens: "not run"
        if review is None
        else ("PASS" if review.get("verdict") == "PASS" else "FAIL")
        for lens, review in reviews.items()
    }
    coverage = listed(spec.get("coverage")) if spec else []
    return {"findings": merged, "coverage": coverage, "verdicts": verdicts}


def within_budget(merged: dict[str, object]) -> str:
    """The merged findings as compact JSON of at most ``BUDGET_BYTES``, dropping from the end."""
    findings, coverage = list(merged["findings"]), list(merged["coverage"])  # type: ignore[call-overload]
    omitted = 0

    def shown() -> str:
        return compact(
            {
                "findings": findings,
                "coverage": coverage,
                "verdicts": merged["verdicts"],
                "omitted": omitted,
            }
        )

    sizes = [len(compact(item).encode()) + 1 for item in findings]
    total = len(shown().encode())
    while total > BUDGET_BYTES and (findings or coverage):
        if findings:
            total -= sizes.pop()
            findings.pop()
        else:
            total -= len(compact(coverage.pop()).encode()) + 1
        omitted += 1
        total += len(str(omitted)) - len(str(omitted - 1))
    return shown()


def run_merge(given: argparse.Namespace) -> int:
    reviews = [parsed(getattr(given, lens), f"--{lens}") for lens in LENSES]
    print(within_budget(merge_findings(*reviews)))
    return 0


def git_diff(path: str, base: str, head: str) -> str:
    """The diff (``-U3``) from ``base`` to ``head`` in the clone, at most ``DIFF_CAP`` bytes."""
    with tempfile.TemporaryFile() as output:
        done = subprocess.run(  # noqa: S603 - a git read with fixed arguments, hooks off
            [*GIT, "-C", path, "diff", "--no-color", "--no-ext-diff", "--no-textconv", "-U3"]
            + [base, head],
            stdout=output,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            check=False,
        )
        output.seek(0)
        data = output.read(DIFF_CAP)
    return data.decode("utf-8", errors="replace") if done.returncode == 0 else ""


def hunks(diff: str) -> dict[str, set[int]]:
    """Each changed file's head-side lines a review comment can sit on (its hunks' lines)."""
    anchors: dict[str, set[int]] = {}
    path = ""
    for line in diff.splitlines():
        if line.startswith("+++ "):
            name = line[4:].strip().strip('"')
            path = name[2:] if name.startswith("b/") else ""
            anchors.setdefault(path, set())
        elif (match := HUNK.match(line)) and path:
            start, count = int(match.group(1)), int(match.group(2) or "1")
            anchors[path].update(range(start, start + count))
    anchors.pop("", None)
    return anchors


def anchor(path: str, line: object) -> str:
    return f"{path}:{line}" if isinstance(line, int) else path


def block(comment: dict[str, object]) -> str:
    return f"## {anchor(str(comment['path']), comment['line'])}\n{comment['body']}\n"


def off_diff(comment: dict[str, object]) -> str:
    label = LABELS[str(comment["severity"])]
    return f"{label} `{anchor(str(comment['path']), comment['line'])}`: {comment['body']}\n"


def draft_comments(draft: dict[str, object]) -> list[dict[str, object]]:
    comments: list[dict[str, object]] = []
    for item in listed(draft.get("comments")):
        body = clean(text_of(item.get("body")))
        if not body:
            continue
        line = item.get("line")
        comments.append(
            {
                "path": one_line(text_of(item.get("path"))).strip(),
                "line": line if isinstance(line, int) and not isinstance(line, bool) else None,
                "severity": "blocking" if item.get("severity") == "blocking" else "minor",
                "body": body,
                "sources": [text_of(s) for s in listed_text(item.get("sources"))],
            }
        )
    return comments


def listed_text(value: object) -> list[str]:
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def kept_blocking(
    comments: list[dict[str, object]], merged: dict[str, object]
) -> list[dict[str, object]]:
    """The draft's comments plus one for each blocking finding no comment cites."""
    cited = {source for comment in comments for source in listed_text(comment["sources"])}
    added: list[dict[str, object]] = []
    for finding in listed(merged.get("findings")):
        ids = {finding.get("id"), *listed_text(finding.get("also"))}
        if finding.get("severity") != "blocking" or ids & cited:
            continue
        body = clean(
            f"{text_of(finding.get('what'))}\nExpected: {text_of(finding.get('expected'))}"
        )
        line = finding.get("line")
        added.append(
            {
                "path": one_line(text_of(finding.get("path"))).strip(),
                "line": line if isinstance(line, int) else None,
                "severity": "blocking",
                "body": body,
                "sources": [text_of(finding.get("id"))],
            }
        )
    return comments + added


def render_review(
    draft: dict[str, object],
    merged: dict[str, object],
    anchors: dict[str, set[int]],
    *,
    header: str,
) -> tuple[str, dict[str, int]]:
    """The review file's text, and its counts."""
    comments = kept_blocking(draft_comments(draft), merged)
    blocking = [c for c in comments if c["severity"] == "blocking"]
    minor = [c for c in comments if c["severity"] == "minor"]
    on_diff = [c for c in comments if c["line"] in anchors.get(str(c["path"]), set())]
    held = bool(blocking)
    sections = {SUMMARY: clean(text_of(draft.get("summary"))) + "\n", BLOCKING: "", OFF_DIFF: ""}
    minor_heading = HELD if held else OPTIONAL
    sections[minor_heading] = ""
    for comment in blocking + minor:
        if comment in on_diff or (held and comment["severity"] == "minor"):
            heading = BLOCKING if comment["severity"] == "blocking" else minor_heading
            sections[heading] += block(comment)
        else:
            sections[OFF_DIFF] += off_diff(comment)
    order = (SUMMARY, BLOCKING, minor_heading, OFF_DIFF)
    text = header + "\n" + "".join(f"{name}\n{sections[name]}" for name in order)
    inline = sum(1 for c in on_diff if c["severity"] == "blocking" or not held)
    counts = {"blocking": len(blocking), "minor": len(minor), "inline": inline}
    return text, counts


def run_id() -> str:
    found = os.environ.get("AGENT_HUB_RUN_ID") or "local"
    if not RUN_ID.fullmatch(found):
        raise InputError("AGENT_HUB_RUN_ID is not a run id")
    return found


def run_compose(given: argparse.Namespace) -> int:
    for value, pattern, name in (
        (given.base, SHA, "base"),
        (given.head, SHA, "head"),
        (given.repo, REPO, "repo"),
        (given.pr, NUMBER, "pr"),
    ):
        if not pattern.fullmatch(value):
            raise InputError(f"{name} is not valid")
    path = FOLDER / f"{run_id()}.md"
    merged = parsed(given.findings, "--findings") or {}
    try:
        draft = json.loads(sys.stdin.read())
    except ValueError:
        draft = None
    if not isinstance(draft, dict):
        raise InputError("the draft is not a JSON object")
    header = (
        f"<!-- review-incoming {given.repo}#{given.pr} at {given.head}. Edit the text, delete a"
        " comment's block to drop it, keep the headings. -->"
    )
    anchors = hunks(git_diff(given.path, given.base, given.head))
    text, counts = render_review(draft, merged, anchors, header=header)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8") as handle:
            handle.write(text)
    except FileExistsError:
        raise RefusedError(f"the review file exists: {path}; start a new run") from None
    suggested = "request-changes" if counts["blocking"] else "comment"
    result = {"path": str(path), **counts, "suggested": suggested, "preview": text[:PREVIEW_CHARS]}
    print(json.dumps(result, ensure_ascii=False))
    return 0


@dataclass
class Comment:
    """One ``## <path>:<line>`` block of the review file."""

    severity: str
    path: str
    line: int | None
    lines: list[str] = field(default_factory=list)

    @property
    def body(self) -> str:
        return "\n".join(self.lines).strip()


@dataclass
class Review:
    """The review file as the owner left it: the held section is never read."""

    summary: list[str] = field(default_factory=list)
    comments: list[Comment] = field(default_factory=list)
    off: list[str] = field(default_factory=list)


def parse_review(text: str) -> Review:
    """The edited review file: its sections, blocks and free text; ``<!--`` lines ignored."""
    review, section = Review(), ""
    for line in text.split("\n"):
        if line.startswith("<!--"):
            continue
        if line in SECTIONS:
            section = SECTIONS[line]
        elif section == "summary":
            review.summary.append(line)
        elif section in {"blocking", "minor"} and (match := BLOCK.fullmatch(line)):
            number = int(match.group(2)) if match.group(2) else None
            review.comments.append(Comment(section, match.group(1).strip(), number))
        elif section in {"blocking", "minor"} and review.comments:
            review.comments[-1].lines.append(line)
        elif section in {"blocking", "minor", "off"}:
            review.off.append(line)
    review.comments = [comment for comment in review.comments if comment.body]
    return review


def safe_path(path: str) -> str:
    parts = path.split("/")
    if not path or path.startswith("/") or ".." in parts or CONTROL.search(path) or "\\" in path:
        raise RefusedError(f"comments.path is not a path in the repo: {one_line(path, 80)}")
    return path


def listing(label: str, items: list[tuple[str, str]]) -> str:
    lines = [f"- `{where}` {body.split(chr(10), 1)[0]}" for where, body in items]
    return "\n".join([f"{label} ({len(items)})", *lines])


def payload(
    review: Review, anchors: dict[str, set[int]], *, head: str
) -> tuple[dict[str, object], dict[str, int]]:
    """What /review posts (no event: it makes a pending review first), and its counts."""
    comments: list[dict[str, object]] = []
    listed_items: dict[str, list[tuple[str, str]]] = {"Blocking": [], "Optional": []}
    off = "\n".join(review.off).strip()
    moved: list[str] = []
    for comment in review.comments:
        path, label = safe_path(comment.path), LABELS[comment.severity]
        listed_items[label[2:-3]].append((anchor(path, comment.line), comment.body))
        if comment.line in anchors.get(path, set()):
            body = f"{label} {comment.body}"
            if len(body) > COMMENT_CAP:
                raise RefusedError(f"comments.body is over {COMMENT_CAP} characters at {path}")
            comments.append({"path": path, "line": comment.line, "side": "RIGHT", "body": body})
        else:
            moved.append(f"{label} `{anchor(path, comment.line)}`: {comment.body}")
    for line in review.off:
        if match := LISTED.fullmatch(line):
            listed_items[match.group(1)].append((match.group(2), match.group(3)))
    if len(comments) > COMMENTS_MAX:
        raise RefusedError(f"comments are over {COMMENTS_MAX}")
    parts = [
        "\n".join(review.summary).strip(),
        listing("Blocking", listed_items["Blocking"]),
        listing("Optional", listed_items["Optional"]),
        "\n".join([off, *moved]).strip(),
    ]
    body = "\n\n".join(part for part in parts if part)
    if len(body) > BODY_CAP:
        raise RefusedError(f"body is over {BODY_CAP} characters")
    counts = {
        "blocking": len(listed_items["Blocking"]),
        "optional": len(listed_items["Optional"]),
        "inline": len(comments),
    }
    return {"commit_id": head, "body": body, "comments": comments}, counts


def read_review(path: Path) -> str:
    """The review file: a regular file (not a link), at most ``REVIEW_CAP`` bytes of UTF-8."""
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise RefusedError(f"cannot read the review: {error.strerror}") from None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise RefusedError("cannot read the review: not a regular file")
        data = handle.read(REVIEW_CAP + 1)
    if len(data) > REVIEW_CAP:
        raise RefusedError(f"cannot read the review: over {REVIEW_CAP} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise RefusedError("cannot read the review: not UTF-8") from None


def write_payload(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(data)


def run_final(given: argparse.Namespace) -> int:
    event = EVENTS.get(given.decision)
    if event is None:
        raise InputError("decision must be comment, request-changes or approve")
    if not (SHA.fullmatch(given.base) and SHA.fullmatch(given.head)):
        raise InputError("base and head must be full commit shas")
    run = run_id()
    if given.file != str(FOLDER / f"{run}.md"):
        raise RefusedError("cannot read the review: not this run's file")
    text = read_review(FOLDER / f"{run}.md")
    if ATTRIBUTION.search(text):
        raise RefusedError("the review holds AI attribution: remove it and run /review again")
    anchors = hunks(git_diff(given.path, given.base, given.head))
    sent, counts = payload(parse_review(text), anchors, head=given.head)
    data = (json.dumps(sent, ensure_ascii=False) + "\n").encode()
    path = FOLDER / f"{run}.payload.json"
    write_payload(path, data)
    digest = hashlib.sha256(data).hexdigest()
    print(json.dumps({"path": str(path), "sha256": digest, "event": event, **counts}))
    return 0


def parser_of() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="review.py")
    commands = parser.add_subparsers(dest="command", required=True)
    merge = commands.add_parser("merge")
    for lens in LENSES:
        merge.add_argument(f"--{lens}", required=True)
    compose = commands.add_parser("compose")
    for name in ("--findings", "--path", "--base", "--head", "--repo", "--pr"):
        compose.add_argument(name, required=True)
    final = commands.add_parser("final")
    for name in ("--file", "--decision", "--path", "--base", "--head"):
        final.add_argument(name, required=True)
    return parser


def main(argv: list[str]) -> int:
    given = parser_of().parse_args(argv)
    runs = {"merge": run_merge, "compose": run_compose, "final": run_final}
    try:
        return runs[given.command](given)
    except InputError as error:
        print(f"review.py: {error}", file=sys.stderr)
        return 2
    except RefusedError as error:
        print(f"review.py: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
