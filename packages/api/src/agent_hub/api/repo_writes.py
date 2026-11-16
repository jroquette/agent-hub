"""``POST /projects/{project}/config/repos``: the Hub config screen's repo edits.

The screen does what ``hub repo`` does (docs/design/project-config.md): add a repo last in
``hub.json``'s ``repos``, change one in place, or remove one no key of ``hub.json`` or this
developer's ``hub.local.json`` names any more. Core's ``repo_edits`` makes the change, so a
refusal is the CLI's, one problem per line at its JSON path (``repos[0].dir``, ``$`` when the
line has no place) with the CLI's text without its ``hub.json: not changed: `` lead. The result
is checked as a read checks it, then ``environment_writes.write_documents`` writes it over the
bytes read; nothing is committed (ADR 0040) and nothing is run (``./hub sync`` is the owner's).

A body's ``dir`` names the repo; ``set_repo`` never changes it (a rename would skip the
reference check a remove makes). Each text is bounded here; the shapes (a ``github`` of two
names, a non-blank ``check``, a safe ``dir``, a timeout of 1 to 160) are the model's, so the
screen gets the same line as the CLI.
"""

from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from agent_hub.api.environment_writes import INVALID_TITLE, HubFiles, write_documents
from agent_hub.core.hub_config.environment_edits import Document
from agent_hub.core.hub_config.repo_edits import (
    REPO_KEY_ORDER,
    Edited,
    add_repo,
    remove_repo,
    set_repo,
)
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.hubs.registered_hub import ValidationProblem
from agent_hub.core.json_form import JsonValue

_MAX_TEXT: Final = 200
_MAX_NAMES: Final = 10

Dir = Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
Text = Annotated[str, Field(max_length=_MAX_TEXT)]
# A JSON integer; its 1..160 bound is the model's.
Timeout = StrictInt


class _RepoEdit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # The repo's dir, next to the hub: the one added, or the one changed or removed.
    dir: Dir


class AddRepo(_RepoEdit):
    """A new repo, last in ``repos``; a key left out is not written."""

    op: Literal["add_repo"]
    github: Text
    check: Text
    check_fast: Text | None = None
    check_fast_timeout: Timeout | None = None
    role: Text | None = None
    default_branch: Text | None = None


class SetRepo(_RepoEdit):
    """A change to a repo: a key left out stays, a key present keeps its place, a new one goes
    last; ``unset`` removes ``role``, ``check_fast``, ``check_fast_timeout`` or
    ``default_branch``."""

    op: Literal["set_repo"]
    github: Text | None = None
    check: Text | None = None
    check_fast: Text | None = None
    check_fast_timeout: Timeout | None = None
    role: Text | None = None
    default_branch: Text | None = None
    # Any text, so a key that cannot be unset gets core's line, as with ``--unset``.
    unset: tuple[Text, ...] = Field(default=(), max_length=_MAX_NAMES)

    @model_validator(mode="after")
    def _changes_something(self) -> Self:
        # The CLI refuses a ``set`` with no option as a usage error: refused before any read.
        if not self.unset and not _given(self):
            raise ValueError(
                "nothing to change: give github, role, check_fast, check_fast_timeout, check,"
                " default_branch or unset"
            )
        return self


class RemoveRepo(_RepoEdit):
    """A repo no other key names any more; its folder and worktrees stay."""

    op: Literal["remove_repo"]


type RepoEdit = Annotated[AddRepo | SetRepo | RemoveRepo, Field(discriminator="op")]


def write_repo_edit(hub_path: str, edit: RepoEdit) -> None:
    """Make ``edit`` on ``hub.json``'s ``repos`` and write it; ``HubInvalidError`` (422) when
    refused or when the result would not be a valid file."""
    files = HubFiles(hub_path)
    edited = _edited(edit, files)
    if isinstance(edited, tuple):
        raise HubInvalidError(
            INVALID_TITLE,
            problems=tuple(
                ValidationProblem(pointer=refusal.path, message=refusal.message)
                for refusal in edited
            ),
        )
    write_documents(files, hub_document=edited, local_document=None)


def _edited(edit: RepoEdit, files: HubFiles) -> Edited:
    document: Document = files.hub_document
    match edit:
        case AddRepo():
            return add_repo(document, {"dir": edit.dir, **_given(edit)})
        case SetRepo():
            return set_repo(document, edit.dir, _given(edit), unset=edit.unset)
        case RemoveRepo():
            # Its references are looked for in hub.local.json too, as the CLI does.
            return remove_repo(document, edit.dir, local_document=files.local_document)


def _given(edit: AddRepo | SetRepo) -> dict[str, JsonValue]:
    """The keys ``edit`` gives, in ``REPO_KEY_ORDER``, never ``dir`` (it names the repo)."""
    fields: dict[str, JsonValue] = {
        "github": edit.github,
        "role": edit.role,
        "check_fast": edit.check_fast,
        "check_fast_timeout": edit.check_fast_timeout,
        "check": edit.check,
        "default_branch": edit.default_branch,
    }
    return {key: fields[key] for key in REPO_KEY_ORDER if fields.get(key) is not None}
