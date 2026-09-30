"""Pick the rules a run needs, run them once each, retune their levels, sort and count.

Selection follows ``hub.json`` → ``doctor.rules`` and ``modules``, and ``--only``; a run on a
``hub.json`` that failed runs only the two config rules (docs/design/hub-doctor.md).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from agent_hub.core.doctor.config_lint import (
    TextProblem,
    file_text,
    instruction_files,
    plugin_files,
)
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import (
    CONFIG_SCHEMA_RULE,
    PLATFORM_VERSION_RULE,
    RULE_MODULES,
    Severity,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import cut_echo

# The rules that read ``hub.json`` itself: the only ones run on a failed config, never retuned.
CONFIG_RULES: Final = (CONFIG_SCHEMA_RULE, PLATFORM_VERSION_RULE)
# The fix of the one finding a hub tree that could not be listed or read gives (E7, E24); the
# message names the cause.
LISTING_FIX: Final = (
    "fix the cause above so every file can be listed and read, then run hub doctor again"
)
# The fix of the one finding a rule whose check raised gives instead of its findings (E27).
CRASH_FIX: Final = "report this as a hub doctor bug"


@dataclass(frozen=True, kw_only=True, slots=True)
class Selection:
    """The rules to run in registry order, stderr notes, and the level each retuned rule reports."""

    rules: tuple[Rule, ...]
    notes: tuple[str, ...]
    severities: Mapping[str, Severity]


@dataclass(frozen=True, slots=True)
class UsageProblem:
    """``--only`` names a rule this run cannot run; the command exits 2 with the message."""

    message: str


@dataclass(frozen=True, kw_only=True, slots=True)
class Totals:
    """How many findings of each level a run reported."""

    errors: int
    warnings: int
    infos: int

    @property
    def has_errors(self) -> bool:
        """Whether the run fails (exit 1)."""
        return self.errors > 0


def select_rules(
    registry: Sequence[Rule], *, config: HubConfig | ConfigFailure, only: Sequence[str]
) -> Selection | UsageProblem:
    """The rules of this run, or why ``--only`` cannot be honored.

    On a failed config only the config rules run and ``--only`` is not checked further. Else
    an ``--only`` id of an unselected module, or one absent from the registry, is refused; a
    rule of an unselected module or disabled in ``doctor.rules`` is skipped (with a note when
    ``--only`` names it); ``config.schema`` always runs.
    """
    if isinstance(config, ConfigFailure):
        return Selection(
            rules=tuple(rule for rule in registry if rule.id in CONFIG_RULES),
            notes=(),
            severities={},
        )
    # Dumped by alias, so the keys are the JSON keys: module and rule ids.
    modules = frozenset(config.modules.model_dump(exclude_none=True, by_alias=True))
    registered = frozenset(rule.id for rule in registry)
    for rule_id in only:
        problem = _only_problem(rule_id, registered=registered, modules=modules)
        if problem is not None:
            return problem
    settings = config.doctor.rules.model_dump(exclude_none=True, by_alias=True)
    wanted = tuple(
        rule
        for rule in registry
        if (rule.module is None or rule.module in modules)
        and (not only or rule.id in only or rule.id == CONFIG_SCHEMA_RULE)
    )
    # ``doctor.rules`` refuses a ``config.schema`` entry, so it is never disabled.
    disabled = tuple(
        rule.id for rule in wanted if not settings.get(rule.id, {}).get("enabled", True)
    )
    return Selection(
        rules=tuple(rule for rule in wanted if rule.id not in disabled),
        notes=tuple(
            f"{rule_id}: disabled in hub.json doctor.rules"
            for rule_id in disabled
            if rule_id in only
        ),
        severities={
            rule_id: Severity(entry["severity"])
            for rule_id, entry in sorted(settings.items())
            if "severity" in entry and rule_id not in CONFIG_RULES
        },
    )


def _only_problem(
    rule_id: str, *, registered: frozenset[str], modules: frozenset[str]
) -> UsageProblem | None:
    module = RULE_MODULES.get(rule_id)
    if module is not None and module not in modules:
        return UsageProblem(f"module {module} is not selected")
    if rule_id not in registered:
        return UsageProblem(f"{rule_id} is not in this release")
    return None


def run_rules(selection: Selection, snapshot: DoctorSnapshot) -> tuple[Finding, ...]:
    """Every finding of the selected rules, each check called once, retuned, then sorted.

    A rule whose check raises an ``Exception`` loses its findings and gives one error instead
    (E27); the other rules still run. That error, the ones of files the config-lint rules read
    that are not text (E28), and the one of a hub tree that could not be listed or read, are
    added after the retune, so their level is never changed.
    """
    failed = isinstance(snapshot.config, ConfigFailure)
    findings: list[Finding] = []
    crashes: list[Finding] = []
    for rule in selection.rules:
        if failed and rule.id not in CONFIG_RULES:
            continue
        severity = selection.severities.get(rule.id)
        emitted = _checked(rule, snapshot)
        if isinstance(emitted, Finding):
            crashes.append(emitted)
            continue
        findings.extend(
            finding if severity is None else replace(finding, severity=severity)
            for finding in emitted
        )
    findings.extend(crashes)
    findings.extend(_text_problem_findings(selection, snapshot))
    problem = _tree_problem_finding(selection, snapshot)
    if problem is not None:
        findings.append(problem)
    return sort_findings(findings)


def _checked(rule: Rule, snapshot: DoctorSnapshot) -> tuple[Finding, ...] | Finding:
    """The rule's findings, or the one error that replaces them when its check raises (E27).

    ``KeyboardInterrupt``, ``SystemExit`` and ``GeneratorExit`` are not ``Exception`` and
    propagate; the message is cut, and the report escapes it. An error whose text itself
    raises reads ``<unprintable>``.
    """
    try:
        return tuple(rule.check(snapshot))
    except Exception as error:  # noqa: BLE001 - any rule bug becomes a finding, not a lost run
        try:
            text = str(error)
        except Exception:  # noqa: BLE001 - a broken __str__ must not undo the finding
            text = "<unprintable>"
        detail = cut_echo(text)
        return Finding(
            rule=rule.id,
            severity=Severity.ERROR,
            path=".",
            line=None,
            message=f"rule crashed: {type(error).__name__}: {detail}",
            fix=CRASH_FIX,
        )


def _text_problem_findings(selection: Selection, snapshot: DoctorSnapshot) -> list[Finding]:
    """One error per instruction or plugin file that is not text, on its first reader (E28).

    The reader is the first selected rule, in registry (``RULE_IDS``) order, that reads a set the
    file is in; the other rules skip the file. None on a failed config (only the config rules run).
    """
    if isinstance(snapshot.config, ConfigFailure):
        return []
    sets = {
        Read.INSTRUCTION_FILES: instruction_files(snapshot.hub),
        Read.PLUGIN_FILES: plugin_files(snapshot.hub),
    }
    findings: list[Finding] = []
    for path in sorted({path for paths in sets.values() for path in paths}):
        reads = {read for read, paths in sets.items() if path in paths}
        reader = next((rule.id for rule in selection.rules if reads & rule.reads), None)
        if reader is None:
            continue
        problem = file_text(snapshot.hub.entries.get(path))
        if isinstance(problem, TextProblem):
            findings.append(
                Finding(
                    rule=reader,
                    severity=Severity.ERROR,
                    path=path,
                    line=None,
                    message=problem.message,
                    fix=problem.fix,
                )
            )
    return findings


def _tree_problem_finding(selection: Selection, snapshot: DoctorSnapshot) -> Finding | None:
    """The one error of a hub tree that could not be listed or read (E24).

    It goes on the first selected rule by id that reads the listing, else on the first selected
    rule other than the config rules; with only those selected, or on a failed config (only
    the config rules run then), there is none.
    """
    if isinstance(snapshot.config, ConfigFailure) or snapshot.hub.problem is None:
        return None
    hub_rules = sorted(
        (Read.HUB_LISTING not in rule.reads, rule.id)
        for rule in selection.rules
        if rule.id not in CONFIG_RULES
    )
    if not hub_rules:
        return None
    return Finding(
        rule=hub_rules[0][1],
        severity=Severity.ERROR,
        path=".",
        line=None,
        message=snapshot.hub.problem,
        fix=LISTING_FIX,
    )


def sort_findings(findings: Iterable[Finding]) -> tuple[Finding, ...]:
    """By rule id, pathless first, then path, no line before lines; ties keep emission order.

    A finding's line is 1 or more, so a missing line, taken as 0, sorts first.
    """
    return tuple(
        sorted(
            findings,
            key=lambda finding: (
                finding.rule,
                finding.path is not None,
                finding.path or "",
                finding.line or 0,
            ),
        )
    )


def count_findings(findings: Iterable[Finding]) -> Totals:
    """The totals line's counts."""
    levels = [finding.severity for finding in findings]
    return Totals(
        errors=levels.count(Severity.ERROR),
        warnings=levels.count(Severity.WARNING),
        infos=levels.count(Severity.INFO),
    )
