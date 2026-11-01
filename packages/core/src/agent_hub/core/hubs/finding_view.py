"""A doctor finding as the Health screen shows it: ``hub doctor --json``'s fields plus project;
the findings answer adds when the checks it shows ran."""

from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.readmodels.page import Page
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel


class FindingView(ViewModel):
    """A finding of a registered hub's doctor run."""

    project: str
    rule: str
    severity: Severity
    path: str | None
    line: int | None
    message: str
    fix: str


class DoctorFindings(Page[FindingView]):
    """The findings of the scoped hubs' last checks; ``checked_at`` is when the oldest of those
    checks ended, None while one of the hubs has not been checked yet."""

    checked_at: ApiTimestamp | None
