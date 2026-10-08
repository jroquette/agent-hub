from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.doctor import config_rules
from agent_hub.core.doctor.config_rules import CONFIG_SCHEMA, PLATFORM_VERSION, config_state
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, PinMismatch
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.effective_identity import IdentityKey, Source, Sourced
from agent_hub.core.hub_config.local_config import LocalConfig, check_local_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document, a_second_repo
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    SECRET_PARTS,
    RepositoryCase,
)

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str, Severity, str | None, int | None, str, str]

RUNNING_VERSION = "0.2.0"
SCHEMA_FIX = "fix hub.json (docs/design/project-config.md)"
LOCAL_FIX = "fix hub.local.json (docs/design/developer-identity.md)"
IDENTITY_FIX = "set project.branch_prefix in hub.local.json to choose another"
STOP_GATE_FIX = "set the repo's check_fast to its fast gate command (docs/design/project-config.md)"


def document_bytes(edit: Callable[[dict[str, Any]], object]) -> bytes:
    """The builder's ``hub.json`` bytes after ``edit`` changed the document in place."""
    document = a_hub_document()
    edit(document)
    return dump_json(document)


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    """Every finding of both config rules, as the runner would call them on a failed config."""
    return [
        (
            finding.rule,
            finding.severity,
            finding.path,
            finding.line,
            finding.message,
            finding.fix,
        )
        for rule in (CONFIG_SCHEMA, PLATFORM_VERSION)
        for finding in rule.check(snapshot)
    ]


def schema_finding(message: str) -> Shown:
    return ("config.schema", Severity.ERROR, "hub.json", None, message, SCHEMA_FIX)


def failure_of(read: bytes | tuple[ConfigProblem, ...]) -> ConfigFailure:
    state = config_state(read, running_version=RUNNING_VERSION)
    assert isinstance(state, ConfigFailure)
    return state


@pytest.mark.parametrize(
    ("content", "messages"),
    [
        pytest.param(
            b'{"project": ', ["$: not valid JSON: Expecting value at line 1 column 13"], id="json"
        ),
        pytest.param(
            document_bytes(lambda document: document["project"].pop("hub_repo")),
            ["project.hub_repo: Field required"],
            id="missing-key",
        ),
        pytest.param(
            document_bytes(lambda document: document.update(colour="blue")),
            ["colour: Extra inputs are not permitted"],
            id="unknown-key",
        ),
        pytest.param(
            document_bytes(lambda document: document["project"].update(name="Demo Hub")),
            ["project.name: String should match pattern '^[a-z0-9]+(-[a-z0-9]+)*$'"],
            id="project-name",
        ),
        pytest.param(
            document_bytes(
                lambda document: (document.update(shade=1), document["tracker"].pop("team"))
            ),
            ["shade: Extra inputs are not permitted", "tracker.team: Field required"],
            id="two-problems",
        ),
    ],
)
def test_reports_one_finding_per_problem_when_config_invalid(
    snapshot_of: SnapshotFactory, content: bytes, messages: list[str]
) -> None:
    snapshot = snapshot_of(config=failure_of(content))

    assert sorted(findings_of(snapshot)) == sorted(schema_finding(m) for m in messages)


def test_reports_reader_problem_when_hub_json_unreadable(snapshot_of: SnapshotFactory) -> None:
    problem = ConfigProblem("$", 'cannot read "/hub/hub.json": not a regular file')

    snapshot = snapshot_of(config=failure_of((problem,)))

    assert findings_of(snapshot) == [
        schema_finding('$: cannot read "/hub/hub.json": not a regular file')
    ]


@pytest.mark.parametrize(
    "schema_version", [pytest.param(1, id="schema-ok"), pytest.param(7, id="schema-wrong")]
)
def test_reports_pin_only_when_pin_differs(
    snapshot_of: SnapshotFactory, schema_version: int
) -> None:
    content = document_bytes(
        lambda document: document.update(
            platform={"version": "0.0.1"}, schema_version=schema_version
        )
    )
    command = (
        "uvx --from git+https://github.com/jroquette/agent-hub@v0.0.1"
        "#subdirectory=packages/agent-hub hub"
    )

    failure = failure_of(content)

    assert failure == ConfigFailure(
        problems=(), pin=PinMismatch(pinned="0.0.1", running=RUNNING_VERSION, command=command)
    )
    assert findings_of(snapshot_of(config=failure)) == [
        (
            "platform.version",
            Severity.ERROR,
            "hub.json",
            None,
            "this hub is pinned to 0.0.1 but this hub command is 0.2.0.",
            f"run the pinned release: {command}",
        )
    ]


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        pytest.param(
            lambda document: document["platform"].pop("version"),
            "platform.version: required: the pinned release, such as 1.2.3",
            id="version-missing",
        ),
        pytest.param(
            lambda document: document["platform"].update(version="v1"),
            'platform.version: must be three numbers such as 1.2.3, not "v1"',
            id="version-malformed",
        ),
        pytest.param(
            lambda document: document.pop("platform"),
            'platform: required: the pinned release, as {"version": "1.2.3"}',
            id="platform-missing",
        ),
    ],
)
def test_reports_config_schema_when_pin_missing_or_malformed(
    snapshot_of: SnapshotFactory, edit: Callable[[dict[str, Any]], object], message: str
) -> None:
    failure = failure_of(document_bytes(edit))

    assert failure.pin is None
    assert findings_of(snapshot_of(config=failure)) == [schema_finding(message)]


