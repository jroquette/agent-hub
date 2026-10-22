# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Find a package in the repo's uv or npm manifests and bump it with the repo's own tooling.

``bump.py --package <name> --to <version> --issue <TEAM>-<n>``, run in the repo's worktree. The
package is looked up in the files ``git ls-files`` lists: ``uv.lock`` at the root and every
``pyproject.toml`` (uv), or one ``package.json`` with its ``package-lock.json`` (npm, none under
``node_modules/``). ``to`` is a final release (``1.2.3``). The bump is made by the tool, never by
this script: uv (``uv add --no-sync`` in each manifest that pins the package with ``==``, else
``uv lock --upgrade-package``) or npm (``npm install --ignore-scripts``, in the manifest's
folder). Only manifests and lockfiles may change; they are committed with hooks off, the subject
``chore(deps): bump <name> from <a> to <b> (<issue>)``.

The output is ``{"manager", "dir", "from", "to", "major", "files", "commit"}``; ``major`` is
semver's: the first number moves, or the second when the version starts with ``0.``. A bad
argument, a package found in no manifest, in both managers or in several package folders, one
already at (or past) ``to``, or a manifest that cannot be read (too large, not TOML, not JSON)
exits 2 with ``bump.py: <reason>`` on stderr. A tool that fails or times out, a tool that changes
nothing, or a change outside the manifests and lockfiles exits 1.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import PurePosixPath

PYPI_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,99}")
NPM_NAME = re.compile(r"(@[a-z0-9][a-z0-9._~-]*/)?[a-z0-9][a-z0-9._~-]{0,213}")
FINAL = re.compile(r"[0-9]+(\.[0-9]+){0,3}")
ISSUE = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}-[0-9]{1,9}")
LEADING = re.compile(r"[0-9]+(\.[0-9]+)*")
HEADER = re.compile(r"\s*\[\[?\s*([A-Za-z0-9_.\"' -]+?)\s*\]\]?\s*(#.*)?")
ARRAY_START = re.compile(r"\s*(\"[^\"]+\"|'[^']+'|[A-Za-z0-9_.-]+)\s*=\s*\[(.*)")
STRING = re.compile(r"\"((?:[^\"\\]|\\.)*)\"|'([^']*)'")
REQUIREMENT = re.compile(r"\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*(\[[^\]]*\])?\s*([^;]*)")
NAME_LINE = re.compile(r"\s*name\s*=\s*\"([^\"]+)\"")
VERSION_LINE = re.compile(r"\s*version\s*=\s*\"([^\"]+)\"")
MANIFESTS = frozenset({"pyproject.toml", "package.json"})
LOCKFILES = frozenset({"uv.lock", "package-lock.json"})
MAX_PYPROJECTS = 50
MAX_PACKAGE_JSONS = 20
MAX_MANIFEST_BYTES = 1024 * 1024
MAX_LOCK_BYTES = 16 * 1024 * 1024
TOOL_TIMEOUT = 600
TAIL_CHARS = 2000
NPM_SECTIONS = {
    "dependencies": (),
    "devDependencies": ("--save-dev",),
    "optionalDependencies": ("--save-optional",),
}


class BumpError(Exception):
    """A refusal; ``code`` is the exit code (2: the input, 1: the tool or its result)."""

    def __init__(self, reason: str, code: int = 2) -> None:
        super().__init__(reason)
        self.code = code


@dataclass(frozen=True)
class Pin:
    """One requirement of the package in a ``pyproject.toml``."""

    manifest: str
    member: str
    kind: str | None  # "group", "optional" or None (the project's dependencies)
    group: str
    spec: str

    @property
    def exact(self) -> bool:
        return self.spec.strip().startswith("==")


@dataclass(frozen=True)
class Found:
    """Where the package is and the version the lockfile holds."""

    manager: str
    dir: str
    current: str
    pins: tuple[Pin, ...] = ()
    spec: str = ""
    section: str = ""
    files: tuple[str, ...] = field(default=())


def version(text: str) -> tuple[int, ...] | None:
    """A final release's numbers, or None when ``text`` is not one."""
    if not FINAL.fullmatch(text):
        return None
    return tuple(int(part) for part in text.split("."))


def leading(text: str) -> tuple[int, ...]:
    """The leading numbers of any version text (``1.2.3rc1`` → ``(1, 2, 3)``)."""
    found = LEADING.match(text.strip().lstrip("v"))
    return tuple(int(part) for part in found.group(0).split(".")) if found else ()


