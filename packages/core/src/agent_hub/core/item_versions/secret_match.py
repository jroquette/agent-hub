"""The secret gate of a unit (AGH-295, D9, O5): a unit holding a secret match is never stored.

A file matches when any rule of r1 (``agent_hub.core.redaction``) would change its text. Every
file is checked, a binary one too: its bytes are decoded as UTF-8 with replacement characters,
so a token between undecodable bytes still matches. False positives are accepted (D9).
"""

from agent_hub.core.item_versions.unit_content import UnitContent
from agent_hub.core.redaction.redact import redact_text


def has_secret_match(content: UnitContent) -> bool:
    """True when a rule of r1 matches in any file of ``content``."""
    for file in content.files:
        text = file.content.decode("utf-8", "replace")
        if redact_text(text) != text:
            return True
    return False