def test_drops_pinned_command_when_pin_too_long(snapshot_of: SnapshotFactory) -> None:
    pinned = "1.2." + "3" * 496
    content = document_bytes(lambda document: document["platform"].update(version=pinned))

    failure = failure_of(content)

    assert failure.pin == PinMismatch(pinned=pinned, running=RUNNING_VERSION, command=None)
    # The message repeats at most 80 characters of the pin: 79 of them, then the cut mark.
    assert findings_of(snapshot_of(config=failure)) == [
        (
            "platform.version",
            Severity.ERROR,
            "hub.json",
            None,
            f"this hub is pinned to {pinned[:79]}… but this hub command is 0.2.0.",
            "run the pinned release",
        )
    ]


def pinned_with_repository(value: object) -> bytes:
    """The builder's ``hub.json`` bytes pinned to 0.0.1, with ``platform.repository`` set."""
    return document_bytes(
        lambda document: document.update(platform={"version": "0.0.1", "repository": value})
    )


def test_fixes_with_custom_source_when_pin_differs_and_hub_sets_repository(
    snapshot_of: SnapshotFactory,
) -> None:
    command = (
        "uvx --from git+https://git.acme.test/tools/agent-hub@v0.0.1"
        "#subdirectory=packages/agent-hub hub"
    )

    failure = failure_of(pinned_with_repository(CUSTOM_REPOSITORY))

    assert failure.pin == PinMismatch(pinned="0.0.1", running=RUNNING_VERSION, command=command)
    assert [finding[5] for finding in findings_of(snapshot_of(config=failure))] == [
        f"run the pinned release: {command}"
    ]


@pytest.mark.parametrize(
    "case",
    [case for case in REPOSITORY_CASES if not case.is_valid],
    ids=lambda case: case.name,
)
def test_fixes_without_command_when_pin_differs_and_repository_invalid(
    snapshot_of: SnapshotFactory, case: RepositoryCase
) -> None:
    failure = failure_of(pinned_with_repository(case.value))

    assert failure.pin == PinMismatch(pinned="0.0.1", running=RUNNING_VERSION, command=None)
    findings = findings_of(snapshot_of(config=failure))
    assert findings == [
        (
            "platform.version",
            Severity.ERROR,
            "hub.json",
            None,
            "this hub is pinned to 0.0.1 but this hub command is 0.2.0.",
            "run the pinned release",
        )
    ]
    assert [part for part in SECRET_PARTS if part in str(findings)] == []


def test_reports_nothing_when_config_valid(snapshot_of: SnapshotFactory) -> None:
    config = config_state(dump_json(a_hub_document()), running_version=RUNNING_VERSION)

    assert config == HubConfig.model_validate(a_hub_document())
    assert findings_of(snapshot_of(config=config)) == []


def local_problems(document: object) -> tuple[ConfigProblem, ...]:
    checked = check_local_document(document)
    assert not isinstance(checked, LocalConfig)
    return checked


def local_finding(message: str) -> Shown:
    return ("config.schema", Severity.ERROR, "hub.local.json", None, message, LOCAL_FIX)


BAD_LOCAL = {"project": {"colour": "blue"}, "tracker": {"transport": "ftp"}}
BAD_LOCAL_MESSAGES = [
    "project.colour: Extra inputs are not permitted",
    "tracker.transport: Input should be 'api' or 'mcp'",
]


@pytest.mark.parametrize("hub_json", ["valid", "invalid"])
def test_reports_local_problem_when_local_file_invalid(
    snapshot_of: SnapshotFactory, hub_json: str
) -> None:
    config = (
        failure_of(document_bytes(lambda document: document.update(shade=1)))
        if hub_json == "invalid"
        else None
    )
    snapshot = snapshot_of(config=config, local=local_problems(BAD_LOCAL))

    hub_findings = [schema_finding("shade: Extra inputs are not permitted")]
    assert findings_of(snapshot) == [
        *(hub_findings if hub_json == "invalid" else []),
        *(local_finding(message) for message in BAD_LOCAL_MESSAGES),
    ]


def test_reports_nothing_of_local_file_when_pin_differs(snapshot_of: SnapshotFactory) -> None:
    # The pinned release judges the rest, the developer's file included.
    failure = failure_of(
        document_bytes(lambda document: document.update(platform={"version": "0.0.1"}))
    )

    snapshot = snapshot_of(config=failure, local=local_problems(BAD_LOCAL))

    assert [shown[0] for shown in findings_of(snapshot)] == ["platform.version"]


