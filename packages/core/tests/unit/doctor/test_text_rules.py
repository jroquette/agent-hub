"""``secrets.config`` and ``attribution.ai``: the old config lint's text checks (AC-11.23, E11).

Each line of the instruction files, the plugins' agent and skill files, ``.mcp.json``,
``.claude/settings.json``, ``CONTRIBUTING.md`` and either PR-template spelling is searched for the
nine secret shapes and the three AI-attribution patterns; a finding names the kind, never the
text. A file that is not text is the runner's to report (E28): the rules skip it.

Every secret-shaped or attribution string here is assembled at run time from harmless pieces, so
this file holds no secret-shaped text.
"""

import re
from collections.abc import Callable

import pytest

from agent_hub.core.doctor import text_rules
from agent_hub.core.doctor.finding import Read, Rule
from agent_hub.core.doctor.run_rules import Selection, run_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.doctor.text_rules import ATTRIBUTION_AI, SECRETS_CONFIG
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.testing.builders import a_hub_document

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str, str]

AGENTS = "AGENTS.md"
SETTINGS = ".claude/settings.json"
PROJECT_SETTINGS = ".claude/settings.project.json"
MEBIBYTE = 1 << 20
# The size of the scale cases whose patterns never retried a run (the rewritten two get 1 MiB).
SMALL = 1 << 16

ROTATE_FIX = "remove it and rotate the credential; reference an env var name instead"
# The builder's hub.json: branch_prefix ``jdoe/``, tracker team ``DEM``.
ATTRIBUTION_FIX = "branches are `jdoe/dem-<N>-<desc>`; commits/PRs carry no AI trailer"

DASHES = "-" * 5
KEY_HEADER = DASHES + "BEGIN " + "PRIVATE" + " KEY" + DASHES
# Each kind at its minimum length, and one character short (the private key: one dash short).
AT_MINIMUM = {
    "JWT": "ey" + "J" + "a" * 15 + "." + "b" * 15,
    "AWS access key": "AK" + "IA" + "A" * 16,
    "private key": KEY_HEADER,
    "API key (live)": "sk" + "_live_" + "a" * 16,
    "API key (dash)": "sk" + "-" + "a" * 20,
    "GitHub token": "gh" + "p_" + "a" * 30,
    "Linear API key": "lin" + "_api_" + "a" * 20,
    "credential assignment": "PASS" + "WORD=" + "x" * 6,
    "Fernet-like key": "a" * 43 + "=",
}
BELOW_MINIMUM = {
    "JWT": "ey" + "J" + "a" * 14 + "." + "b" * 15,
    "AWS access key": "AK" + "IA" + "A" * 15,
    "private key": KEY_HEADER[:-1],
    "API key (live)": "sk" + "_live_" + "a" * 15,
    "API key (dash)": "sk" + "-" + "a" * 19,
    "GitHub token": "gh" + "p_" + "a" * 29,
    "Linear API key": "lin" + "_api_" + "a" * 19,
    "credential assignment": "PASS" + "WORD=" + "x" * 5,
    "Fernet-like key": "a" * 42 + "=",
}

CO_AUTHOR = "Co-" + "Authored-By:"
TRAILER = CO_AUTHOR + " " + "Claude" + " <noreply@example.com>"
GENERATED = "Generated " + "with [Claude" + " Code](https://example.com)"
BRANCH = "git switch -c " + "claude" + "/fix-login"
ATTRIBUTIONS = {
    "AI co-author trailer": TRAILER,
    '"Generated with Claude Code"': GENERATED,
    "`claude/` branch prefix": BRANCH,
}

# The old lint's patterns, verbatim (the private key's dashes assembled): the oracle the rules'
# shapes must agree with on every line below.
OLD_SECRETS = (
    (r"eyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]{15,}", "JWT"),
    (r"AKIA[0-9A-Z]{16}", "AWS access key"),
    (DASHES + r"BEGIN [A-Z ]*PRIVATE KEY" + DASHES, "private key"),
    (r"\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9]{16,}", "API key"),
    (r"\bsk-[A-Za-z0-9_-]{20,}", "API key"),
    (r"\bghp_[A-Za-z0-9]{30,}", "GitHub token"),
    (r"\blin_api_[A-Za-z0-9]{20,}", "Linear API key"),
    (
        r"(?i)\b[A-Z_]*(?:PASSWORD|SECRET|TOKEN|ENCRYPTION_KEY)\s*=\s*['\"]?[^\s'\"<>$`{]{6,}",
        "credential assignment",
    ),
    (r"\b[A-Za-z0-9_-]{43}=(?![A-Za-z0-9])", "Fernet-like key"),
)
OLD_ATTRIBUTIONS = (
    (r"(?i)co-authored-by:\s*(claude|.*anthropic|.*openai|copilot)", "AI co-author trailer"),
    (r"(?i)generated with \[?claude code", '"Generated with Claude Code"'),
    (r"\bclaude/(?:<|[a-z0-9-]+-)", "`claude/` branch prefix"),
)


