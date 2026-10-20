"""``POST /projects/{project}/config/environments``: the Hub config screen's environment edits.

The screen does what ``hub env`` does (docs/design/environments.md § ``hub env``): add, change or
remove an environment, add or remove a service's endpoint, in the team's ``hub.json`` or in
this developer's ``hub.local.json``. Core's ``environment_edits`` makes the change and the
result is checked as a read checks it (each file, then the rules across both) before anything
is written, so the screen cannot save a file every command would refuse. A file changed since it
was read is refused, never overwritten. Neither file is committed (ADR 0040): a ``hub.json``
change waits for the owner's hub pull request and ``./hub sync``.

The CLI's writer (``agent_hub.cli.env_files``) is not importable from here (ADR 0017: ``cli``
is a composition root of its own), so the write mirrors it and ``local_settings``: the same
document form, a temp file in the same folder, then a rename.
"""

import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Annotated, Final, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agent_hub.core.hub_config.document_check import validation_problems
from agent_hub.core.hub_config.effective_environments import local_environment_problems
from agent_hub.core.hub_config.environment_edits import (
    Document,
    EditRefusal,
    add_endpoint,
    add_environment,
    remove_endpoint,
    remove_environment,
    set_environment,
)
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE,
    LOCAL_FILE_MAX_BYTES,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hubs.hub_registry import HubInvalidError
from agent_hub.core.hubs.registered_hub import ValidationProblem
from agent_hub.core.json_form import JsonValue

HUB_FILE: Final = "hub.json"
INVALID_TITLE: Final = "This change was not saved"
CHANGED_MESSAGE: Final = "{file} changed since the page read it; reload and try again"
_MAX_TEXT = 200
_MAX_NAMES = 10

type Scope = Literal["team", "local"]
type Access = Literal["read", "write", "ask"]
Name = Annotated[str, Field(min_length=1, max_length=_MAX_TEXT)]
Text = Annotated[str, Field(max_length=_MAX_TEXT)]


