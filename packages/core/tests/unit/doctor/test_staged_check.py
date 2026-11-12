"""AGH-835 (ADR 0061): ``hub doctor --staged`` decides on what the commit stages only."""

import json
from collections.abc import Mapping
from typing import Any

import pytest

from agent_hub.core.doctor.config_rules import config_state
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.snapshot import ConfigFailure
from agent_hub.core.doctor.staged_check import (
    CONFIG_SKIPPED,
    HYGIENE_RULE,
    StagedIndex,
    check_staged,
    commit_findings,
    hygiene_findings,
    staged_feature_folders,
)
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry
from agent_hub.core.testing.builders import a_hub_document

RUNNING = "0.1.0"
ALPHA = "brain/features/alpha"
BETA = "brain/features/beta"
MISSING = "AC-2: in spec.md but not in features.json"


def no_yaml_problem(_text: str) -> None:
    return None


def a_document() -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    return document


def a_config() -> HubConfig | ConfigFailure:
    return config_state(json.dumps(a_document()).encode(), running_version=RUNNING)


def a_record(feature: str) -> bytes:
    document = a_document()
    record = {
        "feature": feature,
        "linear": [],
        "acs": [
            {
                "id": "AC-1",
                "description": "Given x When y Then z",
                "repo": document["repos"][0]["dir"],
                "verification": "pytest tests/unit/test_x.py::test_1",
                "passes": False,
                "evidence": None,
            }
        ],
    }
    return (json.dumps(record, indent=2) + "\n").encode()


def a_feature(folder: str, *, spec_ids: str = "AC-1") -> dict[str, bytes]:
    return {
        f"{folder}/features.json": a_record(folder.rsplit("/", 1)[-1]),
        f"{folder}/spec.md": f"# spec\n\n- {spec_ids}: works.\n".encode(),
    }


def an_index(staged: tuple[str, ...], files: Mapping[str, bytes]) -> StagedIndex:
    """The index the CLI reads: the staged files and every file of the staged feature folders."""
    folders = staged_feature_folders(staged)
    entries: dict[str, TreeEntry] = {
        path: FileEntry(executable=False, content=content)
        for path, content in files.items()
        if path in staged or path.startswith(folders)
    }
    feature_files = tuple(sorted(path for path in entries if path.startswith(folders)))
    return StagedIndex(staged=staged, entries=entries, feature_files=feature_files)


def shown(findings: tuple[Finding, ...]) -> list[tuple[str, str | None, str]]:
    return [(finding.rule, finding.path, finding.message) for finding in findings]


def test_lists_feature_folders_when_paths_staged_inside() -> None:
    paths = (
        f"{BETA}/reviews/AGH-1/demo.json",
        f"{ALPHA}/spec.md",
        f"{ALPHA}/features.json",
        "brain/features/.hidden/spec.md",
        "brain/features/index.md",
        "brain/now.md",
    )

    assert staged_feature_folders(paths) == (f"{ALPHA}/", f"{BETA}/")


def test_checks_only_staged_feature_when_other_feature_broken() -> None:
    files = {**a_feature(ALPHA, spec_ids="AC-1, AC-2"), **a_feature(BETA)}
    # Feature A is broken in the index too, but the commit stages feature B only.
    index = an_index((f"{BETA}/spec.md",), files)

    run = check_staged(
        index, config=a_config(), running_version=RUNNING, yaml_problem=no_yaml_problem
    )

    assert run.findings == ()
    assert run.notes == ()


def test_blocks_when_staged_spec_names_missing_ac() -> None:
    files = {**a_feature(ALPHA, spec_ids="AC-1, AC-2"), **a_feature(BETA)}
    index = an_index((f"{ALPHA}/spec.md",), files)

    run = check_staged(
        index, config=a_config(), running_version=RUNNING, yaml_problem=no_yaml_problem
    )

    assert shown(run.findings) == [("features.tracker", f"{ALPHA}/features.json", MISSING)]
    assert run.findings[0].severity is Severity.ERROR


def test_drops_config_findings_when_hub_json_not_staged() -> None:
    finding = Finding(
        rule="config.schema",
        severity=Severity.ERROR,
        path="hub.json",
        line=None,
        message="m",
        fix="f",
    )

    assert commit_findings((finding,), hub_json_staged=False) == ()
    assert commit_findings((finding,), hub_json_staged=True) == (finding,)


