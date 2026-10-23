# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the installed security scanners on the hub's repos and print their findings as one JSON
object; never print a scanner's text.

``scan.py [--repo <dir>]``, run in the hub (it reads ``hub.json`` there): each repo of
``hub.json`` (or the one named) is scanned as of ``origin/<its default branch>`` as last fetched
(no fetch), in a detached worktree under the temporary folder that is removed after, so the
repo's checkout is never touched. Each scanner runs only when found on ``PATH`` (none is ever
installed): semgrep, bandit, pip-audit (``--disable-pip --no-deps``, on ``requirements*.txt`` or
on ``uv.lock`` exported offline by ``uv``), npm audit (``--package-lock-only``, the public
registry) and the hub guard's secret-file rule (``plugin/hub-workflow/hooks/guard.py``, loaded
in process). A scanner that is missing, skipped, fails or times out is a status, never a failed
run.

Output: ``{"repos": [{"repo", "ref", "head", "date", "status", "note", "scanners": [{"name",
"status", "note", "count"}]}], "findings": [<FIELDS>], "more", "trimmed"}``; findings sorted by
severity, at most ``MAX_FINDINGS`` and ``MAX_STDOUT`` bytes (the rest counted in ``more``).

A finding keeps only the structured fields of ``FIELDS`` (rule, path, line, severity, CWE,
package, version, advisory, fix, title): never a scanner's message, matched lines, code,
description or stderr (stderr is never read), so a credential in the code cannot reach the
output. A secret finding (``is_secret``) also drops its line: it is its rule and path only.

Exit 0 with the JSON; 2 when ``hub.json`` cannot be read or ``--repo`` is not in it.
``--timeout``, ``--budget`` and ``--max-files`` are for tests.
"""

# The hub runs pack scripts with uv, but they still import on the hooks' Python 3.9 floor.
from __future__ import annotations

import argparse
import contextlib
import importlib.util
import io
import json
import os
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from fnmatch import fnmatch
from functools import partial
from pathlib import Path, PurePosixPath

Finding = dict[str, object]

SCANNERS = ("semgrep", "bandit", "pip-audit", "npm", "guard")
FIELDS = (
    "repo",
    "scanner",
    "rule",
    "path",
    "line",
    "severity",
    "cwe",
    "secret",
    "package",
    "version",
    "advisory",
    "fixed",
    "title",
)
LIMITS = {
    "rule": 200,
    "path": 300,
    "package": 214,
    "version": 64,
    "advisory": 200,
    "fixed": 200,
    "title": 200,
}
SEVERITIES = {
    "semgrep": {"ERROR": "high", "WARNING": "medium", "INFO": "low"},
    "bandit": {"HIGH": "high", "MEDIUM": "medium", "LOW": "low"},
    "npm": {
        "critical": "critical",
        "high": "high",
        "moderate": "medium",
        "low": "low",
        "info": "low",
    },
}
FIXED_SEVERITY = {"pip-audit": "unknown", "guard": "high"}
# Hard-coded credentials, passwords, cryptographic keys, insufficiently protected credentials.
SECRET_CWES = {"CWE-798", "CWE-259", "CWE-321", "CWE-522"}
SECRET_RULE = re.compile(
    r"secret|password|passw|token|credential|api.?key|private.?key|hardcoded", re.IGNORECASE
)
BANDIT_SECRETS = {"B105", "B106", "B107"}
CWE = re.compile(r"CWE-[0-9]{1,5}")
ADVISORY = re.compile(r"[A-Za-z0-9-]+$")


def clip(value: object, limit: int) -> str:
    """``value`` as text with every control or format character dropped, cut to ``limit``."""
    if value is None:
        return ""
    text = value if isinstance(value, str) else str(value)
    kept = "".join(char for char in text if not unicodedata.category(char).startswith("C"))
    return kept[:limit]


def severity(scanner: str, raw: object) -> str:
    """The scanner's severity as ``critical``, ``high``, ``medium``, ``low`` or ``unknown``."""
    if scanner in FIXED_SEVERITY:
        return FIXED_SEVERITY[scanner]
    found = SEVERITIES.get(scanner, {}).get(raw if isinstance(raw, str) else "")
    return found or "unknown"


