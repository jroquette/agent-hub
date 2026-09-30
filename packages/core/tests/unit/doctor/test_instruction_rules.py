"""``instructions.size`` and ``instructions.duplicates``: the port of the hub's old config lint.

Line limits (spec AC-11.19, Q-6) and instruction lines repeated across instruction files
(AC-11.20). A file that is not text is the runner's to report (E28): each rule skips it.
"""

from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor.finding import Read, Rule
from agent_hub.core.doctor.instruction_rules import INSTRUCTIONS_DUPLICATES, INSTRUCTIONS_SIZE
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str]

SIZE_FIX = "keep it a map, not a manual: move details to docs or the brain"
DUPLICATE_FIX = "keep the instruction in one file and link to it"
RULE = ".claude/rules/r.md"
# 60 characters once normalized, and one character shorter.
SIXTY = "Run the fast gate while working and the full gate before PRs"
FIFTY_NINE = SIXTY[:59]


def lines(count: int, *, end: bytes = b"\n") -> bytes:
    return (b"x" + end) * count


def a_config(max_lines: Mapping[str, int] | None = None) -> HubConfig:
    document = a_hub_document()
    if max_lines is not None:
        document["doctor"] = {"rules": {"instructions.size": {"max_lines": dict(max_lines)}}}
    return HubConfig.model_validate(document)


