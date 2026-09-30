"""``rules.frontmatter``: the port of the old config lint's frontmatter checks (spec AC-11.21, Q-5).

A ``.claude/rules`` file with frontmatter needs a non-empty ``paths:`` list whose globs each match
a hub file or folder; an unterminated frontmatter in an instruction or plugin file is an error; an
agent or skill file needs ``name`` and ``description``. A file that is not text is the runner's to
report (E28): the rule skips it.
"""

import fnmatch
import re
from collections.abc import Callable

import pytest

from agent_hub.core.doctor import frontmatter_rule
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.frontmatter_rule import (
    MAX_GLOB_EXPANSIONS,
    MAX_GLOB_LENGTH,
    RULES_FRONTMATTER,
)
from agent_hub.core.doctor.run_rules import Selection, run_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str, str]

RULE = ".claude/rules/r.md"
UNTERMINATED = ("unterminated frontmatter", "close the frontmatter with `---`")
NO_PATHS = (
    "rules frontmatter needs a non-empty `paths:` list",
    "list the globs this rule applies to",
)
UNNAMED = ("agent/skill frontmatter needs `name` and `description`", "add both fields")
GLOB_FIX = "fix or remove the glob"
BUDGET_FIX = "use fewer or narrower globs"
NAMED = b"---\nname: a\ndescription: b\n---\nbody\n"


def found(snapshot: DoctorSnapshot) -> list[Shown]:
    findings = list(RULES_FRONTMATTER.check(snapshot))
    assert all(finding.rule == "rules.frontmatter" for finding in findings)
    assert all(finding.severity is Severity.ERROR for finding in findings)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in findings]


def at(path: str, problem: tuple[str, str]) -> Shown:
    return (path, 1, *problem)


def unmatched(path: str, glob: str) -> Shown:
    message = f"`paths` glob `{cut_echo(glob)}` matches no file or folder in the hub"
    return (path, 1, message, GLOB_FIX)


def unchecked(path: str, glob: str) -> Shown:
    message = f"`paths` glob `{cut_echo(glob)}` was not checked: the run's glob budget is spent"
    return (path, 1, message, BUDGET_FIX)


def a_rule(*globs: str) -> bytes:
    items = "".join(f"  - {glob}\n" for glob in globs)
    return f"---\npaths:\n{items}---\nbody\n".encode()


def test_declares_design_id_when_rule_read() -> None:
    assert RULES_FRONTMATTER.id == "rules.frontmatter"
    assert RULES_FRONTMATTER.severity is Severity.ERROR
    assert RULES_FRONTMATTER.module is None
    assert RULES_FRONTMATTER.reads == frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES})


