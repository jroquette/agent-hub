"""``hub env``: list, show and change the declared environments and services, without a prompt.

The hub is ``AGENT_HUB_ROOT`` or the cwd; ``hub.local.json`` is read from the identity home
(``local_home``). ``list`` and ``show`` print the effective view of both files, or one JSON
object with ``--json`` (names and references only: the files hold no credential value).

``add``, ``set``, ``remove`` and ``service add|remove`` change ``hub.json``, or with ``--local``
``hub.local.json`` (created when absent): core's ``environment_edits`` makes the change, the
result is checked as a read checks it (each file, then the rules across both) before
``env_files`` writes it over the bytes read. A write to ``hub.json`` ends with the sync hint; a
production environment added or set gets its production line. Exit 0 on success, 1 on an
invalid file or a refused change, 2 on a usage error (docs/design/environments.md § ``hub env``).
"""

import os
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final, NamedTuple, cast

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.env_files import document_bytes, is_reformatted, write_document
from agent_hub.cli.hub_config_reader import (
    DISTRIBUTION,
    FILE_LABEL,
    hub_lines,
    load_hub_json_or_exit,
    local_lines,
)
from agent_hub.cli.hub_root import hub_root_or_exit, local_home
from agent_hub.cli.run_children import SESSION_HIDDEN, without
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.effective_environments import (
    EffectiveEnvironments,
    effective_environments,
    local_environment_problems,
)
from agent_hub.core.hub_config.environment_edits import (
    Document,
    EditRefusal,
    add_endpoint,
    add_environment,
    remove_endpoint,
    remove_environment,
    set_environment,
    shown_name,
)
from agent_hub.core.hub_config.local_config import (
    LOCAL_FILE,
    LOCAL_FILE_MAX_BYTES,
    TOO_LARGE_MESSAGE,
    LocalConfig,
    check_local_document,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.json_form import JsonValue, dump_json, load_json_bytes
from agent_hub.core.workspace.environment_lines import (
    environment_json,
    environments_json,
    list_lines,
    production_line,
    show_lines,
)
from agent_hub.generator.hub_config_files import UnreadFile, parse_json, read_file_bytes

COMMAND: Final = "env"
SYNC_HINT: Final = "run ./hub sync to update AGENTS.md"
REFORMAT_LINE: Final = "{file}: rewritten with indent 2"

env_app = typer.Typer(
    name=COMMAND,
    no_args_is_help=True,
    help="List, show and change the declared environments and services.",
)
service_app = typer.Typer(
    name="service", no_args_is_help=True, help="Add or remove a service's endpoint."
)
env_app.add_typer(service_app)

AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]
Name = Annotated[str, typer.Argument(metavar="NAME", help="The environment's name.")]
Local = Annotated[
    bool, typer.Option("--local", help="Change hub.local.json (created when absent), not hub.json.")
]
Description = Annotated[
    str | None, typer.Option("--description", help="At most 80 characters, plain text.")
]
Repo = Annotated[str, typer.Argument(metavar="REPO", help="The repo's dir in hub.json.")]
Service = Annotated[str, typer.Argument(metavar="SERVICE", help="The service's name.")]

# What an edit sees: the document it changes, and the file it is in.
type Edit = Callable[[Document, "_Files"], Document | EditRefusal]


class _Files(NamedTuple):
    """Both files as read: each one's bytes (``None``: no ``hub.local.json``) and config."""

    hub_path: Path
    hub_content: bytes
    config: HubConfig
    local_path: Path
    local_content: bytes | None
    local: LocalConfig


@env_app.command("list")
def list_command(*, as_json: AsJson = False) -> None:
    """List the environments of hub.json and hub.local.json, the services and blocked entries."""
    view = _view()
    if as_json:
        typer.echo(dump_json(environments_json(view)).decode(), nl=False)
        return
    for line in list_lines(view):
        typer.echo(line)


@env_app.command("show")
def show_command(name: Name, *, as_json: AsJson = False) -> None:
    """Show one environment: its access, source, credential names and endpoints."""
    view = _view()
    lines = show_lines(view, name)
    if lines is None:
        fail(f"hub env show: no environment {shown_name(name)} in hub.json or hub.local.json")
    if as_json:
        typer.echo(dump_json(environment_json(view, name)).decode(), nl=False)
        return
    for line in lines:
        typer.echo(line)


