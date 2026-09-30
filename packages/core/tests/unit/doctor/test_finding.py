from collections.abc import Iterable

import pytest

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity


def a_finding(*, fix: str = "run hub sync", line: int | None = None) -> Finding:
    return Finding(
        rule="lock.drift",
        severity=Severity.ERROR,
        path="Makefile",
        line=line,
        message="differs from hub.lock",
        fix=fix,
    )


def no_findings(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    del snapshot
    return ()


@pytest.mark.parametrize(
    "fix",
    [
        pytest.param("", id="empty"),
        pytest.param("run hub sync\nthen commit", id="newline"),
        pytest.param("run hub sync\n", id="trailing-newline"),
        pytest.param("run hub sync\rthen commit", id="carriage-return"),
        pytest.param("run hub sync then commit", id="line-separator"),
    ],
)
def test_refuses_finding_when_fix_empty_or_multiline(fix: str) -> None:
    with pytest.raises(ValueError, match="fix must be one non-empty line"):
        a_finding(fix=fix)


@pytest.mark.parametrize("line", [0, -1])
def test_refuses_finding_when_line_not_positive(line: int) -> None:
    with pytest.raises(ValueError, match="line must be 1 or more"):
        a_finding(line=line)


@pytest.mark.parametrize("line", [None, 1])
def test_builds_finding_when_line_absent_or_first(line: int | None) -> None:
    assert a_finding(line=line).line == line


def test_builds_finding_with_rule_defaults_when_rule_reports() -> None:
    rule = Rule(
        id="makefile.override",
        severity=Severity.WARNING,
        summary="Makefile.project redefines a Makefile target.",
        module=None,
        reads=frozenset({Read.HUB_LISTING}),
        check=no_findings,
    )

    finding = rule.finding(path="Makefile.project", line=3, message="redefines", fix="rename it")
    pathless = rule.finding(path=None, message="no path", fix="look")

    assert finding == Finding(
        rule="makefile.override",
        severity=Severity.WARNING,
        path="Makefile.project",
        line=3,
        message="redefines",
        fix="rename it",
    )
    assert (pathless.rule, pathless.severity, pathless.path, pathless.line) == (
        "makefile.override",
        Severity.WARNING,
        None,
        None,
    )
