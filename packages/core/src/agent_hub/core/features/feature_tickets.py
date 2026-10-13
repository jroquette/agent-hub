"""A feature's Tickets view (AGH-136 C.2): its rows, planning and golden path, with the source.

``feature_tickets`` folds the feature over what the snapshot cache served (``SnapshotRead``):
Linear's snapshot (fresh, or ``stale`` after a failed read), else the plan (``features.json``)
with a notice saying why. ``tracker_problem`` names a failed read as RFC 9457 members (E9):
``type`` ``urn:agent-hub:problem:tracker-<kind>``, ``status`` Linear's HTTP error status, else
502 for an answer of another shape, 504 for a timeout and 503 when Linear gave no answer. The
failure's detail is redacted (r1) and clipped: the key never shows. The MCP transport is never
connected for hub web, whatever the read says.
"""

from typing import Final

from agent_hub.core.errors import TrackerFailure
from agent_hub.core.features.feature_status import FeatureFolder, feature_parts
from agent_hub.core.features.golden_path import LINEAR_NOT_LOADED_REASON
from agent_hub.core.features.ticket_snapshots import SnapshotRead
from agent_hub.core.features.ticket_view import FeatureTickets, TrackerProblem
from agent_hub.core.hub_config.model import Tracker
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.redaction.redact import clip, redact_text

PROBLEM_TYPE_PREFIX: Final = "urn:agent-hub:problem:tracker-"
NOT_CONNECTED_NOTICE: Final = (
    "From the plan (features.json); Linear is not connected for hub web, so status may be "
    "stale. Set LINEAR_API_KEY where hub web runs."
)
NOT_LOADED_NOTICE: Final = LINEAR_NOT_LOADED_REASON
DETAIL_CHARS: Final = 300
NOT_CONNECTED_READ: Final = SnapshotRead(
    snapshot=None,
    source="plan",
    stale=False,
    as_of=None,
    failure="not_connected",
    detail="Linear is not connected for hub web",
    http_status=None,
)
# Each failure kind's problem title and the short cause a notice quotes.
_FAILURES: Final[dict[TrackerFailure, tuple[str, str]]] = {
    "not_connected": ("Linear is not connected", "not connected"),
    "unauthorized": ("Linear refused the key", "the key was refused"),
    "timeout": ("Linear did not answer in time", "it timed out"),
    "rate_limited": ("Linear's rate limit was reached", "rate limited"),
    "unavailable": ("Linear is unavailable", "it is unavailable"),
    "unexpected": ("Linear answered unexpectedly", "its answer was unexpected"),
    "unreachable": ("Linear could not be reached", "it could not be reached"),
    "too_many": ("Too many tickets for one read", "too many tickets"),
    "other": ("Linear could not be read", "an error"),
}
_NO_ANSWER_STATUS: Final = 503
_TIMEOUT_STATUS: Final = 504
_BAD_ANSWER_STATUS: Final = 502
_ERROR_STATUSES: Final = range(400, 600)


def feature_tickets(
    folder: FeatureFolder, read: SnapshotRead, *, project: str, tracker: Tracker
) -> FeatureTickets:
    """The feature's tickets as ``read`` serves them, for the hub whose tracker is ``tracker``."""
    if tracker.transport == "mcp":
        read = NOT_CONNECTED_READ
    parts = feature_parts(folder, read)
    return FeatureTickets(
        project=project,
        slug=folder.slug,
        source=parts.source,
        stale=parts.source == "linear" and read.stale,
        as_of=read.as_of if parts.source == "linear" else None,
        notice=_notice(read),
        tracker_problem=_problem(read),
        tickets=parts.board.rows,
        planning=parts.board.plan,
        golden_path=parts.golden_path,
    )


def _notice(read: SnapshotRead) -> str | None:
    cause = None if read.failure is None else _FAILURES[read.failure][1]
    if read.snapshot is not None:
        if not read.stale:
            return None
        if cause is None:
            return "From Linear's last read; status may be stale."
        return (
            f"From Linear's last good read; the latest read failed ({cause}), "
            "so status may be stale."
        )
    if read.failure is None:
        return NOT_LOADED_NOTICE
    if read.failure == "not_connected":
        return NOT_CONNECTED_NOTICE
    return (
        f"From the plan (features.json); Linear could not be read ({cause}), "
        "so status may be stale."
    )


def _problem(read: SnapshotRead) -> TrackerProblem | None:
    if read.failure is None:
        return None
    title = _FAILURES[read.failure][0]
    detail = (
        title if read.detail is None else clip(redact_text(one_line(read.detail)), DETAIL_CHARS)
    )
    return TrackerProblem(
        type=f"{PROBLEM_TYPE_PREFIX}{read.failure}",
        title=title,
        status=_status(read.failure, read.http_status),
        detail=detail or title,
    )


def _status(failure: TrackerFailure, http_status: int | None) -> int:
    if http_status is not None and http_status in _ERROR_STATUSES:
        return http_status
    if failure == "timeout":
        return _TIMEOUT_STATUS
    if failure == "unexpected":
        return _BAD_ANSWER_STATUS
    return _NO_ANSWER_STATUS
