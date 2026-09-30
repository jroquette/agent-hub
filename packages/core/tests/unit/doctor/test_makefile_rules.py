from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor.makefile_rules import MAKEFILE_OVERRIDE
from agent_hub.core.doctor.run_rules import Selection, count_findings, run_rules, select_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry, TreeEntry
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[Severity, str | None, int | None, str, str]

PROJECT = "Makefile.project"
FIX = "rename the project target"
# The managed Makefile's shapes (the generator's template), rebuilt here: core never reads
# templates. The continued ``HUB`` assignment holds ``echo "hub: …"``, which is no target.
MANAGED = (
    "SHELL := /bin/bash\n"
    ".DEFAULT_GOAL := help\n"
    "HUB = hub() { \\\n"
    '  command -v uvx || { echo "hub: uv is not installed" >&2; return 127; }; \\\n'
    "}; hub\n"
    "\n"
    ".PHONY: brain-brief check help\n"
    "\n"
    "brain-brief:  ## Session brief\n"
    "\t@$(HUB) brief\n"
    "\n"
    "check:  ## Hub gates\n"
    "\t@$(HUB) doctor\n"
    "\n"
    "help:  ## Show this help\n"
    "\t@grep -hE '^[a-z]+:.*?## .*$$' $(MAKEFILE_LIST)\n"
    "\n"
    "-include Makefile.project\n"
)
# The seeded Makefile.project (the generator's template).
SEEDED = (
    "# Project targets and variables. The Makefile includes this file last, so recipes here may"
    " use $(HUB).\n"
    "# Seeded once: hub sync never touches it.\n"
)


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(MAKEFILE_OVERRIDE.check(snapshot))
    assert all(finding.rule == "makefile.override" for finding in found)
    return [
        (finding.severity, finding.path, finding.line, finding.message, finding.fix)
        for finding in found
    ]


def with_project(
    snapshot_of: SnapshotFactory, project: str, *, managed: str = MANAGED
) -> DoctorSnapshot:
    return snapshot_of(files={"Makefile": managed.encode(), PROJECT: project.encode()})


def a_warning(target: str, line: int) -> Shown:
    return (Severity.WARNING, PROJECT, line, f"redefines target '{target}'", FIX)


def test_reads_nothing_beyond_fixed_paths_when_rule_declared() -> None:
    assert MAKEFILE_OVERRIDE.reads == frozenset()
    assert MAKEFILE_OVERRIDE.severity is Severity.WARNING
    assert MAKEFILE_OVERRIDE.module is None


@pytest.mark.parametrize(
    ("project", "expected"),
    [
        pytest.param("# mine\n\ncheck:  ## mine\n\t@echo x\n", [a_warning("check", 3)], id="rule"),
        pytest.param("check::\n\t@echo x\n", [a_warning("check", 1)], id="double-colon"),
        pytest.param("check: lint\n", [a_warning("check", 1)], id="prerequisite"),
        pytest.param("check: ; @echo x\n", [a_warning("check", 1)], id="inline-recipe"),
        pytest.param("lint check:\n", [a_warning("check", 1)], id="several-targets"),
        pytest.param(
            "check help :\n", [a_warning("check", 1), a_warning("help", 1)], id="two-managed"
        ),
        pytest.param("  check:\n", [a_warning("check", 1)], id="indented-by-spaces"),
        pytest.param("lint:\n\r\ncheck:\r\n", [a_warning("check", 3)], id="crlf"),
        pytest.param("X = a \\\n  b\ncheck:\n", [a_warning("check", 3)], id="after-continued-line"),
        pytest.param("check \\\n  lint:\n", [a_warning("check", 1)], id="continued-rule-line"),
        pytest.param("lint:\ncheck: \\\n", [a_warning("check", 2)], id="continued-last-line"),
        # Two backslashes are an escaped one: the line is not continued.
        pytest.param("X = a\\\\\ncheck:\n", [a_warning("check", 2)], id="escaped-backslash"),
        pytest.param(
            "define BODY\ncheck:\nendef\nhelp:\n", [a_warning("help", 4)], id="after-define"
        ),
        pytest.param(
            "define OUTER\ndefine INNER\nendef\ncheck:\nendef\nhelp:\n",
            [a_warning("help", 6)],
            id="after-nested-define",
        ),
        pytest.param(
            "override define BODY =\ncheck:\nendef\nhelp:\n",
            [a_warning("help", 4)],
            id="after-override-define",
        ),
        # GNU make 4.3+ grouped targets: ``&`` before the separator is no part of a name.
        pytest.param("check&: x\n", [a_warning("check", 1)], id="grouped-target"),
        pytest.param("lint check &: x\n", [a_warning("check", 1)], id="grouped-targets"),
        pytest.param("check check:\n", [a_warning("check", 1)], id="repeated-target"),
    ],
)
def test_warns_when_project_makefile_redefines_target(
    snapshot_of: SnapshotFactory, project: str, expected: list[Shown]
) -> None:
    assert findings_of(with_project(snapshot_of, project)) == expected


