"""``claude -p --cloud <id>`` follow-ups (CL, AC-165.40): argv only, bounded, URLs checked."""

import json
import stat
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest

from agent_hub.claude_sessions.cloud_launcher import OUTPUT_LIMIT_BYTES, ClaudeCloudLauncher
from agent_hub.claude_sessions.process_tree import Completed, RunTimeoutError
from agent_hub.core.agent_sessions.cloud import CloudReply
from agent_hub.core.agent_sessions.errors import CloudFailedError, CloudTimeoutError

pytestmark = pytest.mark.anyio

CLOUD_ID = "cse_01synthetic"
URL = f"https://claude.ai/code/{CLOUD_ID}"


class FakeRun:
    """Answers every command with ``answer``; records argv, deadline, limit and environment."""

    def __init__(self, answer: Completed | Exception) -> None:
        self.answer = answer
        self.calls: list[tuple[list[str], float, int, dict[str, str] | None]] = []

    async def __call__(
        self, argv: Sequence[str], *, timeout: float, limit: int, env: Mapping[str, str] | None
    ) -> Completed:
        self.calls.append((list(argv), timeout, limit, None if env is None else dict(env)))
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def _json(data: object, code: int = 0) -> Completed:
    return Completed(code=code, stdout=json.dumps(data).encode(), overflow=False)


def _launcher(
    tmp_path: Path, answer: Completed | Exception
) -> tuple[ClaudeCloudLauncher, FakeRun, str]:
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir(exist_ok=True)
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    run = FakeRun(answer)
    environ = {"PATH": str(claude.parent), "HOME": "/home/demo"}
    return ClaudeCloudLauncher(environ=environ, run=run), run, str(claude)


async def test_passes_text_as_one_argument_when_followed_up(tmp_path: Path) -> None:
    launcher, run, claude = _launcher(
        tmp_path, _json({"ok": True, "session_id": CLOUD_ID, "url": URL})
    )
    text = 'Also fix "docs"; rm -rf / && echo $HOME'

    reply = await launcher.follow_up(CLOUD_ID, text, timeout_seconds=60)

    assert reply == CloudReply(cloud_id=CLOUD_ID, url=URL)
    [(argv, timeout, limit, env)] = run.calls
    assert argv == [claude, "-p", "--cloud", CLOUD_ID, "--output-format", "json", text]
    assert (timeout, limit) == (60, OUTPUT_LIMIT_BYTES)
    assert env == {"PATH": str(tmp_path / "bin"), "HOME": "/home/demo"}


@pytest.mark.parametrize(
    ("cloud_id", "text"), [(CLOUD_ID, "-rf"), ("--help", "go on"), ("a b", "go")]
)
async def test_refuses_text_when_starts_with_dash(tmp_path: Path, cloud_id: str, text: str) -> None:
    launcher, run, _ = _launcher(tmp_path, _json({}))

    with pytest.raises(ValueError, match="argument"):
        await launcher.follow_up(cloud_id, text, timeout_seconds=60)

    assert run.calls == []


async def test_drops_url_when_not_claude_code(tmp_path: Path) -> None:
    answer = _json({"session_id": "other id!", "url": "https://claude.ai.evil/code/x"})
    launcher, _, _ = _launcher(tmp_path, answer)

    reply = await launcher.follow_up(CLOUD_ID, "go on", timeout_seconds=60)

    assert reply == CloudReply(cloud_id=CLOUD_ID, url=None)


async def test_times_out_when_child_hangs(tmp_path: Path) -> None:
    launcher, _, _ = _launcher(tmp_path, RunTimeoutError())

    with pytest.raises(CloudTimeoutError) as raised:
        await launcher.follow_up(CLOUD_ID, "go on", timeout_seconds=60)

    assert raised.value.seconds == 60


@pytest.mark.parametrize(
    ("answer", "step"),
    [
        (Completed(code=1, stdout=b"Error: not logged in", overflow=False), "exit 1"),
        (Completed(code=0, stdout=b"not json", overflow=False), "unreadable"),
        (_json(["a list"]), "unreadable"),
        (_json({"ok": False}), "not ok"),
        (Completed(code=None, stdout=b"x" * 70_000, overflow=True), "64 KiB"),
    ],
    ids=["exit", "not_json", "not_object", "not_ok", "overflow"],
)
async def test_fails_when_followup_unreadable_or_failed(
    tmp_path: Path, answer: Completed, step: str
) -> None:
    launcher, _, _ = _launcher(tmp_path, answer)

    with pytest.raises(CloudFailedError) as raised:
        await launcher.follow_up(CLOUD_ID, "go on", timeout_seconds=60)

    assert step in raised.value.step
    assert "not logged in" not in raised.value.step


async def test_fails_when_claude_missing(tmp_path: Path) -> None:
    launcher = ClaudeCloudLauncher(environ={"PATH": str(tmp_path)}, run=FakeRun(_json({})))

    with pytest.raises(CloudFailedError, match="claude"):
        await launcher.follow_up(CLOUD_ID, "go on", timeout_seconds=60)
