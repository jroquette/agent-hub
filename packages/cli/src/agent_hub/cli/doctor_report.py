"""What ``hub doctor`` prints: one line per finding, then the totals; or one JSON object.

A line reads ``<severity> <rule> <path>[:<line>]: <message> Fix: <fix>``, or
``<severity> <rule>: <message> Fix: <fix>`` without a path; findings come sorted as
``sort_findings`` orders them, and the last line always holds the three counts, singular at 1
(spec D2). The path, the message and the fix each go through ``one_line``, so a file name or
file text holding a line break or another unprintable character stays on its one line (plan
erratum E14). ``--json`` keeps the raw values, which JSON escapes, except a lone surrogate (a
file name that is not UTF-8): UTF-8 cannot encode it, so it is written backslash-escaped.
"""

from collections.abc import Iterable, Sequence

from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.run_rules import Totals, count_findings, sort_findings
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.json_form import JsonValue, dump_json


def finding_line(finding: Finding) -> str:
    """The report line of one finding."""
    where = ""
    if finding.path is not None:
        line = "" if finding.line is None else f":{finding.line}"
        where = f" {one_line(finding.path)}{line}"
    return (
        f"{finding.severity} {finding.rule}{where}: {one_line(finding.message)}"
        f" Fix: {one_line(finding.fix)}"
    )


def totals_line(totals: Totals) -> str:
    """``N errors, M warnings, K infos``, each word singular at 1."""
    return ", ".join(
        _counted(count, noun)
        for count, noun in (
            (totals.errors, "error"),
            (totals.warnings, "warning"),
            (totals.infos, "info"),
        )
    )


def _counted(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def report_lines(findings: Iterable[Finding]) -> list[str]:
    """The sorted finding lines, then the totals line."""
    ordered = sort_findings(findings)
    return [*(finding_line(finding) for finding in ordered), totals_line(count_findings(ordered))]


def report_json(findings: Iterable[Finding]) -> bytes:
    """One JSON object: ``findings`` in the text order, integer ``totals``, then a newline."""
    ordered = sort_findings(findings)
    totals = count_findings(ordered)
    document: dict[str, JsonValue] = {
        "findings": _finding_objects(ordered),
        "totals": {"errors": totals.errors, "warnings": totals.warnings, "infos": totals.infos},
    }
    return dump_json(document)


def _finding_objects(findings: Sequence[Finding]) -> list[JsonValue]:
    return [
        {
            "rule": finding.rule,
            "severity": str(finding.severity),
            "path": None if finding.path is None else _encodable(finding.path),
            "line": finding.line,
            "message": _encodable(finding.message),
            "fix": _encodable(finding.fix),
        }
        for finding in findings
    ]


def _encodable(text: str) -> str:
    """``text`` with each lone surrogate as its ``\\udcff`` escape; valid text unchanged."""
    return text.encode("utf-8", "backslashreplace").decode("utf-8")
