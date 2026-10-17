"""Who a Linear key belongs to: the one read that proves the key works (``hub web`` Settings).

One ``viewer`` and ``organization`` query over the shared transport (``graphql_transport``): the
key from ``LINEAR_API_KEY`` in ``environ`` at call time, never in a message. Only the user's
name and email and the workspace's name and URL key are selected. Every failure is the
transport's ``TrackerError`` with its ``kind``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from agent_hub.tracker_linear.graphql_transport import (
    Post,
    Shape,
    request_data,
    urllib_post,
)

OPERATION: Final = "check the Linear connection"
VIEWER_QUERY: Final = """
query Viewer {
  viewer { name email }
  organization { name urlKey }
}
"""
_SHAPE: Final[Shape] = {
    "viewer": {"name": str, "email": str},
    "organization": {"name": str, "urlKey": str},
}


@dataclass(frozen=True, slots=True)
class LinearAccount:
    """The key's user and workspace."""

    name: str
    email: str
    workspace: str
    url_key: str


def linear_account(
    environ: Mapping[str, str], *, post: Post | None = None, timeout_s: float = 10.0
) -> LinearAccount:
    """The account of ``LINEAR_API_KEY`` in ``environ``; ``TrackerError`` when it does not work."""
    data = request_data(
        post=urllib_post if post is None else post,
        environ=environ,
        timeout_s=timeout_s,
        operation=OPERATION,
        issue_id=None,
        operation_name="Viewer",
        query=VIEWER_QUERY,
        variables={},
        shape=_SHAPE,
    )
    return LinearAccount(
        name=data["viewer"]["name"],
        email=data["viewer"]["email"],
        workspace=data["organization"]["name"],
        url_key=data["organization"]["urlKey"],
    )
