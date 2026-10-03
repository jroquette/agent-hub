from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.doctor.config_rules import CONFIG_SCHEMA, PLATFORM_VERSION, config_state
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, PinMismatch
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.json_form import dump_json
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str, Severity, str | None, int | None, str, str]

RUNNING_VERSION = "0.2.0"
SCHEMA_FIX = "fix hub.json (docs/design/project-config.md)"


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


def test_reports_nothing_when_config_valid(snapshot_of: SnapshotFactory) -> None:
    config = config_state(dump_json(a_hub_document()), running_version=RUNNING_VERSION)

    assert config == HubConfig.model_validate(a_hub_document())
    assert findings_of(snapshot_of(config=config)) == []
