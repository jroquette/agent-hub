"""``POST /projects/{project}/config/environments``: the Hub config screen's environment edits.

The screen does what ``hub env`` does (docs/design/environments.md § ``hub env``): add, change,
rename or remove an environment (its ``values``, which fill scenario inputs, included), add,
change, rename or remove a service and its endpoints, in the team's ``hub.json`` or in this
developer's ``hub.local.json``, where values on a ``hub.json`` environment win per key.
Core's ``environment_edits`` makes the change and the result is checked as a read checks it
(each file, then the rules across both) before anything is written, so the screen cannot save a
file every command would refuse. A file changed since it was read is refused, never
overwritten. Neither file is committed (ADR 0040): a ``hub.json`` change waits for the owner's
hub pull request and ``./hub sync``.

A ``batch`` makes its edits in order on both documents in memory, each in its own scope's file,
then checks the results once and writes both files or neither; a refused edit is named by its
place (``op 2: ...``). A single edit is a batch of one.

A team rename (an environment, or a service) also renames the old name in this developer's
``hub.local.json`` in the same write when it holds it (a tightening, or a service's endpoints),
so the local file keeps meaning what it did. Other developers' local files are not touched:
their tightening or endpoints under the old name stop applying until they rename them too.

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
    environment_names,
    remove_endpoint,
    remove_environment,
    rename_environment,
    repo_dirs,
    service_names,
    set_environment,
    set_service,
    shown_name,
)
from agent_hub.core.hub_config.environments import MAX_VALUES, ValueName
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
_MAX_BATCH = 100

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
    # Scenario input values by input name; an empty text is left out.
    values: dict[ValueName, Text] = Field(default_factory=dict, max_length=MAX_VALUES)


class SetEnvironment(_Edit):
    """A change to an environment: a field left out stays; an empty text removes the key.

    On a ``hub.json`` environment, the ``local`` scope may change only ``access`` (stricter)
    and ``values`` (the developer's, which win per key over the team's).
    """

    op: Literal["set_environment"]
    name: Name
    access: Access | None = None
    production: bool | None = None
    description: Text | None = None
    env_file: Text | None = None
    aws_profile: Text | None = None
    # Replaces ``credentials.env``; an empty list removes it.
    credential_env: tuple[Name, ...] | None = Field(default=None, max_length=_MAX_NAMES)
    # Sets each value named; an empty text removes that value. A value not named stays.
    values: dict[ValueName, Text] | None = Field(default=None, max_length=MAX_VALUES)


class RenameEnvironment(_Edit):
    """A new name for an environment; its endpoints in the same file follow it."""

    op: Literal["rename_environment"]
    name: Name
    new_name: Name


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
    # Replace the endpoint this service has in that environment (an edit), in the same write.
    replace: bool = False


class RemoveEndpoint(_Edit):
    """A service's endpoint in one environment, or the whole service when none is named."""

    op: Literal["remove_endpoint"]
    repo: Name
    service: Name
    environment: Name | None = None


class SetService(_Edit):
    """A change to a service: a field left out stays; an empty text removes the key."""

    op: Literal["set_service"]
    repo: Name
    service: Name
    kind: Text | None = None
    description: Text | None = None
    new_name: Name | None = None


class ServiceAddress(BaseModel):
    """Where a service is reached in one environment: a URL (holds ``://``) or a resource name."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    environment: Name
    address: Name
    note: Text | None = None


class AddService(BaseModel):
    """A new service of a repo with its address in one or more environments, in one step.

    Each address goes to the file of its environment: a team environment's to ``hub.json``, the
    developer's own to ``hub.local.json``; both files are checked before either is written.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["add_service"]
    repo: Name
    service: Name
    kind: Text | None = None
    description: Text | None = None
    addresses: tuple[ServiceAddress, ...] = Field(min_length=1, max_length=50)


type SingleEdit = Annotated[
    AddEnvironment
    | SetEnvironment
    | RenameEnvironment
    | RemoveEnvironment
    | AddEndpoint
    | RemoveEndpoint
    | AddService
    | SetService,
    Field(discriminator="op"),
]


