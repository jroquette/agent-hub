import re

import pytest

from agent_hub.core.errors import AgentHubError
from agent_hub.core.skills.skill_sources import (
    DEFAULT_LIMITS,
    RESERVED_SOURCES,
    SkillLimits,
    SkillPathError,
    file_id,
    role_label,
    role_of,
    skill_relative,
)
from agent_hub.core.skills.skill_view import FILE_ID

REFUSED = [
    "",
    "..",
    "/etc",
    "/etc/passwd",
    "a\\b",
    "brain/x.md",
    "hub.json",
    ".claude/settings.local.json",
    ".claude/skills/.hidden/x",
    ".claude/skills/../../hub.json",
    ".claude/skills/a/./SKILL.md",
    ".claude/skills/a//SKILL.md",
    ".claude/agents/x.txt",
    ".claude/agents/sub/x.md",
    "plugin/p/skills/n/a/b/c/d.txt",
    "plugin/p/README.md",
    "plugin/p/hooks/other.json",
    "plugin/.p/skills/n/SKILL.md",
    "plugin/p/skills/n/SKILL\x00.md",
    "plugin/p/commands/x.md",
    ".claude-plugin/plugin.json",
    "plugin/p/skills/" + "n" * 600 + "/SKILL.md",
]

ACCEPTED = [
    ".claude/skills/alpha",
    ".claude/skills/local-one/SKILL.md",
    ".claude/skills/local-one/references/r.md",
    ".claude/agents/local-agent.md",
    ".claude/settings.json",
    ".claude/settings.project.json",
    ".claude-plugin/marketplace.json",
    "hub.lock",
    "plugin/hub-workflow/skills/alpha",
    "plugin/hub-workflow/skills/alpha/SKILL.md",
    "plugin/hub-workflow/skills/alpha/scripts/s.sh",
    "plugin/hub-workflow/skills/alpha/a/b/c.txt",
    "plugin/hub-workflow/agents/evaluator.md",
    "plugin/hub-workflow/hooks/hooks.json",
]


@pytest.mark.parametrize("path", REFUSED, ids=repr)
def test_refuses_path_when_outside_skill_roots(path: str) -> None:
    with pytest.raises(SkillPathError) as raised:
        skill_relative(path)

    assert isinstance(raised.value, AgentHubError)
    assert raised.value.reason
    assert "/etc" not in raised.value.reason


@pytest.mark.parametrize("path", ACCEPTED)
def test_accepts_path_when_under_skill_roots(path: str) -> None:
    assert str(skill_relative(path)) == path


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("scripts/s.sh", "scripts"),
        ("references/r.md", "references"),
        ("assets/logo.png", "assets"),
        ("notes.md", "other"),
        ("templates/x.md", "other"),
        ("scripts", "other"),
    ],
)
def test_names_role_when_first_segment_known(path: str, role: str) -> None:
    assert role_of(path) == role


def test_labels_roles_when_role_shown() -> None:
    assert role_label("scripts") == "executed at invocation"
    assert role_label("references") == "read on demand"
    assert role_label("other") == "other"


def test_issues_short_hex_id_when_path_given() -> None:
    first = file_id("plugin/hub-workflow/skills/alpha/references/r.md")

    assert re.fullmatch(FILE_ID, first)
    assert first == file_id("plugin/hub-workflow/skills/alpha/references/r.md")
    assert first != file_id("plugin/hub-workflow/skills/alpha/scripts/s.sh")


def test_keeps_plan_bounds_when_limits_default() -> None:
    expected = SkillLimits(
        items_per_kind=500,
        files_per_skill=200,
        skill_depth=3,
        names_examined=20_000,
        plugin_folders=50,
        link_chars=512,
    )

    assert expected == DEFAULT_LIMITS
    assert sorted(RESERVED_SOURCES) == ["claude", "settings", "settings-project"]
