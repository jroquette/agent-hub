"""What a listed file becomes in the knowledge index (AGH-391, ADR 0044): the pure rules.

A path is hub-relative with ``/`` separators: ``brain/…`` for the hub's brain, ``<dir>/docs/…``
for a repo's docs. Its kind comes from its folder (D-kind); only ``.md`` names outside
``brain/auto/`` are indexed (D-files). The bounds of the untrusted input live here (AM-1), and so
do the reasons a skipped file is reported with (D-skipreport, AM-2).
"""

import hashlib
import re
from typing import Final

from agent_hub.core.brain.brain_path import BRAIN_FOLDER, NOTE_SUFFIX, is_personal_folder
from agent_hub.core.brain.frontmatter import split_frontmatter
from agent_hub.core.item_versions.secret_match import has_secret_match
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.knowledge.knowledge_index import (
    Fingerprint,
    IndexedDocument,
    Kind,
    SkippedFile,
)
from agent_hub.core.readmodels.view_types import ViewModel

# A file larger than this is skipped (D-files): the brain's note bound, 256 KiB.
MAX_DOCUMENT_BYTES: Final = 262_144
# A title, status or provenance is cut to this many characters (D-meta).
MAX_META_CHARS: Final = 200
# At most this many Markdown files are listed per hub, all sources together (AM-1).
MAX_LISTED_FILES: Final = 20_000
# Each source's listing is read up to this many bytes (AM-1).
MAX_LISTING_BYTES: Final = 64 * 1024 * 1024

# Why a listed file is skipped (D-skipreport, AM-2), as reported.
RULE_MATCH: Final = "matches a secret rule"
TOO_LARGE: Final = "larger than 256 KiB"
NOT_UTF8: Final = "not UTF-8"
NOT_REGULAR: Final = "not a regular file"
THROUGH_LINK: Final = "reached through a link"
UNREADABLE: Final = "cannot be read"

# The brain folders that name a kind (D-kind); any other brain file is a ``doc``.
_BRAIN_KINDS: Final[dict[str, Kind]] = {
    "decisions": "decision",
    "domain": "domain",
    "learnings": "learning",
    "playbooks": "playbook",
    "system": "system",
    "_inbox": "inbox",
    "features": "feature",
    "journal": "journal",
}
_BYTE_ORDER_MARK: Final = "\ufeff"
_DOCS_FOLDER: Final = "docs"
_ADR_FOLDER: Final = "adr"
# A file inside a folder of a source: the source's segments, the folder and the file's name.
_IN_BRAIN_FOLDER: Final = 3
_IN_DOCS_FOLDER: Final = 4
# The opening of an ATX heading line: up to three spaces, one to six ``#``, then a blank or the
# line's end. The rest is cut by hand: a pattern for the closing ``#`` run backtracks
# quadratically on a long run of blanks.
_HEADING_OPENING: Final = re.compile(r" {0,3}#{1,6}(?:[ \t]|$)")


def kind_of(path: str) -> Kind:
    """The kind of the document at ``path``, from its folder (D-kind): a brain folder's kind,
    ``adr`` under ``<dir>/docs/adr/``, ``doc`` anywhere else."""
    segments = path.split("/")
    if segments[0] == BRAIN_FOLDER:
        if len(segments) >= _IN_BRAIN_FOLDER:
            return _BRAIN_KINDS.get(segments[1], "doc")
        return "doc"
    if len(segments) >= _IN_DOCS_FOLDER and segments[1:3] == [_DOCS_FOLDER, _ADR_FOLDER]:
        return "adr"
    return "doc"


def is_indexed_name(path: str) -> bool:
    """Whether ``path`` names a file the index looks at: a ``.md`` name outside ``brain/auto/``
    (in any case)."""
    segments = path.split("/")
    name = segments[-1]
    if not name.endswith(NOTE_SUFFIX) or name == NOTE_SUFFIX:
        return False
    in_brain_folder = segments[0] == BRAIN_FOLDER and len(segments) >= _IN_BRAIN_FOLDER
    return not (in_brain_folder and is_personal_folder(segments[1]))


class DocumentMeta(ViewModel):
    """What a note shows besides its text: title, status and provenance, and the body searched."""

    title: str
    status: str | None
    provenance: str | None
    body: str


def document_meta(text: str, name: str) -> DocumentMeta:
    """The title, frontmatter status and provenance, and body of a note named ``name`` (P-3).

    The body is the text after a well-formed leading frontmatter block, else the whole text. The
    title is the first ATX heading of the body, else ``name``; status and provenance are the
    frontmatter's text values. Each is cut to ``MAX_META_CHARS`` characters. One leading byte
    order mark is not part of the text.
    """
    # An editor's leading byte order mark would hide the frontmatter and a first-line heading.
    frontmatter = split_frontmatter(text.removeprefix(_BYTE_ORDER_MARK))
    body = frontmatter.body
    return DocumentMeta(
        title=_first_heading(body) or name[:MAX_META_CHARS],
        status=_text_field(frontmatter.fields.get("status")),
        provenance=_text_field(frontmatter.fields.get("provenance")),
        body=body,
    )


def document_from(
    path: str, data: bytes, fingerprint: Fingerprint
) -> IndexedDocument | SkippedFile:
    """The file at ``path`` as a document to index, or as a skipped file and why: larger than
    ``MAX_DOCUMENT_BYTES``, not UTF-8, or matched by a secret rule of r1 (P-4). A skipped file
    keeps nothing of ``data``."""
    if len(data) > MAX_DOCUMENT_BYTES:
        return SkippedFile(path=path, fingerprint=fingerprint, reason=TOO_LARGE)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return SkippedFile(path=path, fingerprint=fingerprint, reason=NOT_UTF8)
    name = path.rsplit("/", 1)[-1]
    if has_secret_match(UnitContent(files=(UnitFile(path=name, content=data),))):
        return SkippedFile(path=path, fingerprint=fingerprint, reason=RULE_MATCH)
    meta = document_meta(text, name)
    return IndexedDocument(
        path=path,
        kind=kind_of(path),
        title=meta.title,
        status=meta.status,
        provenance=meta.provenance,
        fingerprint=fingerprint,
        sha256=hashlib.sha256(data).hexdigest(),
        body=meta.body,
    )


def _first_heading(body: str) -> str | None:
    for line in body.splitlines():
        if (opening := _HEADING_OPENING.match(line)) is not None and (
            title := _heading_text(line[opening.end() :])
        ):
            return title[:MAX_META_CHARS]
    return None


def _heading_text(rest: str) -> str:
    """A heading's text: ``rest`` without its blanks and its closing run of ``#``."""
    text = rest.strip(" \t")
    unclosed = text.rstrip("#")
    if not unclosed or unclosed[-1] in " \t":
        return unclosed.rstrip(" \t")
    return text


def _text_field(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value[:MAX_META_CHARS]
    return None
