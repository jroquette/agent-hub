import base64

import pytest

from agent_hub.core.agent_sessions.agent_session import MessageFile, MessageFileMediaType
from agent_hub.core.agent_sessions.driver import DriverFile
from agent_hub.core.agent_sessions.errors import (
    InvalidMessageFileError,
    MessageFileTooLargeError,
)
from agent_hub.core.agent_sessions.message_file import (
    MAX_MESSAGE_FILE_BYTES,
    decode_message_file,
)

PDF = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
POINTER = "/files/0/data"


def _file(data: bytes, media_type: MessageFileMediaType = "text/plain") -> MessageFile:
    return MessageFile(name="notes.md", media_type=media_type, data=base64.b64encode(data).decode())


def test_returns_text_bytes_when_file_is_utf8_text() -> None:
    # AC-419.1
    text = "# Notes\nolá\n".encode()

    decoded = decode_message_file(_file(text), pointer=POINTER)

    assert decoded == DriverFile(name="notes.md", media_type="text/plain", data=text)


def test_returns_pdf_bytes_when_file_is_pdf() -> None:
    # AC-419.1
    decoded = decode_message_file(_file(PDF, "application/pdf"), pointer=POINTER)

    assert decoded.data == PDF


def test_refuses_pdf_when_signature_missing() -> None:
    # AC-419.2
    with pytest.raises(InvalidMessageFileError) as refused:
        decode_message_file(_file(b"hello", "application/pdf"), pointer=POINTER)

    assert (refused.value.reason, refused.value.pointer) == ("not a PDF", POINTER)


@pytest.mark.parametrize("data", [b"\xff\xfe\x00b", b"a\x00b"])
def test_refuses_text_when_not_utf8_or_has_nul(data: bytes) -> None:
    # AC-419.2
    with pytest.raises(InvalidMessageFileError) as refused:
        decode_message_file(_file(data), pointer=POINTER)

    assert refused.value.reason == "not UTF-8 text"


def test_refuses_file_when_not_base64() -> None:
    # AC-419.2
    bad = MessageFile(name="a.txt", media_type="text/plain", data="not base64!")

    with pytest.raises(InvalidMessageFileError) as refused:
        decode_message_file(bad, pointer=POINTER)

    assert refused.value.reason == "not valid base64"


def test_accepts_file_when_decoded_size_exactly_at_cap() -> None:
    # AC-419.3
    decoded = decode_message_file(_file(b"a" * MAX_MESSAGE_FILE_BYTES), pointer=POINTER)

    assert len(decoded.data) == MAX_MESSAGE_FILE_BYTES == 5 * 1024 * 1024


def test_raises_too_large_when_decoded_size_one_byte_over_cap() -> None:
    # AC-419.3
    with pytest.raises(MessageFileTooLargeError) as raised:
        decode_message_file(_file(b"a" * (MAX_MESSAGE_FILE_BYTES + 1)), pointer=POINTER)

    assert (raised.value.size, raised.value.limit) == (
        MAX_MESSAGE_FILE_BYTES + 1,
        MAX_MESSAGE_FILE_BYTES,
    )


def test_hides_data_when_repr_called() -> None:
    # AC-419.4
    message_file = _file(b"secret text")

    assert message_file.data not in repr(message_file)
    assert "secret" not in repr(decode_message_file(message_file, pointer=POINTER))
