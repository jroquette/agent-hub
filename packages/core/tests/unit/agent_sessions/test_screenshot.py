import base64

import pytest

from agent_hub.core.agent_sessions.agent_session import Screenshot
from agent_hub.core.agent_sessions.driver import DriverImage
from agent_hub.core.agent_sessions.errors import InvalidScreenshotError, ScreenshotTooLargeError
from agent_hub.core.agent_sessions.screenshot import MAX_SCREENSHOT_BYTES, decode_screenshot
from agent_hub.core.testing.builders import a_png_bytes

JPEG_BYTES = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00"
GIF_BYTES = b"GIF89a\x01\x00\x01\x00"


def _screenshot(data: bytes) -> Screenshot:
    return Screenshot(media_type="image/png", data=base64.b64encode(data).decode())


def test_returns_png_bytes_when_screenshot_valid() -> None:
    png = a_png_bytes()

    image = decode_screenshot(_screenshot(png))

    assert image == DriverImage(media_type="image/png", data=png)


def test_raises_too_large_when_decoded_over_limit() -> None:
    png = a_png_bytes()

    with pytest.raises(ScreenshotTooLargeError) as raised:
        decode_screenshot(_screenshot(png), limit=len(png) - 1)

    assert (raised.value.size, raised.value.limit) == (len(png), len(png) - 1)
    assert MAX_SCREENSHOT_BYTES == 5 * 1024 * 1024


@pytest.mark.parametrize("data", ["not base64!", "iVBORw0KGgo", "aGk=\n", "aGk\u00e9"])
def test_raises_invalid_when_base64_malformed(data: str) -> None:
    with pytest.raises(InvalidScreenshotError):
        decode_screenshot(Screenshot(media_type="image/png", data=data))


@pytest.mark.parametrize("data", [JPEG_BYTES, GIF_BYTES])
def test_raises_invalid_when_bytes_are_jpeg_or_gif(data: bytes) -> None:
    with pytest.raises(InvalidScreenshotError):
        decode_screenshot(_screenshot(data))


@pytest.mark.parametrize(
    ("data", "limit"),
    [(a_png_bytes(), 1), (JPEG_BYTES, MAX_SCREENSHOT_BYTES), (b"x" * 7, MAX_SCREENSHOT_BYTES)],
)
def test_keeps_data_out_of_message_when_refused(data: bytes, limit: int) -> None:
    screenshot = _screenshot(data)

    with pytest.raises((InvalidScreenshotError, ScreenshotTooLargeError)) as raised:
        decode_screenshot(screenshot, limit=limit)

    assert screenshot.data not in str(raised.value)
    assert screenshot.data[:8] not in str(raised.value)