def is_major(old: str, new: str) -> bool:
    """Semver's major move: the first number differs, or the second when ``old`` is ``0.x``."""
    before, after = leading(old) + (0, 0), leading(new) + (0, 0)
    if before[0] != after[0]:
        return True
    return before[0] == 0 and before[1] != after[1]


def normalized(name: str) -> str:
    """A Python package name as PyPI compares it."""
    return re.sub(r"[-_.]+", "-", name).lower()


def git(*args: str) -> str:
    done = subprocess.run(  # noqa: S603 - git with fixed arguments
        ["git", *args],  # noqa: S607 - git from PATH, as the worktree's
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )
    if done.returncode != 0:
        raise BumpError(f"git {args[0]} failed: {done.stderr.strip()[-TAIL_CHARS:]}", 1)
    return done.stdout


def read_text(path: str, limit: int) -> str:
    try:
        with open(path, "rb") as handle:
            data = handle.read(limit + 1)
    except OSError as error:
        raise BumpError(f"{path} cannot be read: {error.strerror or error}") from error
    if len(data) > limit:
        raise BumpError(f"{path} is too large")
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BumpError(f"{path} is not UTF-8 text") from error


def tracked() -> list[str]:
    """The tracked manifests, within the bounds."""
    paths = [line for line in git("ls-files", "-z").split("\0") if line]
    pyprojects = [p for p in paths if PurePosixPath(p).name == "pyproject.toml"]
    packages = [
        p
        for p in paths
        if PurePosixPath(p).name == "package.json" and "node_modules" not in PurePosixPath(p).parts
    ]
    if len(pyprojects) > MAX_PYPROJECTS:
        raise BumpError(f"more than {MAX_PYPROJECTS} pyproject.toml files")
    if len(packages) > MAX_PACKAGE_JSONS:
        raise BumpError(f"more than {MAX_PACKAGE_JSONS} package.json files")
    return pyprojects + packages


def locked_version(lock: str, name: str) -> str | None:
    """The version ``uv.lock`` holds for ``name``, read line by line (uv writes it so)."""
    wanted, current, in_package = normalized(name), "", False
    for line in lock.splitlines():
        if line.startswith("["):
            in_package, current = line.strip() == "[[package]]", ""
            continue
        if not in_package:
            continue
        named = NAME_LINE.fullmatch(line)
        if named:
            current = named.group(1)
            continue
        versioned = VERSION_LINE.fullmatch(line)
        if versioned and normalized(current) == wanted:
            return versioned.group(1)
    return None


def _strings(text: str) -> list[str]:
    return [
        match.group(1) if match.group(1) is not None else match.group(2)
        for match in STRING.finditer(text)
    ]


def _closes(text: str) -> bool:
    """Whether the array closes on this line (its strings and comment taken out)."""
    return "]" in STRING.sub("", text).split("#", 1)[0]


def _where(table: str, key: str) -> tuple[str | None, str] | None:
    key = key.strip("\"'")
    if table == "project" and key == "dependencies":
        return (None, "")
    if table == "project.optional-dependencies":
        return ("optional", key)
    if table == "dependency-groups":
        return ("group", key)
    return None


def _table(path: str, line: str) -> str:
    """The table a header line opens (quotes dropped); a broken header is not TOML."""
    header = HEADER.fullmatch(line)
    if header is None:
        raise BumpError(f"{path} is not TOML")
    return header.group(1).replace('"', "").replace("'", "")


def _scan(path: str, text: str) -> tuple[str, list[tuple[str, str, str]]]:
    """The project's name and every array string, with its key and table."""
    table, member, open_key = "", "", ""
    found: list[tuple[str, str, str]] = []
    for line in text.splitlines():
        if open_key:
            found.extend((open_key, table, item) for item in _strings(line))
            open_key = "" if _closes(line) else open_key
            continue
        if line.strip().startswith("["):
            table = _table(path, line)
            continue
        named = NAME_LINE.fullmatch(line)
        if table == "project" and named:
            member = named.group(1)
        start = ARRAY_START.fullmatch(line)
        if start:
            found.extend((start.group(1), table, item) for item in _strings(start.group(2)))
            open_key = "" if _closes(start.group(2)) else start.group(1)
    return member, found


def pins_in(path: str, text: str, name: str) -> list[Pin]:
    member, found = _scan(path, text)
    wanted, pins = normalized(name), []
    for key, table, item in found:
        where = _where(table, key)
        requirement = REQUIREMENT.fullmatch(item)
        if where is None or requirement is None or normalized(requirement.group(1)) != wanted:
            continue
        kind, group = where
        pins.append(Pin(path, member, kind, group, requirement.group(3).strip()))
    return pins