@pytest.mark.parametrize(
    "project",
    [
        pytest.param(SEEDED, id="seeded"),
        pytest.param("lint:  ## mine\n\t@echo check: done\n", id="new-target"),
        pytest.param("check := x\n", id="simple-assignment"),
        pytest.param("check ::= x\n", id="posix-simple-assignment"),
        pytest.param("check :::= x\n", id="immediate-assignment"),
        pytest.param("check ?= x\n", id="conditional-assignment"),
        pytest.param("check = x: y\n", id="recursive-assignment"),
        pytest.param("check += x\n", id="appending-assignment"),
        pytest.param("# check:\n", id="comment"),
        pytest.param("# a comment \\\ncheck:\n", id="continued-comment"),
        pytest.param("X = a \\\n  check: b\n", id="continued-assignment"),
        pytest.param("X = a \\\r\n  check: b\r\n", id="crlf-continued-assignment"),
        pytest.param("\tcheck: x\n", id="recipe-line"),
        pytest.param("define BODY\ncheck:\nendef\n", id="define-block"),
        pytest.param("checks:\nrecheck:\n", id="longer-names"),
    ],
)
def test_reports_nothing_when_rule_line_is_new_target_or_assignment(
    snapshot_of: SnapshotFactory, project: str
) -> None:
    assert findings_of(with_project(snapshot_of, project)) == []


def test_reports_nothing_when_project_makefile_absent(snapshot_of: SnapshotFactory) -> None:
    assert findings_of(snapshot_of(files={"Makefile": MANAGED.encode()})) == []


def test_ignores_phony_and_variables_when_targets_read(snapshot_of: SnapshotFactory) -> None:
    # Neither the special targets, the variables, the text of a continued line, a recipe line nor
    # a define body of the managed Makefile is a managed target.
    managed = MANAGED + "define TEMPLATE\ninner:\nendef\n"
    project = ".PHONY: lint\n.DEFAULT_GOAL:\nSHELL:\nHUB:\nhub:\n@grep:\ninner:\n"

    assert findings_of(with_project(snapshot_of, project, managed=managed)) == []


@pytest.mark.parametrize(
    "entries",
    [
        pytest.param({}, id="both-absent"),
        pytest.param({PROJECT: FileEntry(executable=False, content=b"check:\n")}, id="no-makefile"),
        pytest.param(
            {
                "Makefile": FileEntry(executable=False, content=b"check:\n\x00"),
                PROJECT: FileEntry(executable=False, content=b"check:\n"),
            },
            id="makefile-binary",
        ),
        pytest.param(
            {
                "Makefile": FileEntry(executable=False, content=b"check:\n"),
                PROJECT: LinkEntry(target="elsewhere.mk", outside=False),
            },
            id="project-link",
        ),
        pytest.param(
            {"Makefile": FileEntry(executable=False, content=b"check:\n"), PROJECT: FolderEntry()},
            id="project-folder",
        ),
        pytest.param(
            {
                "Makefile": FileEntry(executable=False, content=b"check:\n"),
                PROJECT: FileEntry(executable=False, content=b"check:\n\xff"),
            },
            id="project-not-utf8",
        ),
    ],
)
def test_reports_nothing_when_makefiles_not_text(
    snapshot_of: SnapshotFactory, entries: Mapping[str, TreeEntry]
) -> None:
    assert findings_of(snapshot_of(entries=entries)) == []


def test_makes_error_when_severity_set_to_error(snapshot_of: SnapshotFactory) -> None:
    document = a_hub_document()
    document["doctor"] = {"rules": {"makefile.override": {"severity": "error"}}}
    retuned = HubConfig.model_validate(document)
    selection = select_rules((MAKEFILE_OVERRIDE,), config=retuned, only=())
    assert isinstance(selection, Selection), selection
    snapshot = snapshot_of(
        config=retuned, files={"Makefile": MANAGED.encode(), PROJECT: b"check:\n"}
    )

    findings = run_rules(selection, snapshot)

    assert [(finding.severity, finding.line) for finding in findings] == [(Severity.ERROR, 1)]
    assert count_findings(findings).has_errors
