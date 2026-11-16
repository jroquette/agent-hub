"""The skill source reader on real folders (AGH-164, S1, P1): stat-only listing under the skill
roots, bounded, no link followed, no FIFO opened for a blocking read, messages without paths."""

import os
import threading
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.skills.skill_sources import SkillLimits, SkillSources
from agent_hub.core.testing.skill_trees import (
    Fifo,
    Link,
    TreeEntry,
    a_skills_fixture_tree,
    write_tree,
)
from agent_hub.generator.skill_files import list_skill_sources, read_skill_file

LIMIT = 4_096
NO_BLOCK_SECONDS = 5.0
SKILLS = "plugin/hub-workflow/skills"


def paths_of(sources: SkillSources) -> list[str]:
    return [entry.path for entry in sources.files]


def a_hub(tmp_path: Path, tree: dict[str, TreeEntry]) -> Path:
    hub = tmp_path / "hub"
    hub.mkdir(parents=True)
    write_tree(hub, tree)
    return hub


def read_in_thread(hub: Path, path: str) -> bytes | UnreadHubFile:
    result: list[bytes | UnreadHubFile] = []
    worker = threading.Thread(
        target=lambda: result.append(read_skill_file(hub, path, max_bytes=LIMIT)), daemon=True
    )
    worker.start()
    worker.join(NO_BLOCK_SECONDS)
    assert not worker.is_alive(), f"reading {path} blocked"
    return result[0]


def test_lists_sources_when_fixture_tree_written(tmp_path: Path) -> None:
    tree = a_skills_fixture_tree()
    hub = a_hub(tmp_path, tree)

    sources = list_skill_sources(hub, SkillLimits())

    assert paths_of(sources) == sorted(tree)
    assert (sources.truncated, sources.skipped) == (False, 0)
    by_path = {entry.path: entry for entry in sources.files}
    link = by_path[".claude/skills/alpha"]
    assert (link.regular, link.link_target) == (False, "../../plugin/hub-workflow/skills/alpha")
    for path, entry in tree.items():
        if isinstance(entry, bytes):
            listed = by_path[path]
            assert listed.regular
            assert listed.link_target is None
            assert listed.size == len(entry)
            assert listed.mtime_ns == os.stat(hub / path).st_mtime_ns
    assert (
        read_skill_file(hub, f"{SKILLS}/alpha/SKILL.md", max_bytes=LIMIT)
        == tree[f"{SKILLS}/alpha/SKILL.md"]
    )


def escaping_tree() -> dict[str, TreeEntry]:
    return {
        ".claude/skills/out": Link("../../../outside"),
        ".claude/skills/abs": Link("/etc"),
        f"{SKILLS}/linked/SKILL.md": Link("../../../../../outside/SKILL.md"),
        f"{SKILLS}/alpha/SKILL.md": b"---\nname: alpha\n---\n",
        f"{SKILLS}/alpha/references/r.md": Link("../../../../../../outside/secret.md"),
        f"{SKILLS}/piped/SKILL.md": Fifo(),
        "plugin/hub-workflow/agents/evaluator.md": Link("/etc/passwd"),
    }


