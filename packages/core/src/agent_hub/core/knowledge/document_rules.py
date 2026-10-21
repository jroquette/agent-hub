"""What a listed file becomes in the knowledge index (AGH-391, ADR 0044): the pure rules.

A path is hub-relative with ``/`` separators: ``brain/…`` for the hub's brain, ``<dir>/docs/…``
for a repo's docs. Its kind comes from its folder (D-kind); only ``.md`` names outside
``brain/auto/`` are indexed (D-files). The bounds of the untrusted input live here (AM-1), and so
do the reasons a skipped file is reported with (D-skipreport, AM-2).
"""

from typing import Final

from agent_hub.core.brain.brain_path import BRAIN_FOLDER, NOTE_SUFFIX, is_personal_folder
from agent_hub.core.knowledge.knowledge_index import Kind

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
_DOCS_FOLDER: Final = "docs"
_ADR_FOLDER: Final = "adr"
# A file inside a folder of a source: the source's segments, the folder and the file's name.
_IN_BRAIN_FOLDER: Final = 3
_IN_DOCS_FOLDER: Final = 4


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
