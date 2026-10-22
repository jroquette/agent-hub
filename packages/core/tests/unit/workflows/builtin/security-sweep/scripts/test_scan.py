"""The security-sweep pack's ``scan.py`` (AGH-486), in process: scanner JSON becomes findings that
keep structured fields only, so no secret value reaches a node output (AC-3)."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from importlib.resources import files
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

SCRIPT = Path(
    str(files("agent_hub.core").joinpath("workflows/builtin/security-sweep/scripts/scan.py"))
)

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.security-sweep.scripts.scan"

# Not a secret shape (no repo lint flags it); a test asserts it never reaches the output.
VALUE = "hunter2-fixture-value"


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Registered before it runs: its dataclasses look their module up.
    sys.modules[MODULE] = module
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def a_semgrep_result(check_id: str, cwe: list[str], line: int = 3) -> dict[str, Any]:
    return {
        "check_id": check_id,
        "path": "app/settings.py",
        "start": {"line": line, "col": 1, "offset": 10},
        "end": {"line": line, "col": 30, "offset": 40},
        "extra": {
            "message": f"Hard-coded password {VALUE} found",
            "lines": f"PASSWORD = '{VALUE}'",
            "severity": "ERROR",
            "fingerprint": VALUE,
            "metadata": {"cwe": cwe, "description": VALUE},
        },
    }


def a_bandit_result(test_id: str, name: str, severity: str = "LOW") -> dict[str, Any]:
    return {
        "test_id": test_id,
        "test_name": name,
        "filename": "./app/settings.py",
        "line_number": 3,
        "line_range": [3],
        "issue_severity": severity,
        "issue_confidence": "MEDIUM",
        "issue_cwe": {"id": 259, "link": "https://cwe.mitre.org/data/definitions/259.html"},
        "issue_text": f"Possible hardcoded password: '{VALUE}'",
        "code": f"3 PASSWORD = '{VALUE}'\n",
        "more_info": "https://bandit.readthedocs.io/",
    }


def test_keeps_rule_and_path_but_not_the_value_when_semgrep_reports_a_secret() -> None:
    data = {
        "results": [
            a_semgrep_result(
                "generic.secrets.hardcoded-password", ["CWE-798: Use of Hard-coded Credentials"]
            )
        ],
        "errors": [{"message": VALUE}],
    }

    (finding,) = load().from_semgrep(data, "demo-api")

    assert finding["rule"] == "generic.secrets.hardcoded-password"
    assert finding["path"] == "app/settings.py"
    assert finding["secret"] is True
    assert finding["line"] is None
    assert finding["cwe"] == "CWE-798"
    assert VALUE not in json.dumps(finding)


def test_keeps_rule_and_path_but_not_the_value_when_bandit_reports_a_hardcoded_password() -> None:
    data = {"results": [a_bandit_result("B105", "hardcoded_password_string")], "errors": []}

    (finding,) = load().from_bandit(data, "demo-api")

    assert (finding["rule"], finding["path"]) == ("B105", "app/settings.py")
    assert finding["secret"] is True
    assert finding["line"] is None
    assert finding["title"] == "hardcoded_password_string"
    assert VALUE not in json.dumps(finding)


def test_drops_message_and_code_when_finding_is_not_a_secret() -> None:
    rule = "python.lang.security.audit.subprocess-shell-true.subprocess-shell-true"
    semgrep = {"results": [a_semgrep_result(rule, ["CWE-78: OS Command Injection"], line=12)]}
    bandit = {"results": [a_bandit_result("B602", "subprocess_popen_with_shell_equals_true")]}
    scan = load()

    (from_semgrep,) = scan.from_semgrep(semgrep, "demo-api")
    (from_bandit,) = scan.from_bandit(bandit, "demo-api")

    assert from_semgrep == {
        "repo": "demo-api",
        "scanner": "semgrep",
        "rule": rule,
        "path": "app/settings.py",
        "line": 12,
        "severity": "high",
        "cwe": "CWE-78",
        "secret": False,
        "package": "",
        "version": "",
        "advisory": "",
        "fixed": "",
        "title": "",
    }
    assert (from_bandit["line"], from_bandit["secret"]) == (3, False)
    assert VALUE not in json.dumps([from_semgrep, from_bandit])


def test_reads_package_advisory_and_fix_when_pip_audit_reports_a_vuln() -> None:
    vuln = {
        "id": "PYSEC-1-2",
        "fix_versions": ["2.11.3", "3.0.0"],
        "aliases": ["CVE-1-2"],
        "description": VALUE,
    }
    data = {
        "dependencies": [
            {"name": "jinja2", "version": "2.11.2", "vulns": [vuln]},
            {"name": "click", "version": "8.1.0", "vulns": []},
            {"name": "local", "skip_reason": VALUE},
        ],
        "fixes": [],
    }

    (finding,) = load().from_pip_audit(data, "demo-api", "requirements.txt")

    assert finding == {
        "repo": "demo-api",
        "scanner": "pip-audit",
        "rule": "PYSEC-1-2",
        "path": "requirements.txt",
        "line": None,
        "severity": "unknown",
        "cwe": "",
        "secret": False,
        "package": "jinja2",
        "version": "2.11.2",
        "advisory": "PYSEC-1-2",
        "fixed": "2.11.3, 3.0.0",
        "title": "",
    }


def test_reads_package_severity_and_advisory_when_npm_audit_reports_a_vuln() -> None:
    advisory = {
        "source": 1065,
        "name": "lodash",
        "dependency": "lodash",
        "title": "Prototype Pollution in lodash",
        "url": "https://github.com/advisories/GHSA-p6mc-m468-83gw",
        "severity": "high",
        "cwe": ["CWE-1321"],
        "range": "<4.17.19",
    }
    data = {
        "auditReportVersion": 2,
        "vulnerabilities": {
            "lodash": {
                "name": "lodash",
                "severity": "high",
                "via": [advisory],
                "range": "<=4.17.18",
                "fixAvailable": {"name": "lodash", "version": "4.17.21", "isSemVerMajor": False},
            },
            # Vulnerable only through another package: that package's entry holds the advisory.
            "wrapper": {"name": "wrapper", "severity": "high", "via": ["lodash"], "range": "*"},
        },
    }

    (finding,) = load().from_npm(data, "demo-web", "web/package-lock.json")

    assert finding == {
        "repo": "demo-web",
        "scanner": "npm",
        "rule": "GHSA-p6mc-m468-83gw",
        "path": "web/package-lock.json",
        "line": None,
        "severity": "high",
        "cwe": "CWE-1321",
        "secret": False,
        "package": "lodash",
        "version": "<=4.17.18",
        "advisory": "GHSA-p6mc-m468-83gw",
        "fixed": "4.17.21",
        "title": "Prototype Pollution in lodash",
    }


@pytest.mark.parametrize(
    ("scanner", "raw", "expected"),
    [
        ("semgrep", "ERROR", "high"),
        ("semgrep", "WARNING", "medium"),
        ("semgrep", "INFO", "low"),
        ("bandit", "HIGH", "high"),
        ("bandit", "MEDIUM", "medium"),
        ("bandit", "LOW", "low"),
        ("npm", "critical", "critical"),
        ("npm", "high", "high"),
        ("npm", "moderate", "medium"),
        ("npm", "low", "low"),
        ("npm", "info", "low"),
        ("pip-audit", "", "unknown"),
        ("guard", "", "high"),
        ("semgrep", "odd", "unknown"),
        ("bandit", None, "unknown"),
    ],
)
def test_normalizes_severity_when_scanners_differ(scanner: str, raw: Any, expected: str) -> None:
    assert load().severity(scanner, raw) == expected


@pytest.mark.parametrize(
    ("scanner", "rule", "cwe", "secret"),
    [
        ("guard", "secret_file", "", True),
        ("bandit", "B106", "CWE-259", True),
        ("bandit", "B107", "", True),
        ("bandit", "B608", "CWE-89", False),
        ("semgrep", "python.django.security.audit.raw-query", "CWE-522", True),
        ("semgrep", "generic.secrets.security.detected-aws-access-key", "", True),
        ("semgrep", "javascript.jwt.security.jwt-hardcode.hardcoded-jwt-key", "", True),
        ("semgrep", "python.lang.security.audit.eval-detected", "CWE-95", False),
        ("npm", "GHSA-x", "CWE-798", False),
    ],
)
def test_marks_secret_when_rule_or_cwe_names_a_credential(
    scanner: str, rule: str, cwe: str, *, secret: bool
) -> None:
    assert load().is_secret(scanner, rule, cwe) is secret


def test_drops_control_chars_and_clips_when_fields_are_long() -> None:
    scan = load()
    result = a_semgrep_result("r\x1b[31m" + "x" * 300, [], line=5)
    result["path"] = "a\nb‮/" + "p" * 400

    (finding,) = scan.from_semgrep({"results": [result]}, "demo-api")

    assert scan.clip("a\tb\x00c​d", 3) == "abc"
    assert finding["rule"] == ("r[31m" + "x" * 300)[:200]
    assert finding["path"] == ("ab/" + "p" * 400)[:300]
    assert scan.clip(None, 5) == ""
    assert scan.clip(12, 5) == "12"


@pytest.mark.parametrize(
    ("parse", "data"),
    [
        ("from_semgrep", []),
        ("from_semgrep", {"results": {}}),
        ("from_bandit", {"results": [1]}),
        ("from_pip_audit", {"dependencies": "x"}),
        ("from_npm", {"vulnerabilities": []}),
    ],
)
def test_raises_value_error_when_scanner_output_has_another_shape(parse: str, data: Any) -> None:
    scan = load()
    with pytest.raises(ValueError, match="unexpected"):
        if parse in {"from_pip_audit", "from_npm"}:
            getattr(scan, parse)(data, "demo-api", "x")
        else:
            getattr(scan, parse)(data, "demo-api")


# The runner: a tmp hub beside a git repo whose origin/main is a local ref, and fake scanners
# (this interpreter, printing canned JSON and logging their argv) in a tmp bin folder.

IDENTITY = ("-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com")
SEMGREP_HIT = {
    "results": [
        a_semgrep_result(
            "python.lang.security.audit.subprocess-shell-true", ["CWE-78: OS Command Injection"]
        )
    ],
    "errors": [],
}
BANDIT_HIT = {"results": [a_bandit_result("B602", "subprocess_popen_with_shell_equals_true")]}
PIP_AUDIT_HIT = {
    "dependencies": [
        {"name": "jinja2", "version": "2.11.2", "vulns": [{"id": "PYSEC-1-2", "fix_versions": []}]}
    ]
}
NPM_HIT = {
    "vulnerabilities": {
        "lodash": {
            "name": "lodash",
            "severity": "high",
            "via": [{"source": 1, "title": "Prototype Pollution", "url": "https://x/GHSA-1"}],
            "range": "<4",
            "fixAvailable": True,
        }
    }
}


class Sweep:
    """``hub/hub.json`` naming ``app``, a git repo at ``app`` with ``origin/main``, and ``bin``."""

    def __init__(self, base: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.base = base
        self.hub = base / "hub"
        self.repo = base / "app"
        self.bin = base / "bin"
        self.log = base / "calls.jsonl"
        self.tmp = base / "tmp"
        git = shutil.which("git")
        assert git is not None
        self.git_path = git
        for folder in (self.hub, self.repo, self.bin, self.tmp, base / "gitbin"):
            folder.mkdir()
        (base / "gitbin" / "git").symlink_to(git)
        self.hub_json({"project": {"default_branch": "main"}, "repos": [{"dir": "app"}]})
        self.commit(
            {
                "app.py": "import subprocess\n",
                "requirements.txt": "jinja2==2.11.2\n",
                "web/package-lock.json": "{}\n",
                "node_modules/x/package-lock.json": "{}\n",
                ".env": f"TOKEN={VALUE}\n",
            }
        )
        monkeypatch.chdir(self.hub)
        monkeypatch.setenv("PATH", f"{self.bin}{os.pathsep}{base / 'gitbin'}")
        # Every temporary folder the scan makes lands here, so a test sees it removed.
        monkeypatch.setattr(tempfile, "tempdir", str(self.tmp))

    def hub_json(self, document: object) -> None:
        (self.hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")

    def git(self, *args: str) -> str:
        return subprocess.run(  # noqa: S603 - this test's git, fixed arguments, a tmp folder
            [self.git_path, *args],
            cwd=self.repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout

    def commit(self, tree: dict[str, str], *, origin: bool = True) -> None:
        if not (self.repo / ".git").exists():
            self.git("init", "-q", "-b", "main")
        for name, text in tree.items():
            (self.repo / name).parent.mkdir(parents=True, exist_ok=True)
            (self.repo / name).write_text(text, encoding="utf-8")
        self.git("add", "-A")
        self.git(*IDENTITY, "commit", "-q", "-m", "change")
        if origin:
            self.git("update-ref", "refs/remotes/origin/main", "HEAD")

    def fake(self, name: str, output: object = None, **behaviour: Any) -> None:
        """A fake ``name`` that logs its call, then sleeps, writes stderr, prints ``output``
        (JSON unless text) and exits ``code``; ``export`` writes the file after ``-o``."""
        printed = output if isinstance(output, str) else json.dumps(output)
        lines = [
            f"#!{sys.executable} -I",
            "import json, os, sys, time",
            "keys = ('UV_OFFLINE', 'UV_PYTHON_DOWNLOADS', 'GIT_TERMINAL_PROMPT')",
            f"call = {{'name': {name!r}, 'argv': sys.argv[1:], 'cwd': os.getcwd(),",
            "        'env': {key: os.environ.get(key, '') for key in keys}}",
            f"with open({str(self.log)!r}, 'a') as log:",
            "    log.write(json.dumps(call) + '\\n')",
            f"time.sleep({behaviour.get('sleep', 0)})",
            f"sys.stderr.write({behaviour.get('stderr', '')!r})",
            "if '-o' in sys.argv:",
            "    with open(sys.argv[sys.argv.index('-o') + 1], 'w') as out:",
            "        out.write('jinja2==2.11.2\\n')",
            f"sys.stdout.write({printed!r})",
            f"sys.exit({behaviour.get('code', 0)})",
        ]
        path = self.bin / name
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        path.chmod(0o755)

    def calls(self) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        return [json.loads(line) for line in self.log.read_text().splitlines()]

    def guard(self, source: str = "") -> None:
        hooks = self.hub / "plugin" / "hub-workflow" / "hooks"
        hooks.mkdir(parents=True, exist_ok=True)
        (hooks / "guard.py").write_text(source or STUB_GUARD, encoding="utf-8")

    def state(self) -> tuple[str, str, str]:
        return (
            self.git("rev-parse", "HEAD"),
            self.git("status", "--porcelain"),
            self.git("worktree", "list", "--porcelain"),
        )


# The guard's public face, as plugin/hub-workflow/hooks/guard.py has it: a secret file by name.
STUB_GUARD = """
import os
def load_config(start=None):
    return {"hub": start}
