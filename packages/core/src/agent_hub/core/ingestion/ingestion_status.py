"""The collector's own status: counters since start, sources' freshness, the redaction rules."""

from typing import Literal

from pydantic import Field

from agent_hub.core.events.event import EventSource
from agent_hub.core.readmodels.view_types import ApiTimestamp, ViewModel

# The version of the redaction rule set (D10); a change is a release note.
REDACTION_RULESET = "r1"


class SourceStatus(ViewModel):
    """When a source last sent an event, and whether that is recent enough."""

    source: EventSource
    last_event_at: ApiTimestamp | None
    state: Literal["fresh", "stale", "never"]


class CollectorStatus(ViewModel):
    """``GET /collector/status``: what ``hub web`` received and stored since it started."""

    state: Literal["running"] = "running"
    db_path: str
    running_version: str
    started_at: ApiTimestamp
    events_total: int = Field(ge=0)
    hooks_received: int = Field(ge=0)
    appended: int = Field(ge=0)
    duplicates: int = Field(ge=0)
    transcript_refused: int = Field(ge=0)
    transcript_lines_skipped: int = Field(ge=0)
    last_event_at: ApiTimestamp | None
    sources: tuple[SourceStatus, ...]
    redaction_ruleset: str = REDACTION_RULESET
