"""Past Claude sessions of a workdir, for Resume (D.7, AC-165.20)."""

from datetime import UTC, datetime

import pytest
from claude_agent_sdk import SDKSessionInfo

from agent_hub.claude_sessions.resumable import MAX_RESUMABLE, list_resumable
from agent_hub.core.agent_sessions.driver import PastSession
from agent_hub.core.agent_sessions.errors import SessionsUnavailableError

pytestmark = pytest.mark.anyio

CWD = "/hubs/demo-hub"
OLD = "11111111-1111-4111-8111-111111111111"
NEW = "22222222-2222-4222-8222-222222222222"
# A synthetic secret of a shape the redaction rules recognise.
SECRET = "ghp_" + "a" * 36


def _info(session_id: str, modified_ms: int, **fields: object) -> SDKSessionInfo:
    values: dict[str, object] = {"summary": "Fix the build", "cwd": CWD} | fields
    return SDKSessionInfo(session_id=session_id, last_modified=modified_ms, **values)


async def test_lists_newest_first_when_sessions_present() -> None:
    seen: list[tuple[str, int]] = []

    def lister(directory: str, limit: int) -> list[SDKSessionInfo]:
        seen.append((directory, limit))
        return [
            _info(OLD, 1_700_000_000_000),
            _info(NEW, 1_800_000_000_000, custom_title="Release"),
        ]

    past = await list_resumable(CWD, lister=lister)

    assert seen == [(CWD, MAX_RESUMABLE)]
    assert MAX_RESUMABLE == 200
    assert past == (
        PastSession(
            session_id=NEW,
            title="Release",
            last_activity=datetime.fromtimestamp(1_800_000_000, UTC),
            cwd=CWD,
        ),
        PastSession(
            session_id=OLD,
            title="Fix the build",
            last_activity=datetime.fromtimestamp(1_700_000_000, UTC),
            cwd=CWD,
        ),
    )


async def test_redacts_and_clips_title_when_prompt_holds_secret() -> None:
    def lister(_directory: str, _limit: int) -> list[SDKSessionInfo]:
        return [_info(NEW, 1_800_000_000_000, summary=f"use {SECRET}\n" + "x" * 400, cwd=None)]

    [past] = await list_resumable(CWD, lister=lister)

    assert past.title is not None
    assert SECRET not in past.title
    assert "[redacted" in past.title
    assert "\n" not in past.title
    assert len(past.title) <= 200
    assert past.cwd == CWD


async def test_keeps_at_most_limit_when_lister_answers_more() -> None:
    def lister(_directory: str, _limit: int) -> list[SDKSessionInfo]:
        return [_info(f"00000000-0000-4000-8000-{n:012d}", n, summary="") for n in range(250)]

    past = await list_resumable(CWD, lister=lister)

    assert len(past) == MAX_RESUMABLE
    assert past[0].session_id.endswith("000000000249")
    assert past[0].title is None


async def test_reports_unavailable_when_sessions_unreadable() -> None:
    def lister(_directory: str, _limit: int) -> list[SDKSessionInfo]:
        raise PermissionError("unreadable")

    with pytest.raises(SessionsUnavailableError, match="past sessions"):
        await list_resumable(CWD, lister=lister)
