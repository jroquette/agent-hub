from collections.abc import Mapping

import pytest

from scripts.check_test_layout import (
    Violation,
    checked_level,
    find_violations,
    main,
    split_git_listing,
)
from scripts.pytest_levels import level_of

MYPY_INI = """\
[mypy]
strict = True
mypy_path = packages/core/src:packages/storage/src
files = packages/core/src,packages/storage/src,scripts,conftest.py
"""

IMPORTLINTER = """\
[importlinter]
root_packages =
    agent_hub

[importlinter:contract:core-independent]
name = core imports nothing internal
type = forbidden
source_modules =
    agent_hub.core
forbidden_modules =
    agent_hub.storage
    sqlalchemy

[importlinter:contract:composition-root]
name = cli is the composition root
type = layers
layers =
    agent_hub.cli
    agent_hub.storage | (agent_hub.api)
"""

MAKEFILE = """\
RUN := uv run --locked --all-packages
COV := --cov=agent_hub.core \\
       --cov=agent_hub.storage --cov-branch --cov-report=

test-fast:
\t$(RUN) pytest $(COV) --cov=agent_hub.collector
"""

REGISTERED = {
    "mypy.ini": MYPY_INI,
    ".importlinter": IMPORTLINTER,
    "Makefile": MAKEFILE,
    "packages/core/src/agent_hub/core/__init__.py": "",
    "packages/storage/src/agent_hub/storage/__init__.py": "",
}

VALID_TEST = "def test_parses_line_when_input_valid() -> None:\n    pass\n"


def rule_hits(files: Mapping[str, str], rule: str) -> list[str]:
    return [violation.path for violation in find_violations(files) if violation.rule == rule]


def files_with(*paths: str, source: str = VALID_TEST) -> dict[str, str]:
    return {**REGISTERED, **dict.fromkeys(paths, source)}


# level-folder


@pytest.mark.parametrize(
    "path",
    [
        "packages/core/tests/test_a.py",
        "packages/core/tests/e2e/test_a.py",
        "packages/core/tests/smoke/test_a.py",
        "tests/integration/test_a.py",
        "tests/test_a.py",
        "packages/core/src/agent_hub/core/test_a.py",
        "packages/core/tests/contract/tests/test_parser.py",
        "packages/core/tests/unit/tests/integration/test_x.py",
        "tests/unit/tests/unit/test_a.py",
    ],
)
def test_reports_level_folder_when_test_outside_allowed_level(path: str) -> None:
    assert rule_hits(files_with(path), "level-folder") == [path]


@pytest.mark.parametrize(
    "path",
    [
        "packages/core/tests/unit/test_a.py",
        "packages/core/tests/contract/test_a.py",
        "packages/storage/tests/integration/test_a.py",
        "tests/unit/scripts/test_a.py",
        "tests/e2e/test_a.py",
        "packages/core/tests/conftest.py",
        "packages/core/tests/__init__.py",
        "tests/conftest.py",
    ],
)
def test_accepts_level_folder_when_test_under_allowed_level(path: str) -> None:
    assert rule_hits(files_with(path), "level-folder") == []


LEVEL_PATHS = [
    "packages/core/tests/unit/test_a.py",
    "packages/core/tests/unit/x/test_a.py",
    "packages/core/tests/contract/test_a.py",
    "packages/storage/tests/integration/test_a.py",
    "packages/core/tests/e2e/test_a.py",
    "packages/core/tests/test_a.py",
    "packages/core/tests/contract/tests/test_parser.py",
    "packages/core/tests/unit/tests/integration/test_x.py",
    "packages/core/src/agent_hub/core/tests/unit/test_a.py",
    "tests/unit/scripts/test_a.py",
    "tests/e2e/test_a.py",
    "tests/integration/test_a.py",
    "tests/unit/tests/unit/test_a.py",
    "tests/test_a.py",
]


@pytest.mark.parametrize("path", LEVEL_PATHS)
def test_agrees_with_marker_plugin_when_level_checked(path: str) -> None:
    reported = rule_hits(files_with(path), "level-folder") == [path]
    level = checked_level(path)

    assert reported == (level is None)
    assert level is None or level == level_of(path)


# test-file-name


