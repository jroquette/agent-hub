"""``hub run``: one tracker issue to a PR, the ``issue-to-pr`` workflow run through the engine.

Since AGH-224 a live ``hub run`` is the ``issue-to-pr`` workflow (ADR 0032) with ``hub run``'s
parent around it (``workflow_delivery``): the hub's own ``workflows/<pack>/issue-to-pr.yaml`` when
present, else the built-in. Its options, usage checks, key check and dry run are ``run_command``'s
and unchanged: the dry run prints v0.14's lines and loads no workflow. Live, the workflow is loaded
and planned after the usage checks (a problem exits 1 before the tracker is read) and must take
the inputs the parent fills (else exit 2): ``issue``, ``repo`` and ``issue_text``, and ``start``
for ``--from verify``, which skips the implementing session through the node's ``when:``.
``--model``, ``--effort``, ``--max-turns`` and ``--budget``, when typed, win over the
``implement`` node's own model and limits (the built-in's are ``hub run``'s defaults). The pack is
copied to a temporary folder at the start and read from there. The run writes ``hub run``'s
records only (no workflow folder, so no resume) and exits as v0.14 did: 0 delivered or no
changes, 3 blocked, 1 failed; Ctrl-C ends it with no tracker write.
"""

import os
import tempfile
from pathlib import Path
from typing import Annotated, Final

import typer
from typer._click.core import ParameterSource

from agent_hub.cli.command_exits import fail
from agent_hub.cli.hub_config_reader import FILE_LABEL, load_hub_config_or_exit
from agent_hub.cli.hub_root import hub_checkout, hub_root_or_exit
from agent_hub.cli.run_children import CHILD_HIDDEN, RunOptions, without
from agent_hub.cli.run_command import (
    COMMAND,
    DEFAULT_BUDGET_USD,
    DEFAULT_MAX_TURNS,
    DEFAULT_MODEL,
    Effort,
    RunStart,
    begin_live_run,
    check_budget,
    check_model,
    dry_run,
    refuse_usage,
    run_setup,
)
from agent_hub.cli.run_log import new_run_id
from agent_hub.cli.workflow_command import discovered, run_delivery
from agent_hub.cli.workflow_delivery import (
    ISSUE_TEXT,
    ISSUE_TO_PR,
    START,
    IssueToPr,
    delivery_problem,
    session_options,
)
from agent_hub.cli.workflow_runs import WorkflowRunError, snapshot_run
from agent_hub.core.hub_config.model_tiers import RUN_TIER
from agent_hub.core.json_form import JsonValue
from agent_hub.core.workflows.engine import WorkflowEngineError, start_inputs

# A flag typed on the command line (not its default): it wins over the implement node's own.
_TYPED: Final = ParameterSource.COMMANDLINE


def run(
    context: typer.Context,
    issue: Annotated[
        str, typer.Argument(metavar="ISSUE", help="The tracker issue, <team>-<n> (DEM-1).")
    ],
    *,
    repo: Annotated[
        str,
        typer.Option("--repo", metavar="REPO", help="The repo to change (its dir in hub.json)."),
    ],
    live: Annotated[
        bool, typer.Option("--live", help="Run it; without it, print what would run.")
    ] = False,
    max_turns: Annotated[
        int, typer.Option("--max-turns", min=1, help="Turns of the implementing session.")
    ] = DEFAULT_MAX_TURNS,
    budget: Annotated[
        float,
        typer.Option(
            "--budget", callback=check_budget, help="USD cap of the implementing session."
        ),
    ] = DEFAULT_BUDGET_USD,
    model: Annotated[
        str,
        typer.Option(
            "--model",
            callback=check_model,
            help="Model of the implementing session; unset, hub.json's models.tiers.medium.",
        ),
    ] = DEFAULT_MODEL,
    start: Annotated[
        RunStart,
        typer.Option("--from", help="verify: gate, PR and report on the commits already made."),
    ] = RunStart.IMPLEMENT,
    effort: Annotated[
        Effort, typer.Option("--effort", help="effortLevel of the implementing session.")
    ] = Effort.MEDIUM,
) -> None:
    """Take one tracker issue to a PR: worktree, implementing session, gate, PR, report."""
    root = hub_root_or_exit(os.environ, command=COMMAND)
    hub = hub_checkout(root, command=COMMAND, environ=without(os.environ, CHILD_HIDDEN))
    hub_config = load_hub_config_or_exit(hub / FILE_LABEL)
    refuse_usage(context, hub_config, issue=issue, repo=repo)
    if live:
        plan, found = discovered(hub, ISSUE_TO_PR)
        if problem := delivery_problem(plan, start=start):
            context.fail(problem)
        values: dict[str, JsonValue] = {"issue": issue, "repo": repo, ISSUE_TEXT: ""}
        if START in plan.document.inputs:
            values[START] = start.value
        try:
            inputs = start_inputs(plan, values)
        except WorkflowEngineError as error:
            context.fail(str(error))
    children, client = run_setup(context, hub_config, hub=hub, issue=issue, repo=repo)
    if context.get_parameter_source("model") is ParameterSource.DEFAULT:
        # Not given: the tier's model, the default itself while hub.json sets none (AGH-180).
        model = hub_config.models.model_for(RUN_TIER)
    options = RunOptions(
        live=live, max_turns=max_turns, budget=budget, model=model, start=start, effort=effort
    )
    if not options.live:
        dry_run(children, client, options=options)
        return
    flags = {"max_turns": max_turns, "budget": budget, "model": model, "effort": effort}
    given = {k: v for k, v in flags.items() if context.get_parameter_source(k) is _TYPED}
    options = session_options(plan, children.config, start=start, given=given)
    with tempfile.TemporaryDirectory(prefix="hub-run-") as scratch:
        # The pack as it was at the start: a session cannot change the prompts the run reads.
        try:
            pack, _ = snapshot_run(
                Path(scratch), document=dict(found.document), plan=plan, pack_root=found.pack_root
            )
        except WorkflowRunError as error:
            fail(f"hub {COMMAND}: {error}")
        parent = IssueToPr(begin_live_run(children, client, options=options, run_id=new_run_id()))
        inputs[ISSUE_TEXT] = parent.issue_text
        raise typer.Exit(run_delivery(hub, parent, plan=plan, inputs=inputs, pack=pack))
