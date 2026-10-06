"""``instructions.size``, ``.refs`` and ``.duplicates``: the port of the old config lint.

Line limits (spec AC-11.19, Q-6), references to paths, ``make`` targets and ``pnpm`` scripts that
do not exist, and instruction lines repeated across instruction files (AC-11.20). A file that is
not text is the runner's to report (E28): each rule skips it.
"""

import json
import re
from collections.abc import Callable, Mapping

import pytest

from agent_hub.core.doctor import config_lint, instruction_rules
from agent_hub.core.doctor.finding import Read, Rule
from agent_hub.core.doctor.instruction_rules import INSTRUCTIONS_DUPLICATES, INSTRUCTIONS_SIZE
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.testing.builders import a_conventions_document, a_hub_document

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


# The project's commit title shape and its example, then a repo's own PR title shape (E32).
WIP_TITLE_SPANS = (
    "Commit title: `wip/{summary}`, e.g. `wip/add the collector`.\n"
    "`demo-api` overrides PR title `x/{ISSUE}-{summary}`.\n"
)


def a_wip_title_config() -> HubConfig:
    """The mixed hub, its project commit title ``wip/{summary}`` and ``demo-api``'s PR title."""
    document = a_conventions_document()
    # A PR title filled from that commit title: it holds no {type} nor {scope}.
    document["project"]["conventions"]["commit_title"] = "wip/{summary}"
    document["project"]["conventions"]["pr_title"] = "{ISSUE}: {summary}"
    document["repos"][0]["conventions"] = {"pr_title": "x/{ISSUE}-{summary}"}
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


def test_uses_design_ids_when_rules_declared() -> None:
    assert (INSTRUCTIONS_SIZE.id, INSTRUCTIONS_DUPLICATES.id) == (
        "instructions.size",
        "instructions.duplicates",
    )


@pytest.mark.parametrize("rule", [INSTRUCTIONS_SIZE, INSTRUCTIONS_DUPLICATES])
def test_reads_instruction_files_when_rule_declared(rule: Rule) -> None:
    assert rule.reads == frozenset({Read.INSTRUCTION_FILES})
    assert rule.severity is Severity.ERROR
    assert rule.module is None


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
            # A class is a glob; an unclosed "[" is a literal character, so the key is a glob that
            # matches only that exact path.
            pytest.param({".claude/rules/[rs].md": 90}, RULE, 90, id="class-glob"),
            pytest.param({".claude/rules/[qs].md": 5}, RULE, 80, id="class-glob-misses"),
            pytest.param({".claude/rules/[r.md": 90}, ".claude/rules/[r.md", 90, id="unclosed"),
            pytest.param({".claude/rules/[r.md": 5}, RULE, 80, id="unclosed-misses"),
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
    def test_matches_line_when_normalized(self, snapshot_of: SnapshotFactory, line: str) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{SIXTY}\n".encode(), "CLAUDE.md": f"{line}\n".encode()}
        )

        assert duplicates(snapshot) == [("CLAUDE.md", 1, "duplicates AGENTS.md:1")]

    def test_flags_duplicate_when_inside_frontmatter(self, snapshot_of: SnapshotFactory) -> None:
        # E11: frontmatter lines are compared too, as the old lint did.
        text = f"---\ndescription: {SIXTY}\n---\n# Body\n".encode()
        snapshot = snapshot_of(files={".claude/agents/a.md": text, ".claude/agents/b.md": text})

        assert duplicates(snapshot) == [
            (".claude/agents/b.md", 2, "duplicates .claude/agents/a.md:2")
        ]

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


STALE_FIX = "update the path or remove the line"
MAKE_FIX = "use an existing target or add it"
PNPM_FIX = "use an existing script"


def refs(snapshot: DoctorSnapshot) -> list[tuple[str | None, int | None, str, str]]:
    # Read through the module, so a missing rule fails each test rather than the collection.
    rule: Rule = instruction_rules.INSTRUCTIONS_REFS
    found = list(rule.check(snapshot))
    assert all(finding.rule == "instructions.refs" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in found]


def stale(path: str, line: int, ref: str) -> tuple[str, int, str, str]:
    return (path, line, f"stale reference `{ref}` (no such path)", STALE_FIX)


# A project branch shape and its example, then a repo's own shape and its example.
WORK_BRANCH_SPANS = (
    "Branch: `work/{issue_lower}/{slug}`, e.g. `work/dem-7/collector`.\n"
    "`demo-api` overrides branch `release/{ISSUE}`, e.g. `release/DEM-7`.\n"
)