@pytest.mark.parametrize(
    "path",
    [
        "packages/core/tests/unit/builders.py",
        "packages/core/tests/sample.py",
        "tests/unit/scripts/fixtures.py",
        "tests/e2e/conftest_extra.py",
        "packages/core/tests/unit/ingestion/a_test.py",
    ],
)
def test_reports_test_file_name_when_tests_tree_module_not_named_test(path: str) -> None:
    assert rule_hits(files_with(path), "test-file-name") == [path]


@pytest.mark.parametrize(
    "path",
    [
        "packages/core/tests/unit/test_a.py",
        "packages/core/tests/conftest.py",
        "packages/core/tests/unit/__init__.py",
        "tests/conftest.py",
        "tests/e2e/test_a.py",
        "packages/core/src/agent_hub/core/errors.py",
        "scripts/check_x.py",
    ],
)
def test_accepts_test_file_name_when_module_named_test_or_exempt(path: str) -> None:
    assert rule_hits(files_with(path), "test-file-name") == []


# mirror

UNMIRRORED_TEST = "packages/core/tests/unit/ingestion/test_ingest_transcript.py"


def test_reports_mirror_when_unit_test_has_no_src_module() -> None:
    assert rule_hits(files_with(UNMIRRORED_TEST), "mirror") == [UNMIRRORED_TEST]


@pytest.mark.parametrize(
    ("test_path", "module_path"),
    [
        (UNMIRRORED_TEST, "packages/core/src/agent_hub/core/ingestion/ingest_transcript.py"),
        (
            UNMIRRORED_TEST,
            "packages/core/src/agent_hub/core/ingestion/ingest_transcript/__init__.py",
        ),
        ("packages/core/tests/unit/test_errors.py", "packages/core/src/agent_hub/core/errors.py"),
        ("packages/storage/tests/unit/test_db.py", "packages/storage/src/agent_hub/storage/db.py"),
        ("packages/cli/tests/unit/test_main.py", "packages/cli/src/agent_hub/cli/main.py"),
        ("tests/unit/scripts/test_pytest_levels.py", "scripts/pytest_levels.py"),
    ],
)
def test_accepts_mirror_when_src_module_exists(test_path: str, module_path: str) -> None:
    files = {**files_with(test_path), module_path: ""}

    assert rule_hits(files, "mirror") == []


def test_reports_mirror_when_module_lives_in_another_package() -> None:
    path = "packages/storage/tests/unit/test_errors.py"
    files = {**files_with(path), "packages/core/src/agent_hub/core/errors.py": ""}

    assert rule_hits(files, "mirror") == [path]


def test_skips_mirror_when_test_is_not_unit_level() -> None:
    files = files_with(
        "packages/storage/tests/integration/test_migrations.py", "tests/e2e/test_hub_cli.py"
    )

    assert rule_hits(files, "mirror") == []


# test-name


def test_reports_test_name_when_function_has_no_condition() -> None:
    path = "tests/e2e/test_a.py"
    source = "def test_something() -> None:\n    pass\n"

    violations = [v for v in find_violations(files_with(path, source=source)) if v.path == path]

    assert [(v.rule, "test_something" in v.message) for v in violations] == [("test-name", True)]


def test_reports_test_name_when_method_in_test_class_has_no_condition() -> None:
    source = "class TestParser:\n    def test_parses(self) -> None:\n        pass\n"

    assert rule_hits(files_with("tests/e2e/test_a.py", source=source), "test-name") == [
        "tests/e2e/test_a.py"
    ]


def test_accepts_test_name_when_behavior_and_condition_present() -> None:
    source = (
        "def helper() -> None:\n    pass\n\n\n"
        "def test_parses_line_when_input_valid() -> None:\n    pass\n\n\n"
        "class TestParser:\n"
        "    def test_parses_line_when_input_valid(self) -> None:\n        pass\n"
    )

    assert rule_hits(files_with("tests/e2e/test_a.py", source=source), "test-name") == []


# ticket-name, generic-name, numbered-name


