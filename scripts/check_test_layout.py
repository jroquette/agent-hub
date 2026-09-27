"""Test layout checker: enforces where tests live and how tests and modules are named (ADR 0005).

``find_violations`` is pure: it takes repo-relative POSIX paths mapped to file contents (only
test files and the gate configs need real contents) and returns the violations. ``main`` lists
the repo files with git, prints ``<path>: <rule> <message>`` per violation and exits 1 if any.

Rules: level-folder, test-file-name, mirror, test-name, ticket-name, generic-name,
numbered-name, forbidden-module, package-registered.

The level of a test comes from ``scripts.pytest_levels.level_of``, the function the marker
plugin uses, so a test the checker accepts always gets the marker the checker expects.
Run it as ``python -m scripts.check_test_layout`` from the repo root.
"""

import ast
import configparser
import re
import subprocess
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from scripts.pytest_levels import level_of

PACKAGE_LEVELS = frozenset({"unit", "contract", "integration"})
ROOT_LEVELS = frozenset({"unit", "e2e"})
EXEMPT_TEST_DIR_FILES = frozenset({"conftest.py", "__init__.py"})
FORBIDDEN_MODULE_NAMES = frozenset({"utils", "util", "helpers", "helper", "common", "misc"})
GENERIC_WORDS = frozenset(
    {"misc", "utils", "util", "helpers", "helper", "common", "new", "temp", "tmp", "stuff"}
)
TEST_NAME = re.compile(r"^test_[a-z0-9]+(_[a-z0-9]+)*_when_[a-z0-9]+(_[a-z0-9]+)*$")
TICKET_NAME = re.compile(r"(?:^|_)(?:pr|agh|gh|issue|bug|ticket)_?\d+(?:_|$)")
NUMBERED_NAME = re.compile(r"_\d+$")
MYPY_CONFIG = "mypy.ini"
IMPORT_CONFIG = ".importlinter"
MAKEFILE = "Makefile"
# The COV variable's value, continuation lines included (C8).
COV_VARIABLE = re.compile(r"^COV\s*:?=((?:.*\\\n)*.*)$", re.MULTILINE)
COV_MODULE = re.compile(r"--cov=(agent_hub\.\w+)")
CORE = "core"
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Violation:
    """One broken layout rule, reported against a repo-relative path."""

    path: str
    rule: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.rule} {self.message}"


def find_violations(files: Mapping[str, str]) -> list[Violation]:
    """Return every layout violation in ``files`` (repo-relative path -> file contents)."""
    violations: list[Violation] = []
    for path, source in sorted(files.items()):
        violations.extend(_check_test_file(path, source, files))
        violations.extend(_check_forbidden_module(path))
    violations.extend(_check_packages_registered(files))
    return violations


def checked_level(path: str) -> str | None:
    """The level of the test at ``path``, or None when its location breaks ``level-folder``.

    Exactly one ``tests`` segment, at the repo root or right under ``packages/<name>/``, followed
    by a level allowed there (C9). The level itself is the marker plugin's ``level_of``.
    """
    parts = PurePosixPath(path).parts
    if parts.count("tests") != 1:
        return None
    if parts[0] == "tests":
        allowed = ROOT_LEVELS
    elif len(parts) > 2 and parts[0] == "packages" and parts[2] == "tests":
        allowed = PACKAGE_LEVELS
    else:
        return None
    level = level_of(path)
    return level if level in allowed else None


def split_git_listing(listing: str) -> list[str]:
    """Paths from ``git ls-files -z`` output: NUL-separated, never quoted or escaped."""
    return [path for path in listing.split("\0") if path]


def main(files: Mapping[str, str] | None = None) -> int:
    """Print the violations in ``files`` (default: the repo) and return the exit code."""
    violations = find_violations(_read_repo_files() if files is None else files)
    for violation in violations:
        print(violation)
    return 1 if violations else 0


# Test files: level-folder, mirror and the naming rules.


def _check_test_file(path: str, source: str, files: Mapping[str, str]) -> Iterator[Violation]:
    pure = PurePosixPath(path)
    if not _is_test_location(pure):
        return
    level = checked_level(path)
    if level is None:
        yield Violation(path, "level-folder", "tests must live under an allowed level folder")
    if not pure.name.startswith("test_"):
        message = "modules in a tests tree are test_*.py, conftest.py or __init__.py"
        yield Violation(path, "test-file-name", message)
        return
    if level == "unit" and not _mirrors_module(pure, files):
        yield Violation(path, "mirror", f"no src module matches {pure.name}")
    yield from _check_name(path, pure.stem, "file")
    yield from _check_test_functions(path, source)