def a_work_branch_config() -> HubConfig:
    """The mixed hub, its project branch ``work/…`` and ``demo-api``'s own ``release/{ISSUE}``."""
    document = a_conventions_document()
    document["project"]["conventions"]["branch"] = "work/{issue_lower}/{slug}"
    document["repos"][0]["conventions"] = {"branch": "release/{ISSUE}"}
    return HubConfig.model_validate(document)


class TestRefs:
    def test_declares_design_id_when_rule_read(self) -> None:
        rule: Rule = instruction_rules.INSTRUCTIONS_REFS

        assert rule.id == "instructions.refs"
        assert rule.reads == frozenset({Read.INSTRUCTION_FILES})
        assert rule.severity is Severity.ERROR
        assert rule.module is None

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param("[site](https://example.com/docs/a.md)", id="url"),
            pytest.param("[mail](mailto:team@example.com)", id="mailto"),
            pytest.param("[home](~/notes/a.md)", id="home"),
            pytest.param("[abs](/etc/hub/a.md)", id="absolute"),
            pytest.param("[sibling](../other-repo/AGENTS.md)", id="parent"),
            pytest.param("[x](docs/<name>.md)", id="angle-placeholder"),
            pytest.param("`path/to/file.md`", id="path-to"),
            pytest.param("`docs/.../x.md`", id="dots"),
            pytest.param("[x](docs/…/x.md)", id="ellipsis"),
            pytest.param("[x]($HUB_ROOT/x.md)", id="variable"),
            pytest.param("[x](${HUB_ROOT}/x.md)", id="braced-variable"),
            pytest.param("`origin/main`", id="origin"),
            pytest.param("`upstream/feature/x`", id="upstream"),
            pytest.param("`application/json`", id="mime-application"),
            pytest.param("`text/plain`", id="mime-text"),
            pytest.param("`multipart/form-data`", id="mime-multipart"),
            pytest.param("`jdoe/dem-12-collector`", id="branch-prefix"),
            pytest.param("`.claude/worktrees`", id="worktrees"),
            pytest.param("`.claude/settings.local.json`", id="local-settings"),
            pytest.param("[deps](node_modules)", id="node-modules"),
            pytest.param("[env](.venv)", id="venv"),
            pytest.param("[any](*.md)", id="glob-from-root"),
            pytest.param("---\nsee `docs/missing.md`\n---\n# Body", id="frontmatter"),
            # An unterminated frontmatter runs to the end of the file, as in the old lint.
            pytest.param("---\n# Body\nsee `docs/missing.md`", id="unterminated-frontmatter"),
            pytest.param("`some words`", id="not-pathy"),
        ],
    )
    def test_skips_reference_when_not_a_path(self, snapshot_of: SnapshotFactory, text: str) -> None:
        snapshot = snapshot_of(files={"AGENTS.md": f"{text}\n".encode()})

        assert refs(snapshot) == []

    def test_reports_reference_when_path_missing(self, snapshot_of: SnapshotFactory) -> None:
        text = (
            "# Agents\n"
            "Read [the guide](docs/missing.md#part) first.\n"
            "Run `scripts/gone.py`, and `scripts/gone.py` again, or [it](scripts/gone.py).\n"
            "Not the branch `other/dem-1-x`.\n"
        )
        snapshot = snapshot_of(files={"AGENTS.md": text.encode()})

        assert refs(snapshot) == [
            stale("AGENTS.md", 2, "docs/missing.md"),
            # Links first, then code spans, as the old lint listed them; each one is reported.
            stale("AGENTS.md", 3, "scripts/gone.py"),
            stale("AGENTS.md", 3, "scripts/gone.py"),
            stale("AGENTS.md", 3, "scripts/gone.py"),
            stale("AGENTS.md", 4, "other/dem-1-x"),
        ]

    def test_skips_reference_when_configured_branch(self, snapshot_of: SnapshotFactory) -> None:
        document = a_hub_document()
        document["project"]["default_branch"] = "stable/1"
        document["repos"][0]["default_branch"] = "release/2"
        text = (
            "Never push `stable/1` or `release/2`.\n"
            "Not the branch `release/3` nor `release/2/notes.md`.\n"
        )
        snapshot = snapshot_of(
            config=HubConfig.model_validate(document), files={"AGENTS.md": text.encode()}
        )

        # Only the configured branches: a path that merely looks like one is still stale.
        assert refs(snapshot) == [
            stale("AGENTS.md", 2, "release/3"),
            stale("AGENTS.md", 2, "release/2/notes.md"),
        ]

    def test_skips_convention_branches_when_agents_names_them(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # AGH-57 (plan O1 a): the branch shapes and examples AGENTS.md renders are not paths.
        # Their first segments are neither the prefix nor a path the hub holds.
        snapshot = snapshot_of(
            config=a_work_branch_config(),
            files={"AGENTS.md": WORK_BRANCH_SPANS.encode()},
        )

        assert refs(snapshot) == []

    def test_reports_stale_reference_when_span_only_resembles_convention(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # Only an exact shape or example is skipped: a path-shaped span near one is still checked.
        text = "Not `work/dem-8/other`, `release/DEM-8` nor `release/{ISSUE}/notes.md`.\n"
        snapshot = snapshot_of(config=a_work_branch_config(), files={"AGENTS.md": text.encode()})

        assert refs(snapshot) == [
            stale("AGENTS.md", 1, "work/dem-8/other"),
            stale("AGENTS.md", 1, "release/DEM-8"),
            stale("AGENTS.md", 1, "release/{ISSUE}/notes.md"),
        ]

    def test_skips_convention_titles_when_agents_names_them(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # AGH-57 (E32): a title shape holding `/` is path-shaped, yet the hub renders it.
        snapshot = snapshot_of(
            config=a_wip_title_config(),
            files={"AGENTS.md": WIP_TITLE_SPANS.encode()},
        )

        assert refs(snapshot) == []

    def test_reports_stale_reference_when_span_only_resembles_title(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # Only an exact title shape or example is skipped: a path beside one is still checked.
        text = "Not `wip/{summary}/notes.md` nor `x/{ISSUE}-{summary}.md`.\n"
        snapshot = snapshot_of(config=a_wip_title_config(), files={"AGENTS.md": text.encode()})

        assert refs(snapshot) == [
            stale("AGENTS.md", 1, "wip/{summary}/notes.md"),
            stale("AGENTS.md", 1, "x/{ISSUE}-{summary}.md"),
        ]

    def test_skips_no_convention_branch_when_hub_unconfigured(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # An unconfigured hub renders no shape, so the same spans stay stale references.
        snapshot = snapshot_of(files={"AGENTS.md": WORK_BRANCH_SPANS.encode()})

        assert [message for _, _, message, _ in refs(snapshot)] == [
            "stale reference `work/{issue_lower}/{slug}` (no such path)",
            "stale reference `work/dem-7/collector` (no such path)",
            "stale reference `release/{ISSUE}` (no such path)",
            "stale reference `release/DEM-7` (no such path)",
        ]

    def test_reports_stale_reference_when_hub_sets_no_prefix(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # A team hub: each developer's prefix is theirs, so no reference is skipped as a branch.
        document = a_hub_document()
        del document["project"]["branch_prefix"]
        text = "Run `scripts/gone.py`.\nNot the branch `jdoe/dem-1-x`.\n"
        snapshot = snapshot_of(
            config=HubConfig.model_validate(document), files={"AGENTS.md": text.encode()}
        )

        assert refs(snapshot) == [
            stale("AGENTS.md", 1, "scripts/gone.py"),
            stale("AGENTS.md", 2, "jdoe/dem-1-x"),
        ]

    def test_skips_local_file_reference_when_named(self, snapshot_of: SnapshotFactory) -> None:
        # hub.local.json is gitignored and each developer's own: never listed, never stale. Only
        # the exact name is skipped, so a path that merely ends in it is still checked.
        text = (
            "Set it in `hub.local.json` or [the local file](hub.local.json).\n"
            "Not `docs/hub.local.json`.\n"
        )
        snapshot = snapshot_of(files={"AGENTS.md": text.encode()})

        assert refs(snapshot) == [stale("AGENTS.md", 2, "docs/hub.local.json")]

    def test_reports_files_in_sorted_order_when_listed_in_reverse(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        files = {"CLAUDE.md": b"`a/gone.md`\n", "AGENTS.md": b"x\r\n`b/gone.md`\r\n"}
        snapshot = snapshot_of(files=files, listed=tuple(sorted(files, reverse=True)))

        assert refs(snapshot) == [
            stale("AGENTS.md", 2, "b/gone.md"),
            stale("CLAUDE.md", 1, "a/gone.md"),
        ]

    @pytest.mark.parametrize(
        ("text", "listed"),
        [
            pytest.param("[x](other.md)", ".claude/rules/other.md", id="file-folder"),
            pytest.param("[x](./other.md)", ".claude/rules/other.md", id="dot-slash"),
            pytest.param("`docs/guide.md`", "docs/guide.md", id="root"),
            pytest.param("[x](sub/../other.md)", ".claude/rules/other.md", id="dot-dot-inside"),
            pytest.param("`docs/design/`", "docs/design/a.md", id="folder-of-listed-file"),
            pytest.param("[x](docs)", "docs/design/a.md", id="top-folder"),
            pytest.param("`src/app/main`", "src/app/main.py", id="extension-py"),
            pytest.param("`src/app/view`", "src/app/view.tsx", id="extension-tsx"),
            pytest.param("`widget.ts`", "packages/ui/widget.ts", id="basename"),
            pytest.param("[x](widget)", "packages/ui/widget.js", id="basename-extension"),
            pytest.param("[x](design)", "docs/design/a.md", id="basename-folder"),
            pytest.param("`ui/widget.ts`", "packages/ui/widget.ts", id="suffix"),
            pytest.param("`app/main`", "src/app/main.py", id="suffix-extension"),
            pytest.param("`web/design`", "apps/web/design/a.md", id="suffix-folder"),
            pytest.param("[x](tests/test_a.py::test_b)", "tests/test_a.py", id="test-id"),
            pytest.param("[x](@/lib/a.ts)", "src/lib/a.ts", id="at-alias"),
            pytest.param("`docs/*.md`", "docs/a.md", id="glob"),
            pytest.param("`docs/{a,b}.md`", "docs/a.md", id="braces"),
        ],
    )
    def test_resolves_reference_when_listed_file_or_folder(
        self, snapshot_of: SnapshotFactory, *, text: str, listed: str
    ) -> None:
        files = {RULE: f"{text}\n".encode(), listed: b"x\n"}

        assert refs(snapshot_of(files=files)) == []
        # The same reference with nothing listed under it is reported.
        assert refs(snapshot_of(files={RULE: f"{text}\n".encode()})) != []

    def test_resolves_reference_when_fixed_path_unlisted(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # A fixed path is looked at by path even when the listing leaves it out (it exists).
        snapshot = snapshot_of(
            files={"AGENTS.md": b"`.mcp.json` and `docs/x.md`\n", ".mcp.json": b"{}\n"},
            listed=("AGENTS.md",),
        )

        assert refs(snapshot) == [stale("AGENTS.md", 1, "docs/x.md")]

    def test_reports_reference_when_it_leaves_hub(self, snapshot_of: SnapshotFactory) -> None:
        # Resolved against the listing only: a path out of the hub is never looked at.
        # (A reference that starts with ``../`` is skipped; one that only climbs later is not.)
        ref = "sub/../../../../AGENTS.md"
        snapshot = snapshot_of(files={RULE: f"[x]({ref})\n".encode(), "AGENTS.md": b"x\n"})

        assert refs(snapshot) == [stale(RULE, 1, ref)]

    def test_resolves_reference_when_listed_link_dangles(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E31: references resolve against the listing, not the disk; a listed link is a path
        # there, whether its target exists or not (the old lint's disk check said it did not).
        snapshot = snapshot_of(
            files={"AGENTS.md": b"`docs/gone.md` and [x](docs/gone.md)\n"},
            links={"docs/gone.md": "../nowhere/gone.md"},
        )

        assert refs(snapshot) == []

    def test_skips_lock_reference_when_lock_absent(self, snapshot_of: SnapshotFactory) -> None:
        # E35: a hub not yet adopted has no hub.lock; that is lock.drift's finding, never a
        # second one here.
        snapshot = snapshot_of(files={"AGENTS.md": b"Never edit `hub.lock` by hand.\n"})

        assert refs(snapshot) == []

    def test_reports_reference_when_under_linked_folder(self, snapshot_of: SnapshotFactory) -> None:
        # E31, D3: a linked folder is one listed link; nothing under it is listed, so a path
        # under it is stale (the old lint followed the link on disk), while the link resolves.
        snapshot = snapshot_of(
            files={"AGENTS.md": b"`vendor/lib/a.md` in `vendor/`\n"},
            links={"vendor": "../shared/vendor"},
        )

        assert refs(snapshot) == [stale("AGENTS.md", 1, "vendor/lib/a.md")]

    def test_checks_make_targets_when_makefile_present(self, snapshot_of: SnapshotFactory) -> None:
        makefile = b"check-fast: lint\n\tx\nlint:\n\tx\nvenv := .venv\n.PHONY: lint\n"
        text = b"Run make check-fast, make lint and make venv. Then make sure: make deploy.\n"
        snapshot = snapshot_of(files={"AGENTS.md": text, "Makefile": makefile})

        assert refs(snapshot) == [
            ("AGENTS.md", 1, "`make sure` is not a Makefile target", MAKE_FIX),
            ("AGENTS.md", 1, "`make deploy` is not a Makefile target", MAKE_FIX),
        ]

    def test_checks_pnpm_scripts_when_package_json_present(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        package = json.dumps({"scripts": {"test": "vitest", "lint:fix": "eslint"}}).encode()
        text = (
            b"pnpm install, pnpm test, pnpm run lint:fix, pnpm exec x, pnpm dlx y.\n"
            b"pnpm build\npnpm run deploy:prod\n"
        )
        snapshot = snapshot_of(files={"AGENTS.md": text, "package.json": package})

        assert refs(snapshot) == [
            ("AGENTS.md", 2, "`pnpm build` is not a package.json script", PNPM_FIX),
            ("AGENTS.md", 3, "`pnpm deploy:prod` is not a package.json script", PNPM_FIX),
        ]

    @pytest.mark.parametrize(
        "files",
        [
            pytest.param({}, id="both-absent"),
            pytest.param({"Makefile": b"# no targets\n"}, id="makefile-without-targets"),
            pytest.param({"package.json": b'{"scripts": {}}'}, id="no-scripts"),
            pytest.param({"package.json": b'{"name": "x"}'}, id="scripts-absent"),
        ],
    )
    def test_skips_targets_when_makefile_or_package_json_absent(
        self, snapshot_of: SnapshotFactory, files: dict[str, bytes]
    ) -> None:
        snapshot = snapshot_of(files={"AGENTS.md": b"make sure, pnpm build\n", **files})

        assert refs(snapshot) == []

    @pytest.mark.parametrize(
        "name",
        [pytest.param("Makefile", id="makefile"), pytest.param("package.json", id="package-json")],
    )
    def test_skips_targets_when_file_is_link(self, snapshot_of: SnapshotFactory, name: str) -> None:
        # Links are never followed (D3), even to a file that would define the name.
        snapshot = snapshot_of(
            files={"AGENTS.md": b"make sure, pnpm build\n", "other": b"x\n"},
            links={name: "other"},
        )

        assert refs(snapshot) == []

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(b'{"scripts": {"test": 1}', id="not-json"),
            pytest.param(b'["scripts"]', id="top-level-list"),
            pytest.param(b'{"scripts": ["test"]}', id="scripts-list"),
            pytest.param(b'{"scripts": "test"}', id="scripts-string"),
            pytest.param(b'{"scripts": {"test": "\xff"}}', id="not-utf8"),
            pytest.param(b"[" * 100_000 + b"]" * 100_000, id="too-deep"),
            pytest.param(b'{"scripts": {"t": ' + b"1" * 5000 + b"}}", id="too-many-digits"),
        ],
    )
    def test_skips_scripts_when_package_json_invalid(
        self, snapshot_of: SnapshotFactory, content: bytes
    ) -> None:
        # E11: as if there were no scripts; the file's own problem is not this rule's.
        snapshot = snapshot_of(files={"AGENTS.md": b"pnpm build\n", "package.json": content})

        assert refs(snapshot) == []

    def test_skips_linked_instruction_file_when_refs_checked(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E1: a file link at an instruction path is not an instruction file.
        agent = b"See `docs/gone.md`.\n"
        target = "plugin/hub-workflow/agents/x.md"
        linked = snapshot_of(files={target: agent}, links={".claude/agents/x.md": target})
        regular = snapshot_of(files={target: agent, ".claude/agents/x.md": agent})

        assert refs(linked) == []
        assert refs(regular) == [stale(".claude/agents/x.md", 1, "docs/gone.md")]

    @pytest.mark.parametrize(
        "suffix",
        [pytest.param(b"\xff", id="undecodable"), pytest.param(b"\x00", id="nul")],
    )
    def test_skips_file_when_not_text(self, snapshot_of: SnapshotFactory, suffix: bytes) -> None:
        # E28: the runner reports the file once; the rule gives nothing on it.
        text = b"`docs/gone.md`\n"
        snapshot = snapshot_of(files={"AGENTS.md": text + suffix, "CLAUDE.md": text})

        assert refs(snapshot) == [stale("CLAUDE.md", 1, "docs/gone.md")]

    def test_skips_file_when_content_unread(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(entries={"AGENTS.md": FileEntry(executable=False, content=None)})

        assert refs(snapshot) == []

    def test_cuts_echoed_reference_when_long(self, snapshot_of: SnapshotFactory) -> None:
        long_ref = "docs/" + "a" * 200 + ".md"
        target, script = "b" * 200, "c" * 200
        snapshot = snapshot_of(
            files={
                "AGENTS.md": f"`{long_ref}` make {target} pnpm {script}\n".encode(),
                "Makefile": b"check:\n",
                "package.json": b'{"scripts": {"test": "x"}}',
            }
        )

        assert [message for _, _, message, _ in refs(snapshot)] == [
            f"stale reference `{long_ref[:79]}…` (no such path)",
            f"`make {target[:79]}…` is not a Makefile target",
            f"`pnpm {script[:79]}…` is not a package.json script",
        ]

    @pytest.mark.parametrize(
        ("line", "expected"),
        [
            pytest.param("](" * 500_000, [], id="link-openers"),
            pytest.param("](a#" * 250_000, [], id="link-fragments-unclosed"),
            pytest.param("`" * 1_000_000, [], id="backticks"),
            pytest.param("`a/" + "b/" * 500_000 + "!`", [], id="long-path-span"),
            pytest.param(
                "](" + "<" * 1_000_000 + ")",
                [stale("AGENTS.md", 1, "<" * 79 + "…")],
                id="placeholder-openers",
            ),
            pytest.param(
                "make " * 200_000,
                [("AGENTS.md", 1, "`make make` is not a Makefile target", MAKE_FIX)] * 100_000,
                id="make-words",
            ),
        ],
    )
    def test_reports_exact_findings_when_line_hostile(
        self, snapshot_of: SnapshotFactory, *, line: str, expected: list[Shown4]
    ) -> None:
        # One line of about 1 MiB of openers, backticks or brackets.
        snapshot = snapshot_of(files={"AGENTS.md": f"{line}\n".encode(), "Makefile": b"check:\n"})

        found = refs(snapshot)

        assert found == expected

    @pytest.mark.parametrize(
        "line",
        [
            pytest.param("](" * 50_000, id="openers"),
            pytest.param("](a#" * 50_000, id="fragments-unclosed"),
            pytest.param("](a" * 50_000 + ")", id="one-close"),
        ],
    )
    def test_scans_each_link_run_once_when_openers_repeat(
        self, monkeypatch: pytest.MonkeyPatch, line: str
    ) -> None:
        # The old pattern rescans the rest of the line from every "](": count what is scanned.
        scanned = ScanCounter(instruction_rules._LINK_TARGET_STOP)
        monkeypatch.setattr(instruction_rules, "_LINK_TARGET_STOP", scanned)

        list(instruction_rules._link_targets(line))

        assert scanned.characters <= len(line)

    @pytest.mark.parametrize(
        "line",
        [
            "[a](b)",
            "[a](b#c)",
            "[a](b#c",
            "[a](b c)",
            "[a](b\tc)",
            "](",
            "[a]()",
            "[a](#x)",
            "[a](b)(c)",
            "[a](](b))",
            "](a#](b)",
            "](a](b)",
            "](a#b)c)",
            "[x](a)[y](b#z)",
            "text](a) more](b#)",
            "](a)](",
            "]((a)",
            "](a](b#c](d)",
            "](a#b](c)",
        ],
    )
    def test_finds_old_link_targets_when_line_crafted(self, line: str) -> None:
        assert list(instruction_rules._link_targets(line)) == OLD_LINK.findall(line)

    @pytest.mark.parametrize(
        "ref",
        ["<a>", "a<b", "a>b<", "<>", "<<>", "a<b>c", "a>b<c>", "x", "path/to/", "$A", "${", "…"],
    )
    def test_matches_old_placeholder_when_ref_crafted(self, ref: str) -> None:
        assert instruction_rules._is_placeholder(ref) is (OLD_PLACEHOLDER.search(ref) is not None)

    def test_resolves_many_references_when_hub_large(self, snapshot_of: SnapshotFactory) -> None:
        # 5100 references over 1700 listed files.
        listed = {f"packages/p{n}/src/m{n}.py": b"x\n" for n in range(1_700)}
        text = "".join(f"`m{n}.py` `p{n}/src/m{n}` `src/gone{n}.py`\n" for n in range(1_700))
        snapshot = snapshot_of(files={"AGENTS.md": text.encode(), **listed})

        found = refs(snapshot)

        assert found == [stale("AGENTS.md", n + 1, f"src/gone{n}.py") for n in range(1_700)]

    def test_resolves_by_name_and_end_when_paths_deep(self, snapshot_of: SnapshotFactory) -> None:
        # Five chains 600 folders deep: every folder and every end of a path is searched.
        chains = [[f"c{n}", *(f"s{depth}" for depth in range(599))] for n in range(5)]
        files = {"/".join([*chain, f"f{n}.md"]): b"x\n" for n, chain in enumerate(chains)}
        text = (
            "`f3.md` `s598/f3.md` `c2/s0/s1` `s10/s11/s12/` `s597/s598`\n`s598/gone.md` `c1/s1`\n"
        )
        snapshot = snapshot_of(files={"AGENTS.md": text.encode(), **files})

        assert refs(snapshot) == [
            stale("AGENTS.md", 2, "s598/gone.md"),
            stale("AGENTS.md", 2, "c1/s1"),
        ]

    def test_keeps_path_tree_linear_when_paths_deep(self) -> None:
        # One node per distinct folder or file, never one per folder's ancestors or ends.
        paths = [
            "/".join([f"c{n}", *(f"s{depth}" for depth in range(599)), "f.md"]) for n in range(5)
        ]

        tree = config_lint.path_tree(paths)

        assert nodes_of(tree) == sum(path.count("/") + 1 for path in paths)

    @pytest.mark.parametrize(
        ("segments", "flagged"),
        [pytest.param(32, False, id="at-bound"), pytest.param(33, True, id="over-bound")],
    )
    def test_searches_end_up_to_bound_when_reference_deep(
        self, snapshot_of: SnapshotFactory, *, segments: int, flagged: bool
    ) -> None:
        # A deeper reference counts only from its folder or the root (SEARCHED_SEGMENTS).
        path = "/".join(f"s{depth}" for depth in range(40))
        ref = "/".join(path.split("/")[-segments:])
        snapshot = snapshot_of(files={"AGENTS.md": f"`{ref}`\n".encode(), path: b"x\n"})

        shown = ref if len(ref) <= 80 else f"{ref[:79]}…"
        assert refs(snapshot) == ([stale("AGENTS.md", 1, shown)] if flagged else [])

    @pytest.mark.parametrize(
        ("entry", "ref"),
        [
            pytest.param(
                FileEntry(executable=False, content=b"x\n"), "`hub.lock.d/x.md`", id="lock-path"
            ),
            pytest.param(
                FileEntry(executable=False, content=b"x\n"), "`x.md`", id="lock-path-name"
            ),
            pytest.param(
                FileEntry(executable=False, content=None), "`hub.lock.d/x.md`", id="leftover"
            ),
        ],
    )
    def test_reports_reference_when_only_unlisted_entry(
        self, snapshot_of: SnapshotFactory, *, entry: FileEntry, ref: str
    ) -> None:
        # E31: only the listing and the fixed paths present count; the lock's paths and the
        # leftover names the reader also records do not, so --only never changes the result.
        snapshot = snapshot_of(
            files={"AGENTS.md": f"{ref}\n".encode()},
            entries={"hub.lock.d/x.md": entry},
            listed=("AGENTS.md",),
        )

        assert refs(snapshot) == [stale("AGENTS.md", 1, ref.strip("`"))]

    def test_checks_project_makefile_targets_when_included(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E31: the managed Makefile includes Makefile.project; a target there is a target.
        snapshot = snapshot_of(
            files={
                "AGENTS.md": b"make check, make deploy, make sure\n",
                "Makefile": b"check:\n\t-include Makefile.project\n",
                "Makefile.project": b"deploy:\n\tx\n",
            }
        )

        assert refs(snapshot) == [
            ("AGENTS.md", 1, "`make sure` is not a Makefile target", MAKE_FIX)
        ]

    def test_accepts_make_target_when_module_makefile_defines_it(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E13: the builder's config selects bench and cloud; marketplace is not selected, so
        # its mk/ file is not included by the Makefile and defines nothing.
        snapshot = snapshot_of(
            files={
                "AGENTS.md": (
                    b"make check, make bench, make cloud-setup, make marketplace-validate\n"
                ),
                "Makefile": b"check:\n",
                "mk/bench.mk": b"bench:\n\tx\n",
                "mk/cloud.mk": b"cloud-setup:\n\tx\n",
                "mk/marketplace.mk": b"marketplace-validate:\n\tx\n",
            }
        )

        assert refs(snapshot) == [
            ("AGENTS.md", 1, "`make marketplace-validate` is not a Makefile target", MAKE_FIX)
        ]

    @pytest.mark.parametrize(
        ("files", "flagged"),
        [
            pytest.param({"Makefile": b"check:\n\xff"}, [], id="not-utf8"),
            pytest.param({"Makefile": b"check:\n\x00"}, [], id="nul"),
            pytest.param({"Makefile.project": b"deploy:\n"}, ["check", "sure"], id="project-only"),
            pytest.param(
                {"Makefile": b"check:\n\x00", "Makefile.project": b"deploy:\n"},
                ["check", "sure"],
                id="nul-makefile-project-text",
            ),
        ],
    )
    def test_reads_makefile_targets_when_text(
        self, snapshot_of: SnapshotFactory, *, files: dict[str, bytes], flagged: list[str]
    ) -> None:
        # A Makefile that is not text gives no targets; with none at all, nothing is checked.
        snapshot = snapshot_of(files={"AGENTS.md": b"make check make deploy make sure\n", **files})

        assert refs(snapshot) == [
            ("AGENTS.md", 1, f"`make {name}` is not a Makefile target", MAKE_FIX)
            for name in flagged
        ]

    def test_skips_project_makefile_when_link(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": b"make deploy\n", "Makefile": b"check:\n", "other": b"deploy:\n"},
            links={"Makefile.project": "other"},
        )

        assert refs(snapshot) == [
            ("AGENTS.md", 1, "`make deploy` is not a Makefile target", MAKE_FIX)
        ]

    @pytest.mark.parametrize(
        ("makefile", "flagged"),
        [
            # The old whole-text pattern: blanks, line breaks included, may precede the ":".
            pytest.param(b"deploy\n: all\ncheck:\n", [], id="colon-on-next-line"),
            # E29: a lone \r does not end a line, so "deploy" is not at a line's start.
            pytest.param(b"check: x\rdeploy: y\n", ["deploy"], id="lone-cr"),
        ],
    )
    def test_reads_makefile_lines_when_breaks_vary(
        self, snapshot_of: SnapshotFactory, *, makefile: bytes, flagged: list[str]
    ) -> None:
        snapshot = snapshot_of(files={"AGENTS.md": b"make deploy\n", "Makefile": makefile})

        assert refs(snapshot) == [
            ("AGENTS.md", 1, f"`make {name}` is not a Makefile target", MAKE_FIX)
            for name in flagged
        ]

    def test_keeps_last_scripts_when_key_repeated(self, snapshot_of: SnapshotFactory) -> None:
        # Read as the old json.load (and pnpm) do: the last "scripts" wins.
        package = b'{"scripts": {"build": "x"}, "scripts": {"test": "y"}}'
        snapshot = snapshot_of(
            files={"AGENTS.md": b"pnpm test pnpm build\n", "package.json": package}
        )

        assert refs(snapshot) == [
            ("AGENTS.md", 1, "`pnpm build` is not a package.json script", PNPM_FIX)
        ]


type Shown4 = tuple[str | None, int | None, str, str]

# The old lint's patterns, to compare the hand-written scans with.
OLD_LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)]*)?\)")
OLD_PLACEHOLDER = re.compile(r"<[^>]*>|path/to/|\.\.\.|…|\$\{?[A-Z_]+")


class ScanCounter:
    """A stand-in for a compiled pattern that counts the characters its searches pass over."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.characters = 0

    def search(self, text: str, start: int) -> re.Match[str] | None:
        found = self.pattern.search(text, start)
        self.characters += (len(text) if found is None else found.start()) - start
        return found


def nodes_of(tree: config_lint.PathTrie) -> int:
    count, pending = 0, [tree]
    while pending:
        children = pending.pop().children
        count += len(children)
        pending.extend(children.values())
    return count
