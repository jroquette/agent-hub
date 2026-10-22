"""``hub workflow schedule list``: each schedule of ``hub.json`` and its next start (ADR 0048).

One line per schedule, in the file's order: ``<workflow>  <cron>  next <YYYY-MM-DDTHH:MMZ>``,
with ``  env <name>`` when it sets an environment; the time is UTC, the first slot strictly
after ``--after`` (default now). ``no schedules in hub.json`` when there is none. ``hub web``
starts them; this command only reads ``hub.json`` (a folder that is not a hub exits 2, a
``hub.json`` that is not valid exits 1). Events are not listed: they have no time.
"""

import os
from datetime import UTC, datetime
from typing import Annotated, Final

import typer

from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.core.hub_config.schedules import Schedule
from agent_hub.core.schedules.cron import parse_cron

COMMAND: Final = "workflow schedule"
_TIME_HINT: Final = "give an ISO 8601 time with its offset, such as 2026-10-26T09:00:00+00:00"

schedule_app = typer.Typer(
    name="schedule", no_args_is_help=True, help="The workflows hub web starts on a schedule."
)


def _time(text: str) -> datetime:
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise typer.BadParameter(_TIME_HINT, param_hint="--after") from None
    if moment.tzinfo is None:
        raise typer.BadParameter(_TIME_HINT, param_hint="--after")
    return moment.astimezone(UTC)


@schedule_app.command("list")
def list_schedules(
    after: Annotated[
        str | None,
        typer.Option("--after", metavar="TIME", help="Show the first start after TIME (ISO 8601)."),
    ] = None,
) -> None:
    """List each schedule of hub.json with its next start (UTC)."""
    moment = datetime.now(UTC) if after is None else _time(after)
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_hub_config_or_exit(root / FILE_LABEL)
    if not config.schedules:
        typer.echo("no schedules in hub.json")
        return
    for schedule in config.schedules:
        typer.echo(_line(schedule, moment))


def _line(schedule: Schedule, after: datetime) -> str:
    following = parse_cron(schedule.cron).next_after(after)
    shown = "never" if following is None else following.strftime("%Y-%m-%dT%H:%MZ")
    line = f"{schedule.workflow}  {schedule.cron}  next {shown}"
    if schedule.environment is not None:
        line += f"  env {schedule.environment}"
    return line
