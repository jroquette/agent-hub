"""The secret gate of a unit (AGH-295, D9): any rule of r1 matching in any file, text or not.

Every token is built here from fragments, so no format-valid secret is ever one literal.
"""

from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.redaction.redact import marker

_ALNUM = "A1b2C3d4E5f6G7h8"


def _github_token() -> str:
    return "gh" + "p_" + _ALNUM * 2 + "xyzw"


def _bearer_value() -> str:
    return "eyJ" + _ALNUM * 2 + ".payload" + _ALNUM


def _unit(*files: tuple[str, bytes]) -> UnitContent:
    return UnitContent(files=tuple(UnitFile(path=path, content=content) for path, content in files))


def test_matches_when_github_token_in_agent() -> None:
    agent = f"---\nname: reviewer\n---\nUse {_github_token()} to push.\n".encode()

    assert has_secret_match(_unit(("reviewer.md", agent)))


def test_matches_when_bearer_in_binary_file() -> None:
    binary = b"\x00\xff\xfe" + b"Authorization: Bearer " + _bearer_value().encode() + b"\x80\x00"

    assert has_secret_match(_unit(("SKILL.md", b"Body\n"), ("assets/blob.bin", binary)))


def test_no_match_when_marker_already_redacted() -> None:
    text = f"token = {marker('github token')}\nAuthorization: Bearer {marker('bearer token')}\n"

    assert not has_secret_match(_unit(("SKILL.md", text.encode())))


def test_no_match_when_unit_plain_text() -> None:
    assert not has_secret_match(_unit(("SKILL.md", b"---\nname: demo\n---\nRun the tests.\n")))
