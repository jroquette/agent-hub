"""``hub next``: the tracker's ready issues, one line each, oldest first (spec D-next, D11).

The hub is ``AGENT_HUB_ROOT`` or the cwd; its ``hub.json`` names the team, the ready label and
the transport, which the developer's ``hub.local.json`` may replace. With transport ``"api"``
and no ``LINEAR_API_KEY`` the command stops before any tracker call (D16); otherwise it names the
transport on stderr, reads ``list_ready`` through the ``TrackerClient`` port once per team, in
config order, and prints ``<id>  <repo>  <title>  <url>`` per issue, team by team, in
issue-number order within a team. The repo is the issue's one label equal to a repo ``dir``,
``?`` when none or several match. An id, title or url that could break its line is shown
escaped. A team whose call fails is named on stderr after the listed lines (the bare reason on a
one-team hub) and the other teams are still listed. Exit codes: 0 listed (none included), 1
config, key or tracker failure, 2 usage or not a hub (D15).
"""

import os
from typing import Final

import typer

from agent_hub.cli.command_exits import fail
from agent_hub.cli.effective_config import load_effective_config_or_exit
from agent_hub.cli.hub_root import hub_root_or_exit
from agent_hub.cli.init_report import shown_text
from agent_hub.cli.tracker_client import missing_key_line, resolve_tracker_client, transport_line
from agent_hub.core.errors import TrackerError
from agent_hub.core.runner.ready_list import (
    ReadyRow,
    no_ready_line,
    ready_rows,
    team_failure_line,
)

COMMAND: Final = "next"
_SEPARATOR: Final = "  "


def next_command() -> None:
    """Print the tracker's ready issues, oldest first: id, repo, title and url."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    config = load_effective_config_or_exit(root).config
    missing = missing_key_line(config, os.environ, command=COMMAND)
    if missing is not None:
        fail(missing)
    typer.echo(transport_line(config), err=True)
    client = resolve_tracker_client(config, os.environ, hub_root=root)
    teams = config.tracker.team_keys
    label = config.tracker.ready_label
    repos = [repo.dir for repo in config.repos]
    rows: list[ReadyRow] = []
    listed: list[str] = []
    failures: list[str] = []
    for team in teams:
        try:
            issues = client.list_ready(team, label)
        except TrackerError as error:
            failures.append(team_failure_line(team=team, reason=str(error), team_count=len(teams)))
            continue
        rows.extend(ready_rows(issues, repos=repos))
        listed.append(team)
    for row in rows:
        typer.echo(_line(row))
    if listed and not rows:
        typer.echo(no_ready_line(teams=listed, label=label))
    if failures:
        fail(*failures)


def _line(row: ReadyRow) -> str:
    # The id, title and url are tracker text: escaped, they cannot fake a second line.
    return _SEPARATOR.join(
        (shown_text(row.id), row.repo, shown_text(row.title), shown_text(row.url))
    )
