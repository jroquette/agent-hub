"""``workflows.starts``: each schedule and event in ``hub.json`` names a workflow hub web can start.

The known names are the workflows that load and plan (the hub's and the built-ins, as
``workflows.valid`` sees them). ``issue-to-pr`` is refused too: its tracker writes need
``LINEAR_API_KEY``, which no child of hub web gets (ADR 0030, ADR 0048). Without a workflow
source read, the rule finds nothing.
"""

from collections.abc import Iterable, Iterator
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import WORKFLOWS_STARTS_RULE, Severity
from agent_hub.core.workflows.catalog import check_workflows
from agent_hub.core.workflows.launch import TRACKER_WORKFLOWS

PATH: Final = "hub.json"
UNKNOWN_FIX: Final = "name a workflow that hub workflow list shows, or add it under workflows/"
TRACKER_FIX: Final = "start issue-to-pr with hub run, or remove this entry"


def _workflows_starts(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    if snapshot.workflows is None:
        return ()
    known = {plan.document.name for plan in check_workflows(snapshot.workflows).plans}
    config = snapshot.hub_config
    named = (
        *(("schedules", index, entry.workflow) for index, entry in enumerate(config.schedules)),
        *(("events", index, entry.workflow) for index, entry in enumerate(config.events)),
    )
    return tuple(_findings(named, known))


def _findings(named: Iterable[tuple[str, int, str]], known: set[str]) -> Iterator[Finding]:
    for key, index, workflow in named:
        where = f"{key}[{index}].workflow"
        if workflow in TRACKER_WORKFLOWS:
            message = f"{where}: {workflow} writes to the tracker and cannot start from hub web"
            yield WORKFLOWS_STARTS.finding(path=PATH, message=message, fix=TRACKER_FIX)
        elif workflow not in known:
            message = f"{where}: unknown workflow {workflow}"
            yield WORKFLOWS_STARTS.finding(path=PATH, message=message, fix=UNKNOWN_FIX)


WORKFLOWS_STARTS: Final = Rule(
    id=WORKFLOWS_STARTS_RULE,
    severity=Severity.ERROR,
    summary="every schedule and event names a workflow hub web can start",
    module=None,
    reads=frozenset({Read.WORKFLOWS}),
    check=_workflows_starts,
)