def is_secret(scanner: str, rule: str, cwe: str) -> bool:
    """Whether a finding may point at a credential: it then keeps its rule and path only."""
    if scanner == "guard":
        return True
    if scanner == "bandit":
        return rule in BANDIT_SECRETS
    if scanner == "semgrep":
        return cwe in SECRET_CWES or bool(SECRET_RULE.search(rule))
    return False


def a_finding(repo: str, scanner: str, **fields: object) -> Finding:
    """A finding of ``FIELDS`` only, each text clipped; a secret one has no line."""
    finding: Finding = {"repo": repo, "scanner": scanner}
    for name, limit in LIMITS.items():
        finding[name] = clip(fields.get(name), limit)
    line = fields.get("line")
    finding["line"] = line if isinstance(line, int) and not isinstance(line, bool) else None
    finding["severity"] = fields.get("severity", "unknown")
    cwe = fields.get("cwe")
    finding["cwe"] = cwe if isinstance(cwe, str) and CWE.fullmatch(cwe) else ""
    secret = is_secret(scanner, str(finding["rule"]), str(finding["cwe"]))
    finding["secret"] = secret
    if secret:
        finding["line"] = None
    return {name: finding[name] for name in FIELDS}


def unexpected(what: str) -> ValueError:
    return ValueError(f"unexpected {what}")


def items_of(data: object, key: str) -> list[dict[str, object]]:
    """``data[key]``, a list of objects, or ``ValueError``."""
    if not isinstance(data, dict):
        raise unexpected("output: not an object")
    found = data.get(key, [])
    if not isinstance(found, list) or not all(isinstance(item, dict) for item in found):
        raise unexpected(f"{key}: not a list of objects")
    return found


