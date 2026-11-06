"""The base plugin's agents, ``/recall`` and ``/learn`` use ``hub mcp`` (AGH-697).

An agent whose frontmatter lists its tools gets no MCP tool it does not name, so every agent of
``plugin/hub-workflow/agents/`` lists the hub MCP's two read-only tools (``mcp__hub__search``,
``mcp__hub__read``) after its built-in ones, never ``mcp__hub__propose``, and keeps its
``mutates_checkout``. Its prompt holds one line, the same in every agent, that searches the brain
for the task's topic and reads what matters before it concludes, with the ``./hub search`` or
Grep fallback. ``/recall`` searches through the MCP, then ``./hub search``, and only then ``rg``.
``/learn`` files a team learning with ``propose`` and writes the inbox note by hand only when the
tool is missing or refused for a reason other than its own text. Checked on the demo, two-team
and conventions renders.
"""

from collections.abc import Callable
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import (
    a_conventions_document,
    a_hub_document,
    a_two_team_document,
)
from agent_hub.generator.render_hub import render_hub

AGENTS_FOLDER = "plugin/hub-workflow/agents/"
# Each base agent's built-in tools, as on origin/main before AGH-697.
BUILTIN_TOOLS = {
    "architect": "Read, Grep, Glob, Bash, Write",
    "evaluator": "Read, Grep, Glob, Bash, Write",
    "planner": "Read, Grep, Glob, Bash, Write",
    "quality-reviewer": "Read, Grep, Glob, Bash",
    "requirements-analyst": "Read, Grep, Glob, Write",
    "researcher": "Read, Grep, Glob, Bash, Write",
    "security-reviewer": "Read, Grep, Glob, Bash",
    "spec-reviewer": "Read, Grep, Glob, Bash",
    "test-writer": "Read, Grep, Glob, Bash, Write",
    "ux-designer": "Read, Grep, Glob, Bash, Write",
}
HUB_READS = "mcp__hub__search, mcp__hub__read"
READ_ONLY = frozenset({"quality-reviewer", "researcher", "security-reviewer", "spec-reviewer"})
# What the agents' one brain line says.
BRAIN_PHRASES = (
    "**Brain:**",
    "`mcp__hub__search`",
    "task's topic",
    "2 to 4 key words",
    "filler word",
    "the guard refuses the call",
    "retry once with fewer words",
    "`mcp__hub__read`",
    "before you conclude",
    "`kind: inbox`",
    "never authoritative",
    "`status: approved` wins over `draft`",
    "`./hub search <words>`",
    "hub directory (the one with `hub.json`)",
    "Grep",
    "never blocks",
)
# What `/recall`'s first step says besides the three searches.
RECALL_PHRASES = (
    "2 to 4 key words",
    "filler words",
    "the guard refuses the call",
    "retry once with fewer words",
    "`mcp__hub__read`",
    "`kind: inbox`",
    "never authoritative",
    "`status: approved` wins over `draft`",
    "hub directory (the one with `hub.json`)",
    "hub MCP was not loaded",
)
MCP_SEARCH = "`mcp__hub__search`"
CLI_SEARCH = "`./hub search <words>`"
BRAIN_RG = '`rg -n -i "<terms>" brain/`'
JOURNAL_RG = '`rg -n -i "<terms>" brain/journal/`'
INBOX_NOTE = "`brain/_inbox/YYYY-MM-DD-<slug>.md`"
DOCUMENTS = [
    pytest.param(a_hub_document, id="demo"),
    pytest.param(a_two_team_document, id="two_teams"),
    pytest.param(a_conventions_document, id="conventions"),
]


@pytest.fixture(params=DOCUMENTS)
def texts(request: pytest.FixtureRequest) -> dict[str, str]:
    """Every rendered file with content, by path, decoded."""
    document: Callable[[], dict[str, Any]] = request.param
    config = HubConfig.model_validate(document())
    return {
        file.path: file.content.decode("utf-8")
        for file in render_hub(config).files
        if file.content is not None
    }


