"""The security-sweep pack's ``scan.py`` (AGH-486), in process: scanner JSON becomes findings that
keep structured fields only, so no secret value reaches a node output (AC-3)."""

import importlib.util
import json
import sys
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