def as_dict(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def relative(path: object) -> str:
    text = path if isinstance(path, str) else ""
    return text.removeprefix("./")


def cwes(value: object) -> list[str]:
    """The CWE ids named in a scanner's CWE field (a list or one text), in order."""
    texts = value if isinstance(value, list) else [value]
    return [match for text in texts if isinstance(text, str) for match in CWE.findall(text)]


def first_cwe(found: list[str], scanner: str, rule: str) -> str:
    """The first secret CWE when there is one, so ``is_secret`` sees it; else the first."""
    secret = [cwe for cwe in found if is_secret(scanner, rule, cwe)]
    return (secret or found or [""])[0]


def from_semgrep(data: object, repo: str) -> list[Finding]:
    """Semgrep's ``--json`` results; its ``message``, ``lines`` and ``metadata`` text dropped."""
    found = []
    for result in items_of(data, "results"):
        extra = as_dict(result.get("extra"))
        rule = clip(result.get("check_id"), LIMITS["rule"])
        found.append(
            a_finding(
                repo,
                "semgrep",
                rule=rule,
                path=relative(result.get("path")),
                line=as_dict(result.get("start")).get("line"),
                severity=severity("semgrep", extra.get("severity")),
                cwe=first_cwe(cwes(as_dict(extra.get("metadata")).get("cwe")), "semgrep", rule),
            )
        )
    return found


def from_bandit(data: object, repo: str) -> list[Finding]:
    """Bandit's ``-f json`` results; its ``issue_text`` and ``code`` dropped."""
    found = []
    for result in items_of(data, "results"):
        cwe = as_dict(result.get("issue_cwe")).get("id")
        found.append(
            a_finding(
                repo,
                "bandit",
                rule=result.get("test_id"),
                path=relative(result.get("filename")),
                line=result.get("line_number"),
                severity=severity("bandit", result.get("issue_severity")),
                cwe=f"CWE-{cwe}" if isinstance(cwe, int) else "",
                title=result.get("test_name"),
            )
        )
    return found


def from_pip_audit(data: object, repo: str, manifest: str) -> list[Finding]:
    """pip-audit's ``--format json``, one finding per vulnerability; ``description`` dropped."""
    dependencies = data if isinstance(data, list) else items_of(data, "dependencies")
    found = []
    for dependency in dependencies:
        if not isinstance(dependency, dict):
            raise unexpected("dependency: not an object")
        for vuln in items_of({"vulns": dependency.get("vulns", [])}, "vulns"):
            fixes = vuln.get("fix_versions")
            fixed = ", ".join(str(fix) for fix in fixes) if isinstance(fixes, list) else ""
            found.append(
                a_finding(
                    repo,
                    "pip-audit",
                    rule=vuln.get("id"),
                    path=manifest,
                    severity=severity("pip-audit", None),
                    package=dependency.get("name"),
                    version=dependency.get("version"),
                    advisory=vuln.get("id"),
                    fixed=fixed,
                )
            )
    return found


def npm_fix(value: object) -> str:
    if isinstance(value, dict):
        return clip(value.get("version"), LIMITS["fixed"])
    return "yes" if value is True else ""


def npm_advisory(via: dict[str, object]) -> str:
    """The advisory id from its URL's last segment (a GHSA id), else npm's ``source`` number."""
    url = via.get("url")
    match = ADVISORY.search(url) if isinstance(url, str) else None
    return match.group(0) if match else clip(via.get("source"), LIMITS["advisory"])


def from_npm(data: object, repo: str, lockfile: str) -> list[Finding]:
    """npm audit's ``--json`` (report version 2): one finding per package that has an advisory
    of its own (one only reached through another package is that package's finding)."""
    vulnerabilities = as_dict(data).get("vulnerabilities")
    if not isinstance(vulnerabilities, dict):
        raise unexpected("vulnerabilities: not an object")
    found = []
    for name, entry in vulnerabilities.items():
        if not isinstance(entry, dict):
            raise unexpected("vulnerability: not an object")
        via = entry.get("via")
        advisories = (
            [item for item in via if isinstance(item, dict)] if isinstance(via, list) else []
        )
        if not advisories:
            continue
        advisory = npm_advisory(advisories[0])
        found.append(
            a_finding(
                repo,
                "npm",
                rule=advisory,
                path=lockfile,
                severity=severity("npm", entry.get("severity")),
                cwe=(cwes(advisories[0].get("cwe")) or [""])[0],
                package=name,
                version=entry.get("range"),
                advisory=advisory,
                fixed=npm_fix(entry.get("fixAvailable")),
                title=advisories[0].get("title"),
            )
        )
    return found


PARSERS: dict[str, Callable[..., list[Finding]]] = {
    "semgrep": from_semgrep,
    "bandit": from_bandit,
    "pip-audit": from_pip_audit,
    "npm": from_npm,
}


MAX_REPOS = 20
MAX_HUB_REPOS = 100
MAX_HUB_BYTES = 1024 * 1024
MAX_FINDINGS = 1000
MAX_STDOUT = 400 * 1024
MAX_CHILD_OUTPUT = 64 * 1024 * 1024
MAX_MANIFESTS = 10
MAX_FILES = 100_000
BUDGET = 40 * 60.0
GIT_TIMEOUT = 120.0
# Seconds per call; a call never outlives the script's budget.
CALL_TIMEOUTS = {
    "semgrep": 900.0,
    "bandit": 600.0,
    "pip-audit": 300.0,
    "uv": 60.0,
    "npm": 180.0,
    "guard": 120.0,
}
REPO_DIR = re.compile(r"[A-Za-z0-9._-]{1,100}")
BRANCH = re.compile(r"(?!-)(?!.*\.\.)[A-Za-z0-9._/-]{1,100}")
HEAD = re.compile(r"[0-9a-f]{40}")
GUARD = "plugin/hub-workflow/hooks/guard.py"
NPM_REGISTRY = "https://registry.npmjs.org/"
RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, "unknown": 4}
# A caller's git location variables would point every git call at another repo.
GIT_LOCATION = {
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_NAMESPACE",
}

