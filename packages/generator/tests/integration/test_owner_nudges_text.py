"""The rendered hub's ``AGENTS.md`` keeps secrets out of what agents write (fewer-owner-nudges).

Cross-repo rule 4 says a secret, including one a command's output printed, is never repeated in a
reply, a commit, a PR, a tracker comment or a brain note (AC-37). The line is generic: it adds no
placeholder to the template. Checked on the demo, two-team and conventions renders.
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
# The template's placeholder names, as on origin/main before this text: the new text adds none.
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
# Rule 4 and its wrapped lines, up to rule 5.
RULE_4 = re.compile(r"^4\. No secrets.*?(?=^5\. )", re.MULTILINE | re.DOTALL)
SECRET_ECHO_PLACES = ("reply", "commit", "PR", "tracker comment", "brain note")
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


def rule_4(agents: str) -> str:
    match = RULE_4.search(agents)
    assert match is not None
    return " ".join(match.group(0).split())


def test_secret_echo_rule_names_every_place_when_rendered(agents: str) -> None:
    rule = rule_4(agents)

    missing = [place for place in SECRET_ECHO_PLACES if not re.search(rf"\b{place}\b", rule)]
    assert missing == []


def test_secret_echo_rule_adds_no_placeholder_when_rendered(agents: str) -> None:
    template = files("agent_hub.generator").joinpath("templates/AGENTS.md.tmpl").read_text("utf-8")

    assert "@@" not in rule_4(agents)
    assert "brain note" in rule_4(agents)
    assert set(PLACEHOLDER.findall(template)) == AGENTS_PLACEHOLDERS
