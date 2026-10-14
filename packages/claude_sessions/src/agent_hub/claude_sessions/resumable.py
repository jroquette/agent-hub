"""Past Claude sessions of one workdir, for Resume (D.7).

The SDK's ``list_sessions`` reads the CLI's own session index for a directory (file metadata and
the head and tail of each session; no conversation is loaded here). Only sessions of that very
directory are listed (not its other git worktrees: a resumed session runs where it was started).
Titles are redacted, put on one line and clipped to 200 characters.
"""

import asyncio
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from typing import Final

from claude_agent_sdk import SDKSessionInfo, list_sessions

from agent_hub.core.agent_sessions.agent_session import MAX_TITLE_CHARS
from agent_hub.core.agent_sessions.driver import PastSession
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError
from agent_hub.core.redaction.redact import clip, redact_text

MAX_RESUMABLE: Final = 200

type SessionLister = Callable[[str, int], Sequence[SDKSessionInfo]]


def sdk_lister(directory: str, limit: int) -> Sequence[SDKSessionInfo]:
    """The CLI's sessions of ``directory`` itself, newest first."""
    return list_sessions(directory=directory, limit=limit, include_worktrees=False)


def _title(info: SDKSessionInfo) -> str | None:
    text = info.custom_title or info.summary or info.first_prompt or ""
    line = " ".join(redact_text(text).split())
    return clip(line, MAX_TITLE_CHARS) or None


def _past(info: SDKSessionInfo, cwd: str) -> PastSession:
    return PastSession(
        session_id=info.session_id,
        title=_title(info),
        last_activity=datetime.fromtimestamp(info.last_modified / 1000, UTC),
        cwd=info.cwd or cwd,
    )


async def list_resumable(
    cwd: str, *, lister: SessionLister = sdk_lister
) -> tuple[PastSession, ...]:
    """Past sessions of ``cwd``, newest first, at most ``MAX_RESUMABLE``."""
    try:
        infos = await asyncio.to_thread(lister, cwd, MAX_RESUMABLE)
    except OSError as failed:
        raise SessionsUnavailableError(
            "could not read the past sessions of this workdir"
        ) from failed
    newest = sorted(infos, key=lambda info: info.last_modified, reverse=True)
    return tuple(_past(info, cwd) for info in newest[:MAX_RESUMABLE])