def test_never_follows_links_when_tree_has_escaping_links_and_fifo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "SKILL.md").write_bytes(b"---\nname: secret\n---\n")
    (outside / "secret.md").write_bytes(b"secret\n")
    tree = escaping_tree()
    hub = a_hub(tmp_path, tree)
    flags_opened: list[int] = []
    real_open = os.open

    def spy_open(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        flags_opened.append(flags)
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(os, "open", spy_open)
    sources = list_skill_sources(hub, SkillLimits())
    monkeypatch.setattr(os, "open", real_open)

    assert flags_opened
    assert all(flags & os.O_DIRECTORY for flags in flags_opened), "the listing opens no file"
    assert paths_of(sources) == sorted(tree)
    for entry in sources.files:
        written = tree[entry.path]
        if isinstance(written, Link):
            assert entry.link_target == written.target
        if not isinstance(written, bytes):
            assert not entry.regular
    piped = next(entry for entry in sources.files if entry.path.endswith("piped/SKILL.md"))
    assert piped.link_target is None
    refused = [
        ".claude/skills/out/SKILL.md",
        ".claude/skills/abs/passwd",
        f"{SKILLS}/linked/SKILL.md",
        f"{SKILLS}/alpha/references/r.md",
        f"{SKILLS}/piped/SKILL.md",
        "plugin/hub-workflow/agents/evaluator.md",
    ]
    for path in refused:
        read = read_in_thread(hub, path)
        assert isinstance(read, UnreadHubFile), path
        assert read.kind in {"not_regular", "missing"}, (path, read)
        assert "/" not in read.message, (path, read.message)
        assert str(tmp_path) not in read.message
    assert read_in_thread(hub, f"{SKILLS}/piped/SKILL.md") == UnreadHubFile(
        message="cannot read: not a regular file", is_missing=False, kind="not_regular"
    )


def test_stops_at_caps_when_tree_over_bounds(tmp_path: Path) -> None:
    many: dict[str, TreeEntry] = {f"{SKILLS}/s-{n:03d}/SKILL.md": b"# Skill\n" for n in range(501)}
    hub = a_hub(tmp_path / "skills", many)

    sources = list_skill_sources(hub, SkillLimits())

    folders = {path.rsplit("/", 1)[0] for path in paths_of(sources)}
    assert sources.truncated
    assert len(folders) == 500
    assert sources.skipped >= 1

    bundled: dict[str, TreeEntry] = {f"{SKILLS}/alpha/SKILL.md": b"# Alpha\n"}
    bundled |= {f"{SKILLS}/alpha/references/r-{n:03d}.md": b"r\n" for n in range(201)}
    hub = a_hub(tmp_path / "files", bundled)

    sources = list_skill_sources(hub, SkillLimits())

    assert sources.truncated
    assert len(sources.files) == 201


def test_stops_at_bounds_when_small_limits_given(tmp_path: Path) -> None:
    tree: dict[str, TreeEntry] = {
        f"plugin/{name}/skills/{name}-skill/SKILL.md": b"# S\n" for name in ("aa", "bb", "cc")
    }
    tree["plugin/aa/skills/deep/a/b/c/SKILL.md"] = b"too deep\n"
    tree["plugin/aa/skills/deep/a/b/ok.md"] = b"deep enough\n"
    tree[".claude/skills/long"] = Link("x" * 40)
    hub = a_hub(tmp_path, tree)

    by_folders = list_skill_sources(hub, SkillLimits(plugin_folders=2))
    by_names = list_skill_sources(hub, SkillLimits(names_examined=3))
    by_depth = list_skill_sources(hub, SkillLimits(link_chars=10))

    assert by_folders.truncated
    assert not any(path.startswith("plugin/cc/") for path in paths_of(by_folders))
    assert by_names.truncated
    assert len(by_names.files) < len(tree)
    listed = {entry.path: entry for entry in by_depth.files}
    assert "plugin/aa/skills/deep/a/b/ok.md" in listed
    assert "plugin/aa/skills/deep/a/b/c/SKILL.md" not in listed
    assert listed[".claude/skills/long"].link_target == ""


def test_never_lists_settings_local_when_present(tmp_path: Path) -> None:
    hub = a_hub(
        tmp_path,
        {
            ".claude/settings.json": b"{}\n",
            ".claude/settings.local.json": b'{"env": {"SECRET": "x"}}\n',
            ".claude/skills/.hidden/SKILL.md": b"# Hidden\n",
            "plugin/.hidden/skills/x/SKILL.md": b"# Hidden plugin\n",
        },
    )

    sources = list_skill_sources(hub, SkillLimits())
    read = read_skill_file(hub, ".claude/settings.local.json", max_bytes=LIMIT)

    assert paths_of(sources) == [".claude/settings.json"]
    assert isinstance(read, UnreadHubFile)
    assert read.kind == "missing"


def test_skips_name_when_not_utf8(tmp_path: Path) -> None:
    hub = a_hub(tmp_path, {f"{SKILLS}/alpha/SKILL.md": b"# Alpha\n"})
    os.close(os.open(bytes(hub / SKILLS / "alpha") + b"/bad-\xff.md", os.O_CREAT | os.O_WRONLY))

    sources = list_skill_sources(hub, SkillLimits())

    assert paths_of(sources) == [f"{SKILLS}/alpha/SKILL.md"]
    assert (sources.skipped, sources.truncated) == (1, False)


def test_lists_nothing_when_hub_has_no_roots(tmp_path: Path) -> None:
    sources = list_skill_sources(tmp_path, SkillLimits())

    assert sources == SkillSources(files=())


def test_lists_nothing_below_when_root_folder_is_link(tmp_path: Path) -> None:
    real = tmp_path / "elsewhere"
    write_tree(real, {"skills/alpha/SKILL.md": b"# Alpha\n"})
    hub = a_hub(tmp_path, {"plugin/hub-workflow": Link(str(real))})

    sources = list_skill_sources(hub, SkillLimits())
    read = read_skill_file(hub, f"{SKILLS}/alpha/SKILL.md", max_bytes=LIMIT)

    assert sources.files == ()
    assert isinstance(read, UnreadHubFile)
    assert read.kind == "not_regular"


@pytest.mark.parametrize("size", [LIMIT, LIMIT + 1])
def test_reads_up_to_cap_when_file_near_limit(tmp_path: Path, size: int) -> None:
    hub = a_hub(tmp_path, {f"{SKILLS}/alpha/SKILL.md": b"x" * size})

    read = read_skill_file(hub, f"{SKILLS}/alpha/SKILL.md", max_bytes=LIMIT)

    if size > LIMIT:
        assert isinstance(read, UnreadHubFile)
        assert read.kind == "too_large"
        assert "/" not in read.message
    else:
        assert read == b"x" * size
