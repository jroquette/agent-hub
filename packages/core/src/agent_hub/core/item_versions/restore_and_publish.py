"""``RestoreAndPublish``: the ``ItemVersionWrites`` port over its two use cases (AGH-295, S7).

Restore (``RestoreItemVersion``) and Publish (``PublishDraft``) are built over one
``RecordAndWrite``, whose lock keeps one write at a time in the app.
"""

from agent_hub.core.item_versions.item_version_ports import ItemRef, ItemWriteResult, ToolkitRef
from agent_hub.core.item_versions.publish_draft import PublishDraft
from agent_hub.core.item_versions.restore_item_version import RestoreItemVersion


class RestoreAndPublish:
    """``ItemVersionWrites``: each write handed to its use case."""

    def __init__(self, *, restore: RestoreItemVersion, publish: PublishDraft) -> None:
        self._restore = restore
        self._publish = publish

    def restore(self, ref: ItemRef, version_id: str, *, confirm_managed: bool) -> ItemWriteResult:
        """``RestoreItemVersion.restore``."""
        return self._restore.restore(ref, version_id, confirm_managed=confirm_managed)

    def publish(
        self, project: str, draft_id: str, target: ToolkitRef | None, *, confirm_managed: bool
    ) -> ItemWriteResult:
        """``PublishDraft.publish``."""
        return self._publish.publish(project, draft_id, target, confirm_managed=confirm_managed)
