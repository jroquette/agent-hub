"""The skill source contract (AGH-164, S1, P1, AC-164.3): ``HubFileReader.skill_sources``,
``read_skill_file`` and ``read_unit`` (AGH-295, S2, D15, A1) on the in-memory fake and on the
file system adapter.

An implementation's ``tests/contract/`` provides a ``skill_tree`` fixture (an empty hub with
``write``, ``link``, ``fifo``, ``make_executable``, ``reader`` and ``hub_path``:
``InMemorySkillTree`` or ``DiskSkillTree`` from ``skill_trees``) and declares
``class Test<Implementation>(SkillSourcesContract)``. Checks raise ``AssertionError`` by hand:
core ships this suite without depending on pytest.
"""

import threading
from typing import Final, Protocol

from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadHubFile, UnreadUnit
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import MAX_UNIT_FILES, UnitContent, UnitFile
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES, SkillLimits, SkillSources

# A FIFO read must come back well before this (it must not block at all).
NO_BLOCK_SECONDS: Final = 5.0
MAX_BYTES: Final = 1_024
SKILL: Final = "plugin/hub-workflow/skills/alpha/SKILL.md"
AGENT: Final = "plugin/hub-workflow/agents/evaluator.md"
SKILL_UNIT: Final = "plugin/hub-workflow/skills/alpha"
HOOK_UNIT: Final = ".claude/settings.json"
WORKFLOW_UNIT: Final = "workflows/demo/review.yaml"
LOCAL_SETTINGS: Final = ".claude/settings.local.json"


class SkillTree(Protocol):
    """An empty hub the contract writes into, and the reader under test."""

    @property
    def hub_path(self) -> str:
        """The hub the reader reads."""
        ...

    @property
    def reader(self) -> HubFileReader:
        """The implementation under test."""
        ...

    def write(self, path: str, content: bytes) -> None:
        """Add a regular file at the hub-relative ``path``."""
        ...

    def link(self, path: str, target: str) -> None:
        """Add a link at ``path`` whose target text is ``target``."""
        ...

    def fifo(self, path: str) -> None:
        """Add a named pipe at ``path``."""
        ...

    def make_executable(self, path: str) -> None:
        """Set the executable bit of the file written at ``path``."""
        ...


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _paths(sources: SkillSources) -> list[str]:
    return [entry.path for entry in sources.files]


def _kind(read: bytes | UnreadHubFile) -> str | None:
    return read.kind if isinstance(read, UnreadHubFile) else None


def _unit_kind(read: UnitContent | UnreadUnit | None) -> str | None:
    return read.kind if isinstance(read, UnreadUnit) else None


def _unit_in_thread(tree: SkillTree, path: str, kind: UnitKind) -> UnitContent | UnreadUnit | None:
    result: list[UnitContent | UnreadUnit] = []

    def read() -> None:
        result.append(tree.reader.read_unit(tree.hub_path, path, kind=kind))

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    worker.join(NO_BLOCK_SECONDS)
    _check(not worker.is_alive(), f"reading the unit {path} blocked")
    return result[0] if result else None


def _read_in_thread(tree: SkillTree, path: str) -> bytes | UnreadHubFile | None:
    result: list[bytes | UnreadHubFile] = []

    def read() -> None:
        result.append(tree.reader.read_skill_file(tree.hub_path, path, max_bytes=MAX_BYTES))

    worker = threading.Thread(target=read, daemon=True)
    worker.start()
    worker.join(NO_BLOCK_SECONDS)
    _check(not worker.is_alive(), f"reading {path} blocked")
    return result[0] if result else None


