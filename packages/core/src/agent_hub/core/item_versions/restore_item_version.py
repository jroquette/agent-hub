"""``RestoreItemVersion``: write a version back (AGH-295, D4, D12, D22, S4, S9, S10).

The item resolves to its unit as the history reads resolve it; the version is taken only from
that unit (an id of another unit is entity ``item version``, as a read answers it). The shared
step then records the disk first, refuses a secret match on disk (``secret_unversioned``) or an
unconfirmed managed unit, writes the version's content and appends a ``restore`` version naming
it; content equal to the disk's is ``changed: false``.
"""

from agent_hub.core.item_versions.item_version import UnitKind, VersionOrigin
from agent_hub.core.item_versions.item_version_ports import (
    ItemRef,
    ItemWriteResult,
    ToolkitUnits,
    WorkflowUnits,
)
from agent_hub.core.item_versions.read_item_versions import VERSION_ENTITY, marked_unit
from agent_hub.core.item_versions.record_and_write import RecordAndWrite
from agent_hub.core.item_versions.unit_content import decode
from agent_hub.core.item_versions.version_store import ItemVersionStore
from agent_hub.core.readmodels.read_ports import EntityNotFoundError


class RestoreItemVersion:
    """``ItemVersionWrites.restore`` over the store, the unit ports and the shared step."""

    def __init__(
        self,
        store: ItemVersionStore,
        *,
        toolkit_units: ToolkitUnits,
        workflow_units: WorkflowUnits,
        step: RecordAndWrite,
    ) -> None:
        self._store = store
        self._toolkit = toolkit_units
        self._workflows = workflow_units
        self._step = step

    def restore(self, ref: ItemRef, version_id: str, *, confirm_managed: bool) -> ItemWriteResult:
        """Write ``version_id`` of the item's unit back (see the module doc)."""
        marked = marked_unit(ref, toolkit_units=self._toolkit, workflow_units=self._workflows)
        unit = marked.unit
        version = self._store.get(unit.project, unit.unit_path, version_id)
        if version is None:
            raise EntityNotFoundError(entity=VERSION_ENTITY, entity_id=version_id)
        content = decode(
            version.content,
            folder=unit.kind is UnitKind.SKILL,
            name=unit.unit_path.rsplit("/", 1)[-1],
        )
        return self._step.write(
            marked.hub_path,
            unit,
            content,
            origin=VersionOrigin.RESTORE,
            confirm_managed=confirm_managed,
            restored_from=version.id,
        )