def _is_test_location(path: PurePosixPath) -> bool:
    if path.suffix != ".py" or path.parts[0] not in {"packages", "tests"}:
        return False
    if path.name.startswith("test_"):
        return True
    return "tests" in path.parts[:-1] and path.name not in EXEMPT_TEST_DIR_FILES


def _mirrors_module(test_path: PurePosixPath, files: Mapping[str, str]) -> bool:
    """A unit test ``<tests>/unit/<rel>/test_<name>.py`` needs ``<root>/<rel>/<name>.py``.

    The root is each ``packages/<name>/src/agent_hub/<module>`` for package tests, and the repo
    root for root tests (so ``tests/unit/scripts/test_x.py`` mirrors ``scripts/x.py``).
    """
    parts = test_path.parts
    if parts[0] == "tests":
        roots = [""]
        relative = parts[2:-1]
    else:
        roots = _module_roots(parts[1], files)
        relative = parts[4:-1]
    module = "/".join((*relative, test_path.stem.removeprefix("test_")))
    candidates = {f"{module}.py", f"{module}/__init__.py"}
    return any(f"{root}{candidate}" in files for root in roots for candidate in candidates)


def _module_roots(package_dir: str, files: Mapping[str, str]) -> list[str]:
    prefix = f"packages/{package_dir}/src/agent_hub/"
    names = {path[len(prefix) :].split("/")[0] for path in files if path.startswith(prefix)}
    return [f"{prefix}{name}/" for name in sorted(names)]


def _check_test_functions(path: str, source: str) -> Iterator[Violation]:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError:
        return  # ruff reports it earlier in the gate
    for name in _test_function_names(tree):
        if not TEST_NAME.match(name):
            yield Violation(
                path, "test-name", f"{name} must match test_<behavior>_when_<condition>"
            )
        yield from _check_name(path, name, "function")


def _test_function_names(tree: ast.Module) -> Iterator[str]:
    functions = (ast.FunctionDef, ast.AsyncFunctionDef)
    for node in tree.body:
        if isinstance(node, functions) and node.name.startswith("test"):
            yield node.name
        elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            for member in node.body:
                if isinstance(member, functions) and member.name.startswith("test"):
                    yield member.name


def _check_name(path: str, name: str, kind: str) -> Iterator[Violation]:
    """Ticket, generic and numbered names; at most one of them per name, in that order."""
    words = name.removeprefix("test_").split("_when_")
    if TICKET_NAME.search(name):
        yield Violation(path, "ticket-name", f"{kind} {name}: name the behavior, not the ticket")
    elif words[0] in GENERIC_WORDS:
        yield Violation(path, "generic-name", f"{kind} {name}: name the behavior under test")
    elif any(NUMBERED_NAME.search(word) for word in words):
        yield Violation(path, "numbered-name", f"{kind} {name}: say what differs, not a number")


# Modules and packages: forbidden-module.


def _check_forbidden_module(path: str) -> Iterator[Violation]:
    """Generic names in scripts/, package src/ and tests trees (folder or module names)."""
    pure = PurePosixPath(path)
    parts = pure.parts
    if pure.suffix != ".py":
        return
    if parts[0] in {"scripts", "tests"}:
        names = parts[1:]
    elif parts[0] == "packages" and len(parts) > 2 and parts[2] in {"src", "tests"}:
        names = parts[3:]
    else:
        return
    if {PurePosixPath(name).stem for name in names} & FORBIDDEN_MODULE_NAMES:
        forbidden = "/".join(sorted(FORBIDDEN_MODULE_NAMES))
        message = (
            f"{forbidden} say nothing as module or folder names (src, scripts, tests); name it"
        )
        yield Violation(path, "forbidden-module", message)


# Gate configs: package-registered.


def _check_packages_registered(files: Mapping[str, str]) -> Iterator[Violation]:
    """Every ``packages/<dir>/src/agent_hub/<name>`` is in mypy, import-linter and Makefile COV."""
    packages = discover_packages(files)
    if not packages:
        return
    yield from _check_mypy(files, packages)
    yield from _check_import_contracts(files, packages)
    yield from _check_coverage_list(files, packages)