def identity_findings(snapshot: DoctorSnapshot) -> list[Shown]:
    # Read through the module, so a missing rule fails each test rather than the collection.
    rule = config_rules.CONFIG_IDENTITY
    return [
        (
            finding.rule,
            finding.severity,
            finding.path,
            finding.line,
            finding.message,
            finding.fix,
        )
        for finding in rule.check(snapshot)
    ]


def test_declares_identity_rule_when_rule_read() -> None:
    rule = config_rules.CONFIG_IDENTITY

    assert rule.id == "config.identity"
    assert rule.severity is Severity.INFO
    assert rule.reads == frozenset({Read.DEVELOPER_IDENTITY})
    assert rule.module is None


@pytest.mark.parametrize(
    ("source", "described"),
    [
        pytest.param(Source.GIT, "derived from git config user.email", id="git"),
        pytest.param(Source.LOCAL, "derived from author_email in hub.local.json", id="local"),
        pytest.param(Source.HUB, "derived from author_email in hub.json", id="hub"),
    ],
)
def test_reports_derived_prefix_when_snapshot_holds_one(
    snapshot_of: SnapshotFactory, source: Source, described: str
) -> None:
    prefix = Sourced("jane/", source, IdentityKey.BRANCH_PREFIX, derived=True)

    snapshot = snapshot_of(branch_prefix=prefix)

    assert identity_findings(snapshot) == [
        (
            "config.identity",
            Severity.INFO,
            None,
            None,
            f"branch prefix `jane/` is {described} (hub.local.json and hub.json set none)",
            IDENTITY_FIX,
        )
    ]


@pytest.mark.parametrize("source", [Source.LOCAL, Source.HUB])
def test_reports_nothing_when_prefix_from_file(
    snapshot_of: SnapshotFactory, source: Source
) -> None:
    prefix = Sourced("me/", source, IdentityKey.BRANCH_PREFIX)

    assert identity_findings(snapshot_of(branch_prefix=prefix)) == []
    # No prefix at all (a team hub with no email anywhere) is no finding either.
    assert identity_findings(snapshot_of()) == []


def stop_gate_findings(snapshot: DoctorSnapshot) -> list[Shown]:
    # Read through the module, so a missing rule fails each test rather than the collection.
    rule = config_rules.CONFIG_STOP_GATE
    return [
        (
            finding.rule,
            finding.severity,
            finding.path,
            finding.line,
            finding.message,
            finding.fix,
        )
        for finding in rule.check(snapshot)
    ]


def stop_gate_finding(index: int, repo_dir: str) -> Shown:
    message = f"repos[{index}].check_fast: no Stop gate for {repo_dir}"
    return ("config.stop_gate", Severity.WARNING, "hub.json", None, message, STOP_GATE_FIX)


def two_repo_config(edit: Callable[[list[dict[str, Any]]], object]) -> HubConfig:
    """The builder's document with ``demo-web`` added, after ``edit`` changed both repos."""
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    edit(document["repos"])
    return HubConfig.model_validate(document)


def test_declares_stop_gate_rule_when_rule_read() -> None:
    rule = config_rules.CONFIG_STOP_GATE

    assert rule.id == "config.stop_gate"
    assert rule.severity is Severity.WARNING
    assert rule.reads == frozenset()
    assert rule.module is None


@pytest.mark.parametrize("blank", ["", "  "])
def test_reports_stop_gate_when_check_fast_absent_or_blank(
    snapshot_of: SnapshotFactory, blank: str
) -> None:
    config = two_repo_config(
        lambda repos: (repos[0].pop("check_fast"), repos[1].update(check_fast=blank))
    )

    assert stop_gate_findings(snapshot_of(config=config)) == [
        stop_gate_finding(0, "demo-api"),
        stop_gate_finding(1, "demo-web"),
    ]


@pytest.mark.parametrize("gate", [None, ""], ids=["absent", "empty"])
def test_reports_stop_gate_at_own_index_when_later_repo_lacks_command(
    snapshot_of: SnapshotFactory, gate: str | None
) -> None:
    # demo-api keeps its command: the finding names demo-web by its own place in repos.
    def drop_web_gate(repos: list[dict[str, Any]]) -> None:
        if gate is None:
            del repos[1]["check_fast"]
        else:
            repos[1]["check_fast"] = gate

    config = two_repo_config(drop_web_gate)

    assert stop_gate_findings(snapshot_of(config=config)) == [stop_gate_finding(1, "demo-web")]


def test_reports_no_stop_gate_when_every_repo_has_command(snapshot_of: SnapshotFactory) -> None:
    config = two_repo_config(lambda repos: repos[1].update(check_fast=" make check-fast "))

    assert stop_gate_findings(snapshot_of(config=config)) == []
    assert stop_gate_findings(snapshot_of()) == []


def test_reports_no_stop_gate_when_config_failed(snapshot_of: SnapshotFactory) -> None:
    failure = failure_of(
        document_bytes(
            lambda document: (document["repos"][0].pop("check_fast"), document.update(shade=1))
        )
    )

    assert stop_gate_findings(snapshot_of(config=failure)) == []
