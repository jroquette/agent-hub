"""``RestoreAndPublish``: the ``ItemVersionWrites`` port over its use cases (AGH-295, S7).

Restore (``RestoreItemVersion``), Publish (``PublishDraft``) and a file unit's write (the
scenario builder's save) are built over one ``RecordAndWrite``, whose lock keeps one write at a
time in the app.
"""

from agent_hub.core.item_versions.item_units import ItemUnit
from agent_hub.core.item_versions.item_version import VersionOrigin
from agent_hub.core.item_versions.item_version_ports import ItemRef, ItemWriteResult, ToolkitRef
from agent_hub.core.item_versions.publish_draft import PublishDraft
from agent_hub.core.item_versions.record_and_write import RecordAndWrite
from agent_hub.core.item_versions.restore_item_version import RestoreItemVersion
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile


class RestoreAndPublish:
    """``ItemVersionWrites``: each write handed to its use case."""

    def __init__(
        self,
        *,
        restore: RestoreItemVersion,
        publish: PublishDraft,
        step: RecordAndWrite | None = None,
    ) -> None:
        self._restore = restore
        self._publish = publish
        self._step = step

    def restore(self, ref: ItemRef, version_id: str, *, confirm_managed: bool) -> ItemWriteResult:
        """``RestoreItemVersion.restore``."""
        return self._restore.restore(ref, version_id, confirm_managed=confirm_managed)

    def publish(
        self, project: str, draft_id: str, target: ToolkitRef | None, *, confirm_managed: bool
    ) -> ItemWriteResult:
        """``PublishDraft.publish``."""
        return self._publish.publish(project, draft_id, target, confirm_managed=confirm_managed)

    def write_file(self, hub_path: str, unit: ItemUnit, content: bytes) -> ItemWriteResult:
        """``RecordAndWrite.write`` of one file unit, recorded as a ``publish``."""
        if self._step is None:
            raise RuntimeError("no write step was composed")
        name = unit.unit_path.rsplit("/", 1)[-1]
        return self._step.write(
            hub_path,
            unit,
            UnitContent(files=(UnitFile(path=name, content=content),)),
            origin=VersionOrigin.PUBLISH,
        )