def test_blocks_when_staged_hub_json_invalid() -> None:
    document = a_document()
    del document["project"]
    content = (json.dumps(document) + "\n").encode()
    index = an_index(("hub.json",), {"hub.json": content})
    config = config_state(content, running_version=RUNNING)

    run = check_staged(index, config=config, running_version=RUNNING, yaml_problem=no_yaml_problem)

    assert {finding.rule for finding in run.findings} == {"config.schema"}
    assert all(finding.severity is Severity.ERROR for finding in run.findings)


def test_skips_doctor_rules_with_note_when_unstaged_hub_json_invalid() -> None:
    files = a_feature(ALPHA, spec_ids="AC-1, AC-2")
    index = an_index((f"{ALPHA}/spec.md",), files)
    config = config_state(b"{", running_version=RUNNING)

    run = check_staged(index, config=config, running_version=RUNNING, yaml_problem=no_yaml_problem)

    assert run.findings == ()
    assert run.notes == (CONFIG_SKIPPED,)


def test_checks_staged_files_hygiene_when_no_feature_staged() -> None:
    index = an_index(("notes.md", "data.json"), {"notes.md": b"a \n", "data.json": b"{\n"})

    run = check_staged(
        index, config=a_config(), running_version=RUNNING, yaml_problem=no_yaml_problem
    )

    assert [(f.rule, f.path) for f in run.findings] == [
        (HYGIENE_RULE, "data.json"),
        (HYGIENE_RULE, "notes.md"),
    ]


def test_skips_link_when_staged() -> None:
    index = StagedIndex(
        staged=("link.md",),
        entries={"link.md": LinkEntry(target="target  ", outside=True)},
        feature_files=(),
    )

    run = check_staged(
        index, config=a_config(), running_version=RUNNING, yaml_problem=no_yaml_problem
    )

    assert run.findings == ()


@pytest.mark.parametrize(
    ("content", "line", "message"),
    [
        pytest.param(
            b"a \nb\n", 1, "trailing whitespace on 1 line(s), first at this line", id="space"
        ),
        pytest.param(
            b"a\nb\t\nc\t\n", 2, "trailing whitespace on 2 line(s), first at this line", id="tabs"
        ),
        pytest.param(
            b"a \r\n", 1, "trailing whitespace on 1 line(s), first at this line", id="crlf"
        ),
        pytest.param(b"a", None, "the file does not end with a newline", id="no-newline"),
        pytest.param(b"a\n\n", None, "the file ends with more than one newline", id="two-newlines"),
        pytest.param(b"\n", None, "the file ends with more than one newline", id="only-newline"),
    ],
)
def test_reports_hygiene_problem_when_text_file_bad(
    content: bytes, line: int | None, message: str
) -> None:
    found = hygiene_findings("notes.md", content, yaml_problem=no_yaml_problem)

    assert [(f.line, f.message) for f in found] == [(line, message)]


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"a\nb\n", id="lf"),
        pytest.param(b"a\r\nb\r\n", id="crlf"),
        pytest.param(b"a \x00\n", id="binary"),
        pytest.param(b"a \xff\n", id="not-utf8"),
    ],
)
def test_reports_nothing_when_file_clean_or_not_text(content: bytes) -> None:
    assert hygiene_findings("notes.md", content, yaml_problem=no_yaml_problem) == ()


@pytest.mark.parametrize(
    "content",
    [
        pytest.param(b"{\n", id="truncated"),
        pytest.param(b'{"a": 1, "a": 2}\n', id="repeated-key"),
        pytest.param(b"{}\n{}\n", id="two-documents"),
    ],
)
def test_reports_json_problem_when_json_invalid(content: bytes) -> None:
    found = hygiene_findings("data.JSON", content, yaml_problem=no_yaml_problem)

    assert [f.fix for f in found] == ["fix the JSON"]
    assert found[0].message.startswith("not valid JSON: ")


def test_reports_yaml_problem_when_parser_refuses() -> None:
    def refusing(text: str) -> str:
        assert text == "a: [\n"
        return "unclosed"

    found = hygiene_findings("ci.yml", b"a: [\n", yaml_problem=refusing)

    assert [(f.message, f.fix) for f in found] == [("not valid YAML: unclosed", "fix the YAML")]


def test_asks_no_yaml_parser_when_file_not_yaml() -> None:
    def failing(_text: str) -> str:
        raise AssertionError

    assert hygiene_findings("notes.md", b"a: [\n", yaml_problem=failing) == ()