class EditBatch(BaseModel):
    """Edits made in order and written together: both files or neither."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    op: Literal["batch"]
    ops: tuple[SingleEdit, ...] = Field(min_length=1, max_length=_MAX_BATCH)


type EnvironmentEdit = Annotated[
    AddEnvironment
    | SetEnvironment
    | RenameEnvironment
    | RemoveEnvironment
    | AddEndpoint
    | RemoveEndpoint
    | AddService
    | SetService
    | EditBatch,
    Field(discriminator="op"),
]


class HubFiles:
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


class _Documents:
    """Both documents as the edits so far left them, and whether each was changed."""

    def __init__(self, files: HubFiles) -> None:
        self.hub: Document = files.hub_document
        self.local: Document = files.local_document
        self.hub_changed = False
        self.local_changed = False

    def get(self, *, is_local: bool) -> Document:
        return self.local if is_local else self.hub

    def other(self, *, is_local: bool) -> Document:
        return self.hub if is_local else self.local

    def put(self, document: Document, *, is_local: bool) -> None:
        if is_local:
            self.local, self.local_changed = document, True
        else:
            self.hub, self.hub_changed = document, True


def write_environment_edit(hub_path: str, edit: EnvironmentEdit) -> None:
    """Make ``edit`` in the file its scope names (an ``AddService``: in the file of each
    address's environment; an ``EditBatch``: each of its edits in turn, written together);
    ``HubInvalidError`` (422) when refused."""
    files = HubFiles(hub_path)
    documents = _Documents(files)
    ops = edit.ops if isinstance(edit, EditBatch) else (edit,)
    for index, op in enumerate(ops):
        refusal = _apply(op, documents)
        if refusal is not None:
            lead = f"op {index + 1}: " if isinstance(edit, EditBatch) else ""
            raise _invalid("$", f"{lead}{refusal.message}")
    write_documents(
        files,
        hub_document=documents.hub if documents.hub_changed else None,
        local_document=documents.local if documents.local_changed else None,
    )


def write_documents(
    files: HubFiles, *, hub_document: Document | None, local_document: Document | None
) -> None:
    """Check the changed documents as a read checks them, then write them, ``hub.json`` first.

    Nothing is written unless both are valid and neither file changed since it was read.
    """
    config = files.config if hub_document is None else _checked_hub(hub_document)
    local = files.local if local_document is None else _checked_local(local_document)
    only_hub = local_document is None
    _check_across(
        config, local, lead=f"{LOCAL_FILE} would no longer be valid: " if only_hub else ""
    )
    writes: list[tuple[Path, bytes | None, Document]] = []
    if hub_document is not None:
        writes.append((files.hub_path, files.hub_content, hub_document))
    if local_document is not None:
        writes.append((files.local_path, files.local_content, local_document))
    contents = []
    for path, read, document in writes:
        content = (json.dumps(document, indent=2, ensure_ascii=False) + "\n").encode()
        if path == files.local_path and len(content) > LOCAL_FILE_MAX_BYTES:
            raise _invalid("$", "the file would be too large")
        if _read_bytes(path) != read:
            raise _invalid("$", CHANGED_MESSAGE.format(file=path.name))
        contents.append((path, document, content))
    for path, document, content in contents:
        if path == files.local_path and not document:
            path.unlink(missing_ok=True)
        else:
            _replace(path, content)


def _apply(edit: SingleEdit, documents: _Documents) -> EditRefusal | None:
    """Make ``edit`` on ``documents``; the refusal when it is refused, else ``None``."""
    if isinstance(edit, AddService):
        return _add_service(edit, documents)
    is_local = edit.scope == "local"
    if isinstance(edit, RenameEnvironment):
        return _rename_environment(edit, documents, is_local=is_local)
    if isinstance(edit, SetService):
        return _set_service(edit, documents, is_local=is_local)
    edited = _edited(edit, documents, is_local=is_local)
    if isinstance(edited, EditRefusal):
        return edited
    documents.put(edited, is_local=is_local)
    return None


def _edited(
    edit: AddEnvironment | SetEnvironment | RemoveEnvironment | AddEndpoint | RemoveEndpoint,
    documents: _Documents,
    *,
    is_local: bool,
) -> Document | EditRefusal:
    document = documents.get(is_local=is_local)
    file = LOCAL_FILE if is_local else HUB_FILE
    match edit:
        case AddEnvironment():
            return _add_environment(edit, documents, file=file, is_local=is_local)
        case SetEnvironment():
            return _set_environment(edit, documents, file=file, is_local=is_local)
        case RemoveEnvironment():
            return _remove_environment(edit, documents, file=file, is_local=is_local)
        case AddEndpoint():
            return _add_endpoint(edit, documents, file=file, is_local=is_local)
        case RemoveEndpoint():
            return remove_endpoint(
                document,
                repo=edit.repo,
                service=edit.service,
                environment=edit.environment,
                file=file,
            )


def _add_service(edit: AddService, documents: _Documents) -> EditRefusal | None:
    """The service's addresses, each in its environment's file."""
    service = edit.service.strip()
    kind = (edit.kind or "").strip() or None
    description = (edit.description or "").strip() or None
    team_environments = environment_names(documents.hub)
    team = [item for item in edit.addresses if item.environment in team_environments]
    own = [item for item in edit.addresses if item not in team]
    local_environments = environment_names(documents.local)
    for item in own:
        if item.environment not in local_environments:
            return EditRefusal(f"no environment {shown_name(item.environment)}")
    committed = service in service_names(documents.hub, edit.repo)
    # The kind and description go with the service's first declaration: hub.json's when it gets
    # an address.
    team_first = not committed
    own_first = not committed and not team
    for items, is_local, first in ((team, False, team_first), (own, True, own_first)):
        edited = documents.get(is_local=is_local)
        for item in items:
            result = add_endpoint(
                edited,
                repo=edit.repo,
                service=service,
                environment=item.environment,
                endpoint=_endpoint(item),
                kind=kind if first else None,
                description=description if first else None,
                file=LOCAL_FILE if is_local else HUB_FILE,
                creates_repo=is_local,
                known_repos=repo_dirs(documents.hub),
            )
            if isinstance(result, EditRefusal):
                return result
            edited = result
        if items:
            documents.put(edited, is_local=is_local)
    return None


def _endpoint(item: ServiceAddress) -> Document:
    address = item.address.strip()
    endpoint: Document = {"url": address} if "://" in address else {"resource": address}
    if item.note and item.note.strip():
        endpoint["note"] = item.note.strip()
    return endpoint


def _add_environment(
    edit: AddEnvironment, documents: _Documents, *, file: str, is_local: bool
) -> Document | EditRefusal:
    entry: Document = {"access": edit.access}
    if edit.production:
        entry["production"] = True
    if edit.description and edit.description.strip():
        entry["description"] = edit.description.strip()
    credentials = _credentials(edit)
    if credentials:
        entry["credentials"] = credentials
    values: Document = {key: text.strip() for key, text in edit.values.items() if text.strip()}
    if values:
        entry["values"] = values
    other = environment_names(documents.other(is_local=is_local))
    return add_environment(
        documents.get(is_local=is_local),
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
    edit: SetEnvironment, documents: _Documents, *, file: str, is_local: bool
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
    if edit.aws_profile is not None:
        credentials["aws_profile"] = edit.aws_profile.strip() or None
    if edit.credential_env is not None:
        names = list(dict.fromkeys(name.strip() for name in edit.credential_env if name.strip()))
        credentials["env"] = cast("JsonValue", names) or None
    tightens = is_local and edit.name in environment_names(documents.hub)
    if tightens and (set(changes) - {"access"} or credentials):
        return EditRefusal(
            f"{HUB_FILE} declares {shown_name(edit.name)};"
            f" {LOCAL_FILE} may only tighten its access or set values"
        )
    values: dict[str, JsonValue | None] = {
        key: text.strip() or None for key, text in (edit.values or {}).items()
    }
    return set_environment(
        documents.get(is_local=is_local),
        edit.name,
        changes,
        file=file,
        may_create=tightens,
        credentials=credentials,
        values=values,
    )


def _rename_environment(
    edit: RenameEnvironment, documents: _Documents, *, is_local: bool
) -> EditRefusal | None:
    """Rename in the edit's file; a team rename also renames this developer's tightening (and
    any endpoint under the old name) in ``hub.local.json``."""
    new_name = edit.new_name.strip()
    team_names = environment_names(documents.hub)
    if is_local and edit.name in team_names:
        return EditRefusal(f"{HUB_FILE} declares {edit.name}; rename it there")
    other = environment_names(documents.other(is_local=is_local))
    if not is_local:
        # This developer's tightening of the old name is renamed with it, so it is no other name.
        other = [name for name in other if name != edit.name]
    edited = rename_environment(
        documents.get(is_local=is_local),
        edit.name,
        new_name,
        declared=other,
        file=LOCAL_FILE if is_local else HUB_FILE,
    )
    if isinstance(edited, EditRefusal):
        return edited
    if not is_local and edit.name in environment_names(documents.local):
        local = rename_environment(
            documents.local, edit.name, new_name, declared=(), file=LOCAL_FILE
        )
        if isinstance(local, EditRefusal):
            return local
        documents.put(local, is_local=True)
    documents.put(edited, is_local=is_local)
    return None


def _remove_environment(
    edit: RemoveEnvironment, documents: _Documents, *, file: str, is_local: bool
) -> Document | EditRefusal:
    edited = remove_environment(documents.get(is_local=is_local), edit.name, file=file)
    if (
        not isinstance(edited, EditRefusal)
        and not is_local
        and edit.name in environment_names(documents.local)
    ):
        # Removed from hub.json, the local tightening would become an environment of its own.
        return EditRefusal(f"{LOCAL_FILE} still holds {edit.name}; remove your own setting first")
    return edited


def _set_service(edit: SetService, documents: _Documents, *, is_local: bool) -> EditRefusal | None:
    """Change the service in the edit's file; a team rename also renames this developer's
    endpoints for it in ``hub.local.json``."""
    service = edit.service
    new_name = None if edit.new_name is None else edit.new_name.strip()
    changes: dict[str, JsonValue | None] = {}
    if edit.kind is not None:
        changes["kind"] = edit.kind.strip() or None
    if edit.description is not None:
        changes["description"] = edit.description.strip() or None
    committed = service in service_names(documents.hub, edit.repo)
    if is_local and committed and (changes or new_name is not None):
        return EditRefusal(
            f"{HUB_FILE} declares {shown_name(service)}; {LOCAL_FILE} may only add its endpoints"
        )
    other = service_names(documents.other(is_local=is_local), edit.repo)
    renames_local = not is_local and new_name is not None and service in other
    edited = set_service(
        documents.get(is_local=is_local),
        repo=edit.repo,
        service=service,
        changes=changes,
        new_name=new_name,
        taken=[name for name in other if name != service],
        file=LOCAL_FILE if is_local else HUB_FILE,
    )
    if isinstance(edited, EditRefusal):
        return edited
    if renames_local:
        local = set_service(
            documents.local,
            repo=edit.repo,
            service=service,
            changes={},
            new_name=new_name,
            taken=(),
            file=LOCAL_FILE,
        )
        if isinstance(local, EditRefusal):
            return local
        documents.put(local, is_local=True)
    documents.put(edited, is_local=is_local)
    return None


def _add_endpoint(
    edit: AddEndpoint, documents: _Documents, *, file: str, is_local: bool
) -> Document | EditRefusal:
    url = (edit.url or "").strip()
    resource = (edit.resource or "").strip()
    if bool(url) == bool(resource):
        return EditRefusal("give either a URL or a resource name")
    endpoint: Document = {"url": url} if url else {"resource": resource}
    if edit.note and edit.note.strip():
        endpoint["note"] = edit.note.strip()
    document = documents.get(is_local=is_local)
    if edit.replace:
        removed = remove_endpoint(
            document,
            repo=edit.repo,
            service=edit.service.strip(),
            environment=edit.environment,
            file=file,
        )
        if isinstance(removed, EditRefusal):
            return removed
        document = removed
    return add_endpoint(
        document,
        repo=edit.repo,
        service=edit.service.strip(),
        environment=edit.environment,
        endpoint=endpoint,
        kind=(edit.kind or "").strip() or None,
        file=file,
        creates_repo=is_local,
        known_repos=repo_dirs(documents.hub),
    )


def _checked_hub(document: Document) -> HubConfig:
    # The model alone, as the server reads a registered hub: its pin may name another release.
    try:
        return HubConfig.model_validate(copy.deepcopy(document))
    except ValidationError as error:
        raise _problems(validation_problems(error, document), lead=f"{HUB_FILE}: ") from error


def _checked_local(document: Document) -> LocalConfig:
    checked = check_local_document(copy.deepcopy(document))
    if not isinstance(checked, LocalConfig):
        raise _problems(checked, lead=f"{LOCAL_FILE}: ")
    return checked


def _check_across(config: HubConfig, local: LocalConfig, *, lead: str = "") -> None:
    across = local_environment_problems(config, local)
    if across:
        raise _problems(across, lead=lead or f"{LOCAL_FILE}: ")


def _problems(problems: tuple[ConfigProblem, ...], *, lead: str) -> HubInvalidError:
    return HubInvalidError(
        INVALID_TITLE,
        problems=tuple(
            ValidationProblem(pointer=problem.path, message=f"{lead}{problem.message}")
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
