"""The hub generator command ``init`` (SPEC layer 1), which writes a hub.

``sync`` is in ``sync_command`` and ``doctor`` in ``doctor_command``.

``init`` runs the pipeline of the AGH-12 spec, and every step that fails exits 1 before any write:
the config (from ``--config``, or from the flags plus git-read defaults; any module set is
accepted), the target, the tree read and the core planner, then the writes (leftovers removed,
folders, files, links, ``hub.json``, ``hub.lock`` last) and the report. Output goes to stdout
only on success, and each error to stderr on its own line. Usage errors are Typer's, exit 2.
"""

import os
from collections.abc import Iterable, Mapping
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Final

import typer

from agent_hub.cli.command_exits import (
    extension_inputs_or_exit,
    fail,
    fail_generator,
    root_or_exit,
)
from agent_hub.cli.git_defaults import AUTHOR_EMAIL, AUTHOR_NAME, HUB_REPO, read_git_defaults
from agent_hub.cli.hub_config_reader import DISTRIBUTION, load_hub_json_or_exit
from agent_hub.cli.init_config import document_from_flags, flag_problems
from agent_hub.cli.init_report import created_lines, next_steps, shown_path
from agent_hub.core.hub_config.document_check import check_hub_document
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.hub_files.extension_inputs import ExtensionInputs
from agent_hub.core.hub_files.hub_lock import HUB_JSON_PATH
from agent_hub.core.hub_files.plan_init import InitPlan, InitRefusal, plan_init
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.json_form import dump_json
from agent_hub.generator.errors import GeneratorError
from agent_hub.generator.file_adapter import apply_writes, ensure_root, remove_leftovers
from agent_hub.generator.hub_tree import read_hub_tree
from agent_hub.generator.render_hub import project_json_siblings, render_hub

_BRANCH_PREFIX: Final = "branch_prefix"
_DEFAULTABLE: Final = (AUTHOR_NAME, AUTHOR_EMAIL, HUB_REPO)


def init(
    context: typer.Context,
    project: Annotated[
        str | None,
        typer.Argument(
            metavar="PROJECT", help="Name of the project the hub is for (not with --config)."
        ),
    ] = None,
    *,
    repos: Annotated[
        str | None,
        typer.Option(
            "--repos", help="Comma-separated repos of the project, e.g. org/backend,org/frontend."
        ),
    ] = None,
    tracker: Annotated[
        str | None, typer.Option("--tracker", help="Task tracker and team key, e.g. linear:LOK.")
    ] = None,
    branch_prefix: Annotated[
        str | None, typer.Option("--branch-prefix", help="Prefix of every branch, e.g. jdoe/.")
    ] = None,
    author_name: Annotated[
        str | None,
        typer.Option(
            "--author-name", help="Author of commits and PRs.", show_default="git user.name"
        ),
    ] = None,
    author_email: Annotated[
        str | None,
        typer.Option("--author-email", help="Author's email.", show_default="git user.email"),
    ] = None,
    hub_repo: Annotated[
        str | None,
        typer.Option(
            "--hub-repo",
            help="GitHub owner/name of the hub.",
            show_default="the hub folder's GitHub origin",
        ),
    ] = None,
    config: Annotated[
        Path | None,
        typer.Option("--config", help="Copy this hub.json instead of building one from flags."),
    ] = None,
    directory: Annotated[
        Path | None,
        typer.Option(
            "--dir", help="Folder to write the hub in.", show_default="the current folder"
        ),
    ] = None,
) -> None:
    """Create a hub for a project with its repos and task tracker."""
    optional = {
        _BRANCH_PREFIX: branch_prefix,
        AUTHOR_NAME: author_name,
        AUTHOR_EMAIL: author_email,
        HUB_REPO: hub_repo,
    }
    flags = {"--repos": repos, "--tracker": tracker}
    flags |= {"--" + key.replace("_", "-"): value for key, value in optional.items()}
    source = _source_or_fail(context, project=project, flags=flags, config=config)
    root = root_or_exit(directory)
    running = version(DISTRIBUTION)
    if isinstance(source, Path):
        loaded = load_hub_json_or_exit(source)
        hub_config, hub_json = loaded.config, loaded.content
    else:
        hub_config, hub_json = _config_from_flags_or_exit(
            source, optional=optional, root=root, running=running
        )
    _check_root_or_exit(root)
    plan, git_present = _plan_or_exit(root, config=hub_config, hub_json=hub_json)
    _apply_or_exit(root, plan)
    for line in [*created_lines(plan, root), "", *next_steps(root, git_present=git_present)]:
        typer.echo(line)


