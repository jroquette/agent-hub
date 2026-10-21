"""The pure input rules of ``hub mcp``'s ``propose`` tool (spec D-propose-input, D-slug, D-note,
D-pr): the bounds of the caller's title, body and kind, checked before anything else runs.

Every refusal is a ``ToolRefusal`` whose line starts ``propose:`` and never quotes the caller's
text.
"""

import re
from collections.abc import Mapping
from typing import Final, Literal

from agent_hub.mcp_server.hub_context import ToolRefusal

MAX_TITLE_CHARS: Final = 120
MAX_BODY_BYTES: Final = 65_536
MAX_SLUG_CHARS: Final = 50
MAX_PR_TITLE_CHARS: Final = 72
MAX_PR_QUOTE_CHARS: Final = 600
# A Claude Code session id as the note may name it; anything else leaves the line out.
SESSION_ID: Final = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
type ProposalKind = Literal["learning", "playbook", "decision", "domain", "system"]
# The kind a caller proposes and the brain folder the note would become part of (Q-1).
KINDS: Final[Mapping[ProposalKind, str]] = {
    "learning": "learnings",
    "playbook": "playbooks",
    "decision": "decisions",
    "domain": "domain",
    "system": "system",
}
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SLUG_WORD: Final = re.compile(r"[a-z0-9]+")


def checked_title(title: str) -> str:
    """``title`` trimmed: 1..``MAX_TITLE_CHARS`` characters on one line, no control character,
    and at least one ``a-z0-9`` run (its slug names the note's file and branch)."""
    trimmed = title.strip()
    if not trimmed:
        raise ToolRefusal("propose: the title is empty")
    if len(trimmed) > MAX_TITLE_CHARS:
        raise ToolRefusal(f"propose: the title is longer than {MAX_TITLE_CHARS} characters")
    if _CONTROL.search(trimmed):
        raise ToolRefusal("propose: the title must be one line with no control characters")
    if not _SLUG_WORD.search(trimmed.lower()):
        raise ToolRefusal("propose: the title has no letters or digits for a file name")
    return trimmed


def checked_body(body: str) -> str:
    """``body`` trimmed: 1..``MAX_BODY_BYTES`` bytes of UTF-8."""
    trimmed = body.strip()
    if not trimmed:
        raise ToolRefusal("propose: the body is empty")
    if len(trimmed.encode("utf-8")) > MAX_BODY_BYTES:
        raise ToolRefusal(f"propose: the body is larger than {MAX_BODY_BYTES} bytes")
    return trimmed


def target_folder(kind: str) -> str:
    """The note's ``target``, ``brain/<folder>/``, for one of the ``KINDS``."""
    for name, folder in KINDS.items():
        if kind == name:
            return f"brain/{folder}/"
    raise ToolRefusal(f"propose: the kind is not one of {', '.join(KINDS)}")
