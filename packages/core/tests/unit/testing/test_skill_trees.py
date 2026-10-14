import json
import stat
from pathlib import Path

from agent_hub.core.hub_files.hub_lock import HubLock, ManagedFileEntry, read_hub_lock
from agent_hub.core.skills.skill_sources import skill_relative
from agent_hub.core.testing.skill_trees import (
    FEATURE_BODY_STEPS,
    FIXTURE_PROJECT,
    Fifo,
    Link,
    a_feature_shaped_body,
    a_skills_fixture_tree,
    fake_hub_of,
    write_tree,
)


def test_writes_tree_when_root_given(tmp_path: Path) -> None:
    tree = {
        "plugin/p/skills/a/SKILL.md": b"# A\n",
        ".claude/skills/a": Link("../../plugin/p/skills/a"),
        ".claude/skills/b/SKILL.md": Fifo(),
    }

    write_tree(tmp_path, tree)

    assert (tmp_path / "plugin/p/skills/a/SKILL.md").read_bytes() == b"# A\n"
    link = tmp_path / ".claude/skills/a"
    assert link.is_symlink()
    assert str(link.readlink()) == "../../plugin/p/skills/a"
    assert stat.S_ISFIFO((tmp_path / ".claude/skills/b/SKILL.md").lstat().st_mode)


def test_lists_spec_items_when_fixture_tree_built() -> None:
    tree = a_skills_fixture_tree()

    skills = {path.split("/")[-2] for path in tree if path.endswith("/SKILL.md")}
    agents = {path.rsplit("/", 1)[-1] for path in tree if "/agents/" in path}
    assert skills == {"alpha", "beta", "gamma", "delta", "local-one"}
    assert agents == {"evaluator.md", "scout.md", "local-agent.md"}
    assert tree[".claude/skills/alpha"] == Link("../../plugin/hub-workflow/skills/alpha")
    assert FIXTURE_PROJECT == "demo"
    for path in tree:
        assert str(skill_relative(path)) == path
    hooks = json.loads(tree[".claude/settings.json"])["hooks"]  # type: ignore[arg-type]
    assert set(hooks) == {"PreToolUse", "SessionStart"}


def test_locks_hub_workflow_files_when_fixture_tree_built() -> None:
    tree = a_skills_fixture_tree()

    lock = read_hub_lock(tree["hub.lock"])  # type: ignore[arg-type]

    assert isinstance(lock, HubLock)
    entry = lock.files["plugin/hub-workflow/skills/alpha/SKILL.md"]
    assert isinstance(entry, ManagedFileEntry)
    assert "plugin/demo/skills/gamma/SKILL.md" not in lock.files


def test_holds_tree_when_fake_hub_built() -> None:
    hub = fake_hub_of(a_skills_fixture_tree(), now=b"# Now\n")

    assert hub.skill_links == {".claude/skills/alpha": "../../plugin/hub-workflow/skills/alpha"}
    assert "plugin/demo/agents/scout.md" in hub.skill_files
    assert isinstance(hub.lock, HubLock)
    assert hub.now == b"# Now\n"
    assert fake_hub_of({"plugin/p/skills/a/SKILL.md": Fifo()}).skill_specials == {
        "plugin/p/skills/a/SKILL.md"
    }


def test_numbers_steps_at_column_zero_when_feature_body_read() -> None:
    body = a_feature_shaped_body()

    top_level = [line for line in body.splitlines() if line[:1].isdigit()]
    assert len(top_level) == FEATURE_BODY_STEPS + 1  # the fenced "6." is not a step
    assert "`requirements-analyst`" in body
    assert "**Gate: user approves the spec**" in body
