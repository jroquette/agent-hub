"""``hub skill-usage``: the hub's skills and agents with their runs over 7, 30 and 90 days,
never used in the chosen window first, as a Markdown table (AGH-482).

Read-only and local: the hub is the one the other hub commands use (``AGENT_HUB_ROOT`` or the
cwd, exit 2 when not a hub), its items are the skills and agents of its ``.claude/skills`` and
``.claude/agents``, and the runs are folded from the event store ``hub collect`` writes to, as
``hub web`` folds them (names, counts and times only, ADR 0019). A cut or partly read catalog
ends the output with one line saying so. Exit codes: 0 printed, 1 the database cannot be opened
or read, 2 usage or not a hub.
"""

import os
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Final, cast

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.database_path import default_database_path
from agent_hub.cli.errors import HomeDirectoryNotFoundError
from agent_hub.cli.knowledge_hub import Database, knowledge_hub_or_exit
from agent_hub.core.readmodels.event_read_models import FoldedEventReadModels
from agent_hub.core.skills.skill_reads import SkillReads
from agent_hub.core.skills.skill_view import UsageDays
from agent_hub.core.skills.usage_report import ordered_usage, usage_markdown
from agent_hub.generator.registered_hub_files import HubFileSystem
from agent_hub.storage.errors import StorageError
from agent_hub.storage.event_store import open_event_store

COMMAND: Final = "skill-usage"


class Window(StrEnum):
    """The windows ``--days`` accepts (``USAGE_WINDOWS``); any other value is a usage error."""

    WEEK = "7"
    MONTH = "30"
    QUARTER = "90"


Days = Annotated[
    Window,
    typer.Option("--days", help="The window the never-used-first order follows, in days."),
]


def skill_usage(*, days: Days = Window.MONTH, db: Database = None) -> None:
    """Print the hub's skills and agents with their runs over 7, 30 and 90 days."""
    window = cast("UsageDays", int(days))
    hub = knowledge_hub_or_exit(os.environ, command=COMMAND)
    try:
        path = db or default_database_path(os.environ)
    except HomeDirectoryNotFoundError as error:
        fail(f"hub {COMMAND}: {error}")
    try:
        store = open_event_store(path)
        events = FoldedEventReadModels(store, now=lambda: datetime.now(UTC))
        reads = SkillReads(HubFileSystem(), events)
        rows, truncated = reads.usage_rows(project=hub.project, hub_path=str(hub.checkout))
    except StorageError as error:
        fail(f"hub {COMMAND}: {error}")
    typer.echo(
        usage_markdown(ordered_usage(rows, window), days=window, truncated=truncated), nl=False
    )