@pytest.mark.parametrize(
    ("path", "rule"),
    [
        ("tests/e2e/test_pr_987.py", "ticket-name"),
        ("tests/e2e/test_agh_12.py", "ticket-name"),
        ("tests/e2e/test_misc.py", "generic-name"),
        ("tests/e2e/test_utils.py", "generic-name"),
        ("tests/e2e/test_new.py", "generic-name"),
        ("tests/e2e/test_temp.py", "generic-name"),
        ("tests/e2e/test_ingest_2.py", "numbered-name"),
    ],
)
def test_reports_name_rule_when_file_stem_is_forbidden(path: str, rule: str) -> None:
    assert rule_hits(files_with(path), rule) == [path]


@pytest.mark.parametrize(
    ("function", "rule"),
    [
        ("test_fixes_crash_when_agh_12", "ticket-name"),
        ("test_misc_when_called", "generic-name"),
        ("test_ingest_2_when_x", "numbered-name"),
    ],
)
def test_reports_name_rule_when_function_name_is_forbidden(function: str, rule: str) -> None:
    source = f"def {function}() -> None:\n    pass\n"

    assert rule_hits(files_with("tests/e2e/test_a.py", source=source), rule) == [
        "tests/e2e/test_a.py"
    ]


def test_reports_only_ticket_name_when_ticket_name_also_numbered() -> None:
    path = "tests/e2e/test_pr_987.py"

    rules = {v.rule for v in find_violations(files_with(path)) if v.path == path}

    assert rules == {"ticket-name"}


@pytest.mark.parametrize(
    "path", ["tests/e2e/test_uuid_v7.py", "tests/e2e/test_hub_cli.py", "tests/e2e/test_newline.py"]
)
def test_accepts_name_rules_when_file_stem_is_descriptive(path: str) -> None:
    violations = [v for v in find_violations(files_with(path)) if v.path == path]

    assert violations == []


def test_accepts_name_rules_when_regression_test_names_behavior() -> None:
    source = (
        'def test_parses_rfc_9457_body_when_error() -> None:\n    """Regression for AGH-12."""\n'
    )
    path = "tests/e2e/test_a.py"

    violations = [v for v in find_violations(files_with(path, source=source)) if v.path == path]

    assert violations == []


# forbidden-module


@pytest.mark.parametrize(
    "path",
    [
        "packages/core/src/agent_hub/core/utils.py",
        "packages/core/src/agent_hub/core/helpers.py",
        "packages/storage/src/agent_hub/storage/common.py",
        "packages/cli/src/agent_hub/cli/misc.py",
        "packages/core/src/agent_hub/core/helpers/__init__.py",
        "packages/core/src/agent_hub/core/common/strings.py",
        "packages/core/src/agent_hub/core/helper.py",
        "scripts/utils.py",
        "scripts/util.py",
        "packages/core/tests/unit/utils.py",
        "packages/core/tests/unit/common/test_strings.py",
        "tests/unit/helper.py",
        "tests/unit/misc/test_a.py",
    ],
)
def test_reports_forbidden_module_when_module_or_package_name_is_generic(path: str) -> None:
    assert rule_hits({**REGISTERED, path: ""}, "forbidden-module") == [path]


@pytest.mark.parametrize(
    "path",
    [
        "scripts/check_x.py",
        "packages/core/src/agent_hub/core/errors.py",
        "packages/core/src/agent_hub/core/utilities_note.md",
        "packages/core/tests/unit/test_utils_when_x.py",
        "tests/unit/scripts/test_check_x.py",
    ],
)
def test_accepts_forbidden_module_when_module_name_is_specific(path: str) -> None:
    assert rule_hits({**REGISTERED, path: ""}, "forbidden-module") == []


# package-registered

COLLECTOR_INIT = "packages/collector/src/agent_hub/collector/__init__.py"


def test_accepts_package_registered_when_every_config_lists_the_package() -> None:
    assert rule_hits(REGISTERED, "package-registered") == []


def test_reports_package_registered_when_package_missing_from_every_config() -> None:
    files = {**REGISTERED, COLLECTOR_INIT: ""}

    messages = [v.message for v in find_violations(files) if v.rule == "package-registered"]

    assert len(messages) == 5
    assert all("collector" in message for message in messages)
    assert sorted(rule_hits(files, "package-registered")) == [
        ".importlinter",
        ".importlinter",
        "Makefile",
        "mypy.ini",
        "mypy.ini",
    ]


