"""A doctor finding as the Health screen shows it: ``hub doctor --json``'s fields plus project."""

from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.readmodels.view_types import ViewModel


class FindingView(ViewModel):
    """A finding of a registered hub's doctor run."""

    project: str
    rule: str
    severity: Severity
    path: str | None
    line: int | None
    message: str
    fix: str