# Named tuples, so the clauses stay parenthesized for Python 3.9's grammar (hooks parse as 3.9).
LOAD_ERRORS = (Exception, SystemExit)
SHAPE_ERRORS = (ValueError, TypeError, AttributeError)
READ_ERRORS = (OSError, ValueError)

Record = dict[str, object]
Outcome = tuple[Record, list[Finding]]


class RefusedError(Exception):
    """``hub.json`` cannot be read; the message says why."""


@dataclass(frozen=True)
class Call:
    """A child's end: ``ran`` (``data`` its stdout), ``failed`` or ``timeout`` with a note."""

    status: str
    note: str = ""
    data: bytes = b""


@dataclass(frozen=True)
class Target:
    """A repo of ``hub.json`` to scan; ``problem`` is why it cannot be, else empty."""

    repo: str
    branch: str
    problem: str = ""


@dataclass(frozen=True)
class Tree:
    """The scanned tree: a detached worktree at ``origin/<branch>`` and its tracked paths."""

    repo: str
    root: Path
    paths: tuple[str, ...]


@dataclass(frozen=True)
class Guard:
    """The hub guard's own functions, so its secret-file rule is the one applied.

    ``secret_path`` is the guard's own predicate for that rule (``_secret_path``), asked alone:
    ``check_file`` answers ``guard.deny_paths`` first, which would hide a secret file under a
    denied path. A guard without it is asked through ``check_file``."""

    check_file: Callable[..., object]
    rule_of: Callable[[str], object]
    config: object
    secret_path: Callable[..., object] | None = None

    def secret(self, path: str) -> bool:
        if self.secret_path is not None:
            return self.secret_path(path, self.config) is True
        verdict = self.check_file("Read", {"file_path": path}, self.config)
        if not (isinstance(verdict, tuple) and len(verdict) == 2 and verdict[0] == "deny"):
            return False
        return isinstance(verdict[1], str) and self.rule_of(verdict[1]) == "secret_file"


@dataclass
class Run:
    """What every scan of this run shares: the hub, git, the children's environment, budgets."""

    hub: Path
    git: str | None
    env: dict[str, str]
    deadline: float
    call_timeout: float | None
    max_files: int
    guards: dict[str, Guard | None] = field(default_factory=dict)

    def limit(self, name: str) -> float:
        """Seconds the next ``name`` call may take: its own limit within what the budget left."""
        own = self.call_timeout if self.call_timeout is not None else CALL_TIMEOUTS[name]
        return min(own, self.deadline - time.monotonic())

    def guard(self) -> Guard | None:
        if "guard" not in self.guards:
            self.guards["guard"] = load_guard(self.hub / GUARD, self.hub)
        return self.guards["guard"]


def load_guard(path: Path, hub: Path) -> Guard | None:
    """The hub's ``guard.py``, loaded in process (its own folder on ``sys.path`` while it loads,
    its prints swallowed, no bytecode written), and its config for ``hub``; None when it fails."""
    spec = importlib.util.spec_from_file_location("hub_guard", path)
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    saved, writes = list(sys.path), sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    # Registered before it runs: a dataclass in it looks its module up.
    sys.modules["hub_guard"] = module
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            spec.loader.exec_module(module)
            check_file, rule_of, load_config = (
                getattr(module, name, None) for name in ("check_file", "rule_of", "load_config")
            )
            if not (callable(check_file) and callable(rule_of) and callable(load_config)):
                return None
            config = load_config(str(hub))
    except LOAD_ERRORS:  # any failure of the hub's file: not loaded
        return None
    finally:
        sys.path[:] = saved
        sys.dont_write_bytecode = writes
    secret_path = getattr(module, "_secret_path", None)
    return Guard(check_file, rule_of, config, secret_path if callable(secret_path) else None)


def stop(child: subprocess.Popen[bytes]) -> None:
    """Kill the child's whole process group, then reap it."""
    with contextlib.suppress(OSError):
        os.killpg(child.pid, signal.SIGKILL)
    child.wait()


