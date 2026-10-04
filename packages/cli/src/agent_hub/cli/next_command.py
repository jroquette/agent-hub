"""``hub next``: the tracker's ready issues, one line each, oldest first (spec D-next, D11).

The hub is ``AGENT_HUB_ROOT`` or the cwd; its ``hub.json`` names the team, the ready label and
the transport, which the developer's ``hub.local.json`` may replace. With transport ``"api"``
and no ``LINEAR_API_KEY`` the command stops before any tracker call (D16); otherwise it names the
transport on stderr, reads ``list_ready`` once through the ``TrackerClient`` port and prints
``<id>  <repo>  <title>  <url>`` per issue, in issue-number order. The repo is the issue's one
label equal to a repo ``dir``, ``?`` when none or several match. An id, title or url that could
break its line is shown escaped. Exit codes: 0 listed (none included), 1 config, key or tracker
failure, 2 usage or not a hub (D15).
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
from agent_hub.core.runner.ready_list import ReadyRow, no_ready_line, ready_rows

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
    try:
        issues = client.list_ready(config.tracker.team, config.tracker.ready_label)
    except TrackerError as error:
        fail(str(error))
    rows = ready_rows(issues, repos=[repo.dir for repo in config.repos])
    if not rows:
        typer.echo(no_ready_line(team=config.tracker.team, label=config.tracker.ready_label))
        return
    for row in rows:
        typer.echo(_line(row))


def _line(row: ReadyRow) -> str:
    # The id, title and url are tracker text: escaped, they cannot fake a second line.
    return _SEPARATOR.join(
        (shown_text(row.id), row.repo, shown_text(row.title), shown_text(row.url))
    )
