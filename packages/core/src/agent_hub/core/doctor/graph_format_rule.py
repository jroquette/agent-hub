"""``scenarios.graph_format``: a warning per scenario still written in the graph format.

A scenario whose ``version`` is the integer 1 holds ``nodes``; the tree format (version 2,
docs/design/scenarios.md § Tree format) replaces it, and the graph format is removed two minor
releases after ``hub scenario migrate`` ships (ADR 0049). Each such file is one warning at its
version line, whose fix names the migrate command. Never an error: a graph scenario still loads
and runs. A file the reader refused, or one with another version, is not this rule's.
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import SCENARIOS_GRAPH_FORMAT_RULE, Severity
from agent_hub.core.workflows.catalog import WorkflowFile

GRAPH_VERSION: Final = 1


def _scenarios_graph_format(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    if snapshot.scenarios is None:
        return ()
    return tuple(
        SCENARIOS_GRAPH_FORMAT.finding(
            path=item.file,
            line=item.line_of(("version",)),
            message=(
                f"scenario {item.stem} is in the graph format (version 1),"
                " which a later release removes"
            ),
            fix=f"run hub scenario migrate {item.stem} to write it as blocks (version 2)",
        )
        for item in snapshot.scenarios.workflow_files()
        if isinstance(item, WorkflowFile) and _is_graph(item.content)
    )


def _is_graph(content: object) -> bool:
    if not isinstance(content, dict):
        return False
    version = content.get("version")
    return type(version) is int and version == GRAPH_VERSION


SCENARIOS_GRAPH_FORMAT: Final = Rule(
    id=SCENARIOS_GRAPH_FORMAT_RULE,
    severity=Severity.WARNING,
    summary="each scenario still in the graph format (version 1), with its migrate command",
    module=None,
    reads=frozenset({Read.SCENARIOS}),
    check=_scenarios_graph_format,
)
