import json

import pytest

from agent_hub.cli.doctor_report import finding_line, report_json, report_lines, totals_line
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.run_rules import Totals
from agent_hub.core.hub_config.doctor_rules import Severity


def a_finding(
    rule: str = "lock.drift",
    *,
    severity: Severity = Severity.ERROR,
    path: str | None = "hub.lock",
    line: int | None = None,
    message: str = "drifted",
    fix: str = "run hub sync",
) -> Finding:
    return Finding(rule=rule, severity=severity, path=path, line=line, message=message, fix=fix)


# AC-11.9's set: two rules, two paths, one pathless finding, one without a line, in reverse.
REVERSED = (
    a_finding("makefile.override", severity=Severity.WARNING, path="Makefile.project", line=4),
    a_finding("makefile.override", severity=Severity.WARNING, path="Makefile.project", line=2),
    a_finding("lock.drift", path="b.md", message="second b"),
    a_finding("lock.drift", path="b.md", message="first b"),
    a_finding("lock.drift", path="a.md", line=3),
    a_finding("lock.drift", path="a.md"),
    a_finding("lock.drift", severity=Severity.INFO, path=None, message="no lock"),
)


def test_formats_line_when_finding_has_path_and_line() -> None:
    finding = a_finding(path="AGENTS.md", line=12, message="too long", fix="split it")

    assert finding_line(finding) == "error lock.drift AGENTS.md:12: too long Fix: split it"
    assert finding_line(a_finding(path="AGENTS.md", line=None)) == (
        "error lock.drift AGENTS.md: drifted Fix: run hub sync"
    )


def test_formats_pathless_line_when_no_path() -> None:
    finding = a_finding(severity=Severity.WARNING, path=None, message="not adopted")

    assert finding_line(finding) == "warning lock.drift: not adopted Fix: run hub sync"


def test_prints_sorted_lines_then_totals_when_findings_given() -> None:
    assert report_lines(REVERSED) == [
        "info lock.drift: no lock Fix: run hub sync",
        "error lock.drift a.md: drifted Fix: run hub sync",
        "error lock.drift a.md:3: drifted Fix: run hub sync",
        "error lock.drift b.md: second b Fix: run hub sync",
        "error lock.drift b.md: first b Fix: run hub sync",
        "warning makefile.override Makefile.project:2: drifted Fix: run hub sync",
        "warning makefile.override Makefile.project:4: drifted Fix: run hub sync",
        "4 errors, 2 warnings, 1 info",
    ]


def test_prints_only_totals_when_no_findings() -> None:
    assert report_lines(()) == ["0 errors, 0 warnings, 0 infos"]


@pytest.mark.parametrize(
    ("totals", "expected"),
    [
        (Totals(errors=0, warnings=1, infos=0), "0 errors, 1 warning, 0 infos"),
        (Totals(errors=1, warnings=0, infos=1), "1 error, 0 warnings, 1 info"),
        (Totals(errors=0, warnings=0, infos=0), "0 errors, 0 warnings, 0 infos"),
        (Totals(errors=2, warnings=2, infos=2), "2 errors, 2 warnings, 2 infos"),
    ],
)
def test_counts_totals_when_findings_mixed(totals: Totals, expected: str) -> None:
    assert totals_line(totals) == expected


@pytest.mark.parametrize(
    ("path", "message", "expected"),
    [
        ("a\nb.md", "plain", "error lock.drift a\\nb.md: plain Fix: run hub sync"),
        ("a.md", "one\ntwo", "error lock.drift a.md: one\\ntwo Fix: run hub sync"),
        ("a.md", "esc \x1b[31m", "error lock.drift a.md: esc \\x1b[31m Fix: run hub sync"),
        ("a\r.md", "line\u2028sep", "error lock.drift a\\r.md: line\\u2028sep Fix: run hub sync"),
        ("é.md", "tab\there", "error lock.drift é.md: tab\\there Fix: run hub sync"),
        ("a.md", "a\u202eb", "error lock.drift a.md: a\\u202eb Fix: run hub sync"),
        ("a.md", "a\x00b", "error lock.drift a.md: a\\x00b Fix: run hub sync"),
        ("a.md", "\x1b]0;t\x07", "error lock.drift a.md: \\x1b]0;t\\x07 Fix: run hub sync"),
        ("\udcff.md", "plain", "error lock.drift \\udcff.md: plain Fix: run hub sync"),
    ],
)
def test_escapes_control_character_when_path_or_message_holds_one(
    path: str, message: str, expected: str
) -> None:
    lines = report_lines((a_finding(path=path, message=message),))

    assert lines[0] == expected
    assert len("\n".join(lines).splitlines()) == len(lines)


def test_escapes_control_character_when_fix_holds_one() -> None:
    # ``Finding`` refuses a line break in ``fix``, not a tab or ESC.
    finding = a_finding(fix="run\thub \x1b sync")

    assert finding_line(finding) == "error lock.drift hub.lock: drifted Fix: run\\thub \\x1b sync"


def test_prints_one_json_object_when_json_requested() -> None:
    output = report_json(REVERSED)

    assert output.endswith(b"}\n")
    assert not output.endswith(b"\n\n")
    document = json.loads(output)
    assert list(document) == ["findings", "totals"]
    assert document["totals"] == {"errors": 4, "infos": 1, "warnings": 2}
    assert all(type(count) is int for count in document["totals"].values())
    assert [
        (finding["rule"], finding["path"], finding["line"], finding["message"])
        for finding in document["findings"]
    ] == [
        ("lock.drift", None, None, "no lock"),
        ("lock.drift", "a.md", None, "drifted"),
        ("lock.drift", "a.md", 3, "drifted"),
        ("lock.drift", "b.md", None, "second b"),
        ("lock.drift", "b.md", None, "first b"),
        ("makefile.override", "Makefile.project", 2, "drifted"),
        ("makefile.override", "Makefile.project", 4, "drifted"),
    ]
    assert document["findings"][2] == {
        "fix": "run hub sync",
        "line": 3,
        "message": "drifted",
        "path": "a.md",
        "rule": "lock.drift",
        "severity": "error",
    }


def test_writes_null_when_field_absent_in_json() -> None:
    output = report_json((a_finding(path=None, line=None, severity=Severity.INFO),))

    finding = json.loads(output)["findings"][0]
    assert finding["path"] is None
    assert finding["line"] is None
    assert finding["severity"] == "info"
    assert b'"path": null' in output
    assert b'"line": null' in output


def test_keeps_raw_text_when_json_holds_control_character() -> None:
    output = report_json((a_finding(path="a\nb.md", message="one\x1btwo"),))

    finding = json.loads(output)["findings"][0]
    assert finding["path"] == "a\nb.md"
    assert finding["message"] == "one\x1btwo"
    assert b'"path": "a\\nb.md"' in output


def test_escapes_lone_surrogate_when_json_path_holds_one() -> None:
    # A file name that is not UTF-8 reaches the doctor as a lone surrogate (``os.scandir``, git).
    output = report_json((a_finding(path="\udcff.md", message="bad \udcff", fix="rename \udcff"),))

    finding = json.loads(output)["findings"][0]
    assert finding["path"] == "\\udcff.md"
    assert finding["message"] == "bad \\udcff"
    assert finding["fix"] == "rename \\udcff"


def test_prints_empty_findings_when_json_has_none() -> None:
    assert report_json(()) == (
        b'{\n  "findings": [],\n  "totals": {\n    "errors": 0,\n'
        b'    "infos": 0,\n    "warnings": 0\n  }\n}\n'
    )
