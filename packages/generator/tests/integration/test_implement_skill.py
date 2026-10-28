"""The rendered ``/implement`` skill (two-level-flows AC-2.1; AGH-579, ADR 0050).

``/implement <ticket>`` conducts one ticket of a planned feature in the session that runs it:
each agent stage is a subagent the session dispatches, with the ``implement`` workflow's own
prompt (``hub step prompt``) and output contract (``hub step output``), and the records are the
ones a run writes (``hub step ticket-brief``, ``preflight``, ``change-request``, ``decide``,
``amend-plan``). It never starts ``hub workflow run``, ``claude -p`` or another session; the
commands the sandbox cannot run (``hub worktree``, the push, ``gh``) are bare calls. A ticket in
no feature is sent to ``issue-to-pr`` or ``/fix``; texts reach a command through a file. Checked
on the demo hub's render; ``/feature``'s Build step is checked in ``test_feature_agents.py``.
"""

import re

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.workflows.document import parse_workflow
from agent_hub.core.workflows.nodes import AgentNode, LoopGroupNode
from agent_hub.generator.render_hub import render_hub
from agent_hub.generator.workflow_discovery import BUILTIN_WORKFLOWS
from agent_hub.generator.workflow_yaml import load_workflow_bytes

IMPLEMENT = "plugin/hub-workflow/skills/implement/SKILL.md"
SDLC = BUILTIN_WORKFLOWS / "sdlc"
# Each stage hub step prompt renders: its workflow and agent node (cli's step_stages.STAGES).
STAGES = {
    "preflight": ("preflight-check", "preflight"),
    "ticket-plan": ("ticket-pass", "plan"),
    "spec-lens": ("ticket-pass", "spec"),
    "quality-lens": ("ticket-pass", "quality"),
    "ticket-eval": ("implement", "eval"),
}


@pytest.fixture
def raw(demo_config: HubConfig) -> str:
    rendered = {file.path: file.content for file in render_hub(demo_config).files}
    content = rendered[IMPLEMENT]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def text(raw: str) -> str:
    return " ".join(raw.split())


def stage_names(stage: str) -> set[str]:
    """The ``with`` names of the stage's agent node, in the built-in pack."""
    workflow, node_id = STAGES[stage]
    path = SDLC / f"{workflow}.yaml"
    document = parse_workflow(load_workflow_bytes(path.read_bytes(), source=str(path)).document)
    nodes = [
        inner
        for node in document.nodes
        for inner in (node.nodes if isinstance(node, LoopGroupNode) else (node,))
    ]
    [node] = [n for n in nodes if n.id == node_id]
    assert isinstance(node, AgentNode)
    return set(node.with_)


def step_text(text: str, number: int) -> str:
    """Step ``number``'s text, up to the next step."""
    start = text.index(f" {number}. **")
    end = text.find(f" {number + 1}. **", start)
    return text[start : end if end != -1 else None]


def test_starts_no_workflow_run_or_other_session_when_implement_rendered(text: str) -> None:
    assert "./hub workflow run" not in text.replace("Never start `./hub workflow run`", "")
    assert "Never start `./hub workflow run`, `claude -p` or another session for a stage" in text
    assert "Agent tool" in text
    # The workflow stays, for hub web and the CLI; the skill says so.
    assert "The built-in `implement` workflow stays for hub web's Workflow runs screen" in text


def test_reports_each_stage_in_the_chat_when_implement_rendered(text: str) -> None:
    assert "**After each stage**, write a short result in the chat" in text
    assert "the record written" in text


@pytest.mark.parametrize("stage", list(STAGES))
def test_gives_each_stage_the_workflows_prompt_values_when_implement_rendered(
    text: str, stage: str
) -> None:
    named = [m.start() for m in re.finditer(f"`--stage {stage}`", text)]
    assert named, stage
    window = text[named[0] : named[0] + 400]

    for name in stage_names(stage):
        assert f"`{name}`" in window or f"`{name}=" in window, (stage, name)


def test_checks_each_subagent_output_as_the_workflow_does_when_implement_rendered(
    text: str,
) -> None:
    assert "`./hub step prompt --stage <stage> --with <name>=<value> …`" in text
    assert "./hub step output --stage <stage> <" in text
    assert "Give it to the subagent whole and unchanged" in text
    assert "re-dispatch the subagent once" in text


def test_records_the_stages_as_a_run_does_when_implement_rendered(text: str) -> None:
    for command in (
        "./hub step ticket-brief --feature <slug> --ticket <ticket>",
        "./hub step pending-decision --feature <slug> --ticket <ticket>",
        "./hub step amend-plan --feature <slug> --request",
        "./hub step preflight --feature <slug> --ticket <ticket> --findings",
        "./hub step change-request --feature <slug> --ticket <ticket> --findings",
        "./hub step decide --feature <slug> --request <n> --decision approved|declined",
    ):
        assert command in text, command
    assert "`AGENT_HUB_RUN_ID=session-<ticket in lowercase> ./hub step …`" in text


