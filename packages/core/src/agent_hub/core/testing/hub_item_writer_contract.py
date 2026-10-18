"""The ``HubItemWriter`` contract (AGH-295, S4, D7, AC-295.24, .25, .26): the in-memory fake and
the generator's file system writer honour it.

An implementation's ``tests/contract/`` provides a ``writer_tree`` fixture (an empty hub with
``write``, ``link``, ``make_executable``, ``make_read_only``, ``files``, ``is_executable``,
``exists``, ``names``, ``writer`` and ``hub_path``) and declares
``class Test<Implementation>(HubItemWriterContract)``. Checks raise ``AssertionError`` by hand:
core ships this suite without depending on pytest.
"""

from typing import Final, Protocol

from agent_hub.core.hub_files.tree_snapshot import is_leftover_name
from agent_hub.core.item_versions.hub_item_writer import (
    HubItemWriteError,
    HubItemWriter,
    ItemWriteRefusedError,
)
from agent_hub.core.item_versions.item_version import UnitKind
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.skills.skill_sources import DEFAULT_LIMITS

SKILL_UNIT: Final = "plugin/demo/skills/alpha"
SKILLS_FOLDER: Final = "plugin/demo/skills"
AGENT_UNIT: Final = ".claude/agents/reviewer.md"
SKILL_V1: Final = b"---\nname: alpha\n---\n# Alpha v1\n"


class WriterTree(Protocol):
    """An empty hub the contract writes into and inspects, and the writer under test."""

    @property
    def hub_path(self) -> str:
        """The hub the writer writes."""
        ...

    @property
    def writer(self) -> HubItemWriter:
        """The implementation under test."""
        ...

    def write(self, path: str, content: bytes) -> None:
        """Add a regular file at the hub-relative ``path``."""
        ...

    def link(self, path: str, target: str) -> None:
        """Add a link at ``path`` whose target text is ``target``."""
        ...

    def make_executable(self, path: str) -> None:
        """Set the executable bit of the file at ``path``."""
        ...

    def make_read_only(self) -> None:
        """Make the whole hub unwritable, as a read-only mount does."""
        ...

    def files(self, below: str) -> dict[str, bytes]:
        """Every regular file under the folder ``below``, by path relative to it."""
        ...

    def is_executable(self, path: str) -> bool:
        """Whether the file at ``path`` has its executable bit."""
        ...

    def exists(self, path: str) -> bool:
        """Whether anything (file, folder, link) is at ``path``; a link is not followed."""
        ...

    def names(self, folder: str) -> set[str]:
        """The names directly in ``folder``, hidden ones included."""
        ...


def _check(condition: bool, message: str) -> None:  # noqa: FBT001 -- an assertion's condition
    if not condition:
        raise AssertionError(message)


def _content(*files: UnitFile) -> UnitContent:
    return UnitContent(files=tuple(sorted(files, key=lambda file: file.path)))


def _refusal(
    tree: WriterTree, unit_path: str, content: UnitContent, *, kind: UnitKind
) -> str | None:
    try:
        tree.writer.write_unit(tree.hub_path, unit_path, content, kind=kind)
    except ItemWriteRefusedError as error:
        return error.code
    return None


def _no_leftover(tree: WriterTree, folder: str) -> None:
    left = {name for name in tree.names(folder) if is_leftover_name(name)}
    _check(not left, f"temp entries left in {folder}: {sorted(left)}")


def _v1() -> UnitContent:
    return _content(
        UnitFile(path="SKILL.md", content=SKILL_V1),
        UnitFile(path="references/r.md", content=b"# R v1\n"),
        UnitFile(path="scripts/s.sh", content=b"#!/bin/sh\necho v1\n", executable=True),
    )


