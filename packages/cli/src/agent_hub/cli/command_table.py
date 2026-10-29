"""The hub's commands by name, each imported from its module only when it runs.

``hub --help`` and ``hub <typo>`` read the table: each name keeps its help as data, so listing
the commands imports no command module. ``HubGroup`` holds one placeholder per entry (Typer's own
``TyperCommand`` or ``TyperGroup``, so Typer's "Did you mean" sees every name) and swaps in the
real command, built from its one module, when the name is resolved. A unit test compares each
entry's help with the loaded command's, so a docstring change shows up there.
"""

from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any, Final, Literal

import typer.core
import typer.main
from typer._click.core import Command, Context
from typer.models import CommandInfo, TyperInfo

# The real commands are built with this value; ``main.app`` must keep it (a unit test checks).
PRETTY_EXCEPTIONS_SHORT: Final = True


@dataclass(frozen=True, kw_only=True)
class CommandEntry:
    """One ``hub`` subcommand: where it lives and the help ``hub --help`` shows for it.

    ``attribute`` is the command function (``kind="command"``) or the ``typer.Typer`` of the group
    (``kind="group"``) in ``module``; ``command_class`` names a ``TyperCommand`` subclass in the
    same module that the real command is built with.
    """

    name: str
    module: str
    attribute: str
    kind: Literal["command", "group"]
    help: str
    short_help: str | None = None
    rich_help_panel: str | None = None
    deprecated: bool = False
    hidden: bool = False
    add_help_option: bool = True
    command_class: str | None = None


def _command(name: str, target: str, help_text: str, **options: Any) -> CommandEntry:
    """A command row; ``target`` is ``<module in agent_hub.cli>:<function>``."""
    module, attribute = target.split(":")
    return CommandEntry(
        name=name,
        module=f"agent_hub.cli.{module}",
        attribute=attribute,
        kind="command",
        help=help_text,
        **options,
    )


def _group(name: str, target: str, help_text: str) -> CommandEntry:
    """A group row; ``target`` is ``<module in agent_hub.cli>:<typer.Typer>``."""
    module, attribute = target.split(":")
    return CommandEntry(
        name=name,
        module=f"agent_hub.cli.{module}",
        attribute=attribute,
        kind="group",
        help=help_text,
    )


SHIP_HELP: Final = """\
Ship an issue: each changed repo's check, push and PR, the PRs linked, the issue to review.

The repos are those whose task worktree for the issue has commits ahead of origin's default
branch (as last fetched; hub ship does not fetch). Every check passes before any push. Run
again after a success, hub ship finds the PRs already open and posts one more comment on
the issue."""

# In the order ``hub --help`` lists them: a new command adds its row here.
COMMANDS: Final[tuple[CommandEntry, ...]] = (
    _command(
        "collect",
        "collect:collect",
        "Ingest events (JSON Lines, a transcript or run records), all or nothing.",
    ),
    _command(
        "init", "generator:init", "Create a hub for a project with its repos and task tracker."
    ),
    _command(
        "sync",
        "sync_command:sync",
        "Reapply the hub templates without overwriting what the project customized.",
    ),
    _command(
        "doctor",
        "doctor_command:doctor",
        "Check the hub's rules, links, dead references and instruction size.",
    ),
    _command(
        "setup",
        "setup_command:setup",
        "Set up this machine for the hub: tools, identity, environments, repos, then hub doctor.",
    ),
    _command(
        "worktree",
        "worktree_command:worktree",
        "Create isolated worktrees for one task in the hub's repos, or remove them.",
    ),
    _command(
        "brief",
        "brief_command:brief",
        "Print the session brief: now.md, the last journal days, each repo's git, PR and CI state.",
    ),
    _command(
        "agent",
        "agent_command:agent",
        "Start Claude Code with every repo in hub.json attached; every argument goes to claude.",
        add_help_option=False,
        command_class="PassThroughCommand",
    ),
    _command(
        "next",
        "next_command:next_command",
        "Print the tracker's ready issues, oldest first: id, repo, title and url.",
    ),
    _command(
        "run",
        "run_engine:run",
        "Take one tracker issue to a PR: worktree, implementing session, gate, PR, report.",
    ),
    _command(
        "ship",
        "ship_command:ship",
        SHIP_HELP,
    ),
    _command(
        "bench",
        "bench_command:bench",
        "Benchmark the hub-workflow plugin on closed issues: each case's hidden tests grade it.\n"
        "\n"
        "BENCH_EFFORT sets the sessions' effortLevel: low, medium (default) or high.",
    ),
    _command(
        "start",
        "start_command:start",
        "Start or resume an issue: its worktrees, its started state and a Claude Code session.",
    ),
    _command(
        "web",
        "web_command:web",
        "Serve the control plane (API and web app) on 127.0.0.1 until interrupted.",
    ),
    _command(
        "validate-output",
        "validate_output_command:validate_output",
        "Check one agent output JSON file: every problem, one per line.",
    ),
    _command(
        "search",
        "search_command:search",
        "Search the hub's brain and its repos' docs; the index is brought up to date first.",
    ),
    _command(
        "mcp",
        "mcp_command:mcp",
        "Serve the hub's brain and repo docs to Claude Code over stdio (MCP tools: search, read,\n"
        "propose).",
    ),
    _command(
        "skill-usage",
        "skill_usage_command:skill_usage",
        "Print the hub's skills and agents with their runs over 7, 30 and 90 days.",
    ),
    _group("workflow", "workflow_command:workflow_app", "List, check and run workflows."),
    _group("step", "step_command:step_app", "Run one stage of hub run."),
    _group(
        "env",
        "env_command:env_app",
        "List, show and change the declared environments and services.",
    ),
    _group("repo", "repo_command:repo_app", "List, add, change and remove the hub's repos."),
    _group("action", "action_command:action_app", "List, plan and run the hub's actions."),
    _group("scenario", "scenario_command:scenario_app", "List, plan and run the hub's scenarios."),
    _group("brain", "brain_command:brain_app", "Work on the hub's brain and its knowledge index."),
)
ENTRIES: Final = {entry.name: entry for entry in COMMANDS}


