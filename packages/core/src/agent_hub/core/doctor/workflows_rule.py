"""``workflows.valid``: every workflow the hub has, its own and the built-ins, loads and plans.

The workflows come through core's ``WorkflowSource`` (the generator reads the YAML), so this rule
sees what ``hub workflow validate`` sees: each problem ``check_workflows`` finds is one finding at
its file and line. A hub file shows relative to the hub, a built-in's as ``<builtin>/…``. The
fixtures are not run here: the hub's ``make check`` runs ``hub workflow test``.
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import WORKFLOWS_VALID_RULE, Severity
from agent_hub.core.workflows.catalog import check_workflows

FIX: Final = "fix the workflow file; hub workflow validate lists each problem"


def _workflows_valid(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    if snapshot.workflows is None:
        return ()
    return tuple(
        WORKFLOWS_VALID.finding(
            path=problem.file,
            line=problem.line,
            message=f"{problem.key}: {problem.message}",
            fix=FIX,
        )
        for problem in check_workflows(snapshot.workflows).problems
    )


WORKFLOWS_VALID: Final = Rule(
    id=WORKFLOWS_VALID_RULE,
    severity=Severity.ERROR,
    summary="every workflow of the hub and the built-ins loads and plans",
    module=None,
    reads=frozenset({Read.WORKFLOWS}),
    check=_workflows_valid,
)
