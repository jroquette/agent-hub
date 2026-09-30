"""The file sets and the frontmatter the config-lint rules share (``config_lint.py``).

The port of the hub's ``agent_config_lint.py`` machinery: instruction files, plugin agent and
skill files, their text and frontmatter. Only listed regular files count: a link, to a file or a
folder, is never followed (spec D3, Q-6; plan E1).
"""

from collections.abc import Callable

import pytest

from agent_hub.core.doctor.config_lint import (
    Frontmatter,
    TextProblem,
    Unterminated,
    agent_skill_files,
    file_text,
    instruction_files,
    parse_frontmatter,
    plugin_files,
)
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]

TEXT = b"# A title\n"
TEXT_FIX = "save it as UTF-8 text"


def files_at(*paths: str) -> dict[str, bytes]:
    return dict.fromkeys(paths, TEXT)


class TestInstructionFiles:
    INSTRUCTION = (
        ".claude/agents/a.md",
        ".claude/commands/deep/c.md",
        ".claude/rules/r.md",
        ".claude/skills/s/SKILL.md",
        ".github/copilot-instructions.md",
        ".github/instructions/i.md",
        "AGENTS.md",
        "CLAUDE.local.md",
        "CLAUDE.md",
        "GEMINI.md",
    )
    NOT_INSTRUCTION = (
        ".claude/agents/notes.txt",
        ".claude/settings.json",
        ".claude/worktrees/x/AGENTS.md",
        ".github/workflows/ci.md",
        "AGENTS.project.md",
        "README.md",
        "docs/AGENTS.md",
        "plugin/demo/agents/p.md",
    )

    def test_lists_instruction_files_when_regular(self, snapshot_of: SnapshotFactory) -> None:
        paths = self.INSTRUCTION + self.NOT_INSTRUCTION
        # Listed in reverse: the set comes back sorted by path string whatever the listing order.
        snapshot = snapshot_of(files=files_at(*paths), listed=tuple(sorted(paths, reverse=True)))

        assert instruction_files(snapshot.hub) == self.INSTRUCTION

    @pytest.mark.parametrize("path", INSTRUCTION)
    def test_lists_one_instruction_file_when_alone(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        assert instruction_files(snapshot_of(files=files_at(path)).hub) == (path,)

    @pytest.mark.parametrize("path", NOT_INSTRUCTION)
    def test_lists_nothing_when_path_not_instruction(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        assert instruction_files(snapshot_of(files=files_at(path)).hub) == ()

    def test_skips_instruction_file_when_link(self, snapshot_of: SnapshotFactory) -> None:
        # E1: a hub links each plugin agent into .claude/agents/ one file at a time; the link is
        # not an instruction file, the same bytes as a regular file are.
        linked = snapshot_of(links={".claude/agents/x.md": "../../plugin/hub-workflow/agents/x.md"})
        regular = snapshot_of(files=files_at(".claude/agents/x.md"))
        root_link = snapshot_of(links={"AGENTS.md": "plugin/AGENTS.md"})
        # A linked folder is one listed link: nothing under it is listed, so nothing is found.
        folder_link = snapshot_of(links={".claude/commands": "../pluginx/commands"})

        assert instruction_files(linked.hub) == ()
        assert instruction_files(regular.hub) == (".claude/agents/x.md",)
        assert instruction_files(root_link.hub) == ()
        assert instruction_files(folder_link.hub) == ()

    def test_skips_instruction_file_when_not_listed(self, snapshot_of: SnapshotFactory) -> None:
        # Only the listing counts: a fixed path read by name, or a folder entry, is no file of it.
        snapshot = snapshot_of(
            files=files_at("AGENTS.md", "CLAUDE.md"),
            entries={".claude/rules/r.md": FolderEntry()},
            listed=("AGENTS.md", ".claude/rules/r.md"),
        )

        assert instruction_files(snapshot.hub) == ("AGENTS.md",)


class TestPluginFiles:
    def test_lists_plugin_files_when_under_agents_or_skills(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        found = (
            "plugin/a/agents/deep/y.md",
            "plugin/a/agents/x.md",
            "plugin/agents/z.md",
            "plugin/b/skills/s/SKILL.md",
            "plugin/b/skills/s/reference.md",
        )
        # A path segment, not a substring (E11): ``agentsx`` and ``my-skills`` are other folders.
        not_found = (
            ".claude/agents/a.md",
            "docs/agents/d.md",
            "plugin/a/agents/notes.txt",
            "plugin/a/agentsx/y.md",
            "plugin/a/hooks/h.md",
            "plugin/a/my-skills/k.md",
            "plugin/agents.md",
            "plugin/skills",
        )
        paths = found + not_found
        snapshot = snapshot_of(files=files_at(*paths), listed=tuple(sorted(paths, reverse=True)))

        assert plugin_files(snapshot.hub) == found

    def test_skips_plugin_file_when_link(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(
            files=files_at("plugin/a/agents/x.md"),
            links={"plugin/a/agents/y.md": "x.md", "plugin/b/skills": "../a/skills"},
        )

        assert plugin_files(snapshot.hub) == ("plugin/a/agents/x.md",)

    def test_lists_agent_and_skill_files_when_regular(self, snapshot_of: SnapshotFactory) -> None:
        found = (
            ".claude/agents/a.md",
            ".claude/skills/k/SKILL.md",
            ".claude/skills/k/more.md",
            "plugin/a/agents/x.md",
            "plugin/b/skills/s/SKILL.md",
        )
        not_found = (
            ".claude/commands/c.md",
            ".claude/rules/r.md",
            ".claude/skills/k/notes.txt",
            "AGENTS.md",
            "plugin/a/agentsx/y.md",
        )
        paths = found + not_found
        snapshot = snapshot_of(
            files=files_at(*paths),
            links={".claude/agents/linked.md": "../../plugin/a/agents/x.md"},
            listed=tuple(sorted([*paths, ".claude/agents/linked.md"], reverse=True)),
        )

        assert agent_skill_files(snapshot.hub) == found


class TestFileText:
    def test_reads_text_when_utf8(self) -> None:
        entry = FileEntry(executable=False, content="línea\r\nzwei\n".encode())

        assert file_text(entry) == "línea\r\nzwei\n"

    def test_reports_not_utf8_when_file_holds_nul(self) -> None:
        # Q-19: a NUL is not text, though it decodes (the old lint read it); the offset is the
        # first NUL's byte in the file, counted in bytes.
        entry = FileEntry(executable=False, content="é\n\x00b\x00\n".encode())

        assert file_text(entry) == TextProblem(
            message="not UTF-8 text: NUL at byte 3", fix=TEXT_FIX
        )

    def test_reports_not_utf8_when_instruction_file_undecodable(self) -> None:
        # Q-19: an instruction file that does not decode is an error, not a skip (the old lint
        # crashed on it).
        entry = FileEntry(executable=False, content=b"ok\n\xff\xfe")

        assert file_text(entry) == TextProblem(
            message="not UTF-8 text: byte 3 cannot be decoded", fix=TEXT_FIX
        )

    @pytest.mark.parametrize(
        "entry",
        [
            None,
            FileEntry(executable=False, content=None),
            LinkEntry(target="x.md", outside=False),
            FolderEntry(),
        ],
        ids=["absent", "unread", "link", "folder"],
    )
    def test_skips_file_when_entry_has_no_content(
        self, entry: FileEntry | LinkEntry | FolderEntry | None
    ) -> None:
        # E28: the reader asked for every listed file, so one with no content is a read that
        # failed, already reported once as the hub's problem (E24).
        assert file_text(entry) is None


class TestFrontmatter:
    def test_parses_frontmatter_when_terminated(self) -> None:
        text = (
            "---\n"
            "name: reviewer\n"
            "description:  Reviews a diff.  \n"
            "paths:\n"
            "  - 'src/**/*.py'\n"
            '  -   "docs/*.md"\n'
            "not a field\n"
            "tools: Read\n"
            "  - ignored\n"
            "---\n"
            "# Body\n"
            "name: not frontmatter\n"
        )

        assert parse_frontmatter(text) == Frontmatter(
            fields={
                "name": "reviewer",
                "description": "Reviews a diff.",
                "paths": ("src/**/*.py", "docs/*.md"),
                "tools": "Read",
            },
            end=10,
        )

    def test_parses_frontmatter_when_lines_end_crlf(self) -> None:
        text = "---\r\nname: x\r\npaths:\r\n  - a/*\r\n---\r\nbody\r\n"

        assert parse_frontmatter(text) == Frontmatter(
            fields={"name": "x", "paths": ("a/*",)}, end=5
        )

    def test_keeps_empty_list_when_crlf_item_has_no_value(self) -> None:
        text = "---\r\npaths:\r\n  -\r\ntools:  Read \r\nglobs:\r\n  - 'a/*' \r\n---\r\n"

        assert parse_frontmatter(text) == Frontmatter(
            fields={"paths": (), "tools": "Read", "globs": ("a/*",)}, end=7
        )

    @pytest.mark.parametrize(
        "text",
        ["\ufeff---\nname: x\n---\n", "---\rname: x\r---\r"],
        ids=["bom", "lone-cr"],
    )
    def test_finds_no_frontmatter_when_first_line_not_bare_marker(self, text: str) -> None:
        # As the old lint: a BOM is part of the first line, and only \n ends a line.
        assert parse_frontmatter(text) is None

    def test_parses_empty_frontmatter_when_closed_at_once(self) -> None:
        assert parse_frontmatter(" --- \n---\n") == Frontmatter(fields={}, end=2)

    def test_ignores_item_when_no_field_before_it(self) -> None:
        assert parse_frontmatter("---\n  - stray\nname: x\n---\n") == Frontmatter(
            fields={"name": "x"}, end=4
        )

    def test_keeps_empty_list_when_field_has_no_value(self) -> None:
        assert parse_frontmatter("---\npaths:\n---\n") == Frontmatter(fields={"paths": ()}, end=3)

    @pytest.mark.parametrize(
        "text",
        ["---\nname: x\n", "---\n", "---\nname: x\n--\n"],
        ids=["no-close", "marker-only", "short-close"],
    )
    def test_reports_unterminated_when_frontmatter_open(self, text: str) -> None:
        assert parse_frontmatter(text) == Unterminated()

    @pytest.mark.parametrize(
        "text",
        ["", "\n", "# Title\n---\nname: x\n---\n", "----\nname: x\n----\n"],
        ids=["empty-file", "blank-line", "late-marker", "long-marker"],
    )
    def test_finds_no_frontmatter_when_first_line_not_marker(self, text: str) -> None:
        assert parse_frontmatter(text) is None
