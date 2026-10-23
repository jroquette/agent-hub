# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Read a PR's facts from the files /review wrote and the local clone; print them as JSON.

``fetch.py --repo <dir> --pr <n> --ref refs/agent-hub/review/<n> --pr-file <abs> --ci-file <abs>
--spec-file <abs> --config <json>``, run in the hub; ``--config`` is the ``config`` node's
output, the CLI's read of the hub's config (the repo's check and the team keys; this script
opens no ``hub.json``). Read-only: it
runs only git reads in the clone ``../<dir>``. Every file is untrusted: an absolute path to a
regular file (not a link), within its byte cap, UTF-8. Its text loses control characters (but
newline and tab) and runs of three or more backticks, and is cut to its bound.

The output: ``{number, url, title, body, body_cut, author, fork, head_sha, head_ref, base_ref,
merge_base, path, hub, check, files[], more_files, ci{state, runs[], more}, issues[], spec}``,
``path`` the clone and ``hub`` the hub, both absolute; ``fork`` when the head repo is deleted or
another one. Bad input exits 2 with ``fetch.py: <reason>`` on stderr: a ``pr`` that is not a
number, a ``ref`` other than the review ref, an unknown repo, an unreadable file, a closed or
merged PR, a ref that is not the PR's head (the PR moved), or no ``origin/<base>``. A CI file
that cannot be read is ``ci.state: unknown`` (CI is context).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import stat
import subprocess
import sys
from pathlib import Path

PR_CAP = 1024 * 1024
CI_CAP = 1024 * 1024
SPEC_CAP = 32768
TITLE_CHARS = 256
BODY_CHARS = 16384
BODY_BYTES = 32768
NAME_CHARS = 255
AUTHOR_CHARS = 100
URL_CHARS = 512
FILES_MAX = 200
PATH_CHARS = 300
FILES_BYTES = 24576
RUNS_MAX = 30
RUN_NAME_CHARS = 100
RUN_FIELD_CHARS = 32
ISSUES_MAX = 10
NUMBER = re.compile(r"[1-9][0-9]{0,8}")
SHA = re.compile(r"[0-9a-f]{40}")
BRANCH = re.compile(r"[A-Za-z0-9._/-]{1,255}")
CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
BACKTICKS = re.compile(r"`{3,}")
FAILED = {"failure", "timed_out", "cancelled", "action_required", "startup_failure"}
GIT = ("git", "-c", "core.hooksPath=/dev/null", "-c", "core.fsmonitor=false")


class InputError(ValueError):
    """Bad input: the run cannot review this PR as given."""


def clean(text: str, limit: int, *, one_line: bool = False) -> str:
    """``text`` without control characters or backtick fences, at most ``limit`` characters."""
    text = text.replace("\r\n", "\n")
    if one_line:
        text = text.replace("\n", " ").replace("\t", " ")
    return BACKTICKS.sub("`", CONTROL.sub("", text))[:limit]


def text_of(value: object) -> str:
    return value if isinstance(value, str) else ""


