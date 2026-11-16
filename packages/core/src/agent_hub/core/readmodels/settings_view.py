"""``GET /settings``: where the control plane reads and writes, and its privacy rules."""

from datetime import date

from agent_hub.core.ingestion.ingestion_status import REDACTION_RULESET
from agent_hub.core.readmodels.view_types import ViewModel


class SettingsView(ViewModel):
    """Read-only settings of the running ``hub web`` (no ``PATCH`` in Phase 2)."""

    db_path: str
    registry_path: str
    port: int
    running_version: str
    redaction_ruleset: str = REDACTION_RULESET
    redaction_kinds: tuple[str, ...]
    metadata_only: bool = True
    prices_as_of: date | None