@pytest.mark.parametrize("config", [".importlinter", "mypy.ini", "Makefile"])
def test_reports_package_registered_when_config_file_missing(config: str) -> None:
    files = {path: source for path, source in REGISTERED.items() if path != config}

    assert rule_hits(files, "package-registered") == [config]


def test_reports_package_registered_when_package_missing_from_makefile_cov() -> None:
    makefile = MAKEFILE.replace("--cov=agent_hub.storage ", "")

    violations = find_violations({**REGISTERED, "Makefile": makefile})

    assert [(v.path, v.rule) for v in violations] == [("Makefile", "package-registered")]
    assert "agent_hub.storage" in violations[0].message


def test_reports_package_registered_when_makefile_has_no_cov_variable() -> None:
    makefile = MAKEFILE.replace("COV :=", "COVERAGE :=")

    assert rule_hits({**REGISTERED, "Makefile": makefile}, "package-registered") == ["Makefile"]


def test_accepts_package_registered_when_cov_uses_recursive_assignment() -> None:
    makefile = MAKEFILE.replace("COV :=", "COV =")

    assert rule_hits({**REGISTERED, "Makefile": makefile}, "package-registered") == []


def test_ignores_cov_flags_when_outside_cov_variable() -> None:
    makefile = MAKEFILE.replace("--cov=agent_hub.core \\\n", "\\\n")
    makefile += "\t$(RUN) pytest --cov=agent_hub.core\n"

    assert rule_hits({**REGISTERED, "Makefile": makefile}, "package-registered") == ["Makefile"]


def test_reports_package_registered_when_core_contract_missing() -> None:
    importlinter = IMPORTLINTER.replace("type = forbidden", "type = independence")

    files = {**REGISTERED, ".importlinter": importlinter}

    assert rule_hits(files, "package-registered") == [".importlinter"]


def test_reports_package_registered_when_layers_contract_missing() -> None:
    importlinter = IMPORTLINTER.replace("type = layers", "type = independence")

    violations = find_violations({**REGISTERED, ".importlinter": importlinter})

    assert [(v.path, v.rule) for v in violations] == [(".importlinter", "package-registered")]
    assert "no layers contract" in violations[0].message


def test_reports_package_registered_when_package_missing_from_layers() -> None:
    importlinter = IMPORTLINTER.replace("agent_hub.storage | ", "")

    violations = find_violations({**REGISTERED, ".importlinter": importlinter})

    assert [(v.path, v.rule) for v in violations] == [(".importlinter", "package-registered")]
    assert violations[0].message == "layers contract lacks agent_hub.storage"


@pytest.mark.parametrize("layer", ["agent_hub.storage : agent_hub.api", "(agent_hub.storage)"])
def test_accepts_package_registered_when_package_in_sibling_or_optional_layer(layer: str) -> None:
    importlinter = IMPORTLINTER.replace("agent_hub.storage | (agent_hub.api)", layer)

    assert rule_hits({**REGISTERED, ".importlinter": importlinter}, "package-registered") == []


# reading the repo


def test_splits_every_path_when_git_listing_is_nul_separated() -> None:
    listing = "scripts/x.py\0tests/unit/scripts/test_caf\u00e9_menu.py\0docs/a b.md\0"

    assert split_git_listing(listing) == [
        "scripts/x.py",
        "tests/unit/scripts/test_caf\u00e9_menu.py",
        "docs/a b.md",
    ]


def test_returns_no_paths_when_git_listing_empty() -> None:
    assert split_git_listing("") == []


# main


def test_exits_nonzero_and_prints_path_and_rule_when_violation_found(
    capsys: pytest.CaptureFixture[str],
) -> None:
    files = {**REGISTERED, "scripts/utils.py": ""}

    exit_code = main(files)

    assert exit_code == 1
    out = capsys.readouterr().out
    assert "scripts/utils.py: forbidden-module" in out
    for name in ("utils", "util", "helpers", "helper", "common", "misc", "tests"):
        assert name in out


def test_exits_zero_when_layout_clean(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(files_with("tests/e2e/test_a.py"))

    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_formats_path_rule_and_message_when_violation_printed() -> None:
    violation = Violation(path="a.py", rule="mirror", message="no module")

    assert str(violation) == "a.py: mirror no module"