class SkillSourcesContract:
    """List the skill roots stat-only, never follow a link, read regular files only, bounded."""

    def test_lists_regular_files_in_path_order_when_tree_written(
        self, skill_tree: SkillTree
    ) -> None:
        written = {
            SKILL: b"---\nname: alpha\n---\n# Alpha\n",
            "plugin/hub-workflow/skills/alpha/references/r.md": b"# R\n",
            AGENT: b"---\nname: evaluator\n---\nYou check.\n",
            "plugin/hub-workflow/hooks/hooks.json": b"{}\n",
            ".claude/skills/local-one/SKILL.md": b"# Local\n",
            ".claude/agents/local-agent.md": b"# Agent\n",
            ".claude/settings.json": b"{}\n",
            ".claude/settings.project.json": b"{}\n",
            ".claude-plugin/marketplace.json": b"{}\n",
            "hub.lock": b"{}\n",
        }
        for path, content in written.items():
            skill_tree.write(path, content)

        sources = skill_tree.reader.skill_sources(skill_tree.hub_path)

        _check(_paths(sources) == sorted(written), f"every root is listed in order: {sources}")
        for entry in sources.files:
            _check(entry.regular and entry.link_target is None, f"{entry.path} is a regular file")
            _check(entry.size == len(written[entry.path]), f"{entry.path} has its size")
            _check(isinstance(entry.mtime_ns, int), f"{entry.path} has a modification time")
        _check(not sources.truncated, "a small tree is not truncated")

    def test_lists_nothing_when_files_outside_roots(self, skill_tree: SkillTree) -> None:
        for path in (
            "hub.json",
            "brain/now.md",
            ".claude/settings.local.json",
            ".claude/commands/x.md",
            "plugin/hub-workflow/README.md",
            "plugin/hub-workflow/commands/x.md",
            "plugin/hub-workflow/skills/alpha/a/b/c/d.txt",
        ):
            skill_tree.write(path, b"x\n")

        sources = skill_tree.reader.skill_sources(skill_tree.hub_path)

        _check(_paths(sources) == [], f"nothing outside the roots is listed: {sources}")

    def test_lists_link_with_target_when_tree_has_link(self, skill_tree: SkillTree) -> None:
        skill_tree.write(SKILL, b"# Alpha\n")
        skill_tree.link(".claude/skills/alpha", "../../plugin/hub-workflow/skills/alpha")
        skill_tree.link(".claude/skills/out", "../../../outside")

        sources = skill_tree.reader.skill_sources(skill_tree.hub_path)

        links = {entry.path: entry for entry in sources.files if entry.link_target is not None}
        _check(set(links) == {".claude/skills/alpha", ".claude/skills/out"}, f"links: {sources}")
        alpha = links[".claude/skills/alpha"]
        _check(alpha.link_target == "../../plugin/hub-workflow/skills/alpha", "target text kept")
        _check(not alpha.regular, "a link is not a regular file")
        _check(".claude/skills/alpha/SKILL.md" not in _paths(sources), "a link is never followed")

    def test_refuses_link_when_read(self, skill_tree: SkillTree) -> None:
        skill_tree.write(AGENT, b"# Evaluator\n")
        skill_tree.link(
            ".claude/agents/evaluator.md", "../../plugin/hub-workflow/agents/evaluator.md"
        )

        read = skill_tree.reader.read_skill_file(
            skill_tree.hub_path, ".claude/agents/evaluator.md", max_bytes=MAX_BYTES
        )

        _check(_kind(read) == "not_regular", f"a link is not read through: {read!r}")

    def test_refuses_fifo_without_blocking_when_read(self, skill_tree: SkillTree) -> None:
        skill_tree.fifo(SKILL)

        sources = skill_tree.reader.skill_sources(skill_tree.hub_path)
        read = _read_in_thread(skill_tree, SKILL)

        entries = [entry for entry in sources.files if entry.path == SKILL]
        _check(len(entries) == 1, f"the FIFO is listed: {sources}")
        _check(not entries[0].regular and entries[0].link_target is None, "listed as special")
        _check(read is not None and _kind(read) == "not_regular", f"FIFO refused: {read!r}")

    def test_reads_bytes_when_file_regular(self, skill_tree: SkillTree) -> None:
        content = b"---\nname: alpha\n---\n# Alpha\n"
        skill_tree.write(SKILL, content)

        read = skill_tree.reader.read_skill_file(skill_tree.hub_path, SKILL, max_bytes=MAX_BYTES)

        _check(read == content, f"the bytes are read as written: {read!r}")

    def test_reports_too_large_when_over_max_bytes(self, skill_tree: SkillTree) -> None:
        skill_tree.write(SKILL, b"x" * (MAX_BYTES + 1))

        read = skill_tree.reader.read_skill_file(skill_tree.hub_path, SKILL, max_bytes=MAX_BYTES)

        _check(_kind(read) == "too_large", f"over the cap is too_large: {read!r}")

    def test_reads_missing_when_path_refused_or_absent(self, skill_tree: SkillTree) -> None:
        skill_tree.write("hub.json", b"{}\n")
        skill_tree.write(".claude/settings.local.json", b"{}\n")

        for path in (
            "../hub.json",
            "/etc/passwd",
            "hub.json",
            ".claude/settings.local.json",
            SKILL,
        ):
            read = skill_tree.reader.read_skill_file(skill_tree.hub_path, path, max_bytes=MAX_BYTES)
            _check(isinstance(read, UnreadHubFile), f"{path!r} is not read")
            if isinstance(read, UnreadHubFile):
                _check(read.kind == "missing" and read.is_missing, f"{path!r} reads missing")
                _check("/" not in read.message, f"{path!r}: the message holds no path")

    def test_sets_truncated_when_limits_small(self, skill_tree: SkillTree) -> None:
        for name in ("alpha", "beta", "gamma"):
            skill_tree.write(f"plugin/hub-workflow/skills/{name}/SKILL.md", b"# Skill\n")

        sources = skill_tree.reader.skill_sources(
            skill_tree.hub_path, limits=SkillLimits(items_per_kind=2)
        )

        folders = {path.rsplit("/", 1)[0] for path in _paths(sources)}
        _check(sources.truncated, f"a bound sets truncated: {sources}")
        _check(len(folders) <= 2, f"at most two skill folders are listed: {sources}")

    def test_reads_folder_with_bits_when_unit_read(self, skill_tree: SkillTree) -> None:
        skill, reference, script = b"# Alpha\n", b"# R\n", b"#!/bin/sh\necho alpha\n"
        skill_tree.write(SKILL, skill)
        skill_tree.write(f"{SKILL_UNIT}/references/r.md", reference)
        skill_tree.write(f"{SKILL_UNIT}/scripts/s.sh", script)
        skill_tree.make_executable(f"{SKILL_UNIT}/scripts/s.sh")
        files = {AGENT: b"# Evaluator\n", HOOK_UNIT: b"{}\n", WORKFLOW_UNIT: b"name: review\n"}
        for path, content in files.items():
            skill_tree.write(path, content)

        folder = skill_tree.reader.read_unit(skill_tree.hub_path, SKILL_UNIT, kind=UnitKind.SKILL)
        units = {
            path: skill_tree.reader.read_unit(skill_tree.hub_path, path, kind=kind)
            for path, kind in (
                (AGENT, UnitKind.AGENT),
                (HOOK_UNIT, UnitKind.HOOK),
                (WORKFLOW_UNIT, UnitKind.WORKFLOW),
            )
        }

        expected = UnitContent(
            files=(
                UnitFile(path="SKILL.md", content=skill),
                UnitFile(path="references/r.md", content=reference),
                UnitFile(path="scripts/s.sh", content=script, executable=True),
            )
        )
        _check(folder == expected, f"the folder is read with each bit: {folder!r}")
        for path, read in units.items():
            name = path.rsplit("/", 1)[-1]
            one = UnitContent(files=(UnitFile(path=name, content=files[path]),))
            _check(read == one, f"{path} is one file named after it: {read!r}")

    def test_reports_too_large_when_unit_past_bounds(self, skill_tree: SkillTree) -> None:
        big = "plugin/hub-workflow/skills/big"
        many = "plugin/hub-workflow/skills/many"
        deep = "plugin/hub-workflow/skills/deep"
        for folder in (big, many, deep):
            skill_tree.write(f"{folder}/SKILL.md", b"# Skill\n")
        skill_tree.write(f"{big}/references/r.md", b"x" * (MAX_SKILL_FILE_BYTES + 1))
        for number in range(MAX_UNIT_FILES):
            skill_tree.write(f"{many}/references/r{number:03}.md", b"# R\n")
        skill_tree.write(f"{deep}/a/b/c/d.md", b"# Deep\n")
        skill_tree.write(HOOK_UNIT, b"{}" + b" " * MAX_SKILL_FILE_BYTES)

        for path, kind in (
            (big, UnitKind.SKILL),
            (many, UnitKind.SKILL),
            (deep, UnitKind.SKILL),
            (HOOK_UNIT, UnitKind.HOOK),
        ):
            read = skill_tree.reader.read_unit(skill_tree.hub_path, path, kind=kind)
            _check(_unit_kind(read) == "too_large", f"{path} is too_large: {read!r}")

    def test_reports_unreadable_when_link_inside_unit(self, skill_tree: SkillTree) -> None:
        linked = "plugin/hub-workflow/skills/linked"
        piped = "plugin/hub-workflow/skills/piped"
        for folder in (SKILL_UNIT, linked, piped):
            skill_tree.write(f"{folder}/SKILL.md", b"# Skill\n")
        skill_tree.link(f"{linked}/references", "../alpha")
        skill_tree.fifo(f"{piped}/scripts/s.sh")
        skill_tree.link(".claude/skills/alpha", "../../plugin/hub-workflow/skills/alpha")
        skill_tree.write("plugin/hub-workflow/agents/target.md", b"# Target\n")
        skill_tree.link(AGENT, "target.md")
        skill_tree.fifo(HOOK_UNIT)

        for path, kind in (
            (linked, UnitKind.SKILL),
            (piped, UnitKind.SKILL),
            (".claude/skills/alpha", UnitKind.SKILL),
            (AGENT, UnitKind.AGENT),
            (HOOK_UNIT, UnitKind.HOOK),
        ):
            read = _unit_in_thread(skill_tree, path, kind)
            _check(_unit_kind(read) == "unreadable", f"{path} is unreadable: {read!r}")

    def test_reports_missing_when_unit_absent(self, skill_tree: SkillTree) -> None:
        skill_tree.write(f"{SKILL_UNIT}/references/r.md", b"# R\n")
        skill_tree.write(AGENT, b"# Evaluator\n")
        skill_tree.write("hub.json", b"{}\n")

        for path, kind in (
            ("plugin/hub-workflow/skills/absent", UnitKind.SKILL),
            (SKILL_UNIT, UnitKind.SKILL),
            ("plugin/hub-workflow/agents/absent.md", UnitKind.AGENT),
            (AGENT, UnitKind.SKILL),
            (AGENT, UnitKind.HOOK),
            ("hub.json", UnitKind.HOOK),
            ("../hub.json", UnitKind.AGENT),
            ("workflows/demo/absent.yaml", UnitKind.WORKFLOW),
            ("workflows/demo/notes.md", UnitKind.WORKFLOW),
        ):
            read = skill_tree.reader.read_unit(skill_tree.hub_path, path, kind=kind)
            _check(_unit_kind(read) == "missing", f"{path} as {kind} reads missing: {read!r}")

    def test_never_opens_local_settings_when_unit_read(self, skill_tree: SkillTree) -> None:
        # A FIFO: opening it would make the read ``unreadable``; refused first, it is ``missing``.
        skill_tree.fifo(LOCAL_SETTINGS)

        read = _unit_in_thread(skill_tree, LOCAL_SETTINGS, UnitKind.HOOK)

        _check(_unit_kind(read) == "missing", f"personal settings are never read: {read!r}")
