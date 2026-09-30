from collections.abc import Callable, Iterable, Iterator, Sequence
from dataclasses import replace
from typing import Any

import pytest

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.run_rules import (
    Selection,
    Totals,
    UsageProblem,
    count_findings,
    run_rules,
    select_rules,
    sort_findings,
)
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]

RUNNING_VERSION = "0.2.0"
FIX = "fix it"


class Spies:
    """A synthetic registry whose rules record, in order, the id of each rule whose check ran."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def rule(
        self,
        rule_id: str,
        *,
        severity: Severity = Severity.WARNING,
        module: str | None = None,
        reads: frozenset[Read] = frozenset(),
        emits: Sequence[tuple[Severity, str | None, int | None, str]] = (),
    ) -> Rule:
        """A rule that records its call and emits ``(severity, path, line, message)`` findings."""

        def check(snapshot: DoctorSnapshot) -> Iterable[Finding]:
            del snapshot
            self.calls.append(rule_id)
            return [
                Finding(
                    rule=rule_id,
                    severity=level,
                    path=path,
                    line=line,
                    message=message,
                    fix=FIX,
                )
                for level, path, line, message in emits
            ]

        return Rule(
            id=rule_id,
            severity=severity,
            summary=f"The synthetic {rule_id} rule.",
            module=module,
            reads=reads,
            check=check,
        )

    def registry(self, *rule_ids: str) -> tuple[Rule, ...]:
        """Silent spies, one per id; ``bench.tasks`` belongs to module ``bench``."""
        return tuple(
            self.rule(rule_id, module="bench" if rule_id == "bench.tasks" else None)
            for rule_id in rule_ids
        )


def a_config(
    *, rules: dict[str, Any] | None = None, modules: dict[str, Any] | None = None
) -> HubConfig:
    document = a_hub_document()
    if rules is not None:
        document["doctor"] = {"rules": rules}
    if modules is not None:
        document["modules"] = modules
    return HubConfig.model_validate(document)


def selected(
    registry: Sequence[Rule],
    *,
    config: HubConfig | ConfigFailure,
    only: Sequence[str] = (),
) -> Selection:
    selection = select_rules(registry, config=config, only=only)
    assert isinstance(selection, Selection), selection
    return selection


def failure_of(document: object) -> ConfigFailure:
    """A ``ConfigFailure`` holding the real problems ``check_hub_document`` finds."""
    result = check_hub_document(document, running_version=RUNNING_VERSION)
    assert not isinstance(result, HubConfig)
    return ConfigFailure(problems=result, pin=None)


def with_rules(rules: dict[str, Any], *, modules: dict[str, Any] | None = None) -> object:
    document = a_hub_document()
    document["doctor"] = {"rules": rules}
    if modules is not None:
        document["modules"] = modules
    return document


def a_finding(
    rule: str, *, path: str | None, line: int | None, message: str, severity: Severity
) -> Finding:
    return Finding(rule=rule, severity=severity, path=path, line=line, message=message, fix=FIX)


def test_skips_check_when_rule_disabled(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "lock.drift", "makefile.override")
    config = a_config(rules={"lock.drift": {"enabled": False}})

    selection = selected(registry, config=config)
    run_rules(selection, snapshot_of(config=config))

    assert spies.calls == ["config.schema", "makefile.override"]
    assert selection.notes == ()


def test_runs_rule_when_enabled_explicitly(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "lock.drift")
    config = a_config(rules={"lock.drift": {"enabled": True}})

    run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert spies.calls == ["config.schema", "lock.drift"]


def test_replaces_every_level_when_severity_set(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule(
            "lock.drift",
            emits=[
                (Severity.ERROR, "Makefile", None, "differs"),
                (Severity.WARNING, "hub.lock", None, "sync pending"),
            ],
        ),
        spies.rule("features.tracker", emits=[(Severity.WARNING, "spec.md", None, "kept")]),
    )
    default = a_config()
    retuned = a_config(rules={"lock.drift": {"severity": "info"}})

    before = run_rules(selected(registry, config=default), snapshot_of(config=default))
    after = run_rules(selected(registry, config=retuned), snapshot_of(config=retuned))

    assert [(f.rule, f.severity) for f in before] == [
        ("features.tracker", Severity.WARNING),
        ("lock.drift", Severity.ERROR),
        ("lock.drift", Severity.WARNING),
    ]
    assert [(f.rule, f.severity) for f in after] == [
        ("features.tracker", Severity.WARNING),
        ("lock.drift", Severity.INFO),
        ("lock.drift", Severity.INFO),
    ]


def test_fails_run_when_warning_rule_set_to_error(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule("makefile.override", emits=[(Severity.WARNING, "Makefile.project", 3, "x")]),
    )
    default = a_config()
    retuned = a_config(rules={"makefile.override": {"severity": "error"}})

    before = run_rules(selected(registry, config=default), snapshot_of(config=default))
    after = run_rules(selected(registry, config=retuned), snapshot_of(config=retuned))

    assert not count_findings(before).has_errors
    assert [finding.severity for finding in after] == [Severity.ERROR]
    assert count_findings(after).has_errors


@pytest.mark.parametrize(
    "document",
    [
        pytest.param(with_rules({"nope": {}}), id="unknown-rule-id"),
        pytest.param(with_rules({"lock.drift": {"nope": True}}), id="unknown-option"),
        pytest.param(with_rules({"config.schema": {}}), id="config-schema-key"),
        pytest.param(
            with_rules({"bench.tasks": {}}, modules={"cloud": {}}), id="rule-of-unselected-module"
        ),
    ],
)
def test_runs_only_config_schema_when_config_invalid(
    snapshot_of: SnapshotFactory, document: object
) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema", emits=[(Severity.ERROR, "hub.json", None, "problem")]),
        *spies.registry("platform.version", "lock.drift", "makefile.override", "bench.tasks"),
    )
    failure = failure_of(document)
    selection = selected(registry, config=failure)

    findings = run_rules(selection, snapshot_of(config=failure))

    assert failure.problems
    assert [rule.id for rule in selection.rules] == ["config.schema", "platform.version"]
    # platform.version runs too: it reports only a pin mismatch, which this failure is not.
    assert spies.calls == ["config.schema", "platform.version"]
    assert [finding.rule for finding in findings] == ["config.schema"]


def test_runs_only_config_rules_when_snapshot_failed(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "platform.version", "lock.drift")
    failure = failure_of(with_rules({"nope": {}}))
    everything = Selection(rules=registry, notes=(), severities={})

    run_rules(everything, snapshot_of(config=failure))

    assert spies.calls == ["config.schema", "platform.version"]


def test_skips_module_rule_when_module_not_selected(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "bench.tasks")
    config = a_config(modules={"cloud": {}})

    run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert spies.calls == ["config.schema"]


def test_runs_module_rule_when_module_selected(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "bench.tasks")
    config = a_config(modules={"bench": {}})

    run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert spies.calls == ["config.schema", "bench.tasks"]


@pytest.mark.parametrize("registered", [True, False], ids=["registered", "unregistered"])
def test_refuses_only_when_module_not_selected(*, registered: bool) -> None:
    rule_ids = ("config.schema", "bench.tasks") if registered else ("config.schema",)

    result = select_rules(
        Spies().registry(*rule_ids), config=a_config(modules={"cloud": {}}), only=["bench.tasks"]
    )

    assert result == UsageProblem("module bench is not selected")


@pytest.mark.parametrize("rule_id", ["bench.tasks", "lock.drift"])
def test_refuses_only_when_rule_not_in_release(rule_id: str) -> None:
    registry = Spies().registry("config.schema", "platform.version", "makefile.override")

    result = select_rules(
        registry,
        config=a_config(modules={"bench": {}}),
        only=["makefile.override", rule_id],
    )

    assert result == UsageProblem(f"{rule_id} is not in this release")


@pytest.mark.parametrize("rule_id", ["bench.tasks", "lock.drift"])
def test_ignores_unregistered_only_when_config_invalid(
    snapshot_of: SnapshotFactory, rule_id: str
) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "platform.version", "makefile.override")
    failure = failure_of(with_rules({"nope": {}}, modules={"cloud": {}}))

    selection = selected(registry, config=failure, only=[rule_id])
    run_rules(selection, snapshot_of(config=failure))

    assert [rule.id for rule in selection.rules] == ["config.schema", "platform.version"]
    assert selection.notes == ()
    assert spies.calls == ["config.schema", "platform.version"]


def test_runs_named_rules_and_config_schema_when_only_given(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry(
        "config.schema", "platform.version", "lock.drift", "makefile.override", "features.tracker"
    )
    config = a_config()

    run_rules(
        selected(registry, config=config, only=["features.tracker", "lock.drift"]),
        snapshot_of(config=config),
    )

    assert spies.calls == ["config.schema", "lock.drift", "features.tracker"]


def test_runs_config_schema_once_when_only_names_it(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "platform.version", "lock.drift")
    config = a_config()

    run_rules(selected(registry, config=config, only=["config.schema"]), snapshot_of(config=config))

    assert spies.calls == ["config.schema"]


@pytest.mark.parametrize(
    ("only", "notes", "calls"),
    [
        pytest.param(
            ["lock.drift"],
            ("lock.drift: disabled in hub.json doctor.rules",),
            ["config.schema"],
            id="only-disabled",
        ),
        pytest.param(
            ["makefile.override"], (), ["config.schema", "makefile.override"], id="only-other"
        ),
        pytest.param([], (), ["config.schema", "makefile.override"], id="no-only"),
    ],
)
def test_notes_disabled_rule_when_only_names_it(
    snapshot_of: SnapshotFactory, *, only: list[str], notes: tuple[str, ...], calls: list[str]
) -> None:
    spies = Spies()
    registry = spies.registry("config.schema", "lock.drift", "makefile.override")
    config = a_config(rules={"lock.drift": {"enabled": False}})

    selection = selected(registry, config=config, only=only)
    run_rules(selection, snapshot_of(config=config))

    assert selection.notes == notes
    assert spies.calls == calls


def test_never_retunes_config_rules_when_severity_set(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema", emits=[(Severity.ERROR, "hub.json", None, "schema")]),
        spies.rule("platform.version", emits=[(Severity.ERROR, "hub.json", None, "pin")]),
        spies.rule("lock.drift", emits=[(Severity.ERROR, "Makefile", None, "drift")]),
    )
    config = a_config(
        rules={"platform.version": {"severity": "info"}, "lock.drift": {"severity": "info"}}
    )

    findings = run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert [(f.rule, f.severity) for f in findings] == [
        ("config.schema", Severity.ERROR),
        ("lock.drift", Severity.INFO),
        ("platform.version", Severity.ERROR),
    ]


ERR, WARN, INFO = Severity.ERROR, Severity.WARNING, Severity.INFO
SORTED = tuple(
    a_finding(rule, path=path, line=line, message=message, severity=level)
    for rule, path, line, message, level in (
        ("lock.drift", None, None, "pathless first", ERR),
        ("lock.drift", None, None, "pathless second", ERR),
        ("lock.drift", "Makefile", None, "no line", ERR),
        ("lock.drift", "Makefile", 2, "line two, first", ERR),
        ("lock.drift", "Makefile", 2, "line two, second", WARN),
        ("lock.drift", "Makefile", 10, "line ten", ERR),
        ("lock.drift", "hub.lock", 1, "other path", WARN),
        ("makefile.override", None, None, "other rule, pathless", INFO),
        ("makefile.override", "Makefile.project", 1, "other rule", WARN),
    )
)
TIES = ((0, 1), (3, 4))


def reversed_keeping_ties(findings: Sequence[Finding]) -> list[Finding]:
    """The findings in reverse, except that each tie keeps its order (emission order wins)."""
    order = list(range(len(findings)))
    for first, second in TIES:
        order[first], order[second] = order[second], order[first]
    return [findings[index] for index in reversed(order)]


def test_sorts_findings_when_emitted_in_reverse(snapshot_of: SnapshotFactory) -> None:
    emitted = reversed_keeping_ties(SORTED)
    spies = Spies()
    registry = tuple(
        spies.rule(
            rule_id,
            emits=[(f.severity, f.path, f.line, f.message) for f in emitted if f.rule == rule_id],
        )
        for rule_id in ("makefile.override", "lock.drift")
    )
    config = a_config()

    assert emitted[0].rule == "makefile.override"
    assert sort_findings(emitted) == SORTED
    assert run_rules(selected(registry, config=config), snapshot_of(config=config)) == SORTED


@pytest.mark.parametrize(
    ("severities", "totals"),
    [
        pytest.param([], Totals(errors=0, warnings=0, infos=0), id="none"),
        pytest.param([Severity.WARNING], Totals(errors=0, warnings=1, infos=0), id="warning"),
        pytest.param(
            [Severity.INFO, Severity.ERROR], Totals(errors=1, warnings=0, infos=1), id="mixed"
        ),
        pytest.param(
            [Severity.ERROR, Severity.WARNING, Severity.INFO] * 2,
            Totals(errors=2, warnings=2, infos=2),
            id="two-each",
        ),
    ],
)
def test_counts_totals_when_findings_mixed(severities: list[Severity], totals: Totals) -> None:
    findings = [
        a_finding("lock.drift", path="Makefile", line=None, message="x", severity=level)
        for level in severities
    ]

    counted = count_findings(findings)

    assert counted == totals
    assert counted.has_errors is (totals.errors > 0)


def test_returns_equal_findings_when_snapshot_run_twice(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule(
            "lock.drift",
            emits=[
                (Severity.WARNING, "hub.lock", None, "b"),
                (Severity.ERROR, "Makefile", 4, "a"),
            ],
        ),
        spies.rule("makefile.override", emits=[(Severity.WARNING, None, None, "c")]),
    )
    config = a_config(rules={"lock.drift": {"severity": "info"}})
    snapshot = snapshot_of(config=config)
    selection = selected(registry, config=config)

    first = run_rules(selection, snapshot)
    second = run_rules(selection, snapshot)

    assert len(first) == 3
    assert first == second


LISTING_PROBLEM = "git ls-files failed: fatal: detected dubious ownership"
LISTING = frozenset({Read.HUB_LISTING})
TRACKER, OVERRIDE = "features.tracker", "makefile.override"
TREE_FIX = "fix the cause above so every file can be listed and read, then run hub doctor again"


def tree_finding(rule: str) -> Finding:
    """The one error a tree problem gives, on ``rule``: level error, path ``.``, never retuned."""
    return Finding(
        rule=rule,
        severity=Severity.ERROR,
        path=".",
        line=None,
        message=LISTING_PROBLEM,
        fix=TREE_FIX,
    )


@pytest.mark.parametrize(
    ("rules", "only", "expected"),
    [
        pytest.param(
            {},
            [TRACKER],
            [(TRACKER, ".", Severity.ERROR), (TRACKER, "spec.md", Severity.WARNING)],
            id="plain",
        ),
        pytest.param(
            {TRACKER: {"severity": "info"}},
            [TRACKER],
            [(TRACKER, ".", Severity.ERROR), (TRACKER, "spec.md", Severity.INFO)],
            id="listing-rule-retuned",
        ),
        pytest.param(
            {},
            [],
            [
                (TRACKER, ".", Severity.ERROR),
                (TRACKER, "spec.md", Severity.WARNING),
                (OVERRIDE, "Makefile.project", Severity.WARNING),
            ],
            id="two-listing-rules",
        ),
    ],
)
def test_reports_listing_problem_once_when_listing_rule_selected(
    snapshot_of: SnapshotFactory,
    *,
    rules: dict[str, Any],
    only: list[str],
    expected: list[tuple[str, str, Severity]],
) -> None:
    spies = Spies()
    # Registered out of id order, so the finding's rule is the first by id, not by registry.
    registry = (
        spies.rule("config.schema"),
        spies.rule(
            OVERRIDE, reads=LISTING, emits=[(Severity.WARNING, "Makefile.project", None, "x")]
        ),
        spies.rule(TRACKER, reads=LISTING, emits=[(Severity.WARNING, "spec.md", None, "kept")]),
    )
    config = a_config(rules=rules)
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=LISTING_PROBLEM))

    findings = run_rules(selected(registry, config=config, only=only), failed)

    assert [(f.rule, f.path, f.severity) for f in findings] == expected
    assert findings[0] == Finding(
        rule=TRACKER,
        severity=Severity.ERROR,
        path=".",
        line=None,
        message=LISTING_PROBLEM,
        fix="fix the cause above so every file can be listed and read, then run hub doctor again",
    )


@pytest.mark.parametrize(
    ("rules", "only"),
    [
        pytest.param({}, ["lock.drift"], id="reader-not-named"),
        pytest.param({TRACKER: {"enabled": False}}, [], id="reader-disabled"),
    ],
)
def test_reports_tree_problem_on_first_rule_when_no_selected_rule_reads_listing(
    snapshot_of: SnapshotFactory, *, rules: dict[str, Any], only: list[str]
) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        spies.rule("lock.drift", reads=frozenset({Read.LOCK_PATHS})),
        spies.rule(TRACKER, reads=LISTING),
    )
    config = a_config(rules=rules)
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=LISTING_PROBLEM))

    findings = run_rules(selected(registry, config=config, only=only), failed)

    assert spies.calls == ["config.schema", "lock.drift"]
    assert findings == (tree_finding("lock.drift"),)


def test_reports_no_listing_problem_when_listing_made(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (spies.rule("config.schema"), spies.rule(TRACKER, reads=LISTING))
    config = a_config()

    findings = run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert spies.calls == ["config.schema", TRACKER]
    assert findings == ()


def test_reports_no_listing_problem_when_config_failed(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema", emits=[(Severity.ERROR, "hub.json", None, "problem")]),
        spies.rule(TRACKER, reads=LISTING),
    )
    failure = failure_of(with_rules({"nope": {}}))
    snapshot = snapshot_of(config=failure)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=LISTING_PROBLEM))

    findings = run_rules(Selection(rules=registry, notes=(), severities={}), failed)

    assert spies.calls == ["config.schema"]
    assert [(f.rule, f.path) for f in findings] == [("config.schema", "hub.json")]


READ_PROBLEM = "could not read the files: .claude/settings.json: Permission denied"


def a_registry_without_listing_readers(spies: Spies) -> tuple[Rule, ...]:
    # makefile.override is registered before lock.drift, so "first" means first by id.
    return (
        spies.rule("config.schema"),
        spies.rule("platform.version"),
        spies.rule(OVERRIDE),
        spies.rule(
            "lock.drift",
            reads=frozenset({Read.LOCK_PATHS}),
            emits=[(Severity.WARNING, "hub.lock", None, "not adopted")],
        ),
    )


@pytest.mark.parametrize(
    ("only", "rule"),
    [
        pytest.param([OVERRIDE], OVERRIDE, id="one-rule-named"),
        pytest.param([], "lock.drift", id="first-by-id"),
    ],
)
def test_reports_tree_problem_on_first_hub_rule_when_no_listing_reader_selected(
    snapshot_of: SnapshotFactory, *, only: list[str], rule: str
) -> None:
    spies = Spies()
    registry = a_registry_without_listing_readers(spies)
    config = a_config(rules={"lock.drift": {"severity": "info"}})
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=READ_PROBLEM))

    findings = run_rules(selected(registry, config=config, only=only), failed)

    problem = [finding for finding in findings if finding.path == "."]
    assert problem == [replace(tree_finding(rule), message=READ_PROBLEM)]
    assert all(f.severity is Severity.INFO for f in findings if f.path == "hub.lock")


@pytest.mark.parametrize("only", [["config.schema"], ["platform.version"]])
def test_drops_tree_problem_when_only_config_rules_selected(
    snapshot_of: SnapshotFactory, only: list[str]
) -> None:
    spies = Spies()
    registry = a_registry_without_listing_readers(spies)
    config = a_config()
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=READ_PROBLEM))

    findings = run_rules(selected(registry, config=config, only=only), failed)

    assert set(spies.calls) <= {"config.schema", "platform.version"}
    assert findings == ()


def test_prefers_listing_reader_when_earlier_rule_reads_no_listing(
    snapshot_of: SnapshotFactory,
) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        spies.rule("attribution.ai"),
        spies.rule(TRACKER, reads=LISTING),
    )
    config = a_config()
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=LISTING_PROBLEM))

    findings = run_rules(selected(registry, config=config), failed)

    assert TRACKER > "attribution.ai"
    assert findings == (tree_finding(TRACKER),)


CRASH_FIX = "report this as a hub doctor bug"


def a_crashing_rule(
    rule_id: str,
    error: BaseException,
    *,
    severity: Severity,
    reads: frozenset[Read] = frozenset(),
) -> Rule:
    """A rule whose check yields one finding, then raises ``error``."""

    def check(snapshot: DoctorSnapshot) -> Iterator[Finding]:
        del snapshot
        yield a_finding(rule_id, path="Makefile", line=2, message="partial", severity=severity)
        raise error

    return Rule(
        id=rule_id,
        severity=severity,
        summary=f"The crashing {rule_id} rule.",
        module=None,
        reads=reads,
        check=check,
    )


def crash_finding(rule: str, message: str) -> Finding:
    return Finding(
        rule=rule, severity=Severity.ERROR, path=".", line=None, message=message, fix=CRASH_FIX
    )


@pytest.mark.parametrize("retune", [False, True], ids=["default", "set-to-info"])
def test_reports_one_error_when_rule_raises(snapshot_of: SnapshotFactory, *, retune: bool) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        a_crashing_rule("lock.drift", ValueError("boom\nline"), severity=Severity.WARNING),
        spies.rule("makefile.override", emits=[(Severity.WARNING, "Makefile", 1, "kept")]),
    )
    config = a_config(rules={"lock.drift": {"severity": "info"}} if retune else None)

    findings = run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert findings == (
        crash_finding("lock.drift", "rule crashed: ValueError: boom\nline"),
        a_finding(
            "makefile.override", path="Makefile", line=1, message="kept", severity=Severity.WARNING
        ),
    )
    assert spies.calls == ["config.schema", "makefile.override"]


def test_cuts_message_when_rule_raises_long_error(snapshot_of: SnapshotFactory) -> None:
    registry = (a_crashing_rule("lock.drift", ValueError("x" * 500), severity=Severity.WARNING),)
    config = a_config()

    findings = run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert findings == (
        crash_finding("lock.drift", "rule crashed: ValueError: " + cut_echo("x" * 500)),
    )
    assert len(findings[0].message) < 120


def test_reports_crash_when_only_names_crashing_rule(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        a_crashing_rule("lock.drift", KeyError("gone"), severity=Severity.WARNING),
        spies.rule("makefile.override"),
    )
    config = a_config()

    findings = run_rules(
        selected(registry, config=config, only=["lock.drift"]), snapshot_of(config=config)
    )

    assert findings == (crash_finding("lock.drift", "rule crashed: KeyError: 'gone'"),)
    assert spies.calls == ["config.schema"]


@pytest.mark.parametrize(
    "error",
    [KeyboardInterrupt(), SystemExit(3), GeneratorExit()],
    ids=["keyboard-interrupt", "system-exit", "generator-exit"],
)
def test_propagates_when_rule_raises_base_exception(
    snapshot_of: SnapshotFactory, error: BaseException
) -> None:
    registry = (a_crashing_rule("lock.drift", error, severity=Severity.WARNING),)
    config = a_config()

    with pytest.raises(type(error)):
        run_rules(selected(registry, config=config), snapshot_of(config=config))


def test_reports_crash_then_tree_problem_when_listing_reader_raises(
    snapshot_of: SnapshotFactory,
) -> None:
    registry = (
        a_crashing_rule("lock.drift", ValueError("boom"), severity=Severity.WARNING, reads=LISTING),
    )
    config = a_config()
    snapshot = snapshot_of(config=config)
    failed = replace(snapshot, hub=replace(snapshot.hub, problem=LISTING_PROBLEM))

    findings = run_rules(selected(registry, config=config), failed)

    assert findings == (
        crash_finding("lock.drift", "rule crashed: ValueError: boom"),
        tree_finding("lock.drift"),
    )


class UnprintableError(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no text")


def test_reports_unprintable_when_error_text_raises(snapshot_of: SnapshotFactory) -> None:
    registry = (a_crashing_rule("lock.drift", UnprintableError(), severity=Severity.WARNING),)
    config = a_config()

    findings = run_rules(selected(registry, config=config), snapshot_of(config=config))

    assert findings == (
        crash_finding("lock.drift", "rule crashed: UnprintableError: <unprintable>"),
    )


# E28: a file the config-lint rules read that is not text gives one error, on its first reader.
INSTRUCTIONS = frozenset({Read.HUB_LISTING, Read.INSTRUCTION_FILES})
PLUGINS = frozenset({Read.HUB_LISTING, Read.PLUGIN_FILES})
SIZE, DUPLICATES, FRONTMATTER = "instructions.size", "instructions.duplicates", "rules.frontmatter"
UNDECODABLE = b"ok\n\xff"
AGENT = "plugin/demo/agents/a.md"


def text_finding(rule: str, path: str, message: str) -> Finding:
    """The one error a file that is not text gives, on ``rule``: never retuned, no line."""
    return Finding(
        rule=rule,
        severity=Severity.ERROR,
        path=path,
        line=None,
        message=message,
        fix="save it as UTF-8 text",
    )


def a_config_lint_registry(spies: Spies) -> tuple[Rule, ...]:
    # In RULE_IDS order: instructions.size comes before instructions.duplicates, though not by id.
    return (
        spies.rule("config.schema"),
        spies.rule(SIZE, reads=INSTRUCTIONS),
        spies.rule(DUPLICATES, reads=INSTRUCTIONS),
        spies.rule(FRONTMATTER, reads=INSTRUCTIONS | PLUGINS),
    )


@pytest.mark.parametrize(
    ("rules", "only", "rule"),
    [
        pytest.param({}, [], SIZE, id="first-reader"),
        pytest.param({SIZE: {"severity": "info"}}, [], SIZE, id="reader-retuned"),
        pytest.param({SIZE: {"enabled": False}}, [], DUPLICATES, id="first-disabled"),
        pytest.param({}, [FRONTMATTER], FRONTMATTER, id="first-not-named"),
    ],
)
def test_reports_not_utf8_once_when_instruction_file_undecodable(
    snapshot_of: SnapshotFactory, *, rules: dict[str, Any], only: list[str], rule: str
) -> None:
    spies = Spies()
    config = a_config(rules=rules)
    snapshot = snapshot_of(
        config=config, files={"AGENTS.md": UNDECODABLE, "CLAUDE.md": b"# Fine\n"}
    )

    findings = run_rules(
        selected(a_config_lint_registry(spies), config=config, only=only), snapshot
    )

    assert findings == (
        text_finding(rule, "AGENTS.md", "not UTF-8 text: byte 3 cannot be decoded"),
    )


def test_reports_each_file_when_first_reader_reads_both_sets(
    snapshot_of: SnapshotFactory,
) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        spies.rule(FRONTMATTER, reads=INSTRUCTIONS | PLUGINS),
        spies.rule("attribution.ai", reads=PLUGINS),
    )
    config = a_config()
    snapshot = snapshot_of(config=config, files={AGENT: b"a\x00", "AGENTS.md": b"\x00"})

    findings = run_rules(selected(registry, config=config), snapshot)

    assert findings == (
        text_finding(FRONTMATTER, "AGENTS.md", "not UTF-8 text: NUL at byte 0"),
        text_finding(FRONTMATTER, AGENT, "not UTF-8 text: NUL at byte 1"),
    )


def test_reports_not_utf8_when_plugin_file_holds_nul(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        spies.rule(SIZE, reads=INSTRUCTIONS),
        spies.rule("attribution.ai", reads=PLUGINS),
        spies.rule(FRONTMATTER, reads=INSTRUCTIONS | PLUGINS),
    )
    config = a_config()
    snapshot = snapshot_of(config=config, files={AGENT: b"---\nname: a\x00\n"})

    findings = run_rules(selected(registry, config=config), snapshot)

    assert findings == (text_finding("attribution.ai", AGENT, "not UTF-8 text: NUL at byte 11"),)


@pytest.mark.parametrize(
    ("rules", "only"),
    [
        pytest.param({}, ["lock.drift"], id="reader-not-named"),
        pytest.param({SIZE: {"enabled": False}, DUPLICATES: {"enabled": False}}, [], id="disabled"),
    ],
)
def test_reports_no_text_problem_when_no_reader_selected(
    snapshot_of: SnapshotFactory, *, rules: dict[str, Any], only: list[str]
) -> None:
    spies = Spies()
    registry = (
        spies.rule("config.schema"),
        spies.rule("lock.drift", reads=LISTING),
        spies.rule(SIZE, reads=INSTRUCTIONS),
        spies.rule(DUPLICATES, reads=INSTRUCTIONS),
        # A plugin-files reader: the instruction file is not in its set.
        spies.rule("attribution.ai", reads=PLUGINS),
    )
    config = a_config(rules=rules)
    snapshot = snapshot_of(config=config, files={"AGENTS.md": UNDECODABLE})

    assert run_rules(selected(registry, config=config, only=only), snapshot) == ()


def test_reports_no_text_problem_when_config_failed(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    registry = a_config_lint_registry(spies)
    snapshot = snapshot_of(
        config=failure_of(with_rules({"nope": {}})), files={"AGENTS.md": UNDECODABLE}
    )

    findings = run_rules(Selection(rules=registry, notes=(), severities={}), snapshot)

    assert spies.calls == ["config.schema"]
    assert findings == ()


def test_reports_no_text_problem_when_files_are_text(snapshot_of: SnapshotFactory) -> None:
    spies = Spies()
    config = a_config()
    snapshot = snapshot_of(
        config=config,
        files={"AGENTS.md": "# Olá\r\n".encode(), AGENT: b"---\nname: a\n---\n"},
        # A listed file with no content: its failed read is the hub's problem (E24), not E28's.
        entries={"CLAUDE.md": FileEntry(executable=False, content=None)},
    )

    assert run_rules(selected(a_config_lint_registry(spies), config=config), snapshot) == ()