def read_bounded(path: str, cap: int, name: str) -> str:
    """The UTF-8 text of the regular file at the absolute ``path``, at most ``cap`` bytes."""
    if not os.path.isabs(path):
        raise InputError(f"cannot read {name}: not an absolute path")
    try:
        # O_NOFOLLOW: a link is refused when opened, not only when looked at.
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError as error:
        raise InputError(f"cannot read {name}: {error.strerror}") from None
    with os.fdopen(descriptor, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise InputError(f"cannot read {name}: not a regular file")
        data = handle.read(cap + 1)
    if len(data) > cap:
        raise InputError(f"cannot read {name}: over {cap} bytes")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        raise InputError(f"cannot read {name}: not UTF-8") from None


def field(value: object, *path: str) -> object:
    for key in path:
        value = value.get(key) if isinstance(value, dict) else None
    return value


def bounded_body(body: str) -> tuple[str, bool]:
    cut = clean(body, BODY_CHARS)
    while len(cut.encode()) > BODY_BYTES:
        cut = cut[: len(cut) - (len(cut.encode()) - BODY_BYTES + 3) // 4 - 1]
    # Cut when the bounds dropped text: compared with the same cleaning and no bound.
    return cut, cut != clean(body, len(body))


def pr_facts(pr: object, number: int) -> dict[str, object]:
    """The PR's facts from the REST ``pulls/<n>`` JSON, bounded; a wrong shape is an error."""
    if field(pr, "number") != number:
        raise InputError("not a PR: number")
    sha = field(pr, "head", "sha")
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise InputError("not a PR: head.sha")
    base = field(pr, "base", "ref")
    if not isinstance(base, str) or not BRANCH.fullmatch(base) or ".." in base:
        raise InputError("not a PR: base.ref")
    if base.startswith(("-", "/")):
        raise InputError("not a PR: base.ref")
    if field(pr, "state") != "open" or field(pr, "merged") is True or field(pr, "merged_at"):
        raise InputError(f"PR #{number} is closed or merged")
    head_repo = field(pr, "head", "repo", "full_name")
    body, cut = bounded_body(text_of(field(pr, "body")))
    return {
        "number": number,
        "url": clean(text_of(field(pr, "html_url")), URL_CHARS, one_line=True),
        "title": clean(text_of(field(pr, "title")), TITLE_CHARS, one_line=True),
        "body": body,
        "body_cut": cut,
        "author": clean(text_of(field(pr, "user", "login")), AUTHOR_CHARS, one_line=True),
        "fork": not isinstance(head_repo, str)
        or head_repo != field(pr, "base", "repo", "full_name"),
        "head_sha": sha,
        "head_ref": clean(text_of(field(pr, "head", "ref")), NAME_CHARS, one_line=True),
        "base_ref": base,
    }


def ci_state(runs: list[dict[str, str]]) -> str:
    if not runs:
        return "none"
    if any(run["conclusion"] in FAILED for run in runs):
        return "failure"
    if any(run["status"] != "completed" for run in runs):
        return "pending"
    return "success"


def ci_summary(checks: object) -> dict[str, object]:
    """The head's check runs (REST ``commits/<sha>/check-runs``) as one state and 30 runs."""
    found = field(checks, "check_runs")
    if not isinstance(found, list):
        return {"state": "unknown", "runs": [], "more": False}
    runs = [
        {
            "name": clean(text_of(field(run, "name")), RUN_NAME_CHARS, one_line=True),
            "status": clean(text_of(field(run, "status")), RUN_FIELD_CHARS, one_line=True),
            "conclusion": clean(text_of(field(run, "conclusion")), RUN_FIELD_CHARS, one_line=True),
        }
        for run in found
    ]
    total = field(checks, "total_count")
    more = len(runs) > RUNS_MAX or (isinstance(total, int) and total > len(runs))
    return {"state": ci_state(runs), "runs": runs[:RUNS_MAX], "more": more}


def issue_keys(texts: list[str], keys: list[str]) -> list[str]:
    """The tracker issues (``<KEY>-<n>``, any case) named in ``texts``, in order, at most 10."""
    if not keys:
        return []
    alternatives = "|".join(re.escape(key) for key in keys)
    pattern = re.compile(rf"(?<![A-Za-z0-9])({alternatives})-([1-9][0-9]{{0,8}})(?![0-9])", re.I)
    found: list[str] = []
    for text in texts:
        for match in pattern.finditer(text):
            key = f"{match.group(1).upper()}-{match.group(2)}"
            if key not in found:
                found.append(key)
    return found[:ISSUES_MAX]


def hub_repo(repo: str, text: str) -> tuple[str, list[str]]:
    """The repo's ``check`` and the tracker team keys, from the ``config`` node's output."""
    if len(text.encode()) > PR_CAP:
        raise InputError("cannot read the config: too large")
    try:
        config = json.loads(text)
    except ValueError as error:
        raise InputError(f"cannot read the config: {error}") from None
    repos = field(config, "repos")
    if not isinstance(repos, list):
        raise InputError("cannot read the config: no repos list")
    entries = [entry for entry in repos if field(entry, "dir") == repo]
    if not entries:
        raise InputError(f"no repo {repo} in the config")
    teams = field(config, "teams")
    keys = teams if isinstance(teams, list) else []
    return text_of(field(entries[0], "check")), [key for key in keys if isinstance(key, str)]


def git(path: Path, *args: str) -> str | None:
    done = subprocess.run(  # noqa: S603 - git reads with fixed arguments, hooks off
        [*GIT, "-C", str(path), *args],
        capture_output=True,
        check=False,
        stdin=subprocess.DEVNULL,
    )
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def changed_files(path: Path, base: str, head: str) -> tuple[list[dict[str, str]], bool]:
    """The diff's files (status, path) within ``FILES_MAX`` and ``FILES_BYTES``."""
    listing = git(path, "diff", "--name-status", "--no-renames", "-z", base, head) or ""
    parts = listing.split("\0")
    entries = [(parts[i], parts[i + 1]) for i in range(0, len(parts) - 1, 2)]
    files: list[dict[str, str]] = []
    size = 0
    for status, name in entries[:FILES_MAX]:
        shown = clean(name, PATH_CHARS, one_line=True)
        size += len(shown.encode())
        if size > FILES_BYTES:
            break
        files.append({"status": clean(status, 8, one_line=True), "path": shown})
    return files, len(files) < len(entries)


def local_facts(path: Path, ref: str, *, head: str, base_ref: str) -> dict[str, object]:
    """The clone's view: the ref is the PR's head, and its merge base with ``origin/<base>``."""
    found = (git(path, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}") or "").strip()
    if found != head:
        raise InputError("the PR moved or the ref is missing; fetch again")
    origin = f"refs/remotes/origin/{base_ref}"
    if git(path, "rev-parse", "--verify", "--quiet", f"{origin}^{{commit}}") is None:
        raise InputError(f"no origin/{base_ref} in the clone; fetch again")
    merge_base = (git(path, "merge-base", origin, head) or "").strip()
    if not SHA.fullmatch(merge_base):
        raise InputError(f"no merge base of origin/{base_ref} and the head")
    files, more = changed_files(path, merge_base, head)
    return {"merge_base": merge_base, "files": files, "more_files": more}


def read_ci(path: str) -> dict[str, object]:
    try:
        return ci_summary(json.loads(read_bounded(path, CI_CAP, "ci_file")))
    except ValueError:
        return {"state": "unknown", "runs": [], "more": False}


def facts(given: argparse.Namespace) -> dict[str, object]:
    if not NUMBER.fullmatch(given.pr):
        raise InputError("pr must be a PR number")
    if given.ref != f"refs/agent-hub/review/{given.pr}":
        raise InputError("ref must be refs/agent-hub/review/<pr>")
    check, keys = hub_repo(given.repo, given.config)
    clone = (Path.cwd().parent / given.repo).resolve()
    if not clone.is_dir():
        raise InputError(f"no clone at ../{given.repo}")
    try:
        pr = json.loads(read_bounded(given.pr_file, PR_CAP, "pr_file"))
    except json.JSONDecodeError:
        raise InputError("not a PR: not JSON") from None
    found = pr_facts(pr, int(given.pr))
    spec = clean(read_bounded(given.spec_file, SPEC_CAP, "spec_file"), SPEC_CAP)
    local = local_facts(
        clone, given.ref, head=str(found["head_sha"]), base_ref=str(found["base_ref"])
    )
    texts = [str(found["title"]), str(found["head_ref"]), str(found["body"])]
    return {
        **found,
        **local,
        "path": str(clone),
        "hub": str(Path.cwd()),
        "check": check,
        "ci": read_ci(given.ci_file),
        "issues": issue_keys(texts, keys),
        "spec": spec,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="fetch.py")
    for name in ("--repo", "--pr", "--ref", "--pr-file", "--ci-file", "--spec-file", "--config"):
        parser.add_argument(name, required=True)
    given = parser.parse_args(argv)
    try:
        result = facts(given)
    except InputError as error:
        print(f"fetch.py: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