def _source_or_fail(
    context: typer.Context,
    *,
    project: str | None,
    flags: Mapping[str, str | None],
    config: Path | None,
) -> Path | dict[str, str]:
    """``--config``'s path, or PROJECT, ``--repos`` and ``--tracker``; else a usage error (exit 2).

    ``flags`` holds every flag by its name, None when not given.
    """
    given = [flag for flag, value in flags.items() if value is not None]
    if config is not None:
        if project is not None:
            context.fail("PROJECT cannot be given with --config")
        if given:
            context.fail(f"{given[0]} cannot be given with --config")
        return config
    if project is None:
        context.fail("give PROJECT with --repos and --tracker, or --config")
    repos, tracker = flags["--repos"], flags["--tracker"]
    if repos is None:
        context.fail("PROJECT needs --repos")
    if tracker is None:
        context.fail("PROJECT needs --tracker")
    return {"project": project, "repos": repos, "tracker": tracker}


def _config_from_flags_or_exit(
    required: Mapping[str, str], *, optional: Mapping[str, str | None], root: str, running: str
) -> tuple[HubConfig, bytes]:
    """The config and ``hub.json`` bytes of the flags, a missing default read from git."""
    missing = frozenset(key for key in _DEFAULTABLE if optional[key] is None)
    defaults = read_git_defaults(missing=missing, target=Path(root))
    values = {**optional, **defaults.values}
    document = document_from_flags(
        project=required["project"],
        repos=required["repos"],
        tracker=required["tracker"],
        branch_prefix=values[_BRANCH_PREFIX],
        author_name=values[AUTHOR_NAME],
        author_email=values[AUTHOR_EMAIL],
        hub_repo=values[HUB_REPO],
        version=running,
    )
    checked = check_hub_document(document, running_version=running)
    if not isinstance(checked, HubConfig):
        fail(*flag_problems(_with_git_reasons(checked, defaults.problems), repos=required["repos"]))
    return checked, dump_json(document)


def _with_git_reasons(
    problems: Iterable[ConfigProblem], reasons: Mapping[str, str]
) -> list[ConfigProblem]:
    """Each problem of a value git could not supply, with why (git not found, timed out, ...)."""
    by_path = {f"project.{key}": reason for key, reason in reasons.items()}
    return [
        ConfigProblem(problem.path, f"{problem.message} ({by_path[problem.path]})")
        if problem.path in by_path
        else problem
        for problem in problems
    ]


def _check_root_or_exit(root: str) -> None:
    # Absent is fine: the folder is made only once every check passed.
    if os.path.lexists(root) and not os.path.isdir(root):
        fail(f"{shown_path(root)}: not a folder")


def _wanted(rendered: RenderedHub, *, siblings: Iterable[str]) -> frozenset[str]:
    """The files read by content: every managed file, ``hub.json`` and the ``*.project.json``."""
    managed = (file.path for file in rendered.files if file.ownership is Ownership.MANAGED)
    return frozenset({*managed, HUB_JSON_PATH, *siblings})


def _plan_or_exit(root: str, *, config: HubConfig, hub_json: bytes) -> tuple[InitPlan, bool]:
    """The init plan and whether the root holds ``.git``; a refusal prints every path, sorted.

    A kept ``*.project.json`` sibling merges into its ``X.json`` (spec D2). Project agents and
    skills are not linked: at init they are unknown entries, refused like any other (Q-22). Dropping
    their names from the inputs is defensive, not observable: the refusal comes first.
    """
    try:
        siblings = project_json_siblings(config)
        tree = read_hub_tree(Path(root), wanted=_wanted(render_hub(config), siblings=siblings))
    except GeneratorError as error:
        fail_generator(error)
    found = extension_inputs_or_exit(tree, project=config.project.name, siblings=siblings)
    extensions = ExtensionInputs(project_json=found.project_json, agents=(), skills=())
    try:
        rendered = render_hub(config, extensions)
    except GeneratorError as error:
        fail_generator(error)
    planned = plan_init(rendered=rendered, config=config, hub_json=hub_json, tree=tree)
    if isinstance(planned, InitRefusal):
        fail(*(f"{shown_path(path)}: {message}" for path, message in planned.problems))
    return planned, tree.git_present


def _apply_or_exit(root: str, plan: InitPlan) -> None:
    hub = Path(root)
    try:
        ensure_root(hub)
        remove_leftovers(hub, plan.leftovers)
        apply_writes(hub, folders=plan.folders, writes=plan.writes)
    except GeneratorError as error:
        fail_generator(error)