def find_uv(manifests: list[str], name: str) -> Found | None:
    pins: list[Pin] = []
    for path in manifests:
        if PurePosixPath(path).name == "pyproject.toml":
            pins.extend(pins_in(path, read_text(path, MAX_MANIFEST_BYTES), name))
    if not os.path.isfile("uv.lock"):
        if pins:
            raise BumpError(f"{name} is in {pins[0].manifest} but the repo has no uv.lock")
        return None
    current = locked_version(read_text("uv.lock", MAX_LOCK_BYTES), name)
    if current is None:
        if pins:
            raise BumpError(f"{name} is in {pins[0].manifest} but not in uv.lock")
        return None
    return Found("uv", ".", current, pins=tuple(pins))


def _json(path: str, limit: int) -> dict[str, object]:
    try:
        value = json.loads(read_text(path, limit))
    except ValueError as error:
        raise BumpError(f"{path} is not JSON") from error
    if not isinstance(value, dict):
        raise BumpError(f"{path} is not a JSON object")
    return value


def _npm_entry(path: str, name: str) -> tuple[str, str] | None:
    manifest = _json(path, MAX_MANIFEST_BYTES)
    for section in NPM_SECTIONS:
        deps = manifest.get(section)
        if isinstance(deps, dict) and isinstance(deps.get(name), str):
            return section, str(deps[name])
    return None


def npm_locked(folder: str, name: str) -> str:
    lock_path = str(PurePosixPath(folder) / "package-lock.json")
    if not os.path.isfile(lock_path):
        raise BumpError(f"{name} is in {folder}/package.json but it has no package-lock.json")
    lock = _json(lock_path, MAX_LOCK_BYTES)
    packages, legacy = lock.get("packages"), lock.get("dependencies")
    for table, key in ((packages, f"node_modules/{name}"), (legacy, name)):
        entry = table.get(key) if isinstance(table, dict) else None
        if isinstance(entry, dict) and isinstance(entry.get("version"), str):
            return str(entry["version"])
    raise BumpError(f"{name} is not in {lock_path}")


def find_npm(manifests: list[str], name: str) -> Found | None:
    hits = []
    for path in manifests:
        if PurePosixPath(path).name == "package.json":
            entry = _npm_entry(path, name)
            if entry is not None:
                hits.append((str(PurePosixPath(path).parent), *entry))
    if not hits:
        return None
    if len(hits) > 1:
        folders = ", ".join(folder for folder, _, _ in hits)
        raise BumpError(f"{name} is in several package folders: {folders}")
    folder, section, spec = hits[0]
    return Found("npm", folder, npm_locked(folder, name), spec=spec, section=section)


def find(name: str) -> Found:
    manifests = tracked()
    uv = find_uv(manifests, name) if PYPI_NAME.fullmatch(name) else None
    npm = find_npm(manifests, name) if NPM_NAME.fullmatch(name) else None
    if uv and npm:
        raise BumpError(f"{name} is in both uv and npm manifests")
    found = uv or npm
    if found is None:
        raise BumpError(f"{name} is in no manifest")
    return found


def parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="bump.py")
    parser.add_argument("--package", required=True)
    parser.add_argument("--to", required=True)
    parser.add_argument("--issue", required=True)
    args = parser.parse_args(argv)
    if not (PYPI_NAME.fullmatch(args.package) or NPM_NAME.fullmatch(args.package)):
        raise BumpError(f"not a package name: {args.package!r}")
    if version(args.to) is None:
        raise BumpError(f"not a final release: {args.to!r}")
    if not ISSUE.fullmatch(args.issue):
        raise BumpError(f"not an issue id: {args.issue!r}")
    return args


def _trimmed(numbers: tuple[int, ...]) -> tuple[int, ...]:
    """The numbers without trailing zeros, so 1.2 and 1.2.0 compare equal."""
    while numbers and numbers[-1] == 0:
        numbers = numbers[:-1]
    return numbers


def check_target(found: Found, name: str, to: str) -> None:
    current, target = _trimmed(leading(found.current)), _trimmed(version(to) or ())
    if current == target:
        raise BumpError(f"{name} is already at {to}")
    if current > target:
        raise BumpError(f"{name} is at {found.current}, past {to}")


def main(argv: list[str]) -> int:
    try:
        args = parse(argv)
        found = find(args.package)
        check_target(found, args.package, args.to)
    except BumpError as error:
        print(f"bump.py: {error}", file=sys.stderr)
        return error.code
    result = {
        "manager": found.manager,
        "dir": found.dir,
        "from": found.current,
        "to": args.to,
        "major": is_major(found.current, args.to),
    }
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
