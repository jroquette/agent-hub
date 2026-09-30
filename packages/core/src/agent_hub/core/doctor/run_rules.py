"""Pick the rules a run needs, run them once each, retune their levels, sort and count.

Selection follows ``hub.json`` → ``doctor.rules`` and ``modules``, and ``--only``; a run on a
``hub.json`` that failed runs only the two config rules (docs/design/hub-doctor.md).
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import CONFIG_SCHEMA_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.model import HubConfig

# The rules that read ``hub.json`` itself: the only ones run on a failed config, never retuned.
CONFIG_RULES: Final = (CONFIG_SCHEMA_RULE, "platform.version")
# The fix of the one finding a failed file listing gives (E7); the message names the cause.
LISTING_FIX: Final = "fix the cause above so this folder can be listed, then run hub doctor again"


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

    A failed hub listing adds one finding, after the retune, so its level is never changed.
    """
    failed = isinstance(snapshot.config, ConfigFailure)
    findings: list[Finding] = []
    for rule in selection.rules:
        if failed and rule.id not in CONFIG_RULES:
            continue
        severity = selection.severities.get(rule.id)
        findings.extend(
            finding if severity is None else replace(finding, severity=severity)
            for finding in rule.check(snapshot)
        )
    listing = _listing_finding(selection, snapshot)
    if listing is not None:
        findings.append(listing)
    return sort_findings(findings)


def _listing_finding(selection: Selection, snapshot: DoctorSnapshot) -> Finding | None:
    """The one error of a failed hub listing, on the first selected rule by id that reads it.

    None on a failed config: then only the config rules run, and none of them reads the listing.
    """
    if isinstance(snapshot.config, ConfigFailure):
        return None
    readers = sorted(rule.id for rule in selection.rules if Read.HUB_LISTING in rule.reads)
    if snapshot.hub.problem is None or not readers:
        return None
    return Finding(
        rule=readers[0],
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