def _view() -> EffectiveEnvironments:
    root = hub_root_or_exit(os.environ, command=COMMAND)
    effective = load_effective_config_or_exit(root)
    return effective_environments(effective.config, effective.local)


@env_app.command("add")
def add_command(
    name: Name,
    *,
    access: Annotated[
        str, typer.Option("--access", help="What the agent may do there: read, write or ask.")
    ],
    production: Annotated[
        bool, typer.Option("--production", help="Flag it as a production environment.")
    ] = False,
    description: Description = None,
    aws_profile: Annotated[
        str | None, typer.Option("--aws-profile", help="The AWS profile name to use there.")
    ] = None,
    credential_env: Annotated[
        list[str] | None,
        typer.Option("--credential-env", help="A variable name holding a credential; repeatable."),
    ] = None,
    local: Local = False,
) -> None:
    """Declare a new environment."""
    entry: Document = {"access": access}
    if production:
        entry["production"] = True
    if description is not None:
        entry["description"] = description
    credentials: Document = {}
    if aws_profile is not None:
        credentials["aws_profile"] = aws_profile
    if credential_env:
        credentials["env"] = list(credential_env)
    if credentials:
        entry["credentials"] = credentials

    def edit(document: Document, files: _Files) -> Document | EditRefusal:
        other = files.config.environments if local else files.local.environments
        other_file = FILE_LABEL if local else LOCAL_FILE
        return add_environment(
            document,
            name,
            entry,
            declared=dict.fromkeys(other, other_file),
            file=_file(is_local=local),
        )

    _write(edit, is_local=local, action=f"added environment {name}", environment=name)


@env_app.command("set")
def set_command(
    context: typer.Context,
    name: Name,
    *,
    access: Annotated[
        str | None, typer.Option("--access", help="read, write or ask (--local: only stricter).")
    ] = None,
    production: Annotated[
        bool | None,
        typer.Option("--production/--no-production", help="Set or clear the production flag."),
    ] = None,
    description: Description = None,
    local: Local = False,
) -> None:
    """Change an environment; with --local on a hub.json one, only a stricter access."""
    changes: dict[str, JsonValue | None] = {}
    if access is not None:
        changes["access"] = access
    if production is not None:
        changes["production"] = True if production else None
    if description is not None:
        changes["description"] = description
    if not changes:
        context.fail(
            "nothing to change: give --access, --production/--no-production or --description"
        )

    def edit(document: Document, files: _Files) -> Document | EditRefusal:
        return set_environment(
            document,
            name,
            changes,
            file=_file(is_local=local),
            may_create=local and name in files.config.environments,
        )

    _write(edit, is_local=local, action=f"updated environment {name}", environment=name)


@env_app.command("remove")
def remove_command(name: Name, *, local: Local = False) -> None:
    """Remove an environment no endpoint uses."""

    def edit(document: Document, _files: _Files) -> Document | EditRefusal:
        return remove_environment(document, name, file=_file(is_local=local))

    _write(edit, is_local=local, action=f"removed environment {name}", environment=None)


@service_app.command("add")
def service_add_command(
    context: typer.Context,
    repo: Repo,
    service: Service,
    *,
    environment: Annotated[
        str, typer.Option("--env", metavar="NAME", help="The declared environment.")
    ],
    url: Annotated[
        str | None, typer.Option("--url", help="scheme://host[:port][/path]; no user info.")
    ] = None,
    resource: Annotated[
        str | None, typer.Option("--resource", help="A resource name, such as a table.")
    ] = None,
    kind: Annotated[
        str | None, typer.Option("--kind", help="What the service is: api, dynamodb, ...")
    ] = None,
    note: Annotated[str | None, typer.Option("--note", help="A note on this endpoint.")] = None,
    local: Local = False,
) -> None:
    """Add a service's endpoint in one environment (the service too, when new)."""
    if (url is None) == (resource is None):
        context.fail("give one of --url or --resource")
    endpoint: Document = {"url": url} if url is not None else {"resource": resource}
    if note is not None:
        endpoint["note"] = note

    def edit(document: Document, _files: _Files) -> Document | EditRefusal:
        return add_endpoint(
            document,
            repo=repo,
            service=service,
            environment=environment,
            endpoint=endpoint,
            kind=kind,
            file=_file(is_local=local),
            creates_repo=local,
        )

    _write(
        edit,
        is_local=local,
        action=f"added endpoint {repo} {service} {environment}",
        environment=None,
    )


