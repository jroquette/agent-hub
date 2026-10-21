"""The pure input rules of ``hub mcp``'s ``propose`` tool (spec D-propose-input, D-slug, D-note,
D-pr): the bounds of the caller's title, body and kind, checked before anything else runs.

Every refusal is a ``ToolRefusal`` whose line starts ``propose:`` and never quotes the caller's
text.
"""

import re
import unicodedata
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Final, Literal

from agent_hub.core.brain.brain_path import INBOX_FOLDER, MAX_SLUG_CHARS
from agent_hub.mcp_server.hub_context import ToolRefusal

MAX_TITLE_CHARS: Final = 120
MAX_BODY_BYTES: Final = 65_536
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
_CONTROL: Final = re.compile(r"[\x00-\x1f\x7f-\x9f\u2028\u2029]")
# The marks of AI attribution (hub ``AGENTS.md`` rule 1) a proposal may not carry into its note,
# commit or pull request.
_ATTRIBUTION: Final = re.compile(
    r"co-authored-by\s*:|generated\s+with|generated\s+by\s+claude|\U0001f916", re.IGNORECASE
)
_BACKTICKS: Final = re.compile(r"`+")
_MIN_FENCE: Final = 3
_SLUG_WORD: Final = re.compile(r"[a-z0-9]+")
_PARAGRAPH_BREAK: Final = re.compile(r"\n[ \t]*\n")
_ELLIPSIS: Final = "…"
_NO_SLUG: Final = "propose: the title has no letters or digits for a file name"
_ATTRIBUTED: Final = "propose: the text carries an AI attribution line"


def _is_utf8(text: str) -> bool:
    try:
        text.encode("utf-8")
    except UnicodeEncodeError:
        return False
    return True


def _has_control(text: str) -> bool:
    """A C0/C1 control, a line or paragraph separator, or a format character (``Cf``: bidi
    overrides, zero-width characters)."""
    return bool(_CONTROL.search(text)) or any(unicodedata.category(c) == "Cf" for c in text)


def checked_title(title: str) -> str:
    """``title`` trimmed: 1..``MAX_TITLE_CHARS`` characters of UTF-8 on one line, no control or
    format character, no AI attribution mark, and at least one ``a-z0-9`` run (its slug names
    the note's file and branch)."""
    trimmed = title.strip()
    if not trimmed:
        raise ToolRefusal("propose: the title is empty")
    if not _is_utf8(trimmed):
        raise ToolRefusal("propose: the title is not UTF-8 text")
    if len(trimmed) > MAX_TITLE_CHARS:
        raise ToolRefusal(f"propose: the title is longer than {MAX_TITLE_CHARS} characters")
    if _has_control(trimmed):
        raise ToolRefusal("propose: the title must be one line with no control characters")
    if _ATTRIBUTION.search(trimmed):
        raise ToolRefusal(_ATTRIBUTED)
    if not _SLUG_WORD.search(trimmed.lower()):
        raise ToolRefusal(_NO_SLUG)
    return trimmed


def checked_body(body: str) -> str:
    """``body`` trimmed: 1..``MAX_BODY_BYTES`` bytes of UTF-8 with no AI attribution mark."""
    trimmed = body.strip()
    if not trimmed:
        raise ToolRefusal("propose: the body is empty")
    if not _is_utf8(trimmed):
        raise ToolRefusal("propose: the body is not UTF-8 text")
    if len(trimmed.encode("utf-8")) > MAX_BODY_BYTES:
        raise ToolRefusal(f"propose: the body is larger than {MAX_BODY_BYTES} bytes")
    if _ATTRIBUTION.search(trimmed):
        raise ToolRefusal(_ATTRIBUTED)
    return trimmed


def target_folder(kind: str) -> str:
    """The note's ``target``, ``brain/<folder>/``, for one of the ``KINDS``."""
    for name, folder in KINDS.items():
        if kind == name:
            return f"brain/{folder}/"
    raise ToolRefusal(f"propose: the kind is not one of {', '.join(KINDS)}")