def agents(texts: dict[str, str]) -> dict[str, str]:
    """The base plugin's agent definitions, by name."""
    return {
        path.removeprefix(AGENTS_FOLDER).removesuffix(".md"): text
        for path, text in texts.items()
        if path.startswith(AGENTS_FOLDER) and path.endswith(".md")
    }


def frontmatter(text: str) -> list[str]:
    """The lines between the first ``---`` and the next one."""
    lines = text.splitlines()
    assert lines[0] == "---"
    return lines[1 : lines.index("---", 1)]


def body(text: str) -> str:
    """What follows the frontmatter."""
    return text.split("\n---\n", 1)[1]


def flat(text: str) -> str:
    """``text`` with every run of whitespace turned into one space."""
    return " ".join(text.split())


def test_lists_hub_mcp_reads_when_agent_rendered(texts: dict[str, str]) -> None:
    found = agents(texts)

    assert sorted(found) == sorted(BUILTIN_TOOLS)
    for name, text in found.items():
        head = frontmatter(text)
        assert [line for line in head if line.startswith("tools:")] == [
            f"tools: {BUILTIN_TOOLS[name]}, {HUB_READS}"
        ], name
        assert "mcp__hub__propose" not in text, name
        assert ("mutates_checkout: false" in head) == (name in READ_ONLY), name


def test_searches_brain_before_concluding_when_agent_rendered(texts: dict[str, str]) -> None:
    lines = {}
    for name, text in agents(texts).items():
        prompt = body(text)
        found = [line for line in prompt.splitlines() if MCP_SEARCH in line]
        assert len(found) == 1, name
        [line] = found
        for phrase in BRAIN_PHRASES:
            assert phrase in line, (name, phrase)
        # It comes with the agent's first reads: after its Start or Input line.
        starts = [prompt.index(label) for label in ("**Start:**", "**Input:**") if label in prompt]
        assert starts, name
        assert min(starts) < prompt.index(line), name
        lines[name] = line

    # One line, the same in every agent.
    assert len(set(lines.values())) == 1, lines


def test_recall_searches_mcp_then_cli_then_rg_when_rendered(texts: dict[str, str]) -> None:
    raw = texts["plugin/hub-workflow/skills/recall/SKILL.md"]
    text = flat(raw)
    journal = flat(next(line for line in raw.splitlines() if line.startswith("3. Journal")))

    assert text.index(MCP_SEARCH) < text.index(CLI_SEARCH) < text.index(BRAIN_RG)
    for phrase in RECALL_PHRASES:
        assert phrase in text, phrase
    assert "Only when neither" in text[text.index(CLI_SEARCH) : text.index(BRAIN_RG)]
    assert journal.index("`kind: journal`") < journal.index("`--kind journal`")
    assert journal.index("`--kind journal`") < journal.index(JOURNAL_RG)


def test_learn_proposes_through_mcp_before_inbox_note_when_rendered(
    texts: dict[str, str],
) -> None:
    raw = texts["plugin/hub-workflow/skills/learn/SKILL.md"]
    team, rest = raw.split("\n## personal\n", 1)
    text = flat(team)

    assert text.index("`mcp__hub__propose`") < text.index(INBOX_NOTE)
    for phrase in (
        "`title`",
        "`body`",
        "`kind`",
        "`external: true`",
        "`Sources:`",
        "`Target:`",
        "hub pull request",
        "`pr_url`",
    ):
        assert phrase in text, phrase
    fallback = text[text.index("`mcp__hub__propose`") : text.index(INBOX_NOTE)]
    for phrase in (
        "missing or refused",
        "`propose:`",
        "`gh`",
        "cloud session",
        "GraphQL",
        "by hand",
        "secret rule",
        "AI attribution",
        "never write refused text",
    ):
        assert phrase in fallback, phrase
    # `personal` and `promote` never propose.
    assert "mcp__hub__propose" not in rest
