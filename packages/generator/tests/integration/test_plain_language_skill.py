"""The rendered ``plain-language`` skill (AGH-319): its sections, rules, sources and size.

The skill holds the rules for text that people read. The checks run on the demo hub's render;
whether an agent follows the rules is not testable from the text.
"""

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

SKILL = "plugin/hub-workflow/skills/plain-language/SKILL.md"
# AC-4: the skill's sections, in order; AC-7: no other heading (no word list or dictionary).
SECTIONS = [
    "Text for people and text for agents",
    "Language",
    "Reply rules",
    "Document rules",
    "Never drop",
    "Sources",
]
# AC-5: the scope, the language rule, the reply and document rules, and what never drops.
RULE_PHRASES = (
    "chat replies to the user",
    "PR bodies and PR review replies",
    "tracker comments",
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
