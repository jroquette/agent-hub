"""What ``ClaudeSdkSessionDriver.send`` hands the SDK, over a recording client (AC-260.9).

The image shape was checked against claude-agent-sdk 0.2.165 (AGH-260, T1):
``ClaudeSDKClient.query`` takes ``str | AsyncIterable[dict]``. For an iterable it writes each
dict as one JSON line, adding ``session_id`` when missing, passes it through
``stamp_user_message`` (which only adds ``client_composed`` when ``verbatim_prompts`` is set),
and does not end the input stream, so later sends still work. One image message is therefore::

    {"type": "user",
     "message": {"role": "user", "content": [
         {"type": "image",
          "source": {"type": "base64", "media_type": "image/png", "data": "<b64>"}},
         {"type": "text", "text": "<prompt>"}]},
     "parent_tool_use_id": None}

sent through a one-item async generator.
"""

import asyncio
import base64
from collections.abc import AsyncIterable, AsyncIterator
from pathlib import Path
from typing import Any

import pytest
from claude_agent_sdk import ClaudeSDKClient

from agent_hub.claude_sessions.sdk_driver import ClaudeSdkSessionDriver
from agent_hub.core.agent_sessions.driver import DriverFile, DriverImage, StartSpec
from agent_hub.core.testing.builders import a_png_bytes

pytestmark = pytest.mark.anyio


class RecordingClient(ClaudeSDKClient):
    """A client that starts no process and records what each ``query`` was given."""

    queries: list[object]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.queries = []
        self.stopped: list[str] = []
        self._done = asyncio.Event()

    async def connect(self, prompt: object = None) -> None:
        return None

    info: dict[str, Any] | None = None

    async def get_server_info(self) -> dict[str, Any] | None:
        return self.info

    async def query(
        self, prompt: str | AsyncIterable[dict[str, Any]], session_id: str = "default"
    ) -> None:
        if isinstance(prompt, str):
            self.queries.append(prompt)
        else:
            self.queries.append([message async for message in prompt])

    async def stop_task(self, task_id: str) -> None:
        self.stopped.append(task_id)

    async def receive_messages(self) -> AsyncIterator[Any]:
        await self._done.wait()
        return
        yield

    async def disconnect(self) -> None:
        self._done.set()


async def _sent(
    tmp_path: Path,
    text: str,
    images: tuple[DriverImage, ...],
    *,
    files: tuple[DriverFile, ...] = (),
    info: dict[str, Any] | None = None,
) -> list[object]:
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    clients: list[RecordingClient] = []

    def factory(*args: Any, **kwargs: Any) -> RecordingClient:
        clients.append(RecordingClient(*args, **kwargs))
        clients[-1].info = info
        return clients[-1]

    driver = ClaudeSdkSessionDriver(environ={"PATH": str(tmp_path)}, client_factory=factory)
    handle = await driver.start(StartSpec(cwd=str(tmp_path), mode="default"))
    await driver.send(handle, text, images=images, files=files)
    await driver.close(handle)
    return clients[0].queries


async def test_queries_plain_text_when_no_image(tmp_path: Path) -> None:
    assert await _sent(tmp_path, "Say hello.", ()) == ["Say hello."]


async def test_queries_exact_names_when_text_uses_short_ones(tmp_path: Path) -> None:
    info = {
        "commands": [{"name": "hub-workflow:fix"}],
        "agents": [{"name": "hub-workflow:researcher"}],
    }

    sent = await _sent(tmp_path, "/fix then ask /agent-researcher", (), info=info)

    assert sent == ["/hub-workflow:fix then ask @agent-hub-workflow:researcher"]


async def test_asks_cli_to_stop_task_when_stop_task_called(tmp_path: Path) -> None:
    claude = tmp_path / "claude"
    claude.write_text("#!/bin/sh\n")
    claude.chmod(0o755)
    clients: list[RecordingClient] = []

    def factory(*args: Any, **kwargs: Any) -> RecordingClient:
        clients.append(RecordingClient(*args, **kwargs))
        return clients[-1]

    driver = ClaudeSdkSessionDriver(environ={"PATH": str(tmp_path)}, client_factory=factory)
    handle = await driver.start(StartSpec(cwd=str(tmp_path), mode="default"))
    await driver.stop_task(handle, "task-1")
    await driver.close(handle)

    assert clients[0].stopped == ["task-1"]
    assert clients[0].queries == []


async def test_queries_files_then_text_when_files_given(tmp_path: Path) -> None:
    pdf = DriverFile(name="spec.pdf", media_type="application/pdf", data=b"%PDF-1.7\n")
    notes = DriverFile(name='my "notes".md', media_type="text/plain", data="olá".encode())

    sent = await _sent(tmp_path, "Read these.", (), files=(pdf, notes))

    content = sent[0][0]["message"]["content"]  # type: ignore[index]
    assert content == [
        {
            "type": "document",
            "source": {
                "type": "base64",
                "media_type": "application/pdf",
                "data": base64.b64encode(b"%PDF-1.7\n").decode("ascii"),
            },
            "title": "spec.pdf",
        },
        {"type": "text", "text": "<file name=\"my 'notes'.md\">\nolá\n</file>"},
        {"type": "text", "text": "Read these."},
    ]


async def test_queries_image_then_text_when_image_given(tmp_path: Path) -> None:
    png = a_png_bytes()
    image = DriverImage(media_type="image/png", data=png)

    sent = await _sent(tmp_path, "What is on this screen?", (image,))

    assert sent == [
        [
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(png).decode("ascii"),
                            },
                        },
                        {"type": "text", "text": "What is on this screen?"},
                    ],
                },
                "parent_tool_use_id": None,
            }
        ]
    ]
