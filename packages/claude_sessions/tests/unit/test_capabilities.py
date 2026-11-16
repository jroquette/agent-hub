"""What ``GET /capabilities`` reports (AC-165.38, AC-165.55): no network, at most 5 s."""

import stat
from collections.abc import Sequence
from pathlib import Path

import pytest

from agent_hub.claude_sessions.capabilities import (
    DETECT_TIMEOUT_SECONDS,
    ENGINE,
    OUTPUT_LIMIT_BYTES,
    CapabilityCache,
    detect,
)
from agent_hub.claude_sessions.process_tree import Completed, RunTimeoutError
from agent_hub.core.agent_sessions.driver import MODEL_ALIASES, DriverCapabilities

pytestmark = pytest.mark.anyio

HELP = "Usage: claude [options]\n  --print\n"
CLOUD_HELP = (
    HELP
    + "  --cloud [description|session_id|url]  Create a cloud session\n  --teleport [session]\n"
)


VERSION_OK = Completed(code=0, stdout=b"2.1.296 (Claude Code)\n", overflow=False)
HELP_OK = Completed(code=0, stdout=CLOUD_HELP.encode(), overflow=False)


class FakeRun:
    """Answers ``--version`` and ``--help``; records every call."""

    def __init__(
        self,
        *,
        version: Completed | Exception = VERSION_OK,
        help_text: Completed | Exception = HELP_OK,
    ) -> None:
        self.calls: list[tuple[list[str], float, int]] = []
        self._version = version
        self._help = help_text

    async def __call__(self, argv: Sequence[str], *, timeout: float, limit: int) -> Completed:
        self.calls.append((list(argv), timeout, limit))
        answer = self._version if "--version" in argv else self._help
        if isinstance(answer, Exception):
            raise answer
        return answer


def _claude_on_path(tmp_path: Path) -> dict[str, str]:
    claude = tmp_path / "bin" / "claude"
    claude.parent.mkdir()
    claude.write_text("#!/bin/sh\n", encoding="utf-8")
    claude.chmod(claude.stat().st_mode | stat.S_IXUSR)
    return {"PATH": str(claude.parent)}


async def test_reports_cloud_when_help_lists_cloud_and_teleport(tmp_path: Path) -> None:
    run = FakeRun()

    found = await detect(_claude_on_path(tmp_path), run)

    assert found == DriverCapabilities(
        available=True,
        engine=ENGINE,
        cli_version="2.1.296",
        models=MODEL_ALIASES,
        cloud=True,
        cloud_followup=False,
    )
    claude = str(tmp_path / "bin" / "claude")
    assert [call[0] for call in run.calls] == [[claude, "--version"], [claude, "--help"]]
    assert {(call[1], call[2]) for call in run.calls} == {
        (DETECT_TIMEOUT_SECONDS, OUTPUT_LIMIT_BYTES)
    }


async def test_reports_followup_when_flag_set_and_cloud_listed(tmp_path: Path) -> None:
    found = await detect(_claude_on_path(tmp_path), FakeRun(), cloud_followup=True)

    assert (found.cloud, found.cloud_followup) == (True, True)


@pytest.mark.parametrize(
    "help_text",
    [
        Completed(code=0, stdout=HELP.encode(), overflow=False),
        Completed(code=0, stdout=b"  --cloud [id]\n", overflow=False),
    ],
    ids=["no_cloud", "cloud_without_teleport"],
)
async def test_reports_no_cloud_when_help_lacks_it(tmp_path: Path, help_text: Completed) -> None:
    found = await detect(
        _claude_on_path(tmp_path), FakeRun(help_text=help_text), cloud_followup=True
    )

    assert found.available
    assert (found.cloud, found.cloud_followup) == (False, False)


async def test_reports_unavailable_when_claude_missing(tmp_path: Path) -> None:
    run = FakeRun()

    found = await detect({"PATH": str(tmp_path)}, run)

    assert not found.available
    assert found.reason is not None
    assert "claude" in found.reason
    assert run.calls == []


async def test_times_out_when_help_hangs(tmp_path: Path) -> None:
    found = await detect(_claude_on_path(tmp_path), FakeRun(help_text=RunTimeoutError()))

    assert found.available
    assert not found.cloud
    assert DETECT_TIMEOUT_SECONDS == 5


@pytest.mark.parametrize(
    ("version", "cause"),
    [
        (RunTimeoutError(), "5 s"),
        (Completed(code=2, stdout=b"", overflow=False), "exit 2"),
        (Completed(code=None, stdout=b"x" * 70_000, overflow=True), "64 KiB"),
    ],
    ids=["timeout", "failed", "overflow"],
)
async def test_reports_unavailable_when_version_fails(
    tmp_path: Path, version: Completed | Exception, cause: str
) -> None:
    found = await detect(_claude_on_path(tmp_path), FakeRun(version=version))

    assert not found.available
    assert found.reason is not None
    assert cause in found.reason


async def test_reuses_answer_when_asked_again_within_a_minute() -> None:
    now = [100.0]
    asked: list[int] = []

    async def probe() -> DriverCapabilities:
        asked.append(1)
        return DriverCapabilities(available=True, cli_version=str(len(asked)))

    cache = CapabilityCache(probe, clock=lambda: now[0])
    first = await cache.get()
    now[0] += 59
    second = await cache.get()
    now[0] += 2
    third = await cache.get()

    assert (first.cli_version, second.cli_version, third.cli_version) == ("1", "1", "2")
