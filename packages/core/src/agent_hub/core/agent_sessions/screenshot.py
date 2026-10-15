"""The screenshot sent with a first prompt: decoded and checked before anything starts.

The checks run in a fixed order (strict base64, then the decoded size, then the PNG
signature), and a refusal names only the cause and the sizes, never the data.
"""

import base64
from typing import Final

from agent_hub.core.agent_sessions.agent_session import Screenshot
from agent_hub.core.agent_sessions.driver import DriverImage
from agent_hub.core.agent_sessions.errors import InvalidScreenshotError, ScreenshotTooLargeError

# 3.75 MiB decoded: its base64 fits the Anthropic API's 5 MiB image limit.
MAX_SCREENSHOT_BYTES: Final = 3_932_160
PNG_SIGNATURE: Final = b"\x89PNG\r\n\x1a\n"


def decode_screenshot(screenshot: Screenshot, *, limit: int = MAX_SCREENSHOT_BYTES) -> DriverImage:
    """The screenshot's PNG bytes; ``InvalidScreenshotError`` or ``ScreenshotTooLargeError``."""
    try:
        data = base64.b64decode(screenshot.data, validate=True)
    except ValueError:  # binascii.Error, or a character outside ASCII
        raise InvalidScreenshotError("not valid base64") from None
    if len(data) > limit:
        raise ScreenshotTooLargeError(size=len(data), limit=limit)
    if not data.startswith(PNG_SIGNATURE):
        raise InvalidScreenshotError("not a PNG")
    return DriverImage(media_type="image/png", data=data)