class TestRulePaths:
    @pytest.mark.parametrize(
        "frontmatter",
        [
            pytest.param(b"---\ndescription: x\n---\n", id="missing"),
            pytest.param(b"---\npaths: src/**\n---\n", id="scalar"),
            pytest.param(b"---\npaths:\n---\n", id="empty"),
            pytest.param(b"---\npaths:\ndescription: x\n  - src/**\n---\n", id="items-elsewhere"),
        ],
    )
    def test_requires_paths_list_when_rule_has_frontmatter(
        self, snapshot_of: SnapshotFactory, frontmatter: bytes
    ) -> None:
        snapshot = snapshot_of(files={RULE: frontmatter, "src/a.py": b""})

        assert found(snapshot) == [at(RULE, NO_PATHS)]

    def test_ignores_rule_when_no_frontmatter(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={RULE: b"# no frontmatter\npaths:\n"})

        assert found(snapshot) == []

    def test_reports_glob_when_it_matches_nothing(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={RULE: a_rule("src/**", "gone/**", "'*.rs'"), "src/a.py": b""})

        assert found(snapshot) == [unmatched(RULE, "gone/**"), unmatched(RULE, "*.rs")]

    @pytest.mark.parametrize(
        "glob",
        [
            pytest.param("app/{api,web}/x.ts", id="braces"),
            pytest.param("{nothing,app}/**/x.ts", id="braces-and-double-star"),
            pytest.param("app/web/**/x.ts", id="double-star-as-slash"),
            pytest.param("app/**", id="double-star-crosses-folders"),
            pytest.param("app/*.ts", id="star-crosses-slash"),
            pytest.param("app/web", id="folder"),
            pytest.param("ap?/[vw]eb", id="folder-glob"),
            pytest.param('"app/web/x.ts"', id="quoted"),
        ],
    )
    def test_matches_glob_when_braces_or_double_star_used(
        self, snapshot_of: SnapshotFactory, glob: str
    ) -> None:
        snapshot = snapshot_of(files={RULE: a_rule(glob), "app/web/x.ts": b""})

        assert found(snapshot) == []

    def test_ignores_commands_paths_when_not_a_rule(self, snapshot_of: SnapshotFactory) -> None:
        text = b"---\ndescription: x\n---\n"
        snapshot = snapshot_of(
            files={".claude/commands/c.md": text, ".github/instructions/i.md": a_rule("gone")}
        )

        assert found(snapshot) == []

    def test_matches_nested_rule_when_under_rules_folder(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        snapshot = snapshot_of(files={".claude/rules/py/r.md": a_rule("gone")})

        assert found(snapshot) == [unmatched(".claude/rules/py/r.md", "gone")]

    def test_matches_fixed_path_when_unlisted(self, snapshot_of: SnapshotFactory) -> None:
        # E31: the listing plus the fixed paths present; never a lock path or leftover name.
        files = {
            RULE: a_rule("Makefile", "plugin/demo/hooks/*.py", "vendor/*", "x.orig"),
            "Makefile": b"",
            "plugin/demo/hooks/project_guard.py": b"",
            "vendor/lib.js": b"",
            "x.orig": b"",
        }
        snapshot = snapshot_of(files=files, listed=(RULE,))

        assert found(snapshot) == [unmatched(RULE, "vendor/*"), unmatched(RULE, "x.orig")]

    def test_matches_linked_path_when_listed(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={RULE: a_rule("doc*")}, links={"docs": "elsewhere"})

        assert found(snapshot) == []

    def test_reports_each_rule_file_when_glob_repeated(self, snapshot_of: SnapshotFactory) -> None:
        rules = {f".claude/rules/r{n}.md": a_rule("gone/*") for n in range(3)}
        snapshot = snapshot_of(files=rules)

        assert found(snapshot) == [unmatched(path, "gone/*") for path in sorted(rules)]

    def test_translates_glob_once_when_repeated(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        compiled: list[str] = []
        patterns = frontmatter_rule._patterns

        def counted(glob: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
            compiled.append(glob)
            return patterns(glob)

        monkeypatch.setattr(frontmatter_rule, "_patterns", counted)
        rules = {f".claude/rules/r{n}.md": a_rule("gone/**/x", "gone/**/x") for n in range(50)}

        found(snapshot_of(files=rules))

        assert compiled == ["gone/**/x", "gone/x"]


class TestAgentsAndSkills:
    @pytest.mark.parametrize(
        "path",
        [
            ".claude/agents/a.md",
            ".claude/skills/s/SKILL.md",
            "plugin/p/agents/a.md",
            "plugin/p/skills/s/SKILL.md",
            "plugin/p/skills/s/references/r.md",
        ],
    )
    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(b"no frontmatter\n", id="none"),
            pytest.param(b"---\nname: a\n---\n", id="no-description"),
            pytest.param(b"---\ndescription: b\n---\n", id="no-name"),
            pytest.param(b"---\nname:\ndescription: b\n---\n", id="empty-name"),
        ],
    )
    def test_requires_name_and_description_when_agent_or_skill(
        self, snapshot_of: SnapshotFactory, *, path: str, text: bytes
    ) -> None:
        snapshot = snapshot_of(files={path: text})

        assert found(snapshot) == [at(path, UNNAMED)]

    @pytest.mark.parametrize(
        "text",
        [
            pytest.param(NAMED, id="values"),
            pytest.param(b"---\nname:\n  - a\ndescription: >\n---\n", id="items-and-scalar"),
            pytest.param(b"---\r\nname: a\r\ndescription: b\r\n---\r\n", id="crlf"),
        ],
    )
    def test_accepts_agent_when_name_and_description_given(
        self, snapshot_of: SnapshotFactory, text: bytes
    ) -> None:
        snapshot = snapshot_of(files={".claude/agents/a.md": text, "plugin/p/agents/a.md": text})

        assert found(snapshot) == []

    @pytest.mark.parametrize(
        "path",
        [
            "plugin/p/agentsx/a.md",
            "plugin/p/hooks/a.md",
            "plugin/agents.md",
            ".claude/rules/r.md",
            ".claude/commands/c.md",
            "AGENTS.md",
            ".claude/agents/a.txt",
        ],
    )
    def test_ignores_file_when_not_agent_or_skill(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        snapshot = snapshot_of(files={path: b"no frontmatter\n"})

        assert found(snapshot) == []

    def test_skips_linked_agent_when_checked(self, snapshot_of: SnapshotFactory) -> None:
        # E1: a hub links each plugin agent into .claude/agents; the link is never followed.
        link = "../../plugin/hub-workflow/agents/a.md"
        linked = snapshot_of(links={".claude/agents/a.md": link, ".claude/skills/s": "../plugin"})
        regular = snapshot_of(files={".claude/agents/a.md": b"no frontmatter\n"})

        assert found(linked) == []
        assert found(regular) == [at(".claude/agents/a.md", UNNAMED)]


class TestUnterminated:
    @pytest.mark.parametrize(
        "path",
        [
            "AGENTS.md",
            ".claude/rules/r.md",
            ".claude/commands/c.md",
            ".claude/agents/a.md",
            "plugin/p/skills/s/SKILL.md",
        ],
    )
    def test_reports_unterminated_when_frontmatter_open(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        # One finding: no paths or name check on a frontmatter that never ends.
        snapshot = snapshot_of(files={path: b"---\nname: a\n"})

        assert found(snapshot) == [at(path, UNTERMINATED)]

    def test_closes_frontmatter_when_line_ends_vary(self, snapshot_of: SnapshotFactory) -> None:
        # E29: \r\n ends a line, a lone \r does not.
        snapshot = snapshot_of(
            files={"AGENTS.md": b"---\r\nx: y\r\n---\r\n", "CLAUDE.md": b"---\nx: y\r---\r"}
        )

        assert found(snapshot) == [at("CLAUDE.md", UNTERMINATED)]

    def test_reports_files_in_sorted_order_when_listed_in_reverse(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        paths = ("plugin/p/agents/a.md", "CLAUDE.md", ".claude/rules/r.md", "AGENTS.md")
        snapshot = snapshot_of(files=dict.fromkeys(paths, b"---\n"), listed=paths)

        assert found(snapshot) == [at(path, UNTERMINATED) for path in sorted(paths)]


class TestNotText:
    @pytest.mark.parametrize(
        "suffix",
        [pytest.param(b"\xff", id="undecodable"), pytest.param(b"\x00", id="nul")],
    )
    def test_skips_file_when_not_text(self, snapshot_of: SnapshotFactory, suffix: bytes) -> None:
        snapshot = snapshot_of(
            files={"AGENTS.md": b"---\n" + suffix, "plugin/p/agents/a.md": b"x\n" + suffix}
        )

        assert found(snapshot) == []

    def test_skips_file_when_content_unread(self, snapshot_of: SnapshotFactory) -> None:
        unread = FileEntry(executable=False, content=None)
        snapshot = snapshot_of(entries={"AGENTS.md": unread, "plugin/p/agents/a.md": unread})

        assert found(snapshot) == []

    def test_reports_plugin_file_once_when_rule_reads_it_first(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E28: the first selected reader of a plugin file reports it, and only once.
        snapshot = snapshot_of(files={"plugin/p/agents/a.md": b"\xff"})
        selection = Selection(rules=(RULES_FRONTMATTER,), notes=(), severities={})

        findings = run_rules(selection, snapshot)

        assert [(f.rule, f.path, f.line, f.message) for f in findings] == [
            (
                "rules.frontmatter",
                "plugin/p/agents/a.md",
                None,
                "not UTF-8 text: byte 0 cannot be decoded",
            )
        ]


# AC-11.21's oracle: the old lint's brace expansion and fnmatch over the files and their folders
# (its index), which the rule must agree with on every glob below.
def old_expand_braces(glob: str) -> list[str]:
    m = re.search(r"\{([^{}]*)\}", glob)
    if not m:
        return [glob]
    return [
        x
        for alt in m.group(1).split(",")
        for x in old_expand_braces(glob[: m.start()] + alt + glob[m.end() :])
    ]


def old_matches(glob: str, files: list[str]) -> bool:
    index = set(files)
    index |= {"/".join(p.split("/")[:k]) for p in list(index) for k in range(1, p.count("/") + 1)}
    globs = [x for e in old_expand_braces(glob) for x in (e, e.replace("/**/", "/"))]
    return any(fnmatch.fnmatch(p, x) for p in index for x in globs)


OLD_FILES = ["a/b/c.py", "a/b/d/e.md", "a[x]/f", "a!b/g", "top.md", "x-y/z", "p/**/q"]


class TestGlobs:
    @pytest.mark.parametrize(
        "glob",
        [
            "a",
            "a/b",
            "a/b/",
            "a/*",
            "a/*.md",
            "*.py",
            "*/c.py",
            "a/**/c.py",
            "a/**/d",
            "**",
            "*",
            "",
            "a/b/d/e.md/",
            "a[x]/f",
            "a[[]x]/f",
            "a[!y]b/g",
            "a[!]b/g",
            "[",
            "a[",
            "a[/f",
            "[]",
            "[!]",
            "a[]x]/f",
            "x-y/[a-z]",
            "x[z-a]y/z",
            "{a,top.md}",
            "{a/b,q}/c.py",
            "{a,{b,c}}/b",
            "{}",
            "{,a}/b",
            "a/{b",
            "a/b}",
            "{a/b/{c,d}.py,nothing}",
            "p/**/q",
            "?/b",
            "t?p.md",
            "a/b/?",
            "a/b/c.py[",
        ],
    )
    def test_matches_like_old_lint_when_glob_crafted(
        self, snapshot_of: SnapshotFactory, glob: str
    ) -> None:
        snapshot = snapshot_of(files={RULE: a_rule(glob), **dict.fromkeys(OLD_FILES, b"")})
        expected = [] if old_matches(glob, [RULE, *OLD_FILES]) else [unmatched(RULE, glob)]

        assert found(snapshot) == expected

    @pytest.mark.parametrize(
        ("glob", "closed"),
        [
            ("[" * 5, "[[]" * 5),
            ("a[b]c[", "a[b]c[[]"),
            ("[]x", "[[]]x"),
            ("[!]", "[[]!]"),
            ("[!]]", "[!]]"),
            ("[a]" * 3, "[a]" * 3),
            ("a*b?", "a*b?"),
        ],
    )
    def test_closes_open_brackets_when_glob_has_them(self, glob: str, closed: str) -> None:
        # Each [ that fnmatch reads as a literal is written [[], so translating is linear.
        assert frontmatter_rule._closed_brackets(glob) == closed

    @pytest.mark.parametrize(
        "glob", ["[", "a[", "[]x", "[!]", "a[b]c[d", "[z-a]", "[!a-]x[", "*[*", "[[[]]"]
    )
    def test_keeps_meaning_when_brackets_closed(self, glob: str) -> None:
        closed = frontmatter_rule._closed_brackets(glob)
        samples = ["", "[", "a[", "[]x", "[!]", "a[b]c[d", "abc[d", "z", "-x[", "a", "*[*", "[]"]
        for sample in samples:
            original = fnmatch.fnmatchcase(sample, glob)
            assert fnmatch.fnmatchcase(sample, closed) is original, (glob, sample)

    def test_reports_glob_when_longer_than_bound(self, snapshot_of: SnapshotFactory) -> None:
        at_bound = "a" * (MAX_GLOB_LENGTH - 2) + "/*"
        over = "[" * (MAX_GLOB_LENGTH + 1)
        path = "a" * (MAX_GLOB_LENGTH - 2) + "/x"
        snapshot = snapshot_of(files={RULE: a_rule(at_bound, over), path: b""})

        assert found(snapshot) == [
            (
                RULE,
                1,
                f"`paths` glob `{'[' * 79}…` is longer than {MAX_GLOB_LENGTH} characters",
                GLOB_FIX,
            )
        ]

    def test_matches_open_brackets_when_glob_at_bound(self, snapshot_of: SnapshotFactory) -> None:
        hostile = "[" * MAX_GLOB_LENGTH
        snapshot = snapshot_of(files={RULE: a_rule(hostile), hostile: b""})

        assert found(snapshot) == []

    @pytest.mark.parametrize(
        ("glob", "flagged"),
        [
            pytest.param("{a,b}" * 6, False, id="at-bound"),
            pytest.param("{a,b}" * 7, True, id="over-bound"),
            pytest.param("{a,b}" * 51, True, id="many-groups"),
            pytest.param("{" * 60 + "a,b" + "}" * 60, False, id="nested"),
            pytest.param("{" + "," * (MAX_GLOB_EXPANSIONS - 1) + "}", False, id="one-group-at"),
            pytest.param("{" + "," * MAX_GLOB_EXPANSIONS + "}", True, id="one-group-over"),
        ],
    )
    def test_bounds_brace_expansions_when_glob_has_many(
        self, snapshot_of: SnapshotFactory, *, glob: str, flagged: bool
    ) -> None:
        snapshot = snapshot_of(files={RULE: a_rule(glob, "gone")})
        too_many = (
            RULE,
            1,
            f"`paths` glob `{cut_echo(glob)}` expands to more than {MAX_GLOB_EXPANSIONS} globs",
            GLOB_FIX,
        )
        expected = [too_many] if flagged else [unmatched(RULE, glob)]

        assert found(snapshot) == [*expected, unmatched(RULE, "gone")]

    def test_stops_expanding_when_bound_reached(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Structural: the brace groups searched are about the bound's worth of expansions along
        # one depth-first path, never the 2**51 a full expansion would take.
        searched = SearchCounter(frontmatter_rule._BRACES)
        monkeypatch.setattr(frontmatter_rule, "_BRACES", searched)

        assert frontmatter_rule._expanded("{a,b}" * 51) is None
        assert searched.calls <= 2 * MAX_GLOB_EXPANSIONS

    def test_expands_like_old_lint_when_braces_crafted(self) -> None:
        for glob in ["{a,b}{c,d}", "{a,{b,c}}", "x{}y", "{,}", "a{b", "{a}{b,c}d"]:
            assert frontmatter_rule._expanded(glob) == old_expand_braces(glob), glob

    def test_matches_deep_folder_when_paths_deep(self, snapshot_of: SnapshotFactory) -> None:
        chains = [[f"c{n}", *(f"s{depth}" for depth in range(599))] for n in range(5)]
        files = {"/".join([*chain, f"f{n}.md"]): b"" for n, chain in enumerate(chains)}
        globs = ("c1/s0/s1", "*/s598", "c3/**/f3.md", "c2/*/s598/f2.md", "*/s599", "c9/*")
        snapshot = snapshot_of(files={RULE: a_rule(*globs), **files})

        assert found(snapshot) == [unmatched(RULE, "*/s599"), unmatched(RULE, "c9/*")]

    def test_reads_each_path_once_per_glob_when_paths_deep(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Structural: no folder is built as a string; each path is matched whole, at most twice.
        chains = [[f"c{n}", *(f"s{depth}" for depth in range(599))] for n in range(5)]
        files = {"/".join([*chain, "f.md"]): b"" for chain in chains}
        counters: list[MatchCounter] = []
        patterns = frontmatter_rule._patterns

        def counted(glob: str) -> tuple[MatchCounter, MatchCounter]:
            pair = tuple(MatchCounter(pattern) for pattern in patterns(glob))
            counters.extend(pair)
            return pair[0], pair[1]

        monkeypatch.setattr(frontmatter_rule, "_patterns", counted)
        snapshot = snapshot_of(files={RULE: a_rule("*/nothing"), **files})

        assert found(snapshot) == [unmatched(RULE, "*/nothing")]
        total = sum(len(path) for path in (RULE, *files))
        assert sum(counter.characters for counter in counters) <= 2 * total

    def test_searches_only_prefix_when_glob_starts_literal(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        counters: list[MatchCounter] = []
        patterns = frontmatter_rule._patterns

        def counted(glob: str) -> tuple[MatchCounter, MatchCounter]:
            pair = tuple(MatchCounter(pattern) for pattern in patterns(glob))
            counters.extend(pair)
            return pair[0], pair[1]

        monkeypatch.setattr(frontmatter_rule, "_patterns", counted)
        files = {f"other/f{n}.py": b"" for n in range(1000)} | {"src/a.py": b""}
        snapshot = snapshot_of(files={RULE: a_rule("src/*.rs"), **files})

        assert found(snapshot) == [unmatched(RULE, "src/*.rs")]
        assert sum(counter.calls for counter in counters) <= 2


class TestBudget:
    def test_spends_run_budget_when_globs_many(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # E33, structural: with a budget of 10 path matches, "src/a0.py" tries 1 path and "*.rs"
        # all 7; "*.txt" would pass the budget, so it and every later glob are not checked (a
        # glob decided before, "src/a0.py", keeps its result).
        monkeypatch.setattr(frontmatter_rule, "MAX_GLOB_MATCHES", 10)
        counters = count_patterns(monkeypatch)
        files = {f"src/a{n}.py": b"" for n in range(5)}
        first = {".claude/rules/a.md": a_rule("src/a0.py", "*.rs", "*.txt")}
        later = {".claude/rules/b.md": a_rule("src/a1.py", "src/a0.py")}
        snapshot = snapshot_of(files={**first, **later, **files})

        assert found(snapshot) == [
            unmatched(".claude/rules/a.md", "*.rs"),
            unchecked(".claude/rules/a.md", "*.txt"),
            unchecked(".claude/rules/b.md", "src/a1.py"),
        ]
        assert sum(counter.calls for counter in counters[0::2]) <= 10

    def test_checks_every_glob_when_budget_enough(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(frontmatter_rule, "MAX_GLOB_MATCHES", 15)
        files = {f"src/a{n}.py": b"" for n in range(5)}
        rules = {".claude/rules/a.md": a_rule("src/a0.py", "*.rs", "*.txt")}
        snapshot = snapshot_of(files={**rules, **files})

        assert found(snapshot) == [
            unmatched(".claude/rules/a.md", "*.rs"),
            unmatched(".claude/rules/a.md", "*.txt"),
        ]

    def test_bounds_run_when_default_budget(self) -> None:
        assert frontmatter_rule.MAX_GLOB_MATCHES == 2_000_000


def count_patterns(monkeypatch: pytest.MonkeyPatch) -> list[MatchCounter]:
    """Wrap each glob's file and folder patterns in counters, in that order."""
    counters: list[MatchCounter] = []
    patterns = frontmatter_rule._patterns

    def counted(glob: str) -> tuple[MatchCounter, MatchCounter]:
        pair = (MatchCounter(patterns(glob)[0]), MatchCounter(patterns(glob)[1]))
        counters.extend(pair)
        return pair

    monkeypatch.setattr(frontmatter_rule, "_patterns", counted)
    return counters


class SearchCounter:
    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.calls = 0

    def search(self, text: str) -> re.Match[str] | None:
        self.calls += 1
        return self.pattern.search(text)


class MatchCounter:
    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.calls = 0
        self.characters = 0

    def match(self, text: str) -> re.Match[str] | None:
        self.calls += 1
        self.characters += len(text)
        return self.pattern.match(text)

    def fullmatch(self, text: str) -> re.Match[str] | None:
        self.calls += 1
        self.characters += len(text)
        return self.pattern.fullmatch(text)