def test_stops_for_the_owner_on_plan_drift_when_implement_rendered(text: str) -> None:
    preflight = step_text(text, 4)

    assert "**Stop**" in preflight
    assert "Never decide it yourself" in preflight
    assert "hub web's ticket panel" in preflight
    assert "do not decide again" in preflight
    # The workflow's loop cap: three passes, a discovery in the third blocks.
    assert "at most 3 passes" in preflight
    assert "a discovery in pass 3 makes the ticket **blocked**" in step_text(text, 7)
    assert "at most 3 per pass" in step_text(text, 8)


def test_runs_the_sandbox_excluded_commands_bare_when_implement_rendered(text: str) -> None:
    assert "`./hub worktree <ticket in lowercase> --only <repo>` as a call of its own" in text
    assert "`./hub worktree <ticket in lowercase> --stack-on <blocker's PR url>`" in text
    pr = step_text(text, 10)
    assert "**wait for their OK**" in pr
    assert "`git push -u origin <branch>`" in pr
    assert "`gh pr create --base" in pr
    assert "`hub step pr` pushes from inside the sandbox and fails there" in pr


def test_dispatches_the_hubs_reviewers_and_evaluator_when_implement_rendered(text: str) -> None:
    assert "`spec-reviewer` and `quality-reviewer` subagents" in text
    assert "a fresh `evaluator` subagent" in text
    assert "`./hub validate-output review <file>`" in text
    assert "`./hub validate-output eval brain/features/<slug>/evals/<delivery>.json`" in text


def test_passes_texts_through_files_when_implement_rendered(text: str) -> None:
    assert '`echo "${TMPDIR:-/tmp}"`' in text
    assert "never type or paste it into a command line" in text
    assert "`test -s <tmp>/<ticket>.txt`" in text
    assert '`spec="$(cat "<tmp>/<ticket>.txt")"`' in text
    assert '"$TMPDIR/' not in text


def test_runs_no_spec_research_plan_or_tickets_step_when_implement_rendered(text: str) -> None:
    assert "no spec, research, plan or tickets step" in text
    assert "you never commit in the hub" in text


def test_names_issue_to_pr_and_fix_for_a_ticket_in_no_feature_when_implement_rendered(
    text: str,
) -> None:
    stop = text[text.index("in no feature") :]

    assert "stop" in stop[:200]
    assert "`issue-to-pr`" in stop
    assert "`/fix`" in stop


def test_reports_the_delivery_as_the_workflow_shapes_it_when_implement_rendered(
    text: str,
) -> None:
    report = step_text(text, 11)

    for outcome in ("`delivered`", "`no_changes`", "`blocked`", "`failed`"):
        assert outcome in report, outcome
    assert "hub PR the owner opens" in report
    # A23: an approval the plan moved past is told to the owner.
    assert "`superseded` whenever it is not empty" in report


def several_repos_text(text: str) -> str:
    """The section on a ticket that owns several repos, up to the closing line (AGH-595)."""
    start = text.index("**A ticket that owns several repos**")
    return text[start : text.index("The PR is reviewed and merged by the user", start)]


def test_keeps_the_one_repo_steps_when_implement_rendered(text: str) -> None:
    # The steps above the section read as they did: a one-repo ticket runs exactly as today.
    assert "./hub worktree <ticket in lowercase> --only <repo>` as a call of its own" in text
    assert text.index("11. **Report the delivery**") < text.index(
        "**A ticket that owns several repos**"
    )


def test_runs_each_repo_of_a_ticket_that_owns_several_when_implement_rendered(text: str) -> None:
    section = several_repos_text(text)

    for expected in (
        # The brief names the repos, in contract order (also the merge order).
        "`repos`",
        # One preflight over every checkout, its commit per repo recorded.
        "`<hub>/..`",
        "`<repo>: <commit>`",
        "`--commit <repo>=<commit>`",
        # Every worktree in one call.
        "`./hub worktree <ticket in lowercase> --only <repo> --only <repo> …`",
        # The lenses per repo, in their own folders.
        "`reviews/<ticket>/<repo>/<reviewer>-r<N>.json`",
        # One eval with each repo's base and commit.
        "`agent-hub/eval/2`",
        # One PR per repo, in order, linked, and recorded in merge order.
        "`gh pr create",
        "`gh pr edit <url> --body-file <file>`",
        "`## Merge order`",
        "`prs: [<repo>#<n>, …]`",
        "`--pr` once per pull request",
    ):
        assert expected in section, expected