def found(rule: Rule, snapshot: DoctorSnapshot) -> list[Shown]:
    findings = list(rule.check(snapshot))
    assert all(finding.rule == rule.id for finding in findings)
    assert all(finding.severity is Severity.ERROR for finding in findings)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in findings]


def secret(path: str, line: int, kind: str) -> Shown:
    return (path, line, f"possible secret ({kind})", ROTATE_FIX)


def attribution(path: str, line: int, kind: str) -> Shown:
    return (path, line, f"AI attribution: {kind}", ATTRIBUTION_FIX)


def kind_of(name: str) -> str:
    return name.split(" (")[0]


def test_declares_design_ids_when_rules_read() -> None:
    assert (SECRETS_CONFIG.id, ATTRIBUTION_AI.id) == ("secrets.config", "attribution.ai")
    for rule in (SECRETS_CONFIG, ATTRIBUTION_AI):
        assert rule.severity is Severity.ERROR
        assert rule.module is None
        # CONTRIBUTING.md and the PR templates come from the listing the file sets need.
        assert rule.reads == frozenset({Read.INSTRUCTION_FILES, Read.PLUGIN_FILES})


class TestSecrets:
    @pytest.mark.parametrize("name", list(AT_MINIMUM))
    def test_flags_each_secret_kind_when_at_minimum_length(
        self, snapshot_of: SnapshotFactory, name: str
    ) -> None:
        text = f"x {AT_MINIMUM[name]}\n{BELOW_MINIMUM[name]}\n"
        snapshot = snapshot_of(files={AGENTS: text.encode()})

        assert found(SECRETS_CONFIG, snapshot) == [secret(AGENTS, 1, kind_of(name))]
        assert found(ATTRIBUTION_AI, snapshot) == []

    def test_reports_two_kinds_when_one_line_holds_both(self, snapshot_of: SnapshotFactory) -> None:
        # In pattern order, not in the order the line holds them.
        line = f"{AT_MINIMUM['GitHub token']} {AT_MINIMUM['AWS access key']}\n"
        snapshot = snapshot_of(files={AGENTS: line.encode()})

        assert found(SECRETS_CONFIG, snapshot) == [
            secret(AGENTS, 1, "AWS access key"),
            secret(AGENTS, 1, "GitHub token"),
        ]

    @pytest.mark.parametrize(
        ("line", "kind"),
        [
            pytest.param(
                f"{AT_MINIMUM['GitHub token']} {AT_MINIMUM['GitHub token']}b",
                "GitHub token",
                id="same-shape",
            ),
            # Two shapes of one kind: the kind is named once.
            pytest.param(
                f"{AT_MINIMUM['API key (live)']} {AT_MINIMUM['API key (dash)']}",
                "API key",
                id="two-shapes",
            ),
        ],
    )
    def test_reports_kind_once_when_repeated_on_line(
        self, snapshot_of: SnapshotFactory, line: str, kind: str
    ) -> None:
        snapshot = snapshot_of(files={AGENTS: f"{line}\n{line}\n".encode()})

        assert found(SECRETS_CONFIG, snapshot) == [secret(AGENTS, 1, kind), secret(AGENTS, 2, kind)]

    def test_names_kind_without_echo_when_secret_found(self, snapshot_of: SnapshotFactory) -> None:
        token = AT_MINIMUM["GitHub token"]
        snapshot = snapshot_of(files={AGENTS: f"use {token}\n".encode()})

        findings = list(SECRETS_CONFIG.check(snapshot))

        assert len(findings) == 1
        assert token not in findings[0].message
        assert token[:8] not in findings[0].message + findings[0].fix

    @pytest.mark.parametrize(
        "line",
        [
            "a" * 43 + "=b",
            "x" + "ey" + "J" + "a" * 15 + "." + "b" * 14,
            "xsk" + "-" + "a" * 20,
            "PASS" + "WORD = $HOME_DIR",
            "PASS" + "WORD=<your-password>",
            "AK" + "IA" + "a" * 16,
        ],
    )
    def test_ignores_line_when_shape_near(self, snapshot_of: SnapshotFactory, line: str) -> None:
        snapshot = snapshot_of(files={AGENTS: f"{line}\n".encode()})

        assert found(SECRETS_CONFIG, snapshot) == []

    @pytest.mark.parametrize(
        "line",
        [
            "ey" + "J" + "a" * 15 + "." + "b" * 15,
            "xey" + "J" + "a" * 15 + "." + "b" * 15,
            "ey" + "Jey" + "J" + "a" * 12 + "." + "b" * 15,
            "ey" + "J" + "a" * 14 + ".." + "b" * 15,
            "ey" + "J" + "a" * 20 + "!" + "ey" + "J" + "a" * 15 + "." + "b" * 15,
            "ey" + "J" * 30 + "." + "b" * 15 + "." + "c" * 15,
            "a" * 43 + "==",
            "a" * 44 + "=",
            "-" + "a" * 43 + "=",
            "é" + "a" * 43 + "=",
            "tok" + "en: x",
            "my_api_TOK" + "EN =  'abcdef'",
            "ENCRYPTION_" + "KEY=" + "{abcdef}",
            "x" + "PASS" + "WORD=abcdefg",
            "1" + "SECRET=abcdefg",
            DASHES + "BEGIN RSA " + "PRIVATE KEY" + DASHES,
            DASHES + "BEGIN rsa " + "PRIVATE KEY" + DASHES,
            "pk" + "_test_" + "A1" * 8,
            "zsk" + "_live_" + "a" * 16,
        ],
    )
    def test_matches_like_old_lint_when_line_crafted(
        self, snapshot_of: SnapshotFactory, line: str
    ) -> None:
        snapshot = snapshot_of(files={AGENTS: f"{line}\n".encode()})
        expected: list[Shown] = []
        for pattern, kind in OLD_SECRETS:
            if re.search(pattern, line) and secret(AGENTS, 1, kind) not in expected:
                expected.append(secret(AGENTS, 1, kind))

        assert found(SECRETS_CONFIG, snapshot) == expected

    def test_anchors_nothing_when_shape_patterns_read(self) -> None:
        # The whole-text pre-filter holds only if no pattern needs the text's start or end.
        for shape in (*text_rules.SECRETS, *text_rules.ATTRIBUTIONS):
            assert shape.patterns
            for pattern in shape.patterns:
                assert anchors_of(pattern.pattern) == [], (shape.kind, pattern.pattern)

    def test_agrees_with_old_patterns_when_shapes_listed(self) -> None:
        assert [kind for _, kind in OLD_SECRETS] == [shape.kind for shape in text_rules.SECRETS]
        assert [kind for _, kind in OLD_ATTRIBUTIONS] == [
            shape.kind for shape in text_rules.ATTRIBUTIONS
        ]

    @pytest.mark.parametrize(
        ("name", "near", "size"),
        [
            # Each a run of near matches a backtracking pattern would retry from every start.
            pytest.param("JWT", "ey" + "J", MEBIBYTE, id="jwt"),
            pytest.param("JWT", "ey" + "J" + "a" * 15 + "!", MEBIBYTE, id="jwt-no-dot"),
            pytest.param("AWS access key", "AK" + "IA" + "a" * 16 + " ", SMALL, id="aws"),
            pytest.param("private key", DASHES + "BEGIN " + "A" * 64, SMALL, id="private-key"),
            pytest.param(
                "API key (live)", "sk" + "_live_" + "a" * 15 + " ", SMALL, id="api-key-live"
            ),
            pytest.param("API key (dash)", "sk" + "-" + "a" * 19 + " ", SMALL, id="api-key-dash"),
            pytest.param("GitHub token", "gh" + "p_" + "a" * 29 + " ", SMALL, id="github"),
            pytest.param("Linear API key", "lin" + "_api_" + "a" * 19 + " ", SMALL, id="linear"),
            pytest.param("credential assignment", "TOK" + "EN = abcde ", SMALL, id="credential"),
            pytest.param("credential assignment", "PASS" + "WORD", SMALL, id="credential-word"),
            pytest.param("Fernet-like key", "a" * 42 + "= ", SMALL, id="fernet"),
            pytest.param("Fernet-like key", "a-", SMALL, id="fernet-dashes"),
        ],
    )
    def test_finds_one_when_line_is_long_run_of_near_matches(
        self, snapshot_of: SnapshotFactory, *, name: str, near: str, size: int
    ) -> None:
        line = near * (size // len(near)) + " " + AT_MINIMUM[name]
        snapshot = snapshot_of(files={AGENTS: line.encode()})

        assert found(SECRETS_CONFIG, snapshot) == [secret(AGENTS, 1, kind_of(name))]


class TestAttribution:
    @pytest.mark.parametrize(
        ("kind", "line"),
        [
            pytest.param(kind, line, id=name)
            for name, (kind, line) in zip(
                ("trailer", "generated", "branch"), ATTRIBUTIONS.items(), strict=True
            )
        ]
        + [
            pytest.param("AI co-author trailer", CO_AUTHOR.lower() + "copilot", id="copilot"),
            pytest.param(
                "AI co-author trailer", CO_AUTHOR + " Bot <bot@anthrop" + "ic.com>", id="vendor"
            ),
            pytest.param("AI co-author trailer", CO_AUTHOR + "Open" + "AI bot", id="openai"),
            pytest.param("`claude/` branch prefix", "clau" + "de/<issue>", id="placeholder"),
        ],
    )
    def test_flags_attribution_kind_when_line_matches(
        self, snapshot_of: SnapshotFactory, kind: str, line: str
    ) -> None:
        snapshot = snapshot_of(files={AGENTS: f"ok\n{line}\n".encode()})

        assert found(ATTRIBUTION_AI, snapshot) == [attribution(AGENTS, 2, kind)]
        assert found(SECRETS_CONFIG, snapshot) == []

    @pytest.mark.parametrize(
        "path",
        [
            pytest.param(AGENTS, id="instruction"),
            pytest.param(".claude/skills/s/SKILL.md", id="instruction-skill"),
            pytest.param("plugin/p/agents/a.md", id="plugin-agent"),
            pytest.param("plugin/p/skills/s/SKILL.md", id="plugin-skill"),
            pytest.param(".mcp.json", id="mcp"),
            pytest.param(SETTINGS, id="settings"),
            pytest.param("CONTRIBUTING.md", id="contributing"),
            pytest.param(".github/PULL_REQUEST_TEMPLATE.md", id="pr-template-upper"),
            pytest.param(".github/pull_request_template.md", id="pr-template-lower"),
        ],
    )
    def test_flags_attribution_when_in_scanned_file(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        snapshot = snapshot_of(files={path: f"x\n{TRAILER}\n".encode()})

        assert found(ATTRIBUTION_AI, snapshot) == [attribution(path, 2, "AI co-author trailer")]

    def test_cuts_branch_shape_when_longer_than_echo_limit(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        document = a_hub_document()
        document["project"]["branch_prefix"] = "a" * 90 + "/"
        snapshot = snapshot_of(
            files={AGENTS: f"{BRANCH}\n".encode()}, config=HubConfig.model_validate(document)
        )

        assert [finding.fix for finding in ATTRIBUTION_AI.check(snapshot)] == [
            "branches are `" + "a" * 79 + "…`; commits/PRs carry no AI trailer"
        ]

    def test_scans_line_once_when_co_author_tags_repeat(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # The old ``.*anthropic`` rescanned the rest of the line from every tag.
        counters = {
            name: ScanCounter(getattr(text_rules, name))
            for name in ("_CO_AUTHOR_TAG", "_CO_AUTHOR_NAMED", "_AI_VENDOR")
        }
        for name, counter in counters.items():
            monkeypatch.setattr(text_rules, name, counter)
        line = (CO_AUTHOR + " x ") * 2_000

        assert found(ATTRIBUTION_AI, snapshot_of(files={AGENTS: line.encode()})) == []
        assert all(counter.searches > 0 for counter in counters.values())
        # One search per counter for the whole text, one per line (the text is one line).
        assert all(counter.characters <= 2 * len(line) for counter in counters.values())

    def test_names_branch_shape_when_fix_given(self, snapshot_of: SnapshotFactory) -> None:
        document = a_hub_document()
        document["project"]["branch_prefix"] = "ab-c/"
        document["tracker"]["team"] = "XyZ9"
        snapshot = snapshot_of(
            files={AGENTS: f"{BRANCH}\n".encode()}, config=HubConfig.model_validate(document)
        )

        assert [finding.fix for finding in ATTRIBUTION_AI.check(snapshot)] == [
            "branches are `ab-c/xyz9-<N>-<desc>`; commits/PRs carry no AI trailer"
        ]
        default = snapshot_of(files={AGENTS: f"{BRANCH}\n".encode()})
        assert found(ATTRIBUTION_AI, default) == [attribution(AGENTS, 1, "`claude/` branch prefix")]

    def test_names_prefix_placeholder_when_hub_sets_no_prefix(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        document = a_hub_document()
        del document["project"]["branch_prefix"]
        snapshot = snapshot_of(
            files={AGENTS: f"{BRANCH}\n".encode()}, config=HubConfig.model_validate(document)
        )

        assert [finding.fix for finding in ATTRIBUTION_AI.check(snapshot)] == [
            "branches are `<prefix>dem-<N>-<desc>`; commits/PRs carry no AI trailer"
        ]

    @pytest.mark.parametrize(
        "line",
        [
            CO_AUTHOR + " Jane Doe <jane@example.com>",
            "anthrop" + "ic said: " + CO_AUTHOR + " Jane",
            "generated with care",
            "clau" + "de/fix",
            "myclau" + "de/fix-x",
        ],
    )
    def test_ignores_line_when_not_attribution(
        self, snapshot_of: SnapshotFactory, line: str
    ) -> None:
        snapshot = snapshot_of(files={AGENTS: f"{line}\n".encode()})

        assert found(ATTRIBUTION_AI, snapshot) == []

    @pytest.mark.parametrize(
        "line",
        [
            CO_AUTHOR + "\t claude",
            CO_AUTHOR + " x " + CO_AUTHOR + " copilot",
            CO_AUTHOR + " x anthrop" + "ic",
            CO_AUTHOR + CO_AUTHOR + " OPEN" + "AI",
            "CO-" + "AUTHORED-BY:" + "CLAUDE",
            "co-" + "authored-by : claude",
            "open" + "ai " + CO_AUTHOR + " x",
            "generated " + "with claude code",
            "Generated with [[Claude Code",
            "clau" + "de/a-",
            "clau" + "de/-",
            "clau" + "de/A-b",
            "(clau" + "de/<x>)",
        ],
    )
    def test_matches_like_old_lint_when_line_crafted(
        self, snapshot_of: SnapshotFactory, line: str
    ) -> None:
        snapshot = snapshot_of(files={AGENTS: f"{line}\n".encode()})
        expected = [
            attribution(AGENTS, 1, kind)
            for pattern, kind in OLD_ATTRIBUTIONS
            if re.search(pattern, line)
        ]

        assert found(ATTRIBUTION_AI, snapshot) == expected

    @pytest.mark.parametrize(
        ("kind", "near", "size"),
        [
            pytest.param("AI co-author trailer", CO_AUTHOR + " x ", MEBIBYTE, id="co-author"),
            pytest.param("AI co-author trailer", CO_AUTHOR, MEBIBYTE, id="co-author-run"),
            pytest.param(
                '"Generated with Claude Code"',
                "generated " + "with [claude cod ",
                SMALL,
                id="generated",
            ),
            pytest.param("`claude/` branch prefix", "clau" + "de/abc ", SMALL, id="branch"),
            pytest.param("`claude/` branch prefix", "a", SMALL, id="branch-run"),
        ],
    )
    def test_finds_one_when_line_is_long_run_of_near_matches(
        self, snapshot_of: SnapshotFactory, *, kind: str, near: str, size: int
    ) -> None:
        body = near * (size // len(near))
        if near == "a":
            body = "clau" + "de/" + body
        line = body + " " + ATTRIBUTIONS[kind]
        snapshot = snapshot_of(files={AGENTS: line.encode()})

        assert found(ATTRIBUTION_AI, snapshot) == [attribution(AGENTS, 1, kind)]


class TestScannedFiles:
    def test_ignores_match_when_split_across_lines(self, snapshot_of: SnapshotFactory) -> None:
        content = ("TOK" + "EN\n=abcdefg\n" + CO_AUTHOR + "\nclaude\n").encode()
        snapshot = snapshot_of(files={AGENTS: content})

        assert found(SECRETS_CONFIG, snapshot) == []
        assert found(ATTRIBUTION_AI, snapshot) == []

    def test_skips_project_settings_when_scanning(self, snapshot_of: SnapshotFactory) -> None:
        # E11: settings.project.json merges into settings.json at every sync; only that is read.
        content = f"{TRAILER}\n{AT_MINIMUM['GitHub token']}\n".encode()
        snapshot = snapshot_of(
            files={PROJECT_SETTINGS: content, ".claude/settings.local.json": content}
        )

        assert found(ATTRIBUTION_AI, snapshot) == []
        assert found(SECRETS_CONFIG, snapshot) == []

    def test_ignores_file_when_not_scanned(self, snapshot_of: SnapshotFactory) -> None:
        content = f"{TRAILER}\n{AT_MINIMUM['GitHub token']}\n".encode()
        paths = ("README.md", "docs/CONTRIBUTING.md", "scripts/x.sh", "plugin/p/hooks/a.md")
        snapshot = snapshot_of(files=dict.fromkeys(paths, content))

        assert found(ATTRIBUTION_AI, snapshot) == []
        assert found(SECRETS_CONFIG, snapshot) == []

    def test_reads_fixed_paths_when_unlisted(self, snapshot_of: SnapshotFactory) -> None:
        content = f"{TRAILER}\n".encode()
        paths = (SETTINGS, ".mcp.json", "CONTRIBUTING.md")
        snapshot = snapshot_of(files=dict.fromkeys(paths, content), listed=())

        # settings and .mcp.json are fixed paths; CONTRIBUTING.md counts only when listed.
        assert found(ATTRIBUTION_AI, snapshot) == [
            attribution(SETTINGS, 1, "AI co-author trailer"),
            attribution(".mcp.json", 1, "AI co-author trailer"),
        ]

    def test_reports_files_in_path_order_when_listed_in_reverse(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        content = f"{AT_MINIMUM['GitHub token']}\n".encode()
        paths = ("plugin/p/agents/a.md", "CONTRIBUTING.md", AGENTS, ".mcp.json")
        snapshot = snapshot_of(files=dict.fromkeys(paths, content), listed=paths)

        assert found(SECRETS_CONFIG, snapshot) == [
            secret(path, 1, "GitHub token") for path in sorted(paths)
        ]

    def test_reads_lines_when_line_ends_vary(self, snapshot_of: SnapshotFactory) -> None:
        # E29: \n and \r\n end a line, a lone \r does not.
        token = AT_MINIMUM["GitHub token"]
        content = f"a\r\nb\rc\n{token}\r\n".encode()
        snapshot = snapshot_of(files={AGENTS: content})

        assert found(SECRETS_CONFIG, snapshot) == [secret(AGENTS, 3, "GitHub token")]

    @pytest.mark.parametrize(
        "suffix", [pytest.param(b"\xff", id="undecodable"), pytest.param(b"\x00", id="nul")]
    )
    def test_skips_file_when_not_text(self, snapshot_of: SnapshotFactory, suffix: bytes) -> None:
        content = f"{TRAILER}\n{AT_MINIMUM['GitHub token']}\n".encode() + suffix
        paths = (AGENTS, "plugin/p/agents/a.md", SETTINGS, ".mcp.json", "CONTRIBUTING.md")
        snapshot = snapshot_of(files=dict.fromkeys(paths, content))

        assert found(ATTRIBUTION_AI, snapshot) == []
        assert found(SECRETS_CONFIG, snapshot) == []

    def test_skips_file_when_linked_or_unread(self, snapshot_of: SnapshotFactory) -> None:
        unread = FileEntry(executable=False, content=None)
        snapshot = snapshot_of(
            links={"CONTRIBUTING.md": "docs/c.md", SETTINGS: "../s.json"},
            entries={AGENTS: unread, ".mcp.json": unread},
        )

        assert found(ATTRIBUTION_AI, snapshot) == []
        assert found(SECRETS_CONFIG, snapshot) == []

    def test_reports_plugin_path_once_when_agent_linked_into_plugin(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # D3, E1: a hub links each plugin agent into .claude/agents/ one file at a time; the old
        # walk read the match twice (through the link and in plugin/), the link is never read now.
        agent = "plugin/p/agents/a.md"
        content = f"{AT_MINIMUM['GitHub token']}\n{TRAILER}\n".encode()
        snapshot = snapshot_of(
            files={agent: content}, links={".claude/agents/a.md": "../../" + agent}
        )

        assert found(SECRETS_CONFIG, snapshot) == [secret(agent, 1, "GitHub token")]
        assert found(ATTRIBUTION_AI, snapshot) == [attribution(agent, 2, "AI co-author trailer")]

    def test_reports_not_text_once_when_rules_read_it_first(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # E28: the first selected reader, in RULE_IDS order, reports it; the other skips it.
        snapshot = snapshot_of(files={AGENTS: b"\xff", "plugin/p/skills/s.md": b"a\x00"})
        selection = Selection(rules=(SECRETS_CONFIG, ATTRIBUTION_AI), notes=(), severities={})

        findings = run_rules(selection, snapshot)

        assert [(f.rule, f.path, f.line, f.message) for f in findings] == [
            ("secrets.config", AGENTS, None, "not UTF-8 text: byte 0 cannot be decoded"),
            ("secrets.config", "plugin/p/skills/s.md", None, "not UTF-8 text: NUL at byte 1"),
        ]

    def test_reads_only_scanned_files_when_listing_large(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        content = f"{AT_MINIMUM['GitHub token']}\n".encode()
        others = {f"docs/d{index}/r.md": content for index in range(50_000)}
        scanned = {f".claude/rules/r{index}.md": content for index in range(3)}
        snapshot = snapshot_of(files=others | scanned)

        assert found(SECRETS_CONFIG, snapshot) == [
            secret(path, 1, "GitHub token") for path in sorted(scanned)
        ]


class ScanCounter:
    """A stand-in for a compiled pattern that counts its searches and the characters they pass."""

    def __init__(self, pattern: re.Pattern[str]) -> None:
        self.pattern = pattern
        self.searches = 0
        self.characters = 0

    def search(self, text: str, start: int = 0) -> re.Match[str] | None:
        found = self.pattern.search(text, start)
        self.searches += 1
        self.characters += (len(text) if found is None else found.start()) - start
        return found


def test_names_every_team_in_branch_shape_when_hub_lists_teams(
    snapshot_of: SnapshotFactory,
) -> None:
    document = a_hub_document()
    document["project"]["branch_prefix"] = "me/"
    document["tracker"] = {"kind": "linear", "teams": ["APP", "OPS"]}
    config = HubConfig.model_validate(document)
    snapshot = snapshot_of(files={AGENTS: f"{BRANCH}\n".encode()}, config=config)

    assert text_rules.branch_shape(config) == "me/<app|ops>-<N>-<desc>"
    assert [finding.fix for finding in ATTRIBUTION_AI.check(snapshot)] == [
        "branches are `me/<app|ops>-<N>-<desc>`; commits/PRs carry no AI trailer"
    ]


def anchors_of(source: str) -> list[str]:
    """The ``^``, ``$``, ``\\A``, ``\\Z`` and ``\\z`` of a pattern outside character classes."""
    anchors: list[str] = []
    index = 0
    while index < len(source):
        character = source[index]
        if character == "\\":
            if source[index + 1 : index + 2] in {"A", "Z", "z"}:
                anchors.append(source[index : index + 2])
            index += 2
        elif character == "[":
            index = class_end(source, index)
        else:
            if character in "^$":
                anchors.append(character)
            index += 1
    return anchors


def class_end(source: str, start: int) -> int:
    """The index after the ``]`` closing the character class opened at ``start``."""
    index = start + 1
    if source[index : index + 1] == "^":
        index += 1
    if source[index : index + 1] == "]":
        index += 1
    while source[index] != "]":
        index += 2 if source[index] == "\\" else 1
    return index + 1


@pytest.mark.parametrize(
    ("source", "anchors"),
    [
        ("a^b$", ["^", "$"]),
        (r"\Ax\Z\z", [r"\A", r"\Z", r"\z"]),
        (r"[^$]\^\$", []),
        (r"[]^][\]$]x", []),
        (r"\bsk-[A-Za-z0-9_-]{20,}", []),
    ],
)
def test_finds_anchors_when_outside_classes(source: str, anchors: list[str]) -> None:
    assert anchors_of(source) == anchors
