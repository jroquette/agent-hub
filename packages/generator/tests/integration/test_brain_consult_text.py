"""The rendered hub tells agents to consult the brain through ``hub mcp`` (brain-consult).

The hub's ``AGENTS.md`` names the hub MCP's ``search``, ``read`` and ``propose`` in workflow
steps 2 and 3 and in the first "Brain rules" bullet: a search of 2 to 4 key words once the task
is known and again before a feature's research, how to weigh ``kind`` and ``status``, and the
``./hub`` fallback when the tools are missing, which never blocks the work. The lines are generic:
no project value reaches them. Checked on the demo, two-team and conventions renders.
"""

import re
from collections.abc import Callable
from importlib.resources import files
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

AGENTS = "AGENTS.md"
# The template's placeholder names, as on origin/main before the brain text (P-5): the new text
# adds none.
AGENTS_PLACEHOLDERS = frozenset(
    {
        "branch_rule",
        "commit_author",
        "conventions_section",
        "environments_section",
        "module_files",
        "module_seeded_files",
        "prefix_note",
        "project_name",
        "protected_branches",
        "repo_dirs",
        "tracker_team_mention",
        "worktree_base",
    }
)
PLACEHOLDER = re.compile(r"@@\{?(\w+)")
DOCUMENTS = [
    pytest.param(a_hub_document, id="demo"),
    pytest.param(a_two_team_document, id="two_teams"),
    pytest.param(a_conventions_document, id="conventions"),
]


@pytest.fixture(params=DOCUMENTS)
def config(request: pytest.FixtureRequest) -> HubConfig:
    document: Callable[[], dict[str, Any]] = request.param
    return HubConfig.model_validate(document())


@pytest.fixture
def agents(config: HubConfig) -> str:
    content = {file.path: file.content for file in render_hub(config).files}[AGENTS]
    assert content is not None
    return content.decode("utf-8")


def flat(text: str) -> str:
    """``text`` with every run of whitespace turned into one space."""
    return " ".join(text.split())


def section(agents: str, heading: str) -> str:
    """The raw text of the ``## heading`` section, up to the next one."""
    return agents.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def workflow_step(agents: str, number: int) -> str:
    """Workflow step ``number``'s raw text, up to the next step."""
    workflow = section(agents, "Workflow (every task)")
    start = workflow.index(f"\n{number}. ")
    return workflow[start : workflow.index(f"\n{number + 1}. ", start)]


def brain_rules_first_bullet(agents: str) -> str:
    """The raw text of the first "Brain rules" bullet."""
    rules = section(agents, "Brain rules").strip("\n")
    return re.split(r"\n(?=- )", rules)[0]


def new_text(agents: str) -> str:
    """Steps 2 and 3 and the first "Brain rules" bullet, raw."""
    return "\n".join(
        (workflow_step(agents, 2), workflow_step(agents, 3), brain_rules_first_bullet(agents))
    )


def test_agents_names_brain_tools_when_hub_rendered(agents: str) -> None:
    step_two = flat(workflow_step(agents, 2))
    step_three = flat(workflow_step(agents, 3))
    rules = flat(section(agents, "Brain rules"))

    for phrase in ("`search`", "`mcp__hub__search`", "`read`", "`mcp__hub__read`"):
        assert phrase in step_two, phrase
    for phrase in ("`search`", "Before research or planning"):
        assert phrase in step_three, phrase
    for phrase in (
        "`propose`",
        "`mcp__hub__propose`",
        "hub pull request",
        "refused where `gh` is missing",
        "`brain/_inbox/`",
        "final message",
    ):
        assert phrase in rules, phrase


def test_agents_query_takes_key_words_when_hub_rendered(agents: str) -> None:
    step_two = flat(workflow_step(agents, 2))

    for phrase in (
        "2 to 4 key words",
        "filler word",
        "the guard refuses it",
        "retry once with fewer words",
        "`kind: inbox`",
        "unreviewed proposal",
        "`status: approved` wins",
        "`draft`",
    ):
        assert phrase in step_two, phrase


def test_agents_generic_lines_hold_no_hub_value_when_hub_rendered(
    config: HubConfig, agents: str
) -> None:
    template = files("agent_hub.generator").joinpath("templates/AGENTS.md.tmpl").read_text("utf-8")
    values = {config.project.name, *(repo.dir for repo in config.repos)}
    values |= set(config.tracker.team_keys)

    assert set(PLACEHOLDER.findall(template)) == AGENTS_PLACEHOLDERS
    for line in new_text(agents).splitlines():
        for value in values:
            token = rf"(?<![\w-]){re.escape(value)}(?![\w-])"
            assert re.search(token, line) is None, (value, line)


def test_agents_fallback_never_blocks_when_mcp_missing(agents: str) -> None:
    step_two = flat(workflow_step(agents, 2))
    sentences = re.split(r"\. |; ", flat(new_text(agents)))
    naming_mcp = [
        sentence for sentence in sentences if "MCP" in sentence or "mcp__hub__" in sentence
    ]

    for phrase in (
        "`./hub brief`",
        "`./hub search <words>`",
        "hub directory (the one with `hub.json`)",
        "`brain/index.md`",
        "first message",
        "hub MCP was not loaded",
        "go on",
    ):
        assert phrase in step_two, phrase
    assert naming_mcp != []
    for sentence in naming_mcp:
        assert re.search(r"\b(stop|wait|ask)\b", sentence, re.IGNORECASE) is None, sentence