@service_app.command("remove")
def service_remove_command(
    repo: Repo,
    service: Service,
    *,
    environment: Annotated[
        str | None,
        typer.Option("--env", metavar="NAME", help="Only this environment's endpoint."),
    ] = None,
    local: Local = False,
) -> None:
    """Remove a service, or with --env only its endpoint in that environment."""

    def edit(document: Document, _files: _Files) -> Document | EditRefusal:
        return remove_endpoint(
            document,
            repo=repo,
            service=service,
            environment=environment,
            file=_file(is_local=local),
        )

    removed = (
        f"service {repo} {service}"
        if environment is None
        else f"endpoint {repo} {service} {environment}"
    )
    _write(edit, is_local=local, action=f"removed {removed}", environment=None)


def _file(*, is_local: bool) -> str:
    return LOCAL_FILE if is_local else FILE_LABEL


def _read_files() -> _Files:
    """Both files, each read once as bytes; exit 1 when either is unusable."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    loaded = load_hub_json_or_exit(root / FILE_LABEL)
    # No token reaches git, which only looks for the main checkout.
    home = local_home(root, environ=without(os.environ, SESSION_HIDDEN))
    local_path = home / LOCAL_FILE
    found = read_file_bytes(local_path, max_bytes=LOCAL_FILE_MAX_BYTES)
    content: bytes | None = None
    local = LocalConfig()
    if isinstance(found, UnreadFile):
        if not found.is_missing:
            fail(*local_lines((found.problem,)))
    else:
        content = found
        parsed = parse_json(content)
        checked = (parsed,) if isinstance(parsed, ConfigProblem) else check_local_document(parsed)
        if not isinstance(checked, LocalConfig):
            fail(*local_lines(checked))
        local = checked
    across = local_environment_problems(loaded.config, local)
    if across:
        fail(*local_lines(across))
    return _Files(root / FILE_LABEL, loaded.content, loaded.config, local_path, content, local)


def _write(edit: Edit, *, is_local: bool, action: str, environment: str | None) -> None:
    """Make ``edit`` on one file, check the result, write it, then print what was done."""
    files = _read_files()
    path, content = (
        (files.local_path, files.local_content) if is_local else (files.hub_path, files.hub_content)
    )
    # Both files were checked as JSON objects; an absent hub.local.json is an empty one.
    document = cast("Document", {} if content is None else load_json_bytes(content))
    edited = edit(document, files)
    if isinstance(edited, EditRefusal):
        fail(edited.message)
    config, local = _checked(edited, files, is_local=is_local)
    new_content = document_bytes(edited)
    if is_local and len(new_content) > LOCAL_FILE_MAX_BYTES:
        fail(*local_lines((ConfigProblem(ROOT_PATH, TOO_LARGE_MESSAGE),)))
    refusal = write_document(path, read=content, content=new_content)
    if refusal is not None:
        fail(refusal)
    if content is not None and is_reformatted(content):
        typer.echo(REFORMAT_LINE.format(file=path.name))
    typer.echo(f"{path.name}: {action}")
    _print_production_line(effective_environments(config, local), environment)
    if not is_local:
        typer.echo(SYNC_HINT)


def _print_production_line(view: EffectiveEnvironments, name: str | None) -> None:
    """The production line of the environment added or set, when it is a production one."""
    for item in view.environments:
        if item.name == name and item.production:
            typer.echo(production_line(item.name, item.access, item.source))


def _checked(edited: Document, files: _Files, *, is_local: bool) -> tuple[HubConfig, LocalConfig]:
    """Both configs after the edit, checked as a read checks them; exit 1 with their lines."""
    config, local = files.config, files.local
    if is_local:
        checked_local = check_local_document(edited)
        if not isinstance(checked_local, LocalConfig):
            fail(*local_lines(checked_local))
        local = checked_local
    else:
        checked = check_hub_document(edited, running_version=version(DISTRIBUTION))
        if not isinstance(checked, HubConfig):
            fail(*hub_lines(checked))
        config = checked
    across = local_environment_problems(config, local)
    if across:
        fail(*local_lines(across))
    return config, local
