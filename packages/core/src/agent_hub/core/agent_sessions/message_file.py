"""A file sent with a message for Claude to read: decoded and checked before anything is
logged or sent.

The checks run in a fixed order (strict base64, then the decoded size, then the content its
media type promises: a PDF's signature, or UTF-8 text without NUL bytes), and a refusal names
only the cause and the sizes, never the data.
"""

import base64
from typing import Final

from agent_hub.core.agent_sessions.agent_session import MessageFile
from agent_hub.core.agent_sessions.driver import DriverFile
from agent_hub.core.agent_sessions.errors import (
    InvalidMessageFileError,
    MessageFileTooLargeError,
)

# 5 MiB decoded per file.
MAX_MESSAGE_FILE_BYTES: Final = 5 * 1024 * 1024
PDF_SIGNATURE: Final = b"%PDF-"


def decode_message_file(
    message_file: MessageFile, *, pointer: str, limit: int = MAX_MESSAGE_FILE_BYTES
) -> DriverFile:
    """The file's bytes; ``InvalidMessageFileError`` (naming ``pointer``) or
    ``MessageFileTooLargeError``."""
    try:
        data = base64.b64decode(message_file.data, validate=True)
    except ValueError:  # binascii.Error, or a character outside ASCII
        raise InvalidMessageFileError("not valid base64", pointer=pointer) from None
    if len(data) > limit:
        raise MessageFileTooLargeError(size=len(data), limit=limit)
    if message_file.media_type == "application/pdf":
        if not data.startswith(PDF_SIGNATURE):
            raise InvalidMessageFileError("not a PDF", pointer=pointer)
    elif not _is_text(data):
        raise InvalidMessageFileError("not UTF-8 text", pointer=pointer)
    return DriverFile(name=message_file.name, media_type=message_file.media_type, data=data)


def _is_text(data: bytes) -> bool:
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