class _Edit(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    # ``team``: hub.json; ``local``: this developer's hub.local.json.
    scope: Scope


class AddEnvironment(_Edit):
    """A new environment, with its credentials by name only."""

    op: Literal["add_environment"]
    name: Name
    access: Access
    production: bool = False
    description: Text | None = None
    aws_profile: Text | None = None
    credential_env: tuple[Name, ...] = Field(default=(), max_length=_MAX_NAMES)
    env_file: Text | None = None


class SetEnvironment(_Edit):
    """A change to an environment: a field left out stays; an empty text removes the key."""

    op: Literal["set_environment"]
    name: Name
    access: Access | None = None
    production: bool | None = None
    description: Text | None = None
    env_file: Text | None = None


class RemoveEnvironment(_Edit):
    """An environment no endpoint uses any more."""

    op: Literal["remove_environment"]
    name: Name


class AddEndpoint(_Edit):
    """A service's endpoint in one environment; the service is added when new."""

    op: Literal["add_endpoint"]
    repo: Name
    service: Name
    environment: Name
    url: Text | None = None
    resource: Text | None = None
    kind: Text | None = None
    note: Text | None = None


class RemoveEndpoint(_Edit):
    """A service's endpoint in one environment, or the whole service when none is named."""

    op: Literal["remove_endpoint"]
    repo: Name
    service: Name
    environment: Name | None = None


type EnvironmentEdit = Annotated[
    AddEnvironment | SetEnvironment | RemoveEnvironment | AddEndpoint | RemoveEndpoint,
    Field(discriminator="op"),
]


class _Files:
    """Both files as read: each one's bytes (``None``: absent), document and config."""

    def __init__(self, hub_path: str) -> None:
        self.hub_path = Path(hub_path, HUB_FILE)
        self.local_path = Path(hub_path, LOCAL_FILE)
        self.hub_content = _read_bytes(self.hub_path)
        if self.hub_content is None:
            raise _invalid("$", f"{HUB_FILE} is missing")
        self.local_content = _read_bytes(self.local_path)
        self.hub_document = _document(self.hub_content, HUB_FILE)
        self.local_document = (
            {} if self.local_content is None else _document(self.local_content, LOCAL_FILE)
        )
        self.config = _checked_hub(self.hub_document)
        self.local = _checked_local(self.local_document)
        _check_across(self.config, self.local)


def write_environment_edit(hub_path: str, edit: EnvironmentEdit) -> None:
    """Make ``edit`` in the file its scope names; ``HubInvalidError`` (422) when refused."""
    files = _Files(hub_path)
    is_local = edit.scope == "local"
    document = files.local_document if is_local else files.hub_document
    edited = _apply(edit, document, files, is_local=is_local)
    if isinstance(edited, EditRefusal):
        raise _invalid("$", edited.message)
    if is_local:
        local = _checked_local(edited)
        _check_across(files.config, local)
        path, read = files.local_path, files.local_content
    else:
        config = _checked_hub(edited)
        _check_across(config, files.local, prefix=f"{LOCAL_FILE} would no longer be valid: ")
        path, read = files.hub_path, files.hub_content
    content = (json.dumps(edited, indent=2, ensure_ascii=False) + "\n").encode()
    if is_local and len(content) > LOCAL_FILE_MAX_BYTES:
        raise _invalid("$", "the file would be too large")
    if _read_bytes(path) != read:
        raise _invalid("$", CHANGED_MESSAGE.format(file=path.name))
    if is_local and not edited:
        path.unlink(missing_ok=True)
        return
    _replace(path, content)


def _apply(
    edit: EnvironmentEdit, document: Document, files: _Files, *, is_local: bool
) -> Document | EditRefusal:
    file = LOCAL_FILE if is_local else HUB_FILE
    match edit:
        case AddEnvironment():
            return _add_environment(edit, document, files, file=file, is_local=is_local)
        case SetEnvironment():
            return _set_environment(edit, document, files, file=file, is_local=is_local)
        case RemoveEnvironment():
            return _remove_environment(edit, document, files, file=file, is_local=is_local)
        case AddEndpoint():
            return _add_endpoint(edit, document, files, file=file, is_local=is_local)
        case RemoveEndpoint():
            return remove_endpoint(
                document,
                repo=edit.repo,
                service=edit.service,
                environment=edit.environment,
                file=file,
            )


def _add_environment(
    edit: AddEnvironment, document: Document, files: _Files, *, file: str, is_local: bool
) -> Document | EditRefusal:
    entry: Document = {"access": edit.access}
    if edit.production:
        entry["production"] = True
    if edit.description and edit.description.strip():
        entry["description"] = edit.description.strip()
    credentials = _credentials(edit)
    if credentials:
        entry["credentials"] = credentials
    other = files.config.environments if is_local else files.local.environments
    return add_environment(
        document,
        edit.name.strip(),
        entry,
        declared=dict.fromkeys(other, HUB_FILE if is_local else LOCAL_FILE),
        file=file,
    )


def _credentials(edit: AddEnvironment) -> Document:
    """The new environment's credentials: names and a path, never a value."""
    credentials: Document = {}
    if edit.aws_profile and edit.aws_profile.strip():
        credentials["aws_profile"] = edit.aws_profile.strip()
    names = list(dict.fromkeys(name.strip() for name in edit.credential_env if name.strip()))
    if names:
        credentials["env"] = cast("JsonValue", names)
    if edit.env_file and edit.env_file.strip():
        credentials["env_file"] = edit.env_file.strip()
    return credentials


def _set_environment(
    edit: SetEnvironment, document: Document, files: _Files, *, file: str, is_local: bool
) -> Document | EditRefusal:
    changes: dict[str, JsonValue | None] = {}
    if edit.access is not None:
        changes["access"] = edit.access
    if edit.production is not None:
        changes["production"] = True if edit.production else None
    if edit.description is not None:
        changes["description"] = edit.description.strip() or None
    credentials: dict[str, JsonValue | None] = {}
    if edit.env_file is not None:
        credentials["env_file"] = edit.env_file.strip() or None
    return set_environment(
        document,
        edit.name,
        changes,
        file=file,
        may_create=is_local and edit.name in files.config.environments,
        credentials=credentials,
    )


def _remove_environment(
    edit: RemoveEnvironment, document: Document, files: _Files, *, file: str, is_local: bool
) -> Document | EditRefusal:
    edited = remove_environment(document, edit.name, file=file)
    if (
        not isinstance(edited, EditRefusal)
        and not is_local
        and edit.name in files.local.environments
    ):
        # Removed from hub.json, the local tightening would become an environment of its own.
        return EditRefusal(f"{LOCAL_FILE} still holds {edit.name}; remove your own setting first")
    return edited


def _add_endpoint(
    edit: AddEndpoint, document: Document, files: _Files, *, file: str, is_local: bool
) -> Document | EditRefusal:
    url = (edit.url or "").strip()
    resource = (edit.resource or "").strip()
    if bool(url) == bool(resource):
        return EditRefusal("give either a URL or a resource name")
    endpoint: Document = {"url": url} if url else {"resource": resource}
    if edit.note and edit.note.strip():
        endpoint["note"] = edit.note.strip()
    return add_endpoint(
        document,
        repo=edit.repo,
        service=edit.service.strip(),
        environment=edit.environment,
        endpoint=endpoint,
        kind=(edit.kind or "").strip() or None,
        file=file,
        creates_repo=is_local,
        known_repos=[repo.dir for repo in files.config.repos],
    )


def _checked_hub(document: Document) -> HubConfig:
    # The model alone, as the server reads a registered hub: its pin may name another release.
    try:
        return HubConfig.model_validate(copy.deepcopy(document))
    except ValidationError as error:
        raise _problems(validation_problems(error, document), prefix=f"{HUB_FILE}: ") from error


def _checked_local(document: Document) -> LocalConfig:
    checked = check_local_document(copy.deepcopy(document))
    if not isinstance(checked, LocalConfig):
        raise _problems(checked, prefix=f"{LOCAL_FILE}: ")
    return checked


def _check_across(config: HubConfig, local: LocalConfig, *, prefix: str = "") -> None:
    across = local_environment_problems(config, local)
    if across:
        raise _problems(across, prefix=prefix or f"{LOCAL_FILE}: ")


def _problems(problems: tuple[ConfigProblem, ...], *, prefix: str) -> HubInvalidError:
    return HubInvalidError(
        INVALID_TITLE,
        problems=tuple(
            ValidationProblem(pointer=problem.path, message=f"{prefix}{problem.message}")
            for problem in problems
        ),
    )


def _invalid(pointer: str, message: str) -> HubInvalidError:
    return HubInvalidError(
        INVALID_TITLE, problems=(ValidationProblem(pointer=pointer, message=message),)
    )


def _read_bytes(path: Path) -> bytes | None:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _document(content: bytes, file: str) -> Document:
    try:
        document = json.loads(content)
    except ValueError as error:
        raise _invalid("$", f"{file} is not valid JSON; fix it first") from error
    if not isinstance(document, dict):
        raise _invalid("$", f"{file} must be a JSON object")
    return cast("Document", document)


def _replace(path: Path, content: bytes) -> None:
    """Write next to the file at its mode, then rename over it: a reader never sees half."""
    if path.is_symlink():
        raise _invalid("$", f"{path.name} is a symlink; edit its target")
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    handle, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