def title_slug(title: str) -> str:
    """The note's and the branch's slug (D-slug): the title lowered, its ``a-z0-9`` runs joined
    by ``-``, cut to ``MAX_SLUG_CHARS`` at a word boundary (a single longer word is cut at the
    limit). A title with no such run is refused."""
    slug = "-".join(_SLUG_WORD.findall(title.lower()))
    if not slug:
        raise ToolRefusal(_NO_SLUG)
    if len(slug) <= MAX_SLUG_CHARS:
        return slug
    head = slug[:MAX_SLUG_CHARS]
    if slug[MAX_SLUG_CHARS] == "-" or "-" not in head:
        return head
    return head.rsplit("-", 1)[0]


def session_id(value: str | None) -> str | None:
    """``value`` when it is a session id ``SESSION_ID`` accepts, else None (left out)."""
    if value is None or SESSION_ID.fullmatch(value) is None:
        return None
    return value


def provenance(*, external: bool) -> str:
    """``agent-from-external`` when the knowledge came from outside the hub, else ``agent``."""
    return "agent-from-external" if external else "agent"


def note_text(
    *,
    title: str,
    body: str,
    kind: str,
    external: bool,
    created: date,
    session: str | None,
) -> str:
    """The inbox note (D-note): a frontmatter of one-line values (only ``title``, as the
    heading, and ``body`` come from the caller, both below it), then ``# <title>``, the body
    and a final newline. ``session`` is the raw ``CLAUDE_CODE_SESSION_ID``; a missing or
    malformed one leaves its line out."""
    lines = [
        "---",
        "type: learning-proposal",
        "status: proposed",
        f"provenance: {provenance(external=external)}",
        f"target: {target_folder(kind)}",
        f"created: {created.isoformat()}",
    ]
    named = session_id(session)
    if named is not None:
        lines.append(f"session: {named}")
    lines.append("---")
    return "\n".join(lines) + f"\n\n# {title}\n\n{body}\n"


def note_path(created: date, slug: str) -> str:
    """The note's path relative to the hub's ``brain/``: ``_inbox/<date>-<slug>.md``."""
    return f"{INBOX_FOLDER}/{created.isoformat()}-{slug}.md"


def proposal_date(now: datetime) -> date:
    """Today's date in UTC (Q-6) for the note's file name and ``created``; ``now`` must carry
    its time zone."""
    if now.tzinfo is None:
        raise ValueError("the clock must give an aware datetime")
    return now.astimezone(UTC).date()


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else f"{text[: limit - 1]}{_ELLIPSIS}"


def pull_request_title(title: str) -> str:
    """``Learning proposal: <title>``, cut to ``MAX_PR_TITLE_CHARS`` with ``…`` (D-pr)."""
    return _cut(f"Learning proposal: {title}", MAX_PR_TITLE_CHARS)


def _fenced(text: str) -> str:
    """``text`` in a Markdown code block whose backtick fence is longer than any backtick run in
    it, so GitHub renders it as written: no @mention notifies, no "Fixes #1" closes an issue."""
    longest = max((len(run) for run in _BACKTICKS.findall(text)), default=0)
    fence = "`" * max(_MIN_FENCE, longest + 1)
    return f"{fence}\n{text}\n{fence}"


def pull_request_body(*, note: str, body: str, external: bool, session: str | None) -> str:
    """The pull request's body (D-pr): which note it adds, its provenance and session, then
    the body's first paragraph cut to ``MAX_PR_QUOTE_CHARS`` in a fenced code block (inert:
    no mention, no closing keyword). ``note`` is relative to ``brain/``; no attribution of any
    kind is added."""
    named = session_id(session)
    origin = provenance(external=external) + ("" if named is None else f", session {named}")
    paragraph = _cut(_PARAGRAPH_BREAK.split(body.strip(), maxsplit=1)[0], MAX_PR_QUOTE_CHARS)
    return f"Adds brain/{note} (provenance {origin}).\n\n{_fenced(paragraph)}\n"


def commit_message(slug: str) -> str:
    """The proposal's commit message, with no trailer: ``docs(brain): propose learning <slug>``."""
    return f"docs(brain): propose learning {slug}"
