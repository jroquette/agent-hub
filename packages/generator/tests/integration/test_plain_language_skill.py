"""The rendered ``plain-language`` skill (AGH-319): its sections, rules, sources and size.

The skill holds the rules for text that people read. The checks run on the demo hub's render;
whether an agent follows the rules is not testable from the text.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

SKILL = "plugin/hub-workflow/skills/plain-language/SKILL.md"
NOTICE = "plugin/hub-workflow/NOTICE"
# AC-4: the skill's sections, in order; AC-7: no other heading (no word list or dictionary).
SECTIONS = [
    "Text for people and text for agents",
    "Language",
    "Reply rules",
    "Code comments",
    "Document rules",
    "Never drop",
    "Sources",
]
# AC-5: the scope, the language rule, the reply and document rules, and what never drops.
RULE_PHRASES = (
    "chat replies to the user",
    "PR bodies and PR review replies",
    "tracker comments",
    "code comments",
    "journal entries",
    "brain notes that people read",
    "prompts to subagents and their replies",
    "keep full detail",
    "the language of their latest message",
    "uses the hub's language",
    "If neither sets one, use English",
    "The first sentence gives the answer or the result",
    "Great question",
    "define it in a few words",
    "No em-dashes. No contractions.",
    "Make the code explain itself first",
    "Comment only a why that the code cannot show",
    "name a ticket",
    "The repo's own `AGENTS.md` wins",
    "20 words or fewer",
    "25 words or fewer",
    "Put the condition before the command",
    "active voice",
    '"should", "would", "may" or "might"',
    "one word for one meaning",
    '"crucial", "robust" or "seamless"',
    "Short, but not terse",
    "Use lists and headings where they help a person scan",
    "These win over every rule above",
    "hedges that carry meaning",
    "scope limits",
    "open questions",
    "decisions that wait for the owner",
    "stay exact",
    "do not count toward the word limits",
)
# AC-6: the credits, with the trademark line and no text taken from the specification.
SOURCE_PHRASES = (
    "AminBlg/SimpleEnglish, under the MIT license",
    "ASD-STE100 is a trademark of ASD",
    "No text from the specification is used",
    "danyuchn/asd-ste100-skill",
    "simplified-english",
)
MAX_SKILL_LINES = 100
# AC-8: rule 6 of the rendered AGENTS.md points to the skill, in at most four lines.
MAX_RULE_LINES = 4
AGENTS_RULE_PHRASES = (
    "`plain-language`",
    "chat",
    "PRs",
    "tracker comments",
    "code comments",
    "handoffs",
    "summaries",
    "brain notes",
    "in the reader's language",
    "versioned text uses the hub's",
    "Text for agents keeps full detail",
)
# AC-10: each step that writes for people names the skill on the line that holds its anchor.
CITATIONS = [
    ("summarize", "Write in the language of the record."),
    ("handoff", "Facts only; no secrets"),
    ("feature", "**Finish**"),
    ("deliver", "**Review threads**"),
    ("deliver", "**Ready**"),
    ("deliver", "**Tracker**"),
]


def flat(text: str) -> str:
    """The text with every run of whitespace made one space, so phrases may wrap."""
    return " ".join(text.split())


def rendered_text(config: HubConfig, path: str) -> str:
    rendered = {file.path: file.content for file in render_hub(config).files}
    content = rendered[path]
    assert content is not None
    return content.decode("utf-8")


@pytest.fixture
def skill_text(demo_config: HubConfig) -> str:
    return rendered_text(demo_config, SKILL)


def headings(text: str) -> list[str]:
    return [line.removeprefix("## ") for line in text.splitlines() if line.startswith("## ")]


def section(text: str, heading: str) -> str:
    """The text of one ``## `` section, up to the next one or the end."""
    start = text.index(f"\n## {heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start : end if end != -1 else len(text)]


def test_has_plain_language_sections_when_skill_rendered(skill_text: str) -> None:
    assert headings(skill_text) == SECTIONS


def test_holds_plain_language_rules_when_skill_rendered(skill_text: str) -> None:
    text = flat(skill_text)
    for phrase in RULE_PHRASES:
        assert phrase in text, phrase


def test_credits_plain_language_sources_when_skill_rendered(skill_text: str) -> None:
    sources = flat(section(skill_text, "Sources"))
    for phrase in SOURCE_PHRASES:
        assert phrase in sources, phrase


def test_keeps_plain_language_size_when_skill_rendered(skill_text: str) -> None:
    lines = skill_text.splitlines()
    assert len(lines) <= MAX_SKILL_LINES
    assert not [line for line in lines if line.startswith("|")]
    assert [line for line in lines if line.startswith("##")] == [f"## {name}" for name in SECTIONS]


def test_credits_simple_english_when_notice_rendered(demo_config: HubConfig) -> None:
    notice = rendered_text(demo_config, NOTICE)
    assert notice.count("skills/plain-language") == 1
    assert notice.count("AminBlg/SimpleEnglish") == 1


def agents_rule(agents: str, number: int) -> str:
    """One item of ``## Cross-repo rules``, from ``<number>. `` to the next ``## `` heading."""
    rules = section(agents, "Cross-repo rules")
    start = rules.index(f"\n{number}. ") + 1
    end = rules.find("\n## ", start)
    return rules[start : end if end != -1 else len(rules)].rstrip("\n")


def test_states_agents_plain_language_rule_when_agents_rendered(
    demo_config: HubConfig, skill_text: str
) -> None:
    rule = agents_rule(rendered_text(demo_config, "AGENTS.md"), 6)

    assert len(rule.splitlines()) <= MAX_RULE_LINES
    text = flat(rule)
    for phrase in AGENTS_RULE_PHRASES:
        assert phrase in text, phrase
    # The doctor's `instructions.duplicates` compares lines of 60 or more characters.
    skill_lines = {line.strip() for line in skill_text.splitlines()}
    long_lines = [line.strip() for line in rule.splitlines() if len(line.strip()) >= 60]
    assert not [line for line in long_lines if line in skill_lines]


@pytest.mark.parametrize(("skill", "anchor"), CITATIONS)
def test_cites_plain_language_when_people_skills_rendered(
    demo_config: HubConfig, skill: str, anchor: str
) -> None:
    text = rendered_text(demo_config, f"plugin/hub-workflow/skills/{skill}/SKILL.md")
    lines = [line for line in text.splitlines() if anchor in line]

    assert len(lines) == 1, lines
    assert "`plain-language`" in lines[0]
