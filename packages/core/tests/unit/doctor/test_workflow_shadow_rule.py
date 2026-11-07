"""``workflows.shadow``: a hub workflow that overrides a built-in whose pack has changed."""

from collections.abc import Callable
from dataclasses import replace

from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot, WorkflowShadow
from agent_hub.core.doctor.workflow_shadow_rule import WORKFLOWS_SHADOW
from agent_hub.core.hub_config.doctor_rules import RULE_IDS, Severity

type SnapshotFactory = Callable[..., DoctorSnapshot]


def a_shadow(*, identical: bool, name: str = "inbox") -> WorkflowShadow:
    return WorkflowShadow(
        name=name,
        path=f"workflows/brain-care/{name}.yaml",
        pack="workflows/brain-care",
        builtin_pack="brain-care",
        identical=identical,
    )


def test_declares_design_fields_when_rule_read() -> None:
    assert WORKFLOWS_SHADOW.id == "workflows.shadow"
    assert WORKFLOWS_SHADOW.severity is Severity.WARNING
    assert WORKFLOWS_SHADOW.reads == frozenset({Read.WORKFLOW_SHADOWS})
    assert WORKFLOWS_SHADOW.module is None
    assert "workflows.shadow" in RULE_IDS


def test_finds_nothing_when_shadows_not_read(snapshot_of: SnapshotFactory) -> None:
    assert list(WORKFLOWS_SHADOW.check(snapshot_of())) == []


def test_finds_nothing_when_no_hub_workflow_shadows_builtin(
    snapshot_of: SnapshotFactory,
) -> None:
    snapshot = replace(snapshot_of(), workflow_shadows=())

    assert list(WORKFLOWS_SHADOW.check(snapshot)) == []


def test_finds_nothing_when_shadow_identical_to_builtin(snapshot_of: SnapshotFactory) -> None:
    # A seeded pack as hub init wrote it hides nothing of the running release (ADR 0032).
    snapshot = replace(snapshot_of(), workflow_shadows=(a_shadow(identical=True),))

    assert list(WORKFLOWS_SHADOW.check(snapshot)) == []


def test_warns_with_compare_fix_when_shadow_differs_from_builtin(
    snapshot_of: SnapshotFactory,
) -> None:
    snapshot = replace(
        snapshot_of(),
        workflow_shadows=(a_shadow(identical=True, name="context"), a_shadow(identical=False)),
    )

    found = list(WORKFLOWS_SHADOW.check(snapshot))

    assert [(f.path, f.line, f.severity) for f in found] == [
        ("workflows/brain-care/inbox.yaml", None, Severity.WARNING)
    ]
    assert found[0].message == (
        "overrides the built-in workflow inbox, and workflows/brain-care/ differs from the"
        " built-in brain-care pack of this release (0.2.0)"
    )
    assert found[0].fix == (
        "compare workflows/brain-care/ with packages/core/src/agent_hub/core/workflows/builtin/"
        "brain-care/ at the platform's tag v0.2.0 and merge what you need, or delete"
        " workflows/brain-care/ to run the built-in"
    )