class HubItemWriterContract:
    """Write units whole, never through a link, never leaving a mix or a temp entry."""

    def test_writes_file_unit_when_written(self, writer_tree: WriterTree) -> None:
        writer_tree.write(AGENT_UNIT, b"old\n")
        new_agent = "plugin/demo/agents/planner.md"
        writer_tree.writer.write_unit(
            writer_tree.hub_path,
            AGENT_UNIT,
            _content(UnitFile(path="reviewer.md", content=b"new\n")),
            kind=UnitKind.AGENT,
        )
        writer_tree.writer.write_unit(
            writer_tree.hub_path,
            new_agent,
            _content(UnitFile(path="planner.md", content=b"planner\n", executable=True)),
            kind=UnitKind.AGENT,
        )
        _check(writer_tree.files(".claude/agents") == {"reviewer.md": b"new\n"}, "agent rewritten")
        _check(not writer_tree.is_executable(AGENT_UNIT), "a plain file stays plain")
        _check(
            writer_tree.files("plugin/demo/agents") == {"planner.md": b"planner\n"},
            "a new agent is written with its folders",
        )
        _check(writer_tree.is_executable(new_agent), "the executable bit is set")
        _no_leftover(writer_tree, ".claude/agents")
        _no_leftover(writer_tree, "plugin/demo/agents")

    def test_writes_plain_file_when_file_written(self, writer_tree: WriterTree) -> None:
        script = "plugin/demo/scripts/check.sh"
        writer_tree.writer.write_file(writer_tree.hub_path, script, b"#!/bin/sh\n", executable=True)
        _check(writer_tree.files("plugin/demo/scripts") == {"check.sh": b"#!/bin/sh\n"}, "written")
        _check(writer_tree.is_executable(script), "the script is executable")
        _no_leftover(writer_tree, "plugin/demo/scripts")

    def test_makes_folder_equal_when_folder_written(self, writer_tree: WriterTree) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", SKILL_V1)
        writer_tree.write(f"{SKILL_UNIT}/references/r.md", b"# R changed\n")
        writer_tree.write(f"{SKILL_UNIT}/scripts/s.sh", b"#!/bin/sh\necho v1\n")
        writer_tree.write(f"{SKILL_UNIT}/assets/new.png", b"\x89PNG")
        writer_tree.write(f"{SKILL_UNIT}/assets/deep/more.png", b"\x89PNG")
        writer_tree.make_executable(f"{SKILL_UNIT}/references/r.md")
        writer_tree.writer.write_unit(writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)
        found = writer_tree.files(SKILL_UNIT)
        expected = {file.path: file.content for file in _v1().files}
        _check(found == expected, f"the folder equals the version: {sorted(found)}")
        _check(writer_tree.is_executable(f"{SKILL_UNIT}/scripts/s.sh"), "s.sh executable again")
        _check(not writer_tree.is_executable(f"{SKILL_UNIT}/references/r.md"), "r.md plain")
        _check(not writer_tree.exists(f"{SKILL_UNIT}/assets"), "now-empty folders are removed")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_writes_new_folder_when_unit_absent(self, writer_tree: WriterTree) -> None:
        writer_tree.writer.write_unit(writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)
        expected = {file.path: file.content for file in _v1().files}
        _check(writer_tree.files(SKILL_UNIT) == expected, "the new folder holds the version")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_keeps_hidden_entries_when_folder_written(self, writer_tree: WriterTree) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        writer_tree.write(f"{SKILL_UNIT}/.cache/data", b"cached")
        writer_tree.write(f"{SKILL_UNIT}/notes/.keep", b"kept")
        writer_tree.write(f"{SKILL_UNIT}/notes/old.md", b"# old note\n")
        writer_tree.link(f"{SKILL_UNIT}/.current", "SKILL.md")
        writer_tree.write(f"{SKILL_UNIT}/.SKILL.md.hub-tmp-0123abcd", b"a crash leftover")
        version = _content(UnitFile(path="SKILL.md", content=SKILL_V1))
        writer_tree.writer.write_unit(
            writer_tree.hub_path, SKILL_UNIT, version, kind=UnitKind.SKILL
        )
        found = writer_tree.files(SKILL_UNIT)
        expected = {"SKILL.md": SKILL_V1, ".cache/data": b"cached", "notes/.keep": b"kept"}
        _check(found == expected, f"hidden entries kept unchanged, the rest the version: {found}")
        _check(writer_tree.exists(f"{SKILL_UNIT}/.current"), "a hidden link is kept")
        _no_leftover(writer_tree, SKILL_UNIT)
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_refuses_link_when_target_component_is_link(self, writer_tree: WriterTree) -> None:
        writer_tree.write("elsewhere/alpha/SKILL.md", b"# elsewhere\n")
        writer_tree.link("plugin/demo/skills", "../../elsewhere")
        writer_tree.write("elsewhere/agent.md", b"agent\n")
        writer_tree.link(AGENT_UNIT, "../../elsewhere/agent.md")
        for path in (SKILL_UNIT, AGENT_UNIT):
            try:
                writer_tree.writer.check_targets(writer_tree.hub_path, [path])
            except ItemWriteRefusedError as error:
                _check(error.code == "link_in_path", f"{path}: refused as {error.code}")
            else:
                raise AssertionError(f"{path}: a linked component passed the check")
        agent = _content(UnitFile(path="reviewer.md", content=b"new\n"))
        _check(
            _refusal(writer_tree, SKILL_UNIT, _v1(), kind=UnitKind.SKILL) == "link_in_path", "skill"
        )
        _check(
            _refusal(writer_tree, AGENT_UNIT, agent, kind=UnitKind.AGENT) == "link_in_path", "agent"
        )
        expected = {"alpha/SKILL.md": b"# elsewhere\n", "agent.md": b"agent\n"}
        _check(writer_tree.files("elsewhere") == expected, "nothing written through a link")
        writer_tree.writer.check_targets(writer_tree.hub_path, ["plugin/other/agents/new.md"])

    def test_removes_unit_when_removed(self, writer_tree: WriterTree) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", SKILL_V1)
        writer_tree.write(f"{SKILL_UNIT}/references/r.md", b"# R\n")
        writer_tree.write(AGENT_UNIT, b"agent\n")
        writer_tree.write(".claude/agents/other.md", b"other\n")
        writer_tree.writer.remove_unit(writer_tree.hub_path, SKILL_UNIT, kind=UnitKind.SKILL)
        writer_tree.writer.remove_unit(writer_tree.hub_path, AGENT_UNIT, kind=UnitKind.AGENT)
        _check(not writer_tree.exists(SKILL_UNIT), "the skill folder is gone")
        _check(writer_tree.files(".claude/agents") == {"other.md": b"other\n"}, "one agent gone")
        writer_tree.writer.remove_unit(writer_tree.hub_path, SKILL_UNIT, kind=UnitKind.SKILL)
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_reports_not_writable_when_hub_read_only(self, writer_tree: WriterTree) -> None:
        writer_tree.write(AGENT_UNIT, b"old\n")
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        _check(writer_tree.writer.is_writable(writer_tree.hub_path, [AGENT_UNIT]), "writable")
        writer_tree.make_read_only()
        _check(not writer_tree.writer.is_writable(writer_tree.hub_path), "the hub is read-only")
        _check(
            not writer_tree.writer.is_writable(writer_tree.hub_path, [SKILL_UNIT]),
            "the unit's folder is read-only",
        )
        agent = _content(UnitFile(path="reviewer.md", content=b"new\n"))
        _check(
            _refusal(writer_tree, AGENT_UNIT, agent, kind=UnitKind.AGENT) == "hub_read_only", "file"
        )
        _check(
            _refusal(writer_tree, SKILL_UNIT, _v1(), kind=UnitKind.SKILL) == "hub_read_only", "dir"
        )
        _check(writer_tree.files(".claude/agents") == {"reviewer.md": b"old\n"}, "agent unchanged")
        _check(writer_tree.files(SKILL_UNIT) == {"SKILL.md": b"# old\n"}, "skill unchanged")

    def test_refuses_path_when_not_plain_or_not_a_unit(self, writer_tree: WriterTree) -> None:
        agent = _content(UnitFile(path="x.md", content=b"x\n"))
        for unit_path in ("../outside/agents/x.md", "/abs/.claude/agents/x.md", "agents/x.md"):
            try:
                writer_tree.writer.write_unit(
                    writer_tree.hub_path, unit_path, agent, kind=UnitKind.AGENT
                )
            except ValueError as error:
                _check(unit_path not in str(error), "the error names no path")
            else:
                raise AssertionError(f"{unit_path}: written")
        try:
            writer_tree.writer.write_file(writer_tree.hub_path, "plugin/../../x.sh", b"x")
        except ValueError:
            pass
        else:
            raise AssertionError("a path climbing out of the hub was written")

    def test_refuses_version_when_it_holds_hidden_name(self, writer_tree: WriterTree) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        writer_tree.write(f"{SKILL_UNIT}/.cache/data", b"cached")
        for hidden in (".cache/other", "notes/.draft"):
            version = _content(
                UnitFile(path="SKILL.md", content=SKILL_V1), UnitFile(path=hidden, content=b"x")
            )
            try:
                writer_tree.writer.write_unit(
                    writer_tree.hub_path, SKILL_UNIT, version, kind=UnitKind.SKILL
                )
            except ValueError as error:
                _check(hidden not in str(error), "the error names no path")
            else:
                raise AssertionError(f"{hidden}: a hidden name was written")
        expected = {"SKILL.md": b"# old\n", ".cache/data": b"cached"}
        _check(writer_tree.files(SKILL_UNIT) == expected, "nothing changed")

    def test_refuses_file_when_not_a_hook_script(self, writer_tree: WriterTree) -> None:
        refused = (
            ".claude/settings.json",
            "plugin/demo/agents/x.md",
            "plugin/demo/hooks/hooks.json",
            "plugin/demo/hooks/check.sh",
            "plugin/demo/scripts/.hidden.sh",
            "plugin/demo/check.sh",
            "workflows/demo/x.yaml",
        )
        for path in refused:
            try:
                writer_tree.writer.write_file(writer_tree.hub_path, path, b"x")
            except ValueError as error:
                _check(path not in str(error), "the error names no path")
            else:
                raise AssertionError(f"{path}: written")
            _check(not writer_tree.exists(path), f"{path}: nothing written")
        writer_tree.writer.write_file(writer_tree.hub_path, "plugin/demo/scripts/lib/a.sh", b"a")
        _check(writer_tree.files("plugin/demo/scripts") == {"lib/a.sh": b"a"}, "a script")

    def test_refuses_link_when_skill_folder_is_link(self, writer_tree: WriterTree) -> None:
        writer_tree.write("elsewhere/alpha/SKILL.md", b"# elsewhere\n")
        writer_tree.link(SKILL_UNIT, "../../../elsewhere/alpha")
        try:
            writer_tree.writer.check_targets(writer_tree.hub_path, [SKILL_UNIT])
        except ItemWriteRefusedError as error:
            _check(error.code == "link_in_path", f"refused as {error.code}")
        else:
            raise AssertionError("a linked skill folder passed the check")
        refused = _refusal(writer_tree, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)
        _check(refused == "link_in_path", f"the write is refused: {refused}")
        _check(writer_tree.exists(SKILL_UNIT), "the link stays")
        expected = {"alpha/SKILL.md": b"# elsewhere\n"}
        _check(writer_tree.files("elsewhere") == expected, "nothing written through the link")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_removes_inner_link_when_folder_written(self, writer_tree: WriterTree) -> None:
        writer_tree.write("elsewhere/data.md", b"kept\n")
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        writer_tree.link(f"{SKILL_UNIT}/references", "../../../../elsewhere")
        writer_tree.link(f"{SKILL_UNIT}/r.md", "../../../../elsewhere/data.md")
        writer_tree.writer.write_unit(writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)
        expected = {file.path: file.content for file in _v1().files}
        _check(writer_tree.files(SKILL_UNIT) == expected, "the folder equals the version")
        _check(not writer_tree.exists(f"{SKILL_UNIT}/r.md"), "the inner link is removed")
        _check(writer_tree.files("elsewhere") == {"data.md": b"kept\n"}, "its target untouched")

    def test_fails_when_skill_path_is_file(self, writer_tree: WriterTree) -> None:
        writer_tree.write(SKILL_UNIT, b"not a folder\n")
        try:
            writer_tree.writer.write_unit(
                writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL
            )
        except HubItemWriteError as error:
            _check(error.kind == "failed", f"the unit is as it was: {error.kind}")
        else:
            raise AssertionError("a file was written over as a folder")
        _check(writer_tree.files(SKILLS_FOLDER) == {"alpha": b"not a folder\n"}, "unchanged")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_fails_when_version_file_is_hidden_entries_folder(
        self, writer_tree: WriterTree
    ) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        writer_tree.write(f"{SKILL_UNIT}/notes/.keep", b"kept")
        version = _content(
            UnitFile(path="SKILL.md", content=SKILL_V1), UnitFile(path="notes", content=b"x")
        )
        try:
            writer_tree.writer.write_unit(
                writer_tree.hub_path, SKILL_UNIT, version, kind=UnitKind.SKILL
            )
        except HubItemWriteError as error:
            _check(error.kind == "failed", f"the unit is as it was: {error.kind}")
        else:
            raise AssertionError("a hidden entry's folder was written over")
        expected = {"SKILL.md": b"# old\n", "notes/.keep": b"kept"}
        _check(writer_tree.files(SKILL_UNIT) == expected, "unchanged")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_carries_hidden_entry_when_at_deepest_folder(self, writer_tree: WriterTree) -> None:
        deep = "refs/a/b/.gitkeep"
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        writer_tree.write(f"{SKILL_UNIT}/refs/a/c.md", b"c")
        writer_tree.write(f"{SKILL_UNIT}/{deep}", b"kept")
        writer_tree.writer.write_unit(writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)
        expected = {file.path: file.content for file in _v1().files} | {deep: b"kept"}
        _check(writer_tree.files(SKILL_UNIT) == expected, "the deepest hidden entry is kept")

    def test_fails_when_old_folder_deeper_than_a_unit(self, writer_tree: WriterTree) -> None:
        tree = {"SKILL.md": b"# old\n", "a/b/c/d.md": b"too deep", "a/b/.keep": b"k"}
        for path, content in tree.items():
            writer_tree.write(f"{SKILL_UNIT}/{path}", content)
        try:
            writer_tree.writer.write_unit(
                writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL
            )
        except HubItemWriteError as error:
            _check(error.kind == "failed", f"the unit is as it was: {error.kind}")
        else:
            raise AssertionError("a folder deeper than a unit was swapped")
        _check(writer_tree.files(SKILL_UNIT) == tree, "unchanged")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_writes_when_old_folder_holds_names_examined_exactly(
        self, writer_tree: WriterTree
    ) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        # With SKILL.md, exactly the names a unit read examines: at the bound, not past it.
        hidden = {f".n{number}": b"" for number in range(DEFAULT_LIMITS.names_examined - 1)}
        for path, content in hidden.items():
            writer_tree.write(f"{SKILL_UNIT}/{path}", content)

        writer_tree.writer.write_unit(writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL)

        expected = {file.path: file.content for file in _v1().files} | hidden
        _check(writer_tree.files(SKILL_UNIT) == expected, "the version, its hidden names kept")
        _no_leftover(writer_tree, SKILLS_FOLDER)

    def test_fails_when_old_folder_holds_more_names_than_examined(
        self, writer_tree: WriterTree
    ) -> None:
        writer_tree.write(f"{SKILL_UNIT}/SKILL.md", b"# old\n")
        # With SKILL.md, one name past the budget a unit read examines.
        for number in range(DEFAULT_LIMITS.names_examined):
            writer_tree.write(f"{SKILL_UNIT}/.n{number}", b"")
        try:
            writer_tree.writer.write_unit(
                writer_tree.hub_path, SKILL_UNIT, _v1(), kind=UnitKind.SKILL
            )
        except HubItemWriteError as error:
            _check(error.kind == "failed", f"the unit is as it was: {error.kind}")
        else:
            raise AssertionError("a folder past the names budget was swapped")
        _check(writer_tree.files(SKILL_UNIT)["SKILL.md"] == b"# old\n", "unchanged")
        _no_leftover(writer_tree, SKILLS_FOLDER)
