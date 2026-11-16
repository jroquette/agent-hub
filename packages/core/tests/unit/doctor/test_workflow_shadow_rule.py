"""``workflows.shadow``: a hub workflow that overrides a built-in, identical to it or not."""

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


def test_warns_with_delete_fix_when_shadow_identical_to_builtin(
    snapshot_of: SnapshotFactory,
) -> None:
    # A copy as hub init seeds it hides nothing today, but hub sync never refreshes it, so it
    # hides every later release's changes to the built-in (ADR 0032).
    snapshot = replace(snapshot_of(), workflow_shadows=(a_shadow(identical=True),))

    (found,) = WORKFLOWS_SHADOW.check(snapshot)

    assert (found.path, found.line, found.severity) == (
        "workflows/brain-care/inbox.yaml",
        None,
        Severity.WARNING,
    )
    assert found.message == (
        "overrides the built-in workflow inbox, and workflows/brain-care/ is identical to the"
        " built-in brain-care pack of this release (0.2.0), so it only hides the changes of"
        " later releases"
    )
    assert found.fix == (
        "delete workflows/brain-care/ to run the built-in (move any file of your own out of it"
        " first)"
    )


def test_warns_with_compare_fix_when_shadow_differs_from_builtin(
    snapshot_of: SnapshotFactory,
) -> None:
    snapshot = replace(snapshot_of(), workflow_shadows=(a_shadow(identical=False),))

    (found,) = WORKFLOWS_SHADOW.check(snapshot)

    assert (found.path, found.line, found.severity) == (
        "workflows/brain-care/inbox.yaml",
        None,
        Severity.WARNING,
    )
    assert found.message == (
        "overrides the built-in workflow inbox, and workflows/brain-care/ differs from the"
        " built-in brain-care pack of this release (0.2.0)"
    )
    assert found.fix == (
        "compare workflows/brain-care/ with packages/core/src/agent_hub/core/workflows/builtin/"
        "brain-care/ at the platform's tag v0.2.0 and merge what you need, or delete"
        " workflows/brain-care/ to run the built-in (move any file of your own out of it first)"
    )


def test_warns_once_per_workflow_when_pack_holds_several(snapshot_of: SnapshotFactory) -> None:
    snapshot = replace(
        snapshot_of(),
        workflow_shadows=(a_shadow(identical=True, name="context"), a_shadow(identical=True)),
    )

    found = list(WORKFLOWS_SHADOW.check(snapshot))

    assert [(f.path, f.message.split(",")[0]) for f in found] == [
        ("workflows/brain-care/context.yaml", "overrides the built-in workflow context"),
        ("workflows/brain-care/inbox.yaml", "overrides the built-in workflow inbox"),
    ]


def test_points_fix_at_workflow_file_when_override_in_another_pack(
    snapshot_of: SnapshotFactory,
) -> None:
    # Deleting the hub pack would drop the hub's other workflows in it.
    mine = WorkflowShadow(
        name="inbox",
        path="workflows/mine/inbox.yaml",
        pack="workflows/mine",
        builtin_pack="brain-care",
        identical=False,
    )
    snapshot = replace(snapshot_of(), workflow_shadows=(mine,))

    (found,) = WORKFLOWS_SHADOW.check(snapshot)

    assert (found.path, found.severity) == ("workflows/mine/inbox.yaml", Severity.WARNING)
    assert found.message == (
        "overrides the built-in workflow inbox of the built-in brain-care pack of this release"
        " (0.2.0) from another pack, workflows/mine/"
    )
    assert found.fix == (
        "compare workflows/mine/inbox.yaml with packages/core/src/agent_hub/core/workflows/"
        "builtin/brain-care/ at the platform's tag v0.2.0 and merge what you need, or delete"
        " workflows/mine/inbox.yaml to run the built-in"
    )


def test_points_delete_fix_at_workflow_file_when_other_pack_identical(
    snapshot_of: SnapshotFactory,
) -> None:
    mine = WorkflowShadow(
        name="inbox",
        path="workflows/mine/inbox.yaml",
        pack="workflows/mine",
        builtin_pack="brain-care",
        identical=True,
    )
    snapshot = replace(snapshot_of(), workflow_shadows=(mine,))

    (found,) = WORKFLOWS_SHADOW.check(snapshot)

    assert (found.path, found.severity) == ("workflows/mine/inbox.yaml", Severity.WARNING)
    assert found.message == (
        "overrides the built-in workflow inbox of the built-in brain-care pack of this release"
        " (0.2.0) from another pack, workflows/mine/, which holds that pack identical, so it"
        " only hides the changes of later releases"
    )
    assert found.fix == "delete workflows/mine/inbox.yaml to run the built-in"
