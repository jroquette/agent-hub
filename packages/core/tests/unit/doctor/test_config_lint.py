"""The file sets and the frontmatter the config-lint rules share (``config_lint.py``).

The port of the hub's ``agent_config_lint.py`` machinery: instruction files, plugin agent and
skill files, their text and frontmatter. Only listed regular files count: a link, to a file or a
folder, is never followed (spec D3, Q-6; plan E1).

The goldens (spec AC-11.18): the sixteen cases of the hub's
``tests/characterization/test_agent_config_lint.py``, goldens at hub commit ``8eaebae`` under
``tests/characterization/golden/agent_config_lint/``, each rebuilt as an in-memory snapshot and run
through the nine ported rules. ``TestGoldenCases`` holds the thirteen whose flagged set is
unchanged: ``clean``, ``instructions_refs``, ``instructions_size``, ``instructions_duplicates``,
``rules_frontmatter``, ``agent_skill_frontmatter``, ``agent_skill_frontmatter_project_dir``,
``settings_valid_invalid_json``, ``settings_valid_deprecated_key``,
``permissions_bypass_settings``, ``secrets_config``, ``mcp_pinned`` and ``attribution_ai``.
``TestPortDivergences`` asserts spec § Port differences: ``non_git_fallback`` and
``permissions_bypass_scripts`` differ (D3), and ``attribution_ai_no_hub`` is the "not a hub"
exit (AC-11.2).
"""

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import pytest

