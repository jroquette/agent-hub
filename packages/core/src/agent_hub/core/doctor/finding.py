"""A doctor finding, and a rule: what it reads beyond the fixed paths and how it checks."""

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from enum import StrEnum

from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity


@dataclass(frozen=True, kw_only=True, slots=True)
class Finding:
    """One problem a rule reports, at a hub path and line when it has them.

    A rule that builds a bad finding (an empty or multi-line fix, a line below 1) has a bug, so
    the finding refuses it with ``ValueError`` instead of printing a broken report line.
    """

    rule: str
    severity: Severity
    path: str | None
    line: int | None
    message: str
    fix: str

    def __post_init__(self) -> None:
        # ``splitlines`` also breaks on ``\r`` and U+2028, which would split the report line too.
        if self.fix.splitlines() != [self.fix]:
            msg = f"fix must be one non-empty line, got {self.fix!r}"
            raise ValueError(msg)
        if self.line is not None and self.line < 1:
            msg = f"line must be 1 or more, got {self.line}"
            raise ValueError(msg)


class Read(StrEnum):
    """What a rule reads beyond the fixed paths every run looks at (``hub_paths``)."""

    LOCK_PATHS = "lock_paths"
    HUB_LISTING = "hub_listing"
    REPOS = "repos"
    BASE_HOOKS = "base_hooks"
    # A rule that reads the text of the instruction files, or of the plugins' agent and skill
    # files (``config_lint``). Those sets come from the listing, so it declares ``HUB_LISTING``
    # too (the command lists the files for either, E24 counts only ``HUB_LISTING``).
    INSTRUCTION_FILES = "instruction_files"
    PLUGIN_FILES = "plugin_files"


@dataclass(frozen=True, kw_only=True, slots=True)
class Rule:
    """A doctor rule: its id in ``RULE_IDS``, default level, one-line summary and check.

    ``module`` is the module that owns the rule (``RULE_MODULES``), ``None`` for a base rule.
    """

    id: str
    severity: Severity
    summary: str
    module: str | None
    reads: frozenset[Read]
    check: Callable[[DoctorSnapshot], Iterable[Finding]]

    def finding(
        self, *, path: str | None, line: int | None = None, message: str, fix: str
    ) -> Finding:
        """A finding of this rule at its default level; the runner applies ``doctor.rules``."""
        return Finding(
            rule=self.id, severity=self.severity, path=path, line=line, message=message, fix=fix
        )
