"""``ClaudeCloudLauncher``: the ``CloudLauncher`` port over the ``claude`` CLI (CL, D8).

A follow-up runs ``claude -p --cloud <id> --output-format json <text>``: an argv list (the text is
one argument, never through a shell), the ``claude`` on ``PATH``, ``hub web``'s environment, its
own process group, a deadline and 64 KiB of output (``process_tree.run_bounded``). The answer is
read as a JSON object: ``session_id`` when it is a valid cloud id (else the one asked for), ``url``
only when it is a claude.ai/code link, and ``ok: false`` is a failure. Failures name the step,
never the CLI's output or the text. Starting a cloud session is not here: the CLI needs a
terminal for it (``agent_hub.core.agent_sessions.cloud``).
"""

import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Final, Protocol

from agent_hub.claude_sessions.options import claude_path
from agent_hub.claude_sessions.process_tree import Completed, RunTimeoutError, run_bounded
from agent_hub.core.agent_sessions.agent_session import CLOUD_ID_PATTERN
from agent_hub.core.agent_sessions.cloud import CloudReply, claude_code_url
from agent_hub.core.agent_sessions.errors import CloudFailedError, CloudTimeoutError

OUTPUT_LIMIT_BYTES: Final = 64 * 1024
_CLOUD_ID = re.compile(CLOUD_ID_PATTERN)


class CloudRunner(Protocol):
    """Runs one command with a deadline, an output limit and an environment."""

    async def __call__(
        self, argv: Sequence[str], *, timeout: float, limit: int, env: Mapping[str, str] | None
    ) -> Completed:
        """Run ``argv``; ``RunTimeoutError`` past the deadline."""
        ...


def _argument(value: str) -> bool:
    return bool(value) and not value.startswith("-")


def _reply(cloud_id: str, done: Completed) -> CloudReply:
    if done.overflow:
        raise CloudFailedError("follow-up output over 64 KiB")
    if done.code != 0:
        raise CloudFailedError(f"follow-up exit {done.code}")
    try:
        data = json.loads(done.stdout.decode("utf-8"))
    except UnicodeDecodeError, json.JSONDecodeError:
        raise CloudFailedError("follow-up output unreadable") from None
    if not isinstance(data, dict):
        raise CloudFailedError("follow-up output unreadable")
    if data.get("ok") is False:
        raise CloudFailedError("follow-up answered not ok")
    answered = data.get("session_id")
    valid = isinstance(answered, str) and _CLOUD_ID.fullmatch(answered) and _argument(answered)
    url = data.get("url")
    return CloudReply(
        cloud_id=answered if valid and isinstance(answered, str) else cloud_id,
        url=claude_code_url(url) if isinstance(url, str) else None,
    )


class ClaudeCloudLauncher:
    """Runs the cloud follow-up with the user's ``claude``; see the module docstring."""

    def __init__(
        self, *, environ: Mapping[str, str] | None = None, run: CloudRunner = run_bounded
    ) -> None:
        self._environ: Mapping[str, str] = os.environ if environ is None else environ
        self._run = run

    async def follow_up(self, cloud_id: str, text: str, *, timeout_seconds: int) -> CloudReply:
        """Send ``text`` to cloud session ``cloud_id`` once."""
        if not (_argument(cloud_id) and _CLOUD_ID.fullmatch(cloud_id) and _argument(text)):
            msg = "a cloud id or text that could be read as a flag is not an argument"
            raise ValueError(msg)
        claude = claude_path(self._environ)
        if claude is None:
            raise CloudFailedError("finding claude on PATH")
        argv = [claude, "-p", "--cloud", cloud_id, "--output-format", "json", text]
        try:
            done = await self._run(
                argv, timeout=timeout_seconds, limit=OUTPUT_LIMIT_BYTES, env=dict(self._environ)
            )
        except RunTimeoutError:
            raise CloudTimeoutError(seconds=timeout_seconds) from None
        return _reply(cloud_id, done)