def run_child(
    argv: list[str], *, cwd: Path, env: dict[str, str], timeout: float, codes: tuple[int, ...]
) -> Call:
    """Run ``argv`` (no shell, no stdin, stderr discarded, its own process group) with its
    stdout in a temporary file; a timeout kills the group, stdout over the cap is not read."""
    with tempfile.TemporaryFile() as out:
        try:
            child = subprocess.Popen(  # noqa: S603 - a fixed argv of the pack, never a shell
                argv,
                cwd=cwd,
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=out,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError:
            return Call("failed", "could not start")
        try:
            code = child.wait(timeout=max(timeout, 0.001))
        except subprocess.TimeoutExpired:
            stop(child)
            return Call("timeout", f"over {timeout:g} s")
        if code not in codes:
            return Call("failed", f"exit {code}")
        if out.seek(0, os.SEEK_END) > MAX_CHILD_OUTPUT:
            return Call("failed", "output over 64 MiB")
        out.seek(0)
        return Call("ran", data=out.read())


def git(run: Run, *args: str, cwd: Path) -> str | None:
    """Git's stdout, with hooks off; None when it fails."""
    if run.git is None:
        return None
    argv = [run.git, "-c", f"core.hooksPath={os.devnull}", *args]
    call = run_child(argv, cwd=cwd, env=run.env, timeout=GIT_TIMEOUT, codes=(0,))
    return call.data.decode(errors="replace") if call.status == "ran" else None


def status(name: str, state: str, note: str = "", *, count: int = 0) -> Record:
    return {"name": name, "status": state, "note": clip(note, 200), "count": count}


Result = tuple[str, str, list[Finding]]


def call_findings(
    run: Run, name: str, argv: list[str], *, cwd: Path, parse: Callable[[object], list[Finding]]
) -> Result:
    """One ``name`` call as ``(status, note, findings)``; its stdout parsed as JSON by ``parse``."""
    limit = run.limit(name)
    if limit <= 0:
        return "skipped", "budget spent", []
    call = run_child(argv, cwd=cwd, env=run.env, timeout=limit, codes=(0, 1))
    if call.status != "ran":
        return call.status, call.note, []
    try:
        data = json.loads(call.data)
    except ValueError:
        return "failed", "output not JSON", []
    try:
        return "ran", "", parse(data)
    except SHAPE_ERRORS:
        return "failed", "unexpected output", []


def merged(name: str, results: list[Result], note: str) -> Outcome:
    """Several calls of one scanner as one status: ``ran`` when all ran, else the first other."""
    found = [finding for _, _, findings in results for finding in findings]
    others = [(state, why) for state, why, _ in results if state != "ran"]
    state, why = others[0] if others else ("ran", note)
    return status(name, state, why, count=len(found)), found


def which(name: str) -> str | None:
    return shutil.which(name)


def semgrep_config(paths: frozenset[str]) -> list[str]:
    """The repo's own tracked Semgrep config, else the registry's audit and secrets rules."""
    for name in (".semgrep.yml", ".semgrep.yaml"):
        if name in paths:
            return ["--config", name]
    if any(path.startswith(".semgrep/") for path in paths):
        return ["--config", ".semgrep/"]
    return ["--config", "p/security-audit", "--config", "p/secrets"]


def semgrep(run: Run, tree: Tree) -> Outcome:
    exe = which("semgrep")
    if exe is None:
        return status("semgrep", "missing", "not installed"), []
    flags = ["--json", "--quiet", "--metrics=off", "--disable-version-check", "--timeout", "30"]
    argv = [exe, "scan", *flags, *semgrep_config(frozenset(tree.paths)), "."]
    parse = partial(from_semgrep, repo=tree.repo)
    return merged("semgrep", [call_findings(run, "semgrep", argv, cwd=tree.root, parse=parse)], "")


def bandit(run: Run, tree: Tree) -> Outcome:
    exe = which("bandit")
    if exe is None:
        return status("bandit", "missing", "not installed"), []
    if not any(path.endswith(".py") for path in tree.paths):
        return status("bandit", "skipped", "no tracked *.py"), []
    argv = [exe, "-r", ".", "-f", "json", "-q", "-ll", "-ii"]
    parse = partial(from_bandit, repo=tree.repo)
    return merged("bandit", [call_findings(run, "bandit", argv, cwd=tree.root, parse=parse)], "")


def named(paths: tuple[str, ...], pattern: str) -> list[str]:
    """Tracked paths whose file name matches ``pattern``, outside ``node_modules/``."""
    return [
        path
        for path in paths
        if fnmatch(PurePosixPath(path).name, pattern)
        and "node_modules" not in PurePosixPath(path).parts
    ]


def capped(found: list[str]) -> tuple[list[str], str]:
    if len(found) <= MAX_MANIFESTS:
        return found, ""
    return found[:MAX_MANIFESTS], f"first {MAX_MANIFESTS} of {len(found)} manifests"


def audit(run: Run, tree: Tree, requirements: str, *, label: str) -> Result:
    argv = [str(which("pip-audit")), "-r", requirements, "--disable-pip", "--no-deps"]
    argv += ["--format", "json", "--progress-spinner", "off"]
    parse = partial(from_pip_audit, repo=tree.repo, manifest=label)
    return call_findings(run, "pip-audit", argv, cwd=tree.root, parse=parse)


def audit_lock(run: Run, tree: Tree, lock: str, *, index: int) -> Result:
    """``uv.lock`` exported offline to a requirements file beside the tree, then audited."""
    uv = which("uv")
    if uv is None:
        return "skipped", "uv not found to export uv.lock", []
    limit = run.limit("uv")
    if limit <= 0:
        return "skipped", "budget spent", []
    exported = tree.root.parent / f"uv-requirements-{index}.txt"
    flags = ["--frozen", "--no-hashes", "--no-emit-project", "--no-emit-workspace"]
    argv = [uv, "export", *flags, "--format", "requirements-txt", "-o", str(exported)]
    env = {**run.env, "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never"}
    folder = tree.root / PurePosixPath(lock).parent
    call = run_child(argv, cwd=folder, env=env, timeout=limit, codes=(0,))
    if call.status != "ran":
        return call.status, f"uv export: {call.note}", []
    return audit(run, tree, str(exported), label=lock)


def pip_audit(run: Run, tree: Tree) -> Outcome:
    if which("pip-audit") is None:
        return status("pip-audit", "missing", "not installed"), []
    locks, over_locks = capped(named(tree.paths, "uv.lock"))
    files, over_files = capped(named(tree.paths, "requirements*.txt"))
    if not locks and not files:
        return status("pip-audit", "skipped", "no uv.lock or requirements*.txt"), []
    results = [audit_lock(run, tree, lock, index=n) for n, lock in enumerate(locks)]
    results += [audit(run, tree, path, label=path) for path in files]
    return merged("pip-audit", results, over_locks or over_files)


def npm(run: Run, tree: Tree) -> Outcome:
    exe = which("npm")
    if exe is None:
        return status("npm", "missing", "not installed"), []
    locks, over = capped(named(tree.paths, "package-lock.json"))
    if not locks:
        return status("npm", "skipped", "no package-lock.json"), []
    # The public registry, whatever a repo's .npmrc names, so the lockfile goes nowhere else.
    argv = [exe, "audit", "--json", "--package-lock-only", f"--registry={NPM_REGISTRY}"]
    results = [
        call_findings(
            run,
            "npm",
            argv,
            cwd=tree.root / PurePosixPath(lock).parent,
            parse=partial(from_npm, repo=tree.repo, lockfile=lock),
        )
        for lock in locks
    ]
    return merged("npm", results, over)


def guard(run: Run, tree: Tree) -> Outcome:
    """The hub guard's secret-file rule on every tracked path, by name (no file is opened)."""
    if not (run.hub / GUARD).is_file():
        return status("guard", "missing", f"no {GUARD} in the hub"), []
    limit = run.limit("guard")
    if limit <= 0:
        return status("guard", "skipped", "budget spent"), []
    loaded = run.guard()
    if loaded is None:
        return status("guard", "failed", "the hub's guard.py did not load"), []
    if len(tree.paths) > run.max_files:
        return status("guard", "failed", f"over {run.max_files} files"), []
    deadline = time.monotonic() + limit
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            hits = [
                path for path in tree.paths if time.monotonic() < deadline and loaded.secret(path)
            ]
    except Exception:  # noqa: BLE001 - the hub's code: any error is a failed scanner
        return status("guard", "failed", "the hub's guard raised an error"), []
    if time.monotonic() >= deadline:
        return status("guard", "timeout", f"over {limit:g} s"), []
    found = [
        a_finding(tree.repo, "guard", rule="secret_file", path=path, severity="high")
        for path in hits
    ]
    return status("guard", "ran", "", count=len(found)), found


SCANS: tuple[Callable[[Run, Tree], Outcome], ...] = (semgrep, bandit, pip_audit, npm, guard)


def scan_tree(run: Run, tree: Tree) -> tuple[list[Record], list[Finding]]:
    records, findings = [], []
    for scan in SCANS:
        record, found = scan(run, tree)
        records.append(record)
        findings.extend(found)
    return records, findings


def in_worktree(
    run: Run, folder: Path, *, repo: str, head: str
) -> tuple[str, list[Record], list[Finding]]:
    """Scan ``head`` in a detached worktree under the temporary folder, removed after; the note
    says why it could not be made or listed, else it is empty."""
    base = Path(tempfile.mkdtemp(prefix="security-sweep-"))
    root = base / repo
    try:
        if git(run, "worktree", "add", "--detach", "--quiet", str(root), head, cwd=folder) is None:
            return "the scan worktree could not be created", [], []
        listed = git(run, "ls-files", "-z", cwd=root)
        if listed is None:
            return "the tracked files could not be listed", [], []
        tree = Tree(repo, root, tuple(path for path in listed.split("\0") if path))
        return ("", *scan_tree(run, tree))
    finally:
        if git(run, "worktree", "remove", "--force", str(root), cwd=folder) is None:
            shutil.rmtree(base, ignore_errors=True)
            git(run, "worktree", "prune", cwd=folder)
        shutil.rmtree(base, ignore_errors=True)


def a_record(target: Target, note: str) -> Record:
    ref = f"origin/{target.branch}" if target.branch else ""
    return {
        "repo": target.repo,
        "ref": ref,
        "head": "",
        "date": "",
        "status": "unreadable",
        "note": note,
        "scanners": [],
    }


def scan_repo(run: Run, target: Target) -> tuple[Record, list[Finding]]:
    """One repo's record and findings; an unusable repo is ``unreadable`` with a fixed note."""
    record = a_record(target, target.problem)
    folder = run.hub.parent / target.repo
    if target.problem:
        return record, []
    if not (folder / ".git").exists():
        return a_record(target, f"no folder ../{target.repo} beside the hub"), []
    ref = f"refs/remotes/origin/{target.branch}^{{commit}}"
    head = (git(run, "rev-parse", "--verify", "--quiet", ref, cwd=folder) or "").strip()
    if not HEAD.fullmatch(head):
        return a_record(target, f"no origin/{target.branch}: fetch it first"), []
    date = git(run, "log", "-1", "--format=%cI", head, cwd=folder) or ""
    note, scanners, findings = in_worktree(run, folder, repo=target.repo, head=head)
    record.update(head=head, date=clip(date.strip(), 40), note=note, scanners=scanners)
    record["status"] = "unreadable" if note else "scanned"
    return record, findings


def read_hub(path: Path) -> dict[str, object]:
    """``hub.json``: a regular file of at most 1 MiB holding an object with a ``repos`` list."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        raise RefusedError("not found") from None
    except OSError as error:
        raise RefusedError(type(error).__name__) from None
    if not stat.S_ISREG(info.st_mode):
        raise RefusedError("not a regular file")
    if info.st_size > MAX_HUB_BYTES:
        raise RefusedError("over 1 MiB")
    try:
        data = json.loads(path.read_bytes())
    except READ_ERRORS:
        raise RefusedError("not JSON") from None
    if not isinstance(data, dict) or not isinstance(data.get("repos"), list):
        raise RefusedError("no repos list")
    if len(data["repos"]) > MAX_HUB_REPOS:
        raise RefusedError(f"over {MAX_HUB_REPOS} repos")
    return data


def usable_dir(name: object) -> bool:
    return isinstance(name, str) and bool(REPO_DIR.fullmatch(name)) and name not in {".", ".."}


def a_target(entry: object, default: object) -> Target:
    item = as_dict(entry)
    name, branch = item.get("dir"), item.get("default_branch") or default
    if not usable_dir(name):
        return Target(clip(name, 100), "", "the repo dir in hub.json is not usable")
    if not (isinstance(branch, str) and BRANCH.fullmatch(branch)):
        return Target(str(name), "", "the default branch in hub.json is not usable")
    return Target(str(name), branch)


def targets(hub: dict[str, object], wanted: str) -> list[Target] | None:
    """The repos to scan, in ``hub.json``'s order (only ``wanted`` when given; None when it is
    not there); past ``MAX_REPOS``, each is unreadable."""
    default = as_dict(hub.get("project")).get("default_branch") or "main"
    entries = hub["repos"]
    found = [a_target(entry, default) for entry in entries] if isinstance(entries, list) else []
    if wanted:
        found = [target for target in found if usable_dir(wanted) and target.repo == wanted]
        if not found:
            return None
    over = "over 20 repos: not scanned"
    return [
        target if n < MAX_REPOS else Target(target.repo, target.branch, over)
        for n, target in enumerate(found)
    ]


def order(finding: Finding) -> tuple[int, str, str, int]:
    line = finding["line"]
    rank = RANK.get(str(finding["severity"]), len(RANK))
    return rank, str(finding["repo"]), str(finding["path"]), line if isinstance(line, int) else -1


def finished(repos: list[Record], findings: list[Finding]) -> dict[str, object]:
    """The output: findings by severity, at most ``MAX_FINDINGS`` and ``MAX_STDOUT`` bytes."""
    kept = sorted(findings, key=order)[:MAX_FINDINGS]
    more = len(findings) - len(kept)
    size = len(json.dumps({"repos": repos, "findings": kept, "more": more, "trimmed": True}))
    trimmed = size > MAX_STDOUT
    while kept and size > MAX_STDOUT:
        size -= len(json.dumps(kept.pop())) + 2
        more += 1
    return {"repos": repos, "findings": kept, "more": more, "trimmed": trimmed}


def a_run(arguments: argparse.Namespace) -> Run:
    env = {key: value for key, value in os.environ.items() if key not in GIT_LOCATION}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_LFS_SKIP_SMUDGE="1")
    return Run(
        hub=Path.cwd(),
        git=shutil.which("git"),
        env=env,
        deadline=time.monotonic() + arguments.budget,
        call_timeout=arguments.timeout,
        max_files=arguments.max_files,
    )


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="scan.py", description=__doc__.split("\n")[0])
    parser.add_argument("--repo", default="", help="one repo's dir in hub.json (default: all)")
    parser.add_argument("--timeout", type=float, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--budget", type=float, default=BUDGET, help=argparse.SUPPRESS)
    parser.add_argument("--max-files", type=int, default=MAX_FILES, help=argparse.SUPPRESS)
    arguments = parser.parse_args(argv)
    try:
        hub = read_hub(Path("hub.json"))
    except RefusedError as error:
        print(f"scan.py: cannot read hub.json: {error}", file=sys.stderr)
        return 2
    chosen = targets(hub, arguments.repo)
    if chosen is None:
        print(
            f"scan.py: repo {json.dumps(arguments.repo[:100])} is not in hub.json", file=sys.stderr
        )
        return 2
    run = a_run(arguments)
    repos, findings = [], []
    for target in chosen:
        record, found = scan_repo(run, target)
        repos.append(record)
        findings.extend(found)
    print(json.dumps(finished(repos, findings)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