from agent_hub.core.doctor.config_lint import (
    Frontmatter,
    TextProblem,
    Unterminated,
    agent_skill_files,
    file_text,
    instruction_files,
    line_count,
    parse_frontmatter,
    plugin_files,
    text_lines,
)
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, run_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry, FolderEntry, LinkEntry
from agent_hub.core.testing.builders import a_hub_document

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

    @pytest.mark.parametrize(
        ("content", "byte"),
        [(b"ok\n\xff\xfe", 3), (b"\x00\xff", 1)],
        # A file that holds a NUL and does not decode reads as undecodable, not as a NUL.
        ids=["undecodable", "nul-then-undecodable"],
    )
    def test_reports_not_utf8_when_instruction_file_undecodable(
        self, content: bytes, byte: int
    ) -> None:
        # Q-19: an instruction file that does not decode is an error, not a skip (the old lint
        # crashed on it).
        entry = FileEntry(executable=False, content=content)

        assert file_text(entry) == TextProblem(
            message=f"not UTF-8 text: byte {byte} cannot be decoded", fix=TEXT_FIX
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


class TestTextLines:
    LINE_ENDS = (
        pytest.param("", (), id="empty"),
        pytest.param("a\nb\n", ("a", "b"), id="lf"),
        pytest.param("a\r\nb\r\n", ("a", "b"), id="crlf"),
        pytest.param("a\rb\n", ("a\rb",), id="lone-cr-inside"),
        pytest.param("a\n\nb", ("a", "", "b"), id="blank-and-unended"),
        pytest.param("a\u2028b\n", ("a\u2028b",), id="line-separator-is-text"),
        pytest.param("\n", ("",), id="one-empty-line"),
        pytest.param("a\r", ("a",), id="final-cr-unended"),
    )

    @pytest.mark.parametrize(("text", "lines"), LINE_ENDS)
    def test_ends_line_at_newline_only_when_text_split(
        self, text: str, lines: tuple[str, ...]
    ) -> None:
        # E29: every config-lint rule reads these lines.
        assert text_lines(text) == lines

    @pytest.mark.parametrize(("text", "lines"), LINE_ENDS)
    def test_counts_as_text_lines_when_counted_without_split(
        self, text: str, lines: tuple[str, ...]
    ) -> None:
        # E30: the size rule counts without building the lines.
        assert line_count(text) == len(text_lines(text)) == len(lines)


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


# The goldens: hub commit 8eaebae, tests/characterization/golden/agent_config_lint/ (spec AC-11.18).
# Each case's files are the hub test's, rebuilt in memory; every agent-config file name, secret
# shape, attribution line and the skip-permissions flag is assembled here from fragments at run
# time, so no committed line holds one.

FLAG = "--dangerously-" + "skip-permissions"
BARE_FLAG = FLAG[2:]
TRAILER = "Co-Authored-" + "By: Claude <noreply@example.com>"
GENERATED = "Generated " + "with [Claude Code](https://example.com)"
AI_BRANCH = "claude" + "/fix-login"
AGENTS, CLAUDE = "AGENTS" + ".md", "CLAUDE" + ".md"
LOCAL, GEMINI = "CLAUDE" + ".local.md", "GEMINI" + ".md"
SKILL = "SKILL" + ".md"
DOT = "." + "claude/"
SETTINGS, MCP = DOT + "settings" + ".json", "." + "mcp.json"
COPILOT = ".github/copilot-instructions.md"
LINT_NAME = "scripts/agent_config_lint.py"
# The fixture repos' committed ignore file (the hub's REPO_IGNORES).
GITIGNORE = ".claude/worktrees/\n.venv/\nnode_modules/\n__pycache__/\n"

# One line per secret kind, each at the pattern's minimum length and matching that pattern only.
SHAPES = {
    "jwt": "ey" + "J" + "a" * 15 + "." + "b" * 15,
    "aws": "AK" + "IA" + "Z" * 16,
    "pem": "-" * 5 + "BEGIN " + "RSA PRIVATE" + " KEY" + "-" * 5,
    "stripe": "sk" + "_live_" + "c" * 16,
    "openai": "sk" + "-" + "d" * 20,
    "github": "gh" + "p_" + "e" * 30,
    "linear": "lin" + "_api_" + "f" * 20,
    "cred": "PGPASS" + "WORD=" + "abcdef",
    "fernet": "k" * 43 + "=",
}

L60 = "keep every change small, tested and reviewed before merging!"
L59 = "keep each commit focused on one concern and on one issue no"
LONG_TABLE = "| " + "table cell that repeats in two instruction files, on purpose" + " |"
LONG_HEADING = "## " + "a heading that repeats in two instruction files, on purpose ok"
LONG_FENCE = "```" + "sh # a fence line that repeats in two instruction files on purpose"

# The nine ported rules, taken from the registry, so a rule missing there fails every golden.
CONFIG_LINT_IDS = (
    "instructions.size",
    "instructions.refs",
    "instructions.duplicates",
    "rules.frontmatter",
    "settings.valid",
    "permissions.bypass",
    "secrets.config",
    "mcp.pinned",
    "attribution.ai",
)
CONFIG_LINT_RULES = tuple(rule for rule in REGISTRY if rule.id in CONFIG_LINT_IDS)

type Flagged = tuple[str, str, int | None]


@dataclass(frozen=True, kw_only=True, slots=True)
class GoldenCase:
    """A golden case's repo: its files (committed or untracked alike) and its links."""

    files: Mapping[str, str | bytes]
    links: Mapping[str, str] = field(default_factory=dict)
    git: bool = True


def numbered(count: int, word: str) -> str:
    return "".join(f"{word} {index}\n" for index in range(1, count + 1))


def frontmatter(**fields: str) -> str:
    return "---\n" + "".join(f"{key}: {value}\n" for key, value in fields.items()) + "---\n"


def dumps(data: object) -> str:
    return json.dumps(data, indent=2) + "\n"


def clean_case() -> GoldenCase:
    # Every reference takes a skip or an exists path; AGENTS.md is exactly 100 lines,
    # CLAUDE.local.md exactly 50.
    body = [
        "---",
        "title: agents",
        "note: see `gone/in-frontmatter.md`",
        "---",
        "# Agents",
        "- Web: [site](https://example.com/docs), [mail](mailto:a@example.com), "
        "[home](~/notes/x.md), [abs](/nonexistent-char/x.md).",
        "- Sibling and placeholders: `../agent-hub/docs/SPEC.md`, [p](docs/<name>.md), "
        "`path/to/file.md`, `docs/.../x.md`, [u](docs/…/y.md), [v](${ROOT}/a.md).",
        "- Not paths: `origin/main`, `application/json`, the branch `dev/tst-1-login`.",
        "- Ignored by design: `.claude/worktrees/`; globs `src/**/*.py` and [all](*.md).",
        "- Code: `@/lib/util`, `helpers.py`, `pkg/helpers.py`, `src/pkg/`, "
        "[t](tests/test_app.py::test_ok), [g](docs/guide.md#intro).",
        "- Run `make lint` and `make test`; `pnpm install`, `pnpm run build`, `pnpm test:unit`, "
        "`pnpm i`.",
    ]
    agents = "\n".join(body) + "\n" + numbered(100 - len(body), "- note")
    rule = (
        frontmatter(paths='\n  - "src/**/*.{py,ts}"\n  - docs')
        + "See [notes](local/notes.txt) and `build/out.txt`.\n"
    )
    servers = {
        "docs": {"command": "npx", "args": ["-y", "docs-mcp@1.2.3"]},
        "remote": {"type": "http", "url": "https://mcp.example.com/mcp"},
    }
    return GoldenCase(
        files={
            AGENTS: agents,
            LOCAL: numbered(50, "local"),
            DOT + "rules/r.md": rule,
            DOT + "agents/rev.md": frontmatter(name="rev", description="Reviews diffs") + "Body\n",
            DOT + "skills/k/" + SKILL: frontmatter(name="k", description="A project skill")
            + "Body\n",
            ".github/instructions/py.md": "Python notes.\n",
            "plugin/p/skills/s/" + SKILL: frontmatter(name="s", description="A skill") + "Body\n",
            SETTINGS: dumps(
                {"permissions": {"defaultMode": "acceptEdits", "allow": ["Bash(make lint)"]}}
            ),
            MCP: dumps({"mcpServers": servers}),
            "CONTRIBUTING.md": "Branches: `dev/tst-<N>-<desc>`.\n",
            "Makefile": "lint:\n\techo ok\ntest: lint\n\techo ok\n",
            "package.json": dumps({"scripts": {"build": "tsc", "test:unit": "vitest"}}),
            "src/app.py": "",
            "src/lib/util.ts": "",
            "src/pkg/helpers.py": "",
            "docs/guide.md": "# Guide\n",
            "tests/test_app.py": "",
            "scripts/run.sh": "echo ok\n",
            ".github/workflows/ci.yml": "run: make check\n",
            # Untracked, not ignored.
            DOT + "rules/local/notes.txt": "n\n",
            "build/out.txt": "o\n",
        }
    )


def instructions_refs_case() -> GoldenCase:
    # Line 3: the repeated path is reported twice.
    agents = (
        "# Agents\n\nRead `src/gone.py` and the [guide](docs/missing.md#setup), then "
        "`src/gone.py` again.\n"
        "Run `make lint`, then make sure it is green.\n"
        "Build with `pnpm build`, `pnpm run e2e` and `pnpm deploy`.\n"
    )
    package = (
        '{\n  "scripts": {\n    "build": "tsc",\n    "e2e": "claude ' + FLAG + ' -p e2e"\n  }\n}\n'
    )
    return GoldenCase(
        files={AGENTS: agents, "Makefile": "lint:\n\techo ok\n", "package.json": package}
    )


def instructions_size_case() -> GoldenCase:
    return GoldenCase(
        files={
            AGENTS: numbered(101, "agents"),
            CLAUDE: numbered(150, "claude"),
            LOCAL: numbered(51, "local"),
            GEMINI: numbered(500, "gemini"),
            DOT + "rules/x.md": numbered(81, "rule"),
            DOT + "rules/y.md": numbered(80, "rule"),
            COPILOT: numbered(81, "copilot"),
        }
    )


def instructions_duplicates_case() -> GoldenCase:
    # No Makefile or package.json: the make and pnpm mentions are not checked; CLAUDE.md is 151
    # lines. One finding of each other check too.
    agents = (
        "\n".join(
            [
                "# Agents",
                "- " + L60,
                "- " + L60,
                LONG_TABLE,
                LONG_HEADING,
                LONG_FENCE,
                L59,
                "Run `make nothing` and `pnpm nothing`.",
                "See `gone/x.md`.",
                SHAPES["aws"],
            ]
        )
        + "\n"
    )
    shouted = "1.   " + L60.upper().replace(" ", "  ", 3)
    claude = (
        "\n".join([shouted, LONG_TABLE, LONG_HEADING, LONG_FENCE, L59])
        + "\n"
        + numbered(146, "pad")
    )
    return GoldenCase(
        files={
            AGENTS: agents,
            CLAUDE: claude,
            GEMINI: "* " + L60 + "\n",
            "plugin/p/skills/s/" + SKILL: frontmatter(description="No name") + "Body\n",
            SETTINGS: dumps({"allowedTools": []}),
            "scripts/run.sh": "#!/bin/sh\nclaude " + FLAG + " -p task\n",
        }
    )


def rules_frontmatter_case() -> GoldenCase:
    rules = DOT + "rules/"
    return GoldenCase(
        files={
            rules + "a-nopaths.md": frontmatter(description="no paths") + "Body\n",
            rules + "b-scalar.md": frontmatter(paths="src/**") + "Body\n",
            rules + "c-empty.md": frontmatter(paths="") + "Body\n",
            rules + "d-globs.md": frontmatter(paths='\n  - "src/**/*.{ts,py}"\n  - nomatch/**/*.md')
            + "Body\n",
            rules + "e-nofm.md": "Just a body, no frontmatter.\n",
            rules + "f-unterminated.md": "---\npaths:\n  - src/*.py\nno closing line\n",
            rules + "g-empty.md": "",
            DOT + "commands/c.md": frontmatter(paths="\n  - nomatch/*") + "Not a rules file.\n",
            "src/app.py": "",
        }
    )


def agent_skill_frontmatter_case() -> GoldenCase:
    # .claude/skills links into plugin/, .claude/commands into pluginx/: folder links.
    return GoldenCase(
        files={
            DOT + "agents/a.md": frontmatter(name="a") + "Body\n",
            DOT + "agents/b.md": "No frontmatter.\n",
            DOT + "agents/ok.md": frontmatter(name="ok", description="Fine") + "Body\n",
            "plugin/p/skills/s/" + SKILL: frontmatter(description="No name") + "Body\n",
            "plugin/p/agents/ok.md": frontmatter(name="ok", description="Fine") + "Body\n",
            "plugin/p/hooks/notes.md": "Not an agent or a skill.\n",
            "pluginx/commands/c.md": "A command.\n",
        },
        links={DOT + "skills": "../plugin/p/skills", DOT + "commands": "../pluginx/commands"},
    )


def settings_valid_invalid_json_case() -> GoldenCase:
    return GoldenCase(
        files={
            SETTINGS: '{\n  "permissions": {\n    "allow": ["Bash(ls)",]\n  }\n}\n',
            MCP: '{\n  "mcpServers": oops\n}\n',
        }
    )


def settings_valid_deprecated_key_case() -> GoldenCase:
    settings = {
        "allowedTools": ["Bash(ls)"],
        "model": "sonnet",
        "permissions": {"defaultMode": "acceptEdits"},
    }
    return GoldenCase(
        files={
            SETTINGS: dumps(settings),
            "scripts/run.sh": "#!/bin/sh\nclaude " + FLAG + " -p task\n",
        }
    )


def permissions_bypass_settings_case() -> GoldenCase:
    settings = {
        "ignorePatterns": [],
        "permissions": {"defaultMode": "bypass" + "Permissions"},
        "env": {"AGENT_ARGS": FLAG},
    }
    servers = {"x": {"command": "npx", "args": ["x-mcp@2.0.0", BARE_FLAG]}}
    return GoldenCase(
        files={
            SETTINGS: dumps(settings),
            MCP: dumps({"mcpServers": servers}),
            ".github/workflows/ci.yml": "jobs:\n  agent:\n    run: claude " + FLAG + " -p review\n",
        }
    )


def permissions_bypass_scripts_case() -> GoldenCase:
    return GoldenCase(
        files={
            "Makefile": "agent:\n\tclaude " + FLAG + " -p task\n",
            LINT_NAME: "# " + FLAG + "\n",
            "scripts/sub/tool.sh": "echo ok\n",
            "scripts/blob.bin": b"\xff\xfe" + FLAG.encode() + b"\n",
            "docs/run.sh": "claude " + FLAG + "\n",
            # Untracked, not ignored.
            "scripts/x.sh": "claude " + FLAG + "\n",
        }
    )


def secrets_config_case() -> GoldenCase:
    agents = (
        "\n".join(
            [
                "# Agents",
                SHAPES["jwt"],
                SHAPES["aws"],
                SHAPES["pem"],
                SHAPES["stripe"],
                SHAPES["openai"],
                SHAPES["linear"],
                "PASSWORD=<x>",
                # Two kinds on one line: two errors. One kind twice: one error.
                SHAPES["github"] + " " + SHAPES["aws"],
                SHAPES["jwt"] + " " + SHAPES["jwt"],
            ]
        )
        + "\n"
    )
    vault = {
        "type": "http",
        "url": "https://mcp.example.com/mcp",
        "headers": {"X-Key": SHAPES["fernet"]},
    }
    return GoldenCase(
        files={
            AGENTS: agents,
            "plugin/p/skills/s/" + SKILL: frontmatter(name="s", description="A skill")
            + "gh: "
            + SHAPES["github"]
            + "\n",
            SETTINGS: dumps({"env": {"PGOPTS": SHAPES["cred"]}}),
            MCP: dumps({"mcpServers": {"vault": vault}}),
        }
    )


def mcp_pinned_case() -> GoldenCase:
    # Unpinned: `@latest` without npx (zeta), npx without a version (beta), in key order; the
    # settings' mcpServers are not checked.
    servers = {
        "zeta": {"command": "uvx", "args": ["zeta-mcp@latest"]},
        "beta": {"command": "npx", "args": ["-y", "beta-mcp"]},
        "alpha": {"command": "npx", "args": ["-y", "alpha-mcp@1.2.3"]},
        "local": {"command": "node", "args": ["server.js"]},
        "remote": {"type": "http", "url": "https://mcp.example.com/mcp"},
    }
    mcp = {
        "mcpServers": servers,
        "allowedTools": ["x"],
        "permissions": {"defaultMode": "bypass" + "Permissions"},
    }
    settings = {"mcpServers": {"s": {"command": "npx", "args": ["s-mcp"]}}}
    return GoldenCase(files={MCP: dumps(mcp), SETTINGS: dumps(settings)})


def attribution_ai_case() -> GoldenCase:
    # CONTRIBUTING.md line 5 holds two kinds, line 6 one kind twice (one error).
    contributing = (
        "# Contributing\n\nEnd commits with:\n"
        + TRAILER
        + "\nBranch "
        + AI_BRANCH
        + ", "
        + GENERATED
        + "\n"
        + TRAILER
        + " and "
        + TRAILER
        + "\n"
    )
    template = "## Summary\n\n" + GENERATED + "\nBranch: " + AI_BRANCH + "\n"
    return GoldenCase(
        files={
            AGENTS: "Branch: `dev/tst-1-login`.\n",
            "CONTRIBUTING.md": contributing,
            ".github/PULL_REQUEST_TEMPLATE.md": template,
        }
    )


def non_git_fallback_case() -> GoldenCase:
    return GoldenCase(
        files={
            AGENTS: "# Agents\nCI runs `ci.yml`.\nVendored: `vendor.json`.\n"
            "Entry point: `main.py`.\n",
            "Makefile": "agent:\n\tclaude " + FLAG + " -p task\n",
            ".github/workflows/ci.yml": "run: claude " + FLAG + "\n",
            "node_modules/pkg/vendor.json": "{}\n",
            "src/main.py": "",
        },
        git=False,
    )


def agent_skill_frontmatter_project_dir_case() -> GoldenCase:
    # A regular (not linked) .claude/skills tree gets the agent and skill check.
    return GoldenCase(
        files={DOT + "skills/k/" + SKILL: frontmatter(description="No name") + "Body\n"}
    )


SIZE, REFS, DUPLICATES = "instructions.size", "instructions.refs", "instructions.duplicates"
FRONTMATTER, VALID, BYPASS = "rules.frontmatter", "settings.valid", "permissions.bypass"
SECRETS, PINNED, ATTRIBUTION = "secrets.config", "mcp.pinned", "attribution.ai"

# Each golden's ERROR lines as (rule id, path, line): the old message mapped to its rule id (spec
# § Port differences), ``instructions.size`` without a line. The thirteen cases whose flagged set
# is unchanged; ``non_git_fallback`` and ``permissions_bypass_scripts`` differ (D3) and are
# asserted divergent below, and ``attribution_ai_no_hub`` (no ``hub.json``) is not reachable:
# ``hub doctor`` exits 2 on a folder that is not a hub (AC-11.2).
GOLDENS: dict[str, tuple[Callable[[], GoldenCase], tuple[Flagged, ...]]] = {
    "clean": (clean_case, ()),
    "instructions_refs": (
        instructions_refs_case,
        (
            (REFS, AGENTS, 3),
            (REFS, AGENTS, 3),
            (REFS, AGENTS, 3),
            (REFS, AGENTS, 4),
            (REFS, AGENTS, 5),
            (BYPASS, "package.json", 4),
        ),
    ),
    "instructions_size": (
        instructions_size_case,
        (
            (SIZE, DOT + "rules/x.md", None),
            (SIZE, COPILOT, None),
            (SIZE, AGENTS, None),
            (SIZE, LOCAL, None),
        ),
    ),
    "instructions_duplicates": (
        instructions_duplicates_case,
        (
            (REFS, AGENTS, 9),
            (SIZE, CLAUDE, None),
            (FRONTMATTER, "plugin/p/skills/s/" + SKILL, 1),
            (VALID, SETTINGS, 1),
            (SECRETS, AGENTS, 10),
            (BYPASS, "scripts/run.sh", 2),
            (DUPLICATES, CLAUDE, 1),
            (DUPLICATES, GEMINI, 1),
        ),
    ),
    "rules_frontmatter": (
        rules_frontmatter_case,
        tuple(
            (FRONTMATTER, DOT + f"rules/{name}.md", 1)
            for name in ("a-nopaths", "b-scalar", "c-empty", "d-globs", "f-unterminated")
        ),
    ),
    "agent_skill_frontmatter": (
        agent_skill_frontmatter_case,
        (
            (FRONTMATTER, DOT + "agents/a.md", 1),
            (FRONTMATTER, DOT + "agents/b.md", 1),
            (FRONTMATTER, "plugin/p/skills/s/" + SKILL, 1),
        ),
    ),
    "settings_valid_invalid_json": (
        settings_valid_invalid_json_case,
        ((VALID, SETTINGS, 3), (VALID, MCP, 2)),
    ),
    "settings_valid_deprecated_key": (
        settings_valid_deprecated_key_case,
        ((VALID, SETTINGS, 1), (BYPASS, "scripts/run.sh", 2)),
    ),
    "permissions_bypass_settings": (
        permissions_bypass_settings_case,
        (
            (VALID, SETTINGS, 1),
            (BYPASS, SETTINGS, 1),
            (BYPASS, SETTINGS, 1),
            (BYPASS, MCP, 1),
            (BYPASS, ".github/workflows/ci.yml", 3),
        ),
    ),
    "secrets_config": (
        secrets_config_case,
        (
            *((SECRETS, AGENTS, line) for line in (2, 3, 4, 5, 6, 7, 9, 9, 10)),
            (SECRETS, "plugin/p/skills/s/" + SKILL, 5),
            (SECRETS, MCP, 7),
            (SECRETS, SETTINGS, 3),
        ),
    ),
    "mcp_pinned": (mcp_pinned_case, ((PINNED, MCP, 1), (PINNED, MCP, 1))),
    "attribution_ai": (
        attribution_ai_case,
        (
            *((ATTRIBUTION, "CONTRIBUTING.md", line) for line in (4, 5, 5, 6)),
            (ATTRIBUTION, ".github/PULL_REQUEST_TEMPLATE.md", 3),
            (ATTRIBUTION, ".github/PULL_REQUEST_TEMPLATE.md", 4),
        ),
    ),
    "agent_skill_frontmatter_project_dir": (
        agent_skill_frontmatter_project_dir_case,
        ((FRONTMATTER, DOT + "skills/k/" + SKILL, 1),),
    ),
}


# The two goldens whose flagged set differs, as the old lint reported them.
NON_GIT_FALLBACK_GOLDEN: tuple[Flagged, ...] = (
    (REFS, AGENTS, 2),
    (REFS, AGENTS, 3),
    (BYPASS, "Makefile", 2),
)
PERMISSIONS_BYPASS_SCRIPTS_GOLDEN: tuple[Flagged, ...] = ((BYPASS, "Makefile", 2),)


def golden_config() -> HubConfig:
    # The hub copy's hub.json: branch prefix ``dev/``, tracker team ``TST``.
    document = a_hub_document()
    document["project"]["branch_prefix"] = "dev/"
    document["tracker"]["team"] = "TST"
    return HubConfig.model_validate(document)


def case_snapshot(snapshot_of: SnapshotFactory, case: GoldenCase) -> DoctorSnapshot:
    files = {
        path: content.encode() if isinstance(content, str) else content
        for path, content in case.files.items()
    }
    if case.git:
        files[".gitignore"] = GITIGNORE.encode()
    return snapshot_of(files=files, links=case.links, config=golden_config())


def run_case(snapshot_of: SnapshotFactory, case: GoldenCase) -> tuple[Finding, ...]:
    selection = Selection(rules=CONFIG_LINT_RULES, notes=(), severities={})
    return run_rules(selection, case_snapshot(snapshot_of, case))


def flagged(findings: tuple[Finding, ...]) -> list[Flagged]:
    return sorted(
        ((finding.rule, finding.path or "", finding.line) for finding in findings),
        key=lambda item: (item[0], item[1], item[2] or 0),
    )


def expected(golden: tuple[Flagged, ...]) -> list[Flagged]:
    return sorted(golden, key=lambda item: (item[0], item[1], item[2] or 0))


class TestGoldenCases:
    @pytest.mark.parametrize("name", sorted(GOLDENS))
    def test_matches_golden_when_case_rebuilt(
        self, snapshot_of: SnapshotFactory, name: str
    ) -> None:
        build, golden = GOLDENS[name]
        findings = run_case(snapshot_of, build())

        assert tuple(rule.id for rule in CONFIG_LINT_RULES) == CONFIG_LINT_IDS
        # E27's guard turns a raising rule into a finding: none may hide a rule failure here.
        assert not [f for f in findings if f.message.startswith("rule crashed")]
        assert flagged(findings) == expected(golden)


class TestPortDivergences:
    """One test per spec § Port differences row that a golden case shows (AC-11.18, D4)."""

    def test_reports_without_line_when_instructions_size_exceeded(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # The old lint put the count in the line (``AGENTS.md:101``); the doctor names no line.
        findings = run_case(snapshot_of, instructions_size_case())

        assert [(f.path, f.line, f.message) for f in findings if f.path == AGENTS] == [
            (AGENTS, None, "101 lines, limit 100")
        ]
        assert {f.line for f in findings} == {None}

    def test_lists_github_and_node_modules_when_walked(self, snapshot_of: SnapshotFactory) -> None:
        # ``non_git_fallback``: the old walk dropped every path holding ``.git`` (so ``.github/``)
        # or ``node_modules``; only ``.git`` is skipped now (D3), so both references resolve and
        # the workflow's flag is found.
        findings = run_case(snapshot_of, non_git_fallback_case())

        assert flagged(findings) == expected(
            (
                *(item for item in NON_GIT_FALLBACK_GOLDEN if item[0] != REFS),
                (BYPASS, ".github/workflows/ci.yml", 1),
            )
        )

    def test_flags_untracked_script_when_listed(self, snapshot_of: SnapshotFactory) -> None:
        # ``permissions_bypass_scripts``: the old scan read tracked files only; the listing holds
        # untracked, unignored files too (D3, Q-4), so ``scripts/x.sh`` is flagged.
        findings = run_case(snapshot_of, permissions_bypass_scripts_case())

        assert flagged(findings) == expected(
            (*PERMISSIONS_BYPASS_SCRIPTS_GOLDEN, (BYPASS, "scripts/x.sh", 1))
        )

    def test_ignores_linked_commands_folder_when_listed(self, snapshot_of: SnapshotFactory) -> None:
        # ``agent_skill_frontmatter``: the old walk went into the linked ``.claude/commands``
        # folder (its count line said 4 instruction files); links are never followed (D3), so
        # the flagged set is the golden's and ``c.md`` is no instruction file.
        case = agent_skill_frontmatter_case()
        snapshot = case_snapshot(snapshot_of, case)

        assert flagged(run_case(snapshot_of, case)) == expected(
            GOLDENS["agent_skill_frontmatter"][1]
        )
        assert instruction_files(snapshot.hub) == (
            DOT + "agents/a.md",
            DOT + "agents/b.md",
            DOT + "agents/ok.md",
        )

    def test_ignores_linked_agent_file_when_listed(self, snapshot_of: SnapshotFactory) -> None:
        # E1: a hub links each plugin agent into ``.claude/agents/`` one file at a time; the old
        # walk opened the link and checked the plugin's text as an instruction file. The same
        # ``clean`` hub with such a link, to an agent of 200 lines holding a stale reference,
        # stays clean: the link is no instruction file and the plugin file is not one either.
        agent = frontmatter(name="big", description="A long agent") + "See `gone/x.md`.\n"
        base = clean_case()
        case = GoldenCase(
            files={**base.files, "plugin/p/agents/big.md": agent + numbered(196, "step")},
            links={DOT + "agents/big.md": "../../plugin/p/agents/big.md"},
        )

        assert run_case(snapshot_of, case) == ()

    def test_splits_settings_checks_when_ids_differ(self, snapshot_of: SnapshotFactory) -> None:
        # One old check, three ids now: the files' validity and deprecated keys under
        # ``settings.valid``, the bypass mode and flag under ``permissions.bypass``.
        invalid = run_case(snapshot_of, settings_valid_invalid_json_case())
        bypass = run_case(snapshot_of, permissions_bypass_settings_case())

        assert {(f.rule, f.path) for f in invalid} == {(VALID, SETTINGS), (VALID, MCP)}
        assert {(f.rule, f.path, f.message) for f in bypass} == {
            (VALID, SETTINGS, "deprecated settings key `ignorePatterns`"),
            (BYPASS, SETTINGS, "`bypassPermissions` in shared settings"),
            (BYPASS, SETTINGS, f"`{FLAG}` in config"),
            (BYPASS, MCP, f"`{FLAG}` in config"),
            (BYPASS, ".github/workflows/ci.yml", f"`{FLAG}`"),
        }

    def test_flags_near_named_script_when_exception_anchored(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # Q-8: the old scan skipped any path ending ``agent_config_lint.py``; only exactly
        # ``scripts/agent_config_lint.py`` is skipped now.
        base = permissions_bypass_scripts_case()
        case = GoldenCase(
            files={
                **base.files,
                "scripts/sub/" + LINT_NAME.removeprefix("scripts/"): "# " + FLAG + "\n",
            }
        )

        paths = {f.path for f in run_case(snapshot_of, case)}

        assert "scripts/sub/agent_config_lint.py" in paths
        assert LINT_NAME not in paths

    def test_reports_error_when_instruction_file_not_utf8(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # Q-19: the old lint crashed on an instruction file that does not decode; the ``clean``
        # hub with such an ``AGENTS.md`` gives one error, from the first rule that reads it.
        base = clean_case()
        case = GoldenCase(files={**base.files, AGENTS: b"# Agents\n\xff\n"})

        findings = run_case(snapshot_of, case)

        assert [(f.rule, f.path, f.line, f.message) for f in findings] == [
            (SIZE, AGENTS, None, "not UTF-8 text: byte 9 cannot be decoded")
        ]

    # ``attribution_ai_no_hub`` has no test here: without ``hub.json`` the folder is not a hub,
    # and ``hub doctor`` exits 2 before any rule runs (AC-11.2, the cli's doctor command tests).