def discover_packages(files: Iterable[str]) -> dict[str, str]:
    """Map each ``agent_hub.<name>`` module to its ``packages/<dir>/src`` directory.

    ``files`` are repo-relative POSIX paths; a module counts once it has a file in it.
    """
    found: dict[str, str] = {}
    for path in files:
        parts = PurePosixPath(path).parts
        if len(parts) > 5 and parts[0] == "packages" and parts[2:4] == ("src", "agent_hub"):
            found[parts[4]] = "/".join(parts[:3])
    return found


def _check_mypy(files: Mapping[str, str], packages: Mapping[str, str]) -> Iterator[Violation]:
    config = _parse_config(files, MYPY_CONFIG)
    if config is None:
        yield Violation(MYPY_CONFIG, "package-registered", "missing; packages cannot be typed")
        return
    for option in ("files", "mypy_path"):
        listed = _split(config.get("mypy", option, fallback=""), ",:")
        for name, src in sorted(packages.items()):
            if src not in listed:
                message = f"[mypy] {option} lacks {src} (agent_hub.{name})"
                yield Violation(MYPY_CONFIG, "package-registered", message)


def _check_import_contracts(
    files: Mapping[str, str], packages: Mapping[str, str]
) -> Iterator[Violation]:
    config = _parse_config(files, IMPORT_CONFIG)
    if config is None:
        yield Violation(IMPORT_CONFIG, "package-registered", "missing; imports are unchecked")
        return
    modules = {f"agent_hub.{name}" for name in packages if name != CORE}
    core = _contract_option(config, "forbidden", "forbidden_modules")
    layers = _contract_option(config, "layers", "layers")
    labels = ("forbidden contract on agent_hub.core", "layers contract")
    for label, listed in zip(labels, (core, layers), strict=True):
        if listed is None:
            yield Violation(IMPORT_CONFIG, "package-registered", f"no {label} contract")
            continue
        for module in sorted(modules - listed):
            message = f"{label} lacks {module}"
            yield Violation(IMPORT_CONFIG, "package-registered", message)


def _check_coverage_list(
    files: Mapping[str, str], packages: Mapping[str, str]
) -> Iterator[Violation]:
    if MAKEFILE not in files:
        yield Violation(MAKEFILE, "package-registered", "missing; coverage is not measured")
        return
    match = COV_VARIABLE.search(files[MAKEFILE])
    if match is None:
        yield Violation(MAKEFILE, "package-registered", "no COV variable; coverage is unmeasured")
        return
    listed = set(COV_MODULE.findall(match.group(1)))
    for name in sorted(packages):
        if f"agent_hub.{name}" not in listed:
            message = f"COV lacks --cov=agent_hub.{name}"
            yield Violation(MAKEFILE, "package-registered", message)


def _contract_option(
    config: configparser.ConfigParser, contract_type: str, option: str
) -> set[str] | None:
    """The option's modules in the first contract of that type (core's, for forbidden).

    A layers entry may hold sibling layers (``a | b`` or ``a : b``) and optional ones (``(a)``).
    """
    for section in config.sections():
        if not section.startswith("importlinter:contract:"):
            continue
        if config.get(section, "type", fallback="") != contract_type:
            continue
        sources = _split(config.get(section, "source_modules", fallback=""), ",")
        if contract_type == "forbidden" and f"agent_hub.{CORE}" not in sources:
            continue
        listed = _split(config.get(section, option, fallback=""), ",|:")
        return {module.strip("()") for module in listed}
    return None


def _parse_config(files: Mapping[str, str], path: str) -> configparser.ConfigParser | None:
    if path not in files:
        return None
    config = configparser.ConfigParser(interpolation=None)
    config.read_string(files[path], source=path)
    return config


def _split(value: str, separators: str) -> set[str]:
    items = re.split(f"[\\s{re.escape(separators)}]+", value)
    return {item.rstrip("/") for item in items if item}


# Reading the repo.


def _read_repo_files() -> dict[str, str]:
    """Tracked and untracked (not ignored) files; contents only where a rule reads them."""
    command = ["git", "-C", str(REPO_ROOT), "ls-files", "-z", "--cached", "--others"]
    listing = subprocess.run(
        [*command, "--exclude-standard"],
        capture_output=True,
        check=True,
        encoding="utf-8",
    ).stdout
    files: dict[str, str] = {}
    for path in split_git_listing(listing):
        full = REPO_ROOT / path
        if not full.is_file():
            continue  # deleted but still in the index
        needs_source = path in {MYPY_CONFIG, IMPORT_CONFIG, MAKEFILE} or _is_test_location(
            PurePosixPath(path)
        )
        files[path] = full.read_text(encoding="utf-8") if needs_source else ""
    return files


if __name__ == "__main__":
    sys.exit(main())
