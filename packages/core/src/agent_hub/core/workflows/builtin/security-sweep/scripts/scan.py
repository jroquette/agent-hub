# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
"""Run the installed security scanners on the hub's repos and print their findings as one JSON
object; never print a scanner's text.

A finding keeps only the structured fields of ``FIELDS`` (rule, path, line, severity, CWE,
package, version, advisory, fix, title): never a scanner's message, matched lines, code,
description or stderr, so a credential in the code cannot reach the output. A secret finding
(``is_secret``) also drops its line: it is its rule and path only.
"""

import json
import re
import sys
import unicodedata
from collections.abc import Callable

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


def main(argv: list[str]) -> int:
    print(f"scan.py: no runner yet for {json.dumps(argv)}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
