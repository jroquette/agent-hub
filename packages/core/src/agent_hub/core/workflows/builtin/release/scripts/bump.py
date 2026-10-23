# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Make the release commit in the platform repo's checkout (the node's cwd), and print it as JSON.

``bump.py --version X.Y.Z --previous X.Y.Z --last-tag vX.Y.Z --issue <team>-<n>
--regenerate <command> [--today YYYY-MM-DD]`` makes the edits a release PR makes, as the
previous ones did: ``version`` of the two pyprojects ``scripts/check_release.py`` keeps in
lockstep and their two ``uv.lock`` entries (as text: only those lines change, no network);
``CHANGELOG.md`` turns ``[Unreleased]`` into the new version's section and adds its compare
link; ``README.md`` replaces the previous version as a whole token; the ``docs/SPEC.md`` status
line names the date and the release (its prose phrase is the owner's, in the PR). Then it runs
``--regenerate`` (split as a shell would, no shell; the repo's generated files) and commits once,
``chore(repo): release X.Y.Z (<issue>)``, with git hooks off. Only ``RELEASE_FILES`` may change;
the repo's ``scripts/check_release.py --root .`` runs before the commit when the repo has one.
Any failure puts the checkout back on the commit it started from; a re-run that finds its own
release commit on ``HEAD`` (a clean checkout) prints it again.

Prints ``{"version", "previous", "sha", "files", "changelog", "changelog_empty",
"readme_replaced", "lockstep"}``: ``changelog`` is the new section (at most ``MAX_SECTION``
bytes). A bad argument, or a release file that is missing, not UTF-8, larger than 4 MiB or
without what the edit needs exits 2; a dirty checkout, a failed command, a change outside the
release files or a failed release check exits 1. Both say why on stderr.
"""

import argparse
import datetime
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

PROG = "bump.py"
CLI_PYPROJECT = "packages/cli/pyproject.toml"
META_PYPROJECT = "packages/agent-hub/pyproject.toml"
LOCK_PACKAGES = ("agent-hub", "agent-hub-cli")
EDITED_FILES = (
    "CHANGELOG.md",
    "README.md",
    "docs/SPEC.md",
    CLI_PYPROJECT,
    META_PYPROJECT,
    "uv.lock",
)
# What the release commit may change: the edited files and what --regenerate rewrites from them.
RELEASE_FILES = frozenset({*EDITED_FILES, "llms.txt", "llms-full.txt"})
CHECK_RELEASE = "scripts/check_release.py"
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_SECTION = 32 * 1024
COMMAND_TIMEOUT = 600
VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+")
ISSUE = re.compile(r"[A-Za-z][A-Za-z0-9]{0,15}-[0-9]{1,9}")
DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
UNRELEASED = "## [Unreleased]\n"
UNRELEASED_LINK = re.compile(r"^\[Unreleased\]: (\S+)/compare/\S+\.\.\.HEAD$", re.MULTILINE)


class RefusedError(Exception):
    """Bad input: exit 2."""


class FailedError(Exception):
    """A command, the checkout or the release check failed: exit 1."""


def _one(pattern: str, replacement: str, text: str, *, where: str) -> str:
    found, count = re.subn(pattern, replacement, text, count=2, flags=re.MULTILINE)
    if count != 1:
        raise RefusedError(f"{where}: expected one match of {pattern!r}, found {count}")
    return found


def set_project_version(text: str, previous: str, version: str, *, where: str) -> str:
    """The ``[project]`` table's ``version`` line only; other tables' keep theirs."""
    head, bracket, rest = text.partition("\n[")
    pattern = rf'^version = "{re.escape(previous)}"$'
    return _one(pattern, f'version = "{version}"', head, where=where) + bracket + rest


def set_lock_versions(text: str, previous: str, version: str) -> str:
    for name in LOCK_PACKAGES:
        pattern = rf'^(name = "{re.escape(name)}"\n)version = "{re.escape(previous)}"$'
        text = _one(pattern, rf'\g<1>version = "{version}"', text, where="uv.lock")
    return text


def open_section(text: str, *, version: str, last_tag: str, today: str) -> str:
    """``[Unreleased]`` becomes the version's section; its compare links follow."""
    if text.count(UNRELEASED) != 1:
        raise RefusedError("CHANGELOG.md: expected one '## [Unreleased]' heading")
    link = UNRELEASED_LINK.search(text)
    if link is None:
        raise RefusedError("CHANGELOG.md: no '[Unreleased]: <url>/compare/<tag>...HEAD' link")
    base = link.group(1)
    links = (
        f"[Unreleased]: {base}/compare/v{version}...HEAD\n"
        f"[{version}]: {base}/compare/{last_tag}...v{version}"
    )
    text = text[: link.start()] + links + text[link.end() :]
    return text.replace(UNRELEASED, f"{UNRELEASED}\n## [{version}] - {today}\n", 1)


def section(text: str, version: str) -> str:
    """The version's CHANGELOG section, without its heading, cut to ``MAX_SECTION`` bytes."""
    heading = re.search(rf"^## \[{re.escape(version)}\] - .*$", text, re.MULTILINE)
    if heading is None:
        return ""
    rest = text[heading.end() :]
    end = re.search(r"^## \[|^\[[^\]]+\]: ", rest, re.MULTILINE)
    found = (rest if end is None else rest[: end.start()]).strip()
    return found.encode()[:MAX_SECTION].decode(errors="ignore")


def replace_tokens(text: str, previous: str, version: str) -> tuple[str, int]:
    """The previous version as a whole token (not inside ``0.20.10`` or ``10.20.1``)."""
    pattern = rf"(?<![0-9.]){re.escape(previous)}(?![0-9]|\.[0-9])"
    return re.subn(pattern, version, text)


def set_status(text: str, previous: str, *, version: str, today: str) -> str:
    pattern = rf"^Status \([0-9-]+, latest release v{re.escape(previous)};"
    return _one(pattern, f"Status ({today}, latest release v{version};", text, where="docs/SPEC.md")


def edits(
    files: dict[str, str], *, version: str, previous: str, last_tag: str, today: str
) -> dict[str, str]:
    """Each release file's new text (pure)."""
    readme, _ = replace_tokens(files["README.md"], previous, version)
    return {
        "CHANGELOG.md": open_section(
            files["CHANGELOG.md"], version=version, last_tag=last_tag, today=today
        ),
        "README.md": readme,
        "docs/SPEC.md": set_status(files["docs/SPEC.md"], previous, version=version, today=today),
        CLI_PYPROJECT: set_project_version(
            files[CLI_PYPROJECT], previous, version, where=CLI_PYPROJECT
        ),
        META_PYPROJECT: set_project_version(
            files[META_PYPROJECT], previous, version, where=META_PYPROJECT
        ),
        "uv.lock": set_lock_versions(files["uv.lock"], previous, version),
    }


def read_file(root: Path, name: str) -> str:
    path = root / name
    try:
        if path.is_symlink() or not path.is_file():
            raise RefusedError(f"{name}: not a regular file")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise RefusedError(f"{name}: larger than 4 MiB")
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise RefusedError(f"{name}: {error}") from None


def _run(command: list[str], root: Path) -> str:
    try:
        done = subprocess.run(  # noqa: S603 - git, the release check or the given regenerate
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise FailedError(f"{shlex.join(command)}: {error}") from None
    if done.returncode != 0:
        tail = "\n".join((done.stdout + done.stderr).strip().splitlines()[-20:])
        raise FailedError(f"{shlex.join(command)} exited {done.returncode}: {tail}")
    return done.stdout


def _git(root: Path, *args: str) -> str:
    return _run(["git", "-c", "core.hooksPath=/dev/null", *args], root)


def changed(root: Path) -> list[str]:
    status = _git(root, "status", "--porcelain", "--untracked-files=all", "-z")
    return sorted(entry[3:] for entry in status.split("\0") if entry)


def _checked(given: argparse.Namespace) -> None:
    for name in ("version", "previous"):
        if not VERSION.fullmatch(getattr(given, name)):
            raise RefusedError(f"--{name} must be X.Y.Z with ASCII digits")
    if given.last_tag != f"v{given.previous}":
        raise RefusedError("--last-tag must be v + --previous")
    if not ISSUE.fullmatch(given.issue):
        raise RefusedError("--issue must be <team>-<n>")
    if not DAY.fullmatch(given.today):
        raise RefusedError("--today must be YYYY-MM-DD")


def _lockstep(root: Path) -> str:
    """The repo's release check on the files as they are, when the repo has one."""
    if not (root / CHECK_RELEASE).is_file():
        return ""
    lines = _run([sys.executable, CHECK_RELEASE, "--root", "."], root).strip().splitlines()
    return lines[-1] if lines else ""


def _restore(root: Path, base: str) -> None:
    """Put the checkout back on ``base``, clean, after a failed run (best effort)."""
    for args in (("reset", "-q", "--hard", base), ("clean", "-fdq")):
        try:
            _git(root, *args)
        except FailedError:
            return


def _result(
    root: Path, given: argparse.Namespace, *, readme: str, lockstep: str
) -> dict[str, object]:
    """What the release commit on HEAD holds; ``readme`` is the README before it."""
    changelog = section(read_file(root, "CHANGELOG.md"), given.version)
    return {
        "version": given.version,
        "previous": given.previous,
        "sha": _git(root, "rev-parse", "HEAD").strip(),
        "files": sorted(_git(root, "diff", "--name-only", "HEAD^", "HEAD").split()),
        "changelog": changelog,
        "changelog_empty": not changelog,
        "readme_replaced": replace_tokens(readme, given.previous, given.version)[1],
        "lockstep": lockstep,
    }


def _commit(root: Path, given: argparse.Namespace, *, subject: str) -> dict[str, str]:
    """Edit, regenerate, check and commit; the release files as they were before."""
    files = {name: read_file(root, name) for name in EDITED_FILES}
    texts = edits(
        files,
        version=given.version,
        previous=given.previous,
        last_tag=given.last_tag,
        today=given.today,
    )
    for name, text in texts.items():
        (root / name).write_text(text, encoding="utf-8")
    _run(shlex.split(given.regenerate), root)
    touched = changed(root)
    outside = [name for name in touched if name not in RELEASE_FILES]
    if outside:
        raise FailedError(f"the release changed files outside the release files: {outside}")
    lockstep = _lockstep(root)
    _git(root, "add", "--", *touched)
    _git(root, "commit", "-q", "-m", subject)
    return {"readme": files["README.md"], "lockstep": lockstep}


def release(root: Path, given: argparse.Namespace) -> dict[str, object]:
    """Make the release commit, or find this run's own on HEAD (a re-run); undo a failed one."""
    _checked(given)
    subject = f"chore(repo): release {given.version} ({given.issue})"
    clean = not changed(root)
    if clean and _git(root, "log", "-1", "--format=%s").strip() == subject:
        readme = _git(root, "show", "HEAD^:README.md")
        return _result(root, given, readme=readme, lockstep=_lockstep(root))
    if not clean:
        raise FailedError("the checkout is not clean; the release commit holds only its edits")
    base = _git(root, "rev-parse", "HEAD").strip()
    try:
        made = _commit(root, given, subject=subject)
    except FailedError, RefusedError:
        _restore(root, base)
        raise
    return _result(root, given, readme=made["readme"], lockstep=made["lockstep"])


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog=PROG)
    for name in ("--version", "--previous", "--last-tag", "--issue", "--regenerate"):
        parser.add_argument(name, required=True)
    parser.add_argument("--today", default=datetime.datetime.now(datetime.UTC).date().isoformat())
    given = parser.parse_args(argv)
    try:
        found = release(Path.cwd().resolve(), given)
    except RefusedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 2
    except FailedError as error:
        print(f"{PROG}: {error}", file=sys.stderr)
        return 1
    print(json.dumps(found))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
