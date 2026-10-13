"""Root of the agent-hub exception hierarchy; each package defines its own subclasses."""

from typing import Literal

from agent_hub.core.hub_config.problems import one_line

# Why a tracker read failed (ADR 0025), so a caller can say so without parsing the message:
# no key or the MCP transport (``not_connected``), a 401/403 (``unauthorized``), the deadline
# (``timeout``), a 429 (``rate_limited``), a 5xx (``unavailable``), an answer of another shape
# (``unexpected``), no answer at all (``unreachable``), more ids than one read takes
# (``too_many``); ``other`` for everything else, the default of every older raise site.
type TrackerFailure = Literal[
    "not_connected",
    "unauthorized",
    "timeout",
    "rate_limited",
    "unavailable",
    "unexpected",
    "unreachable",
    "too_many",
    "other",
]


class AgentHubError(Exception):
    """Base class for every error agent-hub raises on purpose."""


class EventConflictError(AgentHubError):
    """An event has the key ``(source, source_id)`` of another event but different content.

    ``position`` is the index, in the appended batch, of the event that conflicts.
    """

    def __init__(self, *, source: str, source_id: str, position: int) -> None:
        self.source = source
        self.source_id = source_id
        self.position = position
        super().__init__(
            f"event ({source}, {source_id}) at position {position} differs from an event "
            "with the same key"
        )


class TrackerError(AgentHubError):
    """A tracker operation failed; the message names the operation, issue, cause and fix.

    The message is one line, ``"<operation> <issue_id>: <cause>; <fix>"`` (no issue id for an
    operation without one). Control characters are escaped, because the cause may quote
    untrusted text such as an issue title or a tracker reply. Each part is also kept as an
    attribute, so a caller can show the cause without the adapter's fix. ``kind`` says why it
    failed (``TrackerFailure``, ``"other"`` unless the raise site knows better) and
    ``http_status`` is the tracker's HTTP status when it answered with one.
    """

    def __init__(
        self,
        *,
        operation: str,
        issue_id: str | None = None,
        cause: str,
        fix: str,
        kind: TrackerFailure = "other",
        http_status: int | None = None,
    ) -> None:
        self.operation = operation
        self.kind: TrackerFailure = kind
        self.http_status = http_status
        self.issue_id = issue_id
        self.cause = cause
        self.fix = fix
        subject = operation if issue_id is None else f"{operation} {issue_id}"
        super().__init__(one_line(f"{subject}: {cause}; {fix}"))