def _target(entry: CommandEntry) -> Any:  # noqa: ANN401 - a command function or a typer.Typer
    """Import the entry's module and return its command function or group ``Typer``."""
    return getattr(import_module(entry.module), entry.attribute)


def import_all() -> None:
    """Import every command module in the table and read each entry's attribute."""
    for entry in COMMANDS:
        _target(entry)


class HubGroup(typer.core.TyperGroup):
    """The root ``hub`` group: placeholders from ``COMMANDS``, real commands built on demand."""

    def __init__(self, **attrs: Any) -> None:  # noqa: ANN401 - TyperGroup's own keywords
        super().__init__(**attrs)
        self._placeholders: dict[str, Command] = {}
        for entry in COMMANDS:
            placeholder = self._placeholder(entry)
            self._placeholders[entry.name] = placeholder
            self.commands[entry.name] = placeholder

    def _placeholder(self, entry: CommandEntry) -> Command:
        kind: Callable[..., Command] = (
            typer.core.TyperGroup if entry.kind == "group" else typer.core.TyperCommand
        )
        return kind(
            name=entry.name,
            help=entry.help,
            short_help=entry.short_help,
            hidden=entry.hidden,
            deprecated=entry.deprecated,
            add_help_option=entry.add_help_option,
            rich_help_panel=entry.rich_help_panel,
            rich_markup_mode=self.rich_markup_mode,
        )

    def _load(self, entry: CommandEntry) -> Command:
        """Build the real command from its module, as ``app.command`` or ``app.add_typer`` would."""
        module = import_module(entry.module)
        target = getattr(module, entry.attribute)
        if entry.kind == "group":
            command: Command = typer.main.get_group_from_info(
                TyperInfo(target, name=entry.name),
                pretty_exceptions_short=PRETTY_EXCEPTIONS_SHORT,
                suggest_commands=self.suggest_commands,
                rich_markup_mode=self.rich_markup_mode,
            )
        else:
            cls = getattr(module, entry.command_class) if entry.command_class else None
            command = typer.main.get_command_from_info(
                CommandInfo(
                    entry.name, cls=cls, add_help_option=entry.add_help_option, callback=target
                ),
                pretty_exceptions_short=PRETTY_EXCEPTIONS_SHORT,
                rich_markup_mode=self.rich_markup_mode,
            )
        self.commands[entry.name] = command
        return command

    def resolve_command(
        self, ctx: Context, args: list[str]
    ) -> tuple[str | None, Command | None, list[str]]:
        name, command, rest = super().resolve_command(ctx, args)
        if name is not None and command is not None and command is self._placeholders.get(name):
            command = self._load(ENTRIES[name])
        return name, command, rest