def check_file(tool, ti, cfg=None):
    name = os.path.basename(ti.get("file_path", ""))
    if tool == "Read" and name.startswith(".env") and name != ".env.example":
        return "deny", name + " may hold secrets; reference variable names instead of reading it"
    return None
def rule_of(reason):
    return "secret_file" if " may hold secrets" in reason else None
"""


@pytest.fixture
def sweep(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Sweep:
    return Sweep(tmp_path, monkeypatch)


def scanned(capsys: pytest.CaptureFixture[str], *argv: str) -> dict[str, Any]:
    code = load().main(list(argv))
    captured = capsys.readouterr()
    assert code == 0, captured.err
    output: dict[str, Any] = json.loads(captured.out)
    return output


def statuses(output: dict[str, Any]) -> dict[str, tuple[str, str, int]]:
    (repo,) = output["repos"]
    return {
        item["name"]: (item["status"], item["note"], item["count"]) for item in repo["scanners"]
    }


def test_marks_scanner_missing_when_not_on_path(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    output = scanned(capsys)

    (repo,) = output["repos"]
    assert repo["status"] == "scanned"
    assert repo["ref"] == "origin/main"
    assert repo["head"] == sweep.git("rev-parse", "HEAD").strip()
    assert statuses(output) == {
        "semgrep": ("missing", "not installed", 0),
        "bandit": ("missing", "not installed", 0),
        "pip-audit": ("missing", "not installed", 0),
        "npm": ("missing", "not installed", 0),
        "guard": ("missing", "no plugin/hub-workflow/hooks/guard.py in the hub", 0),
    }
    assert output["findings"] == []
    assert (output["more"], output["trimmed"]) == (0, False)


def test_runs_each_found_scanner_when_installed(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    for name, hit in (
        ("semgrep", SEMGREP_HIT),
        ("bandit", BANDIT_HIT),
        ("pip-audit", PIP_AUDIT_HIT),
        ("npm", NPM_HIT),
    ):
        sweep.fake(name, hit, code=1)

    output = scanned(capsys)

    assert statuses(output)["semgrep"] == ("ran", "", 1)
    assert statuses(output)["bandit"] == ("ran", "", 1)
    assert statuses(output)["pip-audit"] == ("ran", "", 1)
    assert statuses(output)["npm"] == ("ran", "", 1)
    assert {finding["scanner"] for finding in output["findings"]} == {
        "semgrep",
        "bandit",
        "pip-audit",
        "npm",
    }
    calls = {call["name"]: call for call in sweep.calls()}
    assert calls["semgrep"]["argv"] == [
        "scan",
        "--json",
        "--quiet",
        "--metrics=off",
        "--disable-version-check",
        "--timeout",
        "30",
        "--config",
        "p/security-audit",
        "--config",
        "p/secrets",
        ".",
    ]
    assert calls["bandit"]["argv"] == ["-r", ".", "-f", "json", "-q", "-ll", "-ii"]
    assert calls["npm"]["argv"] == ["audit", "--json", "--package-lock-only"]
    # Only the lockfile outside node_modules/, in its own folder of the scanned tree.
    assert Path(calls["npm"]["cwd"]).name == "web"
    for call in calls.values():
        assert Path(call["cwd"]).is_relative_to(sweep.tmp)
        assert call["env"]["GIT_TERMINAL_PROMPT"] == "0"
    assert list(sweep.tmp.iterdir()) == []


def test_uses_the_repo_config_when_semgrep_config_is_tracked(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.commit({".semgrep.yml": "rules: []\n"})
    sweep.fake("semgrep", {"results": []})

    scanned(capsys)

    (call,) = sweep.calls()
    assert call["argv"][-3:] == ["--config", ".semgrep.yml", "."]


def test_runs_pip_audit_without_pip_when_requirements_found(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.fake("pip-audit", PIP_AUDIT_HIT, code=1)

    output = scanned(capsys)

    (call,) = sweep.calls()
    assert call["argv"] == [
        "-r",
        "requirements.txt",
        "--disable-pip",
        "--no-deps",
        "--format",
        "json",
        "--progress-spinner",
        "off",
    ]
    (finding,) = output["findings"]
    assert (finding["path"], finding["package"]) == ("requirements.txt", "jinja2")


def test_exports_uv_lock_offline_when_repo_has_one(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.git("rm", "-q", "requirements.txt")
    sweep.commit({"uv.lock": "version = 1\n"})
    sweep.fake("uv", "")
    sweep.fake("pip-audit", PIP_AUDIT_HIT, code=1)

    output = scanned(capsys)

    export, audit = sweep.calls()
    assert export["argv"][:7] == [
        "export",
        "--frozen",
        "--no-hashes",
        "--no-emit-project",
        "--no-emit-workspace",
        "--format",
        "requirements-txt",
    ]
    assert export["env"]["UV_OFFLINE"] == "1"
    assert export["env"]["UV_PYTHON_DOWNLOADS"] == "never"
    assert audit["argv"][:2] == ["-r", export["argv"][-1]]
    assert "--disable-pip" in audit["argv"]
    (finding,) = output["findings"]
    assert finding["path"] == "uv.lock"


def test_skips_pip_audit_when_uv_lock_needs_a_missing_uv(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.git("rm", "-q", "requirements.txt")
    sweep.commit({"uv.lock": "version = 1\n"})
    sweep.fake("pip-audit", PIP_AUDIT_HIT)

    output = scanned(capsys)

    assert statuses(output)["pip-audit"] == ("skipped", "uv not found to export uv.lock", 0)


def test_finds_secret_files_with_the_hub_guard_when_guard_is_present(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.commit({".env.example": "TOKEN=\n"})
    sweep.guard()

    output = scanned(capsys)

    assert statuses(output)["guard"] == ("ran", "", 1)
    (finding,) = output["findings"]
    assert finding["scanner"] == "guard"
    assert (finding["rule"], finding["path"]) == ("secret_file", ".env")
    assert (finding["secret"], finding["line"], finding["severity"]) == (True, None, "high")
    assert VALUE not in json.dumps(output)


@pytest.mark.parametrize(
    "source", ["raise RuntimeError('no')", "import sys\nprint('ask')\nsys.exit(0)", "x = 1"]
)
def test_marks_guard_failed_when_hub_guard_does_not_load(
    sweep: Sweep, capsys: pytest.CaptureFixture[str], source: str
) -> None:
    sweep.guard(source)

    output = scanned(capsys)

    assert statuses(output)["guard"] == ("failed", "the hub's guard.py did not load", 0)


def test_marks_guard_missing_when_hub_has_no_guard(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    output = scanned(capsys)

    assert statuses(output)["guard"][0] == "missing"
    assert output["findings"] == []


def test_fails_guard_scan_when_tree_has_too_many_files(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.guard()

    output = scanned(capsys, "--max-files", "3")

    assert statuses(output)["guard"] == ("failed", "over 3 files", 0)


@pytest.mark.parametrize(
    ("printed", "code", "note"),
    [
        ("not json", 0, "output not JSON"),
        ('{"results": 3}', 0, "unexpected output"),
        ("{}", 7, "exit 7"),
    ],
)
def test_marks_scanner_failed_when_output_is_not_json(
    sweep: Sweep, capsys: pytest.CaptureFixture[str], *, printed: str, code: int, note: str
) -> None:
    sweep.fake("semgrep", printed, code=code)

    output = scanned(capsys)

    assert statuses(output)["semgrep"] == ("failed", note, 0)


def test_marks_scanner_timeout_when_call_exceeds_limit(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.fake("semgrep", SEMGREP_HIT, sleep=30)

    output = scanned(capsys, "--timeout", "0.5")

    status, note, count = statuses(output)["semgrep"]
    assert (status, count) == ("timeout", 0)
    assert note.startswith("over ")
    assert list(sweep.tmp.iterdir()) == []


def test_skips_scanners_when_budget_is_spent(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.fake("semgrep", SEMGREP_HIT)
    sweep.guard()

    output = scanned(capsys, "--budget", "0")

    assert statuses(output)["semgrep"] == ("skipped", "budget spent", 0)
    assert statuses(output)["guard"] == ("skipped", "budget spent", 0)
    assert sweep.calls() == []


def test_keeps_the_value_out_when_scanner_stderr_holds_it(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.fake("semgrep", VALUE, code=2, stderr=f"error near {VALUE}\n")
    sweep.fake("bandit", {"results": [a_bandit_result("B105", "hardcoded_password_string")]})

    code = load().main([])
    captured = capsys.readouterr()

    assert code == 0
    assert VALUE not in captured.out
    assert VALUE not in captured.err
    assert statuses(json.loads(captured.out))["semgrep"] == ("failed", "exit 2", 0)


def test_marks_repo_unreadable_when_origin_ref_is_missing(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.git("update-ref", "-d", "refs/remotes/origin/main")
    sweep.hub_json(
        {
            "project": {"default_branch": "main"},
            "repos": [{"dir": "app"}, {"dir": "gone"}, {"dir": "app", "default_branch": "-x"}],
        }
    )

    output = scanned(capsys)

    assert [(r["repo"], r["status"], r["note"]) for r in output["repos"]] == [
        ("app", "unreadable", "no origin/main: fetch it first"),
        ("gone", "unreadable", "no folder ../gone beside the hub"),
        ("app", "unreadable", "the default branch in hub.json is not usable"),
    ]
    assert all(repo["scanners"] == [] for repo in output["repos"])


def test_scans_only_the_named_repo_when_repo_given(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.hub_json({"repos": [{"dir": "app"}, {"dir": "gone"}]})

    output = scanned(capsys, "--repo", "app")

    assert [repo["repo"] for repo in output["repos"]] == ["app"]


def test_marks_repos_over_the_cap_unreadable_when_hub_json_lists_many(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    sweep.hub_json({"repos": [{"dir": f"r{n}"} for n in range(22)]})

    output = scanned(capsys)

    notes = [repo["note"] for repo in output["repos"]]
    assert notes[19] == "no folder ../r19 beside the hub"
    assert notes[20:] == ["over 20 repos: not scanned", "over 20 repos: not scanned"]


@pytest.mark.parametrize("repo", ["other", "..", "app/../x"])
def test_exits_two_when_repo_is_not_in_hub_json(
    sweep: Sweep, capsys: pytest.CaptureFixture[str], repo: str
) -> None:
    code = load().main(["--repo", repo])

    captured = capsys.readouterr()
    assert (code, captured.out) == (2, "")
    assert captured.err == f"scan.py: repo {json.dumps(repo)} is not in hub.json\n"


@pytest.mark.parametrize(
    ("content", "reason"),
    [
        (None, "not found"),
        ("{", "not JSON"),
        ("[]", "no repos list"),
        ('{"repos": {}}', "no repos list"),
        ("big", "over 1 MiB"),
    ],
)
def test_exits_two_when_hub_json_is_unreadable(
    sweep: Sweep, capsys: pytest.CaptureFixture[str], *, content: str | None, reason: str
) -> None:
    path = sweep.hub / "hub.json"
    path.unlink()
    if content is not None:
        path.write_text(" " * (1024 * 1024 + 1) if content == "big" else content, encoding="utf-8")

    code = load().main([])

    captured = capsys.readouterr()
    assert (code, captured.out) == (2, "")
    assert captured.err == f"scan.py: cannot read hub.json: {reason}\n"


def test_stays_under_output_cap_when_findings_are_many(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    rule = "python.lang.security.audit.eval-detected." + "x" * 150
    results = []
    for n in range(3000):
        result = a_semgrep_result(rule, ["CWE-95"], line=n)
        result["path"] = f"src/{'d' * 200}/{n}.py"
        results.append(result)
    sweep.fake("semgrep", {"results": results})

    code = load().main([])

    out = capsys.readouterr().out
    assert code == 0
    output = json.loads(out)
    assert len(out.encode()) <= 400 * 1024
    assert len(output["findings"]) <= 1000
    assert output["more"] == 3000 - len(output["findings"])
    assert output["trimmed"] is True


def test_leaves_repo_checkout_unchanged_when_scan_ran(
    sweep: Sweep, capsys: pytest.CaptureFixture[str]
) -> None:
    before = sweep.state()
    sweep.fake("semgrep", SEMGREP_HIT)
    sweep.fake("bandit", "boom", code=3)
    sweep.guard()

    scanned(capsys)

    assert sweep.state() == before
    assert list(sweep.tmp.iterdir()) == []