def shown(rule: Rule, snapshot: DoctorSnapshot, *, fix: str) -> list[Shown]:
    found = list(rule.check(snapshot))
    assert all(finding.rule == rule.id for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    assert all(finding.fix == fix for finding in found)
    return [(finding.path, finding.line, finding.message) for finding in found]


def sizes(snapshot: DoctorSnapshot) -> list[Shown]:
    return shown(INSTRUCTIONS_SIZE, snapshot, fix=SIZE_FIX)


def duplicates(snapshot: DoctorSnapshot) -> list[Shown]:
    return shown(INSTRUCTIONS_DUPLICATES, snapshot, fix=DUPLICATE_FIX)


@pytest.mark.parametrize("rule", [INSTRUCTIONS_SIZE, INSTRUCTIONS_DUPLICATES])
def test_reads_instruction_files_when_rule_declared(rule: Rule) -> None:
    assert rule.reads == frozenset({Read.INSTRUCTION_FILES})
    assert rule.severity is Severity.ERROR
    assert rule.module is None
    assert (INSTRUCTIONS_SIZE.id, INSTRUCTIONS_DUPLICATES.id) == (
        "instructions.size",
        "instructions.duplicates",
    )


class TestSize:
    @pytest.mark.parametrize(
        ("path", "count", "limit"),
        [
            pytest.param("AGENTS.md", 101, 100, id="agents-over"),
            pytest.param("AGENTS.md", 100, None, id="agents-at"),
            pytest.param("CLAUDE.md", 151, 150, id="claude-over"),
            pytest.param("CLAUDE.md", 150, None, id="claude-at"),
            pytest.param("CLAUDE.local.md", 51, 50, id="local-over"),
            pytest.param("CLAUDE.local.md", 50, None, id="local-at"),
            pytest.param(RULE, 81, 80, id="rule-over"),
            pytest.param(RULE, 80, None, id="rule-at"),
            pytest.param(".claude/agents/deep/a.md", 81, 80, id="nested-agent-over"),
            pytest.param(".github/copilot-instructions.md", 81, 80, id="copilot-over"),
            pytest.param(".github/copilot-instructions.md", 80, None, id="copilot-at"),
            pytest.param("GEMINI.md", 500, None, id="gemini-no-limit"),
        ],
    )
    def test_limits_root_and_nested_files_when_defaults_apply(
        self, snapshot_of: SnapshotFactory, *, path: str, count: int, limit: int | None
    ) -> None:
        snapshot = snapshot_of(files={path: lines(count)})

        expected = [] if limit is None else [(path, None, f"{count} lines, limit {limit}")]
        assert sizes(snapshot) == expected

    def test_reports_count_without_line_when_over_limit(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={"AGENTS.md": lines(101), "CLAUDE.md": lines(3)})

        assert sizes(snapshot) == [("AGENTS.md", None, "101 lines, limit 100")]

    @pytest.mark.parametrize(
        ("content", "count"),
        [
            pytest.param(lines(101, end=b"\r\n"), 101, id="crlf-once"),
            pytest.param(lines(50) + b"a\rb\n", 51, id="lone-cr-inside-line"),
            pytest.param(lines(100) + b"no final newline", 101, id="last-line-unended"),
        ],
    )
    def test_ends_line_at_newline_only_when_line_ends_vary(
        self, snapshot_of: SnapshotFactory, *, content: bytes, count: int
    ) -> None:
        # E29: \n and \r\n end a line; a lone \r does not (the old lint's text mode split there).
        snapshot = snapshot_of(files={"CLAUDE.local.md": content, "AGENTS.md": content})

        assert sizes(snapshot) == [
            (path, None, f"{count} lines, limit {limit}")
            for path, limit in (("AGENTS.md", 100), ("CLAUDE.local.md", 50))
            if count > limit
        ]

    @pytest.mark.parametrize(
        ("count", "flagged"),
        [pytest.param(120, False, id="at"), pytest.param(121, True, id="over")],
    )
    def test_applies_project_limit_when_max_lines_given(
        self, snapshot_of: SnapshotFactory, *, count: int, flagged: bool
    ) -> None:
        snapshot = snapshot_of(
            config=a_config({"AGENTS.md": 120}),
            files={"AGENTS.md": lines(count), "CLAUDE.md": lines(151), RULE: lines(81)},
        )

        assert sizes(snapshot) == [
            (RULE, None, "81 lines, limit 80"),
            *([("AGENTS.md", None, f"{count} lines, limit 120")] if flagged else []),
            ("CLAUDE.md", None, "151 lines, limit 150"),
        ]

    @pytest.mark.parametrize(
        ("max_lines", "path", "limit"),
        [
            # A project key wins over a default one, even a glob over a default exact name.
            pytest.param({"*.md": 30}, "AGENTS.md", 30, id="project-over-default"),
            # An exact key wins over any glob of the same project.
            pytest.param({"*": 10, RULE: 90}, RULE, 90, id="exact-over-glob"),
            # Among globs, the longest pattern.
            pytest.param({"*.md": 10, ".claude/rules/*": 90}, RULE, 90, id="longest-glob"),
            # Globs of one length: the first in sorted order ("?" sorts before "r").
            pytest.param(
                {".claude/rules/r.m*": 70, ".claude/rules/?.md": 90}, RULE, 90, id="sorted-glob"
            ),
            # A key with no "/" and no glob character names a root file only.
            pytest.param({"r.md": 5}, RULE, 80, id="name-root-only"),
            # A root file with no default limit takes a project one.
            pytest.param({"GEMINI.md": 60}, "GEMINI.md", 60, id="gemini-given"),
        ],
    )
    def test_prefers_exact_then_longest_glob_when_keys_overlap(
        self,
        snapshot_of: SnapshotFactory,
        *,
        max_lines: dict[str, int],
        path: str,
        limit: int,
    ) -> None:
        config = a_config(max_lines)

        at_limit = snapshot_of(config=config, files={path: lines(limit)})
        over_limit = snapshot_of(config=config, files={path: lines(limit + 1)})

        assert sizes(at_limit) == []
        assert sizes(over_limit) == [(path, None, f"{limit + 1} lines, limit {limit}")]

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(lines(200) + b"\xff", id="undecodable"),
            pytest.param(lines(200) + b"\x00", id="nul"),
        ],
    )
    def test_skips_file_when_not_text(self, snapshot_of: SnapshotFactory, content: bytes) -> None:
        # E28: the runner reports the file once; the rule itself gives nothing on it.
        snapshot = snapshot_of(files={"AGENTS.md": content, "CLAUDE.md": lines(151)})

        assert sizes(snapshot) == [("CLAUDE.md", None, "151 lines, limit 150")]

    def test_skips_file_when_content_unread(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(entries={"AGENTS.md": FileEntry(executable=False, content=None)})

        assert sizes(snapshot) == []


class TestDuplicates:
    def test_flags_duplicate_when_line_reaches_sixty_characters(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        assert len(SIXTY) == 60
        snapshot = snapshot_of(
            files={
                "AGENTS.md": f"# Agents\n{SIXTY}\n".encode(),
                "CLAUDE.md": f"{SIXTY}\n".encode(),
            }
        )

        assert duplicates(snapshot) == [("CLAUDE.md", 1, "duplicates AGENTS.md:2")]

    def test_ignores_line_when_fifty_nine_characters(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{FIFTY_NINE}\n".encode(), "CLAUDE.md": f"{FIFTY_NINE}\n".encode()}
        )

        assert duplicates(snapshot) == []

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(f"| {SIXTY} |", id="table"),
            pytest.param(f"```{SIXTY}", id="fence"),
            pytest.param(f"## {SIXTY}", id="heading"),
        ],
    )
    def test_ignores_table_fence_and_heading_when_duplicated(
        self, snapshot_of: SnapshotFactory, line: str
    ) -> None:
        text = f"{line}\n".encode()
        snapshot = snapshot_of(files={"AGENTS.md": text, "CLAUDE.md": text})

        assert duplicates(snapshot) == []

    def test_flags_later_file_when_paths_sorted(self, snapshot_of: SnapshotFactory) -> None:
        # Listed in reverse: "later" is the sorted path order (".claude/…" before "AGENTS.md").
        # Each repeat in a later file is flagged, naming the first file's line.
        files = {
            "CLAUDE.md": f"{SIXTY}\nother\n{SIXTY}\n".encode(),
            "AGENTS.md": f"intro\n{SIXTY}\n".encode(),
            RULE: f"a\nb\n{SIXTY}\n".encode(),
        }
        snapshot = snapshot_of(files=files, listed=tuple(sorted(files, reverse=True)))

        assert duplicates(snapshot) == [
            ("AGENTS.md", 2, f"duplicates {RULE}:3"),
            ("CLAUDE.md", 1, f"duplicates {RULE}:3"),
            ("CLAUDE.md", 3, f"duplicates {RULE}:3"),
        ]

    def test_ignores_repeat_when_same_file(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{SIXTY}\n{SIXTY}\n".encode(), "CLAUDE.md": b"# Claude\n"}
        )

        assert duplicates(snapshot) == []

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param(f"- {SIXTY}", id="dash"),
            pytest.param(f"* {SIXTY}", id="star"),
            pytest.param(f"12. {SIXTY}", id="numbered"),
            pytest.param(f"  {SIXTY.upper()}  ", id="case-and-blanks"),
            pytest.param(SIXTY.replace(" ", " \t  "), id="inner-blanks"),
            pytest.param(f"{SIXTY}\r", id="crlf"),
        ],
    )
    def test_normalizes_list_marker_when_compared(
        self, snapshot_of: SnapshotFactory, line: str
    ) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{SIXTY}\n".encode(), "CLAUDE.md": f"{line}\n".encode()}
        )

        assert duplicates(snapshot) == [("CLAUDE.md", 1, "duplicates AGENTS.md:1")]

    def test_skips_link_when_same_line_behind_it(self, snapshot_of: SnapshotFactory) -> None:
        # E1: a linked instruction file is not an instruction file.
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{SIXTY}\n".encode()}, links={"CLAUDE.md": "AGENTS.md"}
        )

        assert duplicates(snapshot) == []

    @pytest.mark.parametrize(
        "suffix",
        [pytest.param(b"\xff", id="undecodable"), pytest.param(b"\x00", id="nul")],
    )
    def test_skips_file_when_not_text(self, snapshot_of: SnapshotFactory, suffix: bytes) -> None:
        # E28: the runner reports the file once; the rule neither flags it nor counts its lines.
        text = f"{SIXTY}\n".encode()
        snapshot = snapshot_of(
            files={"AGENTS.md": text + suffix, "CLAUDE.md": text, "GEMINI.md": text}
        )

        assert duplicates(snapshot) == [("GEMINI.md", 1, "duplicates CLAUDE.md:1")]
