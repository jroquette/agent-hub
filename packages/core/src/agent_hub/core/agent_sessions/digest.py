"""A session's glimpse for the Sessions list: its last prompt, its last reply, the files changed.

Pure. ``SessionDigest`` folds stored (redacted) records in ``seq`` order: the latest
``user.message`` (``by: web``) is the prompt, the latest assistant ``text`` (``by: driver``) the
reply (``thinking`` never counts), and each ``tool.call`` of a file tool names the file it
changes. The files follow the web chat's ``changedFiles()`` (``model.ts``): the path is the
input's ``file_path``, else its ``notebook_path``; every call counts, subagents' included,
denied or failed ones too; a file's ``last_change_id`` is the ``tool_use_id`` of its latest
change, so the chat's review marks (``{path: lastChangeId}``) line up with the list's.

Snippets are redacted (again: the stored text already is), cut to one line of whitespace
collapsed to single spaces, and clipped to 280 characters after redaction; the reply also drops
light markdown marks (heading ``#``, list bullets, quote ``>``, ``*``/``_`` emphasis, backticks).
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Final

from agent_hub.core.agent_sessions.agent_session import (
    MAX_CHANGED_FILES,
    MAX_SNIPPET_CHARS,
    AgentSession,
    ChangedFile,
)
from agent_hub.core.agent_sessions.records import LogRecord, RecordKind
from agent_hub.core.agent_sessions.store import AgentSessionFields
from agent_hub.core.redaction.redact import clip, redact_text

# The tools whose calls change a file, as the web chat counts them.
FILE_TOOLS: Final = frozenset({"Edit", "MultiEdit", "Write", "NotebookEdit"})
# The record kinds a digest reads (a backfill asks the store for these only).
DIGEST_KINDS: Final[frozenset[RecordKind]] = frozenset({"user.message", "text", "tool.call"})

_WHITESPACE: Final = re.compile(r"\s+")
# At a line's start: a heading's hashes, a quote's ``>``, a list bullet or number.
_LINE_MARKS: Final = re.compile(
    r"^[ \t]*(?:#{1,6}[ \t]+|>[ \t]?|[-*+][ \t]+|\d{1,9}[.)][ \t]+)+", re.M
)
# Emphasis around text: ``**x**``, ``__x__``, ``*x*``, ``_x_`` (an underscore inside a word, as
# in ``snake_case``, is no mark).
_STRONG: Final = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_STAR: Final = re.compile(r"\*(?=\S)([^*]+?)(?<=\S)\*")
_UNDERSCORE: Final = re.compile(r"(?<!\w)_(?=\S)([^_]+?)(?<=\S)_(?!\w)")


def _one_line(text: str) -> str | None:
    line = _WHITESPACE.sub(" ", text).strip()
    return clip(redact_text(line), MAX_SNIPPET_CHARS) if line else None


def prompt_snippet(text: str) -> str | None:
    """A prompt as the list shows it: redacted, one line, at most 280 characters; None when
    it holds no text."""
    return _one_line(redact_text(text))


def reply_snippet(text: str) -> str | None:
    """A reply as the list shows it: ``prompt_snippet`` of the markdown without its marks."""
    plain = _LINE_MARKS.sub("", redact_text(text))
    plain = _STRONG.sub(r"\2", plain)
    plain = _STAR.sub(r"\1", plain)
    plain = _UNDERSCORE.sub(r"\1", plain).replace("`", "")
    return _one_line(plain)


def _changed_path(record: LogRecord) -> tuple[str, str] | None:
    """``(path, tool_use_id)`` of a file tool's call, else None."""
    body = record.body
    if body.get("name") not in FILE_TOOLS:
        return None
    tool_input = body.get("input")
    if not isinstance(tool_input, dict):
        return None
    path = tool_input.get("file_path")
    if not isinstance(path, str):
        path = tool_input.get("notebook_path")
    if not isinstance(path, str):
        return None
    tool_use_id = body.get("tool_use_id")
    return path, tool_use_id if isinstance(tool_use_id, str) else ""


@dataclass(eq=False)
class SessionDigest:
    """The glimpse of one session, folded record by record (see the module docstring).

    ``files`` maps each path to its latest change's id, the least recently changed first.
    ``version`` counts the changes, so a store write records which ones it saved
    (``pending`` / ``saved``).
    """

    last_prompt: str | None = None
    last_reply: str | None = None
    files: dict[str, str] = field(default_factory=dict)
    version: int = 0
    _saved: int = 0

    @classmethod
    def of(cls, session: AgentSession) -> SessionDigest:
        """The digest a stored session holds, nothing pending."""
        files = {item.path: item.last_change_id for item in reversed(session.changed_files)}
        return cls(last_prompt=session.last_prompt, last_reply=session.last_reply, files=files)

    @classmethod
    def of_records(cls, records: Iterable[LogRecord]) -> SessionDigest:
        """The digest of a log read from its start, in ``seq`` order."""
        digest = cls()
        for record in records:
            digest.add(record)
        return digest

    @property
    def empty(self) -> bool:
        """Whether nothing was prompted, replied or changed."""
        return self.last_prompt is None and self.last_reply is None and not self.files

    def add(self, record: LogRecord) -> None:
        """Fold one stored record in."""
        if record.kind == "user.message" and record.by == "web":
            self._set_prompt(record.body.get("text"))
        elif record.kind == "text" and record.by == "driver":
            self._set_reply(record.body.get("text"))
        elif record.kind == "tool.call":
            changed = _changed_path(record)
            if changed is not None:
                self._set_file(*changed)

    def _set_prompt(self, text: object) -> None:
        snippet = prompt_snippet(text) if isinstance(text, str) else None
        if snippet is not None and snippet != self.last_prompt:
            self.last_prompt = snippet
            self.version += 1

    def _set_reply(self, text: object) -> None:
        snippet = reply_snippet(text) if isinstance(text, str) else None
        if snippet is not None and snippet != self.last_reply:
            self.last_reply = snippet
            self.version += 1

    def _set_file(self, path: str, tool_use_id: str) -> None:
        if self.files.get(path) == tool_use_id:
            return  # the same call again: the chat keeps it where it was
        self.files.pop(path, None)
        self.files[path] = tool_use_id
        while len(self.files) > MAX_CHANGED_FILES:
            del self.files[next(iter(self.files))]
        self.version += 1

    def changed_files(self) -> tuple[ChangedFile, ...]:
        """The files, latest change first."""
        return tuple(
            ChangedFile(path=path, last_change_id=tool_use_id)
            for path, tool_use_id in reversed(self.files.items())
        )

    def fields(self) -> AgentSessionFields:
        """The session fields that hold the digest."""
        return {
            "last_prompt": self.last_prompt,
            "last_reply": self.last_reply,
            "changed_files": self.changed_files(),
        }

    def pending(self) -> tuple[AgentSessionFields, int]:
        """The fields to store (empty when nothing changed since the last save) and the
        version they hold, for ``saved``."""
        return (self.fields() if self.version != self._saved else {}), self.version

    def saved(self, version: int) -> None:
        """The fields of ``version`` are stored."""
        self._saved = max(self._saved, version)
