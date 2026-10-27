"""``hub repo``: list a hub's repos, and add, change or remove one, without a prompt.

The hub is ``AGENT_HUB_ROOT`` or the cwd. ``list`` reads ``hub.json`` only and prints one line
per repo: its dir, github, role, check_fast (``-`` when absent), check and effective default
branch, separated by tabs; or one JSON object with ``--json``.

``add``, ``set`` and ``remove`` change ``hub.json``'s ``repos``: core's ``repo_edits`` makes the
change, the result is checked as a read checks it (``hub.json``, then the rules across it and
the developer's ``hub.local.json``) before ``env_files`` writes it over the bytes read. Then the
command names what to run next; it runs nothing itself. Exit 0 on success, 1 on an invalid file
or a refused change (the files unchanged), 2 on a usage error (docs/design/project-config.md).
"""

import os
from collections.abc import Callable, Sequence
from typing import Annotated, Final, cast

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.env_files import document_bytes, is_reformatted, write_document
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_json_or_exit
from agent_hub.cli.hub_edit_files import HubFiles, checked_documents, read_hub_files
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.hub_config.environment_edits import Document, shown_name
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.repo_edits import Edited, add_repo, remove_repo, set_repo
from agent_hub.core.json_form import JsonValue, dump_json, load_json_bytes

COMMAND: Final = "repo"
ABSENT: Final = "-"
REFUSED: Final = f"{FILE_LABEL}: not changed: "
REFORMAT_LINE: Final = f"{FILE_LABEL}: rewritten with indent 2"
SYNC_LINE: Final = "run ./hub sync to update AGENTS.md and .claude/settings.json"

repo_app = typer.Typer(
    name=COMMAND, no_args_is_help=True, help="List, add, change and remove the hub's repos."
)

AsJson = Annotated[bool, typer.Option("--json", help="Print one JSON object instead of lines.")]
Dir = Annotated[str, typer.Argument(metavar="DIR", help="The repo's dir, next to the hub.")]
Role = Annotated[str | None, typer.Option("--role", help="What the repo is: app, web, ...")]
CheckFast = Annotated[
    str | None, typer.Option("--check-fast", help="The fast gate the Stop hook runs.")
]
CheckFastTimeout = Annotated[
    int | None,
    typer.Option("--check-fast-timeout", help="Seconds the Stop hook gives check_fast (1-160)."),
]
DefaultBranch = Annotated[
    str | None,
    typer.Option("--default-branch", help="The repo's default branch; absent: the project's."),
]

# What an edit sees: the document it changes, and both files as read.
type Edit = Callable[[Document, HubFiles], Edited]


@repo_app.command("list")
def list_command(*, as_json: AsJson = False) -> None:
    """List the repos of hub.json."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    repos = _listed(load_hub_json_or_exit(root / FILE_LABEL).config)
    if as_json:
        typer.echo(dump_json({"repos": list(repos)}).decode(), nl=False)
        return
    for repo in repos:
        typer.echo("\t".join(ABSENT if value is None else str(value) for value in repo.values()))


def _listed(config: HubConfig) -> tuple[dict[str, JsonValue], ...]:
    """Each repo's six listed keys, its default branch the effective one."""
    return tuple(
        {
            "dir": repo.dir,
            "github": repo.github,
            "role": repo.role,
            "check_fast": repo.check_fast,
            "check": repo.check,
            "default_branch": config.default_branch_for(repo.dir),
        }
        for repo in config.repos
    )


@repo_app.command("add")
def add_command(
    dir_: Dir,
    *,
    github: Annotated[str, typer.Option("--github", metavar="OWNER/NAME", help="Its GitHub repo.")],
    check: Annotated[str, typer.Option("--check", help="The full gate, run before a PR.")],
    check_fast: CheckFast = None,
    check_fast_timeout: CheckFastTimeout = None,
    role: Role = None,
    default_branch: DefaultBranch = None,
) -> None:
    """Add a repo last in hub.json's repos."""
    entry: dict[str, JsonValue] = {"dir": dir_, "github": github, "check": check}
    entry |= _given(
        role=role,
        check_fast=check_fast,
        check_fast_timeout=check_fast_timeout,
        default_branch=default_branch,
    )
    shown = shown_name(dir_)
    _write(
        lambda document, _files: add_repo(document, entry),
        action=f"added repo {shown}",
        next_lines=(
            SYNC_LINE,
            f"run ./hub setup to clone ../{shown}",
            f"run /onboard to set {shown}'s gates and project rules",
        ),
    )


@repo_app.command("set")
def set_command(
    context: typer.Context,
    dir_: Dir,
    *,
    github: Annotated[
        str | None, typer.Option("--github", metavar="OWNER/NAME", help="Its GitHub repo.")
    ] = None,
    check: Annotated[
        str | None, typer.Option("--check", help="The full gate, run before a PR.")
    ] = None,
    check_fast: CheckFast = None,
    check_fast_timeout: CheckFastTimeout = None,
    role: Role = None,
    default_branch: DefaultBranch = None,
    unset: Annotated[
        list[str] | None,
        typer.Option(
            "--unset",
            metavar="KEY",
            help="Remove role, check_fast, check_fast_timeout or default_branch; repeatable.",
        ),
    ] = None,
) -> None:
    """Change a repo of hub.json: a key present keeps its place, a new one goes last."""
    changes = _given(
        github=github,
        role=role,
        check_fast=check_fast,
        check_fast_timeout=check_fast_timeout,
        check=check,
        default_branch=default_branch,
    )
    keys = list(unset or [])
    if not changes and not keys:
        context.fail(
            "nothing to change: give --github, --role, --check-fast, --check-fast-timeout,"
            " --check, --default-branch or --unset"
        )
    _write(
        lambda document, _files: set_repo(document, dir_, changes, unset=keys),
        action=f"updated repo {shown_name(dir_)}",
        next_lines=(SYNC_LINE,),
    )


@repo_app.command("remove")
def remove_command(dir_: Dir) -> None:
    """Remove a repo no other key of hub.json or hub.local.json names; its folder stays."""

    def edit(document: Document, files: HubFiles) -> Edited:
        # hub.local.json, when there is one, was checked as a JSON object.
        local = (
            None
            if files.local_content is None
            else cast("Document", load_json_bytes(files.local_content))
        )
        return remove_repo(document, dir_, local_document=local)

    shown = shown_name(dir_)
    _write(
        edit,
        action=f"removed repo {shown}",
        next_lines=(
            SYNC_LINE,
            f"../{shown} and its worktrees are left in place",
            f"a teammate whose hub.local.json names {shown} in repos must drop that entry",
        ),
    )


def _given(**options: JsonValue) -> dict[str, JsonValue]:
    """The options given, by key; an option left out is ``None`` and not written."""
    return {key: value for key, value in options.items() if value is not None}


def _write(edit: Edit, *, action: str, next_lines: Sequence[str]) -> None:
    """Make ``edit`` on ``hub.json``, check the result, write it, then print what was done."""
    files = read_hub_files(command=COMMAND)
    # hub.json was checked as a JSON object.
    document = cast("Document", load_json_bytes(files.hub_content))
    edited = edit(document, files)
    if isinstance(edited, tuple):
        fail(*(REFUSED + refusal.message for refusal in edited))
    checked_documents(edited, files, is_local=False)
    refusal = write_document(files.hub_path, read=files.hub_content, content=document_bytes(edited))
    if refusal is not None:
        fail(refusal)
    if is_reformatted(files.hub_content):
        typer.echo(REFORMAT_LINE)
    typer.echo(f"{FILE_LABEL}: {action}")
    for line in next_lines:
        typer.echo(line)
