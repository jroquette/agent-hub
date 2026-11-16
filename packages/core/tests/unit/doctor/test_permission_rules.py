"""``settings.valid``, ``permissions.bypass`` and ``mcp.pinned``: the old config lint's settings,
bypass and MCP checks (spec AC-11.22, Q-8, plan E6, E11, E25).

``.claude/settings.json`` (strict JSON, as ``settings.weakening`` reads it) and ``.mcp.json`` must
parse, at the parser's line; settings hold no deprecated key and no bypass mode; neither holds the
skip-permissions flag, nor does a line of a listed script, workflow, ``Makefile`` or
``package.json``; each ``.mcp.json`` server is pinned. A value of the wrong type is skipped.
"""

from collections.abc import Callable

import pytest

from agent_hub.core.doctor.finding import Read, Rule
from agent_hub.core.doctor.permission_rules import (
    MCP_PINNED,
    PERMISSIONS_BYPASS,
    PERMISSIONS_WRITING,
    SETTINGS_VALID,
)
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, run_rules, select_rules
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.hub_files.writing_commands import WRITING_COMMANDS, effective_allows
from agent_hub.core.json_form import JsonValue, dump_json

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, int | None, str, str]

SETTINGS = ".claude/settings.json"
MCP = ".mcp.json"
LINT_SCRIPT = "scripts/agent_config_lint.py"
# Assembled here, so this file never holds the flag it tests for.
BARE_FLAG = "dangerously-" + "skip-permissions"
FLAG = "--" + BARE_FLAG

SYNTAX_FIX = "fix the syntax"
NOT_OBJECT = ("must be a JSON object", "make the top level a JSON object")
DEPRECATED_FIX = "use `permissions.allow` / `permissions.deny`"
BYPASS_MODE = (
    "`bypassPermissions` in shared settings",
    "use acceptEdits/auto; bypass only in a firewalled container",
)
FLAG_IN_CONFIG = (f"`{FLAG}` in config", "remove it")
FLAG_IN_FILE = (f"`{FLAG}`", "run agents with an allowlist and the sandbox instead")
PIN_FIX = "pin an exact version (pkg@1.2.3) or use the official remote URL"
# Nested deeper than a recursive walk could go; the loader still reads it.
DEEP = 5_000


def found(rule: Rule, snapshot: DoctorSnapshot) -> list[Shown]:
    findings = list(rule.check(snapshot))
    assert all(finding.rule == rule.id for finding in findings)
    assert all(finding.severity is Severity.ERROR for finding in findings)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in findings]


def unpinned(name: str) -> Shown:
    return (MCP, 1, f"MCP server `{name}` is not version-pinned", PIN_FIX)


def mcp_with(servers: JsonValue) -> bytes:
    return dump_json({"mcpServers": servers})


def deep(value: str) -> bytes:
    """``value`` inside an object, nested ``DEEP`` arrays down (compact: no quadratic indent)."""
    return ('{"d": ' + "[" * DEEP + value + "]" * DEEP + "}").encode()


def test_declares_design_ids_when_rules_read() -> None:
    assert (SETTINGS_VALID.id, PERMISSIONS_BYPASS.id, MCP_PINNED.id) == (
        "settings.valid",
        "permissions.bypass",
        "mcp.pinned",
    )
    for rule in (SETTINGS_VALID, PERMISSIONS_BYPASS, MCP_PINNED):
        assert rule.severity is Severity.ERROR
        assert rule.module is None
    # settings.json and .mcp.json are fixed paths; only the scripts scan needs the listing.
    assert SETTINGS_VALID.reads == frozenset()
    assert MCP_PINNED.reads == frozenset()
    assert PERMISSIONS_BYPASS.reads == frozenset({Read.HUB_LISTING})


class TestSettingsValid:
    def test_reports_parser_line_when_json_invalid(self, snapshot_of: SnapshotFactory) -> None:
        # The golden settings_valid_invalid_json case.
        snapshot = snapshot_of(
            files={
                SETTINGS: b'{\n  "permissions": {\n    "allow": ["Bash(ls)",]\n  }\n}\n',
                MCP: b'{\n  "mcpServers": oops\n}\n',
            }
        )

        assert found(SETTINGS_VALID, snapshot) == [
            (
                SETTINGS,
                3,
                "not valid JSON: Illegal trailing comma before end of array at line 3 column 25",
                SYNTAX_FIX,
            ),
            (MCP, 2, "not valid JSON: Expecting value at line 2 column 17", SYNTAX_FIX),
        ]
        assert found(PERMISSIONS_BYPASS, snapshot) == []
        assert found(MCP_PINNED, snapshot) == []

    @pytest.mark.parametrize(
        ("path", "content", "message"),
        [
            pytest.param(
                SETTINGS,
                b'{"a": 1, "a": 2}',
                'not valid JSON here: the key "a" appears more than once',
                id="settings-repeated-key",
            ),
            pytest.param(
                SETTINGS,
                b'{"a": NaN}',
                "not valid JSON here: NaN is not a JSON number",
                id="settings-nan",
            ),
            pytest.param(
                MCP, b"\xff{}", "not UTF-8 text: byte 0 cannot be decoded", id="mcp-not-utf8"
            ),
        ],
    )
    def test_reports_without_line_when_json_unreadable(
        self, snapshot_of: SnapshotFactory, *, path: str, content: bytes, message: str
    ) -> None:
        # settings.json is read as strictly as settings.weakening reads it (E25).
        snapshot = snapshot_of(files={path: content})

        assert found(SETTINGS_VALID, snapshot) == [(path, None, message, SYNTAX_FIX)]

    # AGH-431 (AC-431.4): the parser's overflow is simulated, not built.
    def test_reports_without_line_when_json_nested_too_deeply(
        self, snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # How deep the parser can go depends on the interpreter and the machine (Python 3.14
        # reads 200,000 levels), so the overflow itself is simulated.
        def overflow(*_args: object, **_kwargs: object) -> object:
            raise RecursionError

        snapshot = snapshot_of(files={MCP: b"[[]]"})
        monkeypatch.setattr("agent_hub.core.json_form.json.loads", overflow)

        assert found(SETTINGS_VALID, snapshot) == [
            (MCP, None, "not valid JSON here: it is nested too deeply", SYNTAX_FIX)
        ]

    @pytest.mark.parametrize("path", [SETTINGS, MCP])
    def test_reports_without_line_when_number_over_digit_limit(
        self, snapshot_of: SnapshotFactory, path: str
    ) -> None:
        # E34: a number of more than 4300 digits, which the old lint's parse crashed on, is one
        # error with no line in either file; 4300 digits still read.
        over = snapshot_of(files={path: b'{"a": ' + b"1" * 4301 + b"}"})
        at_limit = snapshot_of(files={path: b'{"a": ' + b"1" * 4300 + b"}"})
        message = (
            "not valid JSON here: a number has more than 4300 digits, which this reader does not"
            " accept"
        )

        assert found(SETTINGS_VALID, over) == [(path, None, message, SYNTAX_FIX)]
        assert found(SETTINGS_VALID, at_limit) == []

    def test_reads_mcp_leniently_when_key_repeated(self, snapshot_of: SnapshotFactory) -> None:
        # .mcp.json keeps the old lint's reader: a repeated key or NaN is not an error there.
        snapshot = snapshot_of(files={MCP: b'{"a": 1, "a": NaN}'})

        assert found(SETTINGS_VALID, snapshot) == []

    def test_reports_each_deprecated_key_when_sorted(self, snapshot_of: SnapshotFactory) -> None:
        # Written in reverse order; .mcp.json is not checked for them.
        keys = b'{"ignorePatterns": [], "model": "sonnet", "allowedTools": ["Bash(ls)"]}'
        snapshot = snapshot_of(files={SETTINGS: keys, MCP: keys})

        assert found(SETTINGS_VALID, snapshot) == [
            (SETTINGS, 1, "deprecated settings key `allowedTools`", DEPRECATED_FIX),
            (SETTINGS, 1, "deprecated settings key `ignorePatterns`", DEPRECATED_FIX),
        ]

    @pytest.mark.parametrize("path", [SETTINGS, MCP])
    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(b'["allowedTools"]', id="array"),
            pytest.param(b'"allowedTools"', id="string"),
            pytest.param(b"1", id="number"),
            pytest.param(b"null", id="null"),
        ],
    )
    def test_reports_object_when_top_level_not_object(
        self, snapshot_of: SnapshotFactory, path: str, content: bytes
    ) -> None:
        snapshot = snapshot_of(files={path: content})

        assert found(SETTINGS_VALID, snapshot) == [(path, None, *NOT_OBJECT)]
        assert found(PERMISSIONS_BYPASS, snapshot) == []
        assert found(MCP_PINNED, snapshot) == []

    def test_skips_file_when_absent_or_linked(self, snapshot_of: SnapshotFactory) -> None:
        # A link is never followed (D3); an absent file is nothing to check.
        snapshot = snapshot_of(links={SETTINGS: "elsewhere.json", MCP: "../x.json"})

        assert found(SETTINGS_VALID, snapshot) == []
        assert found(SETTINGS_VALID, snapshot_of()) == []


class TestPermissionsBypass:
    def test_flags_bypass_mode_when_in_settings(self, snapshot_of: SnapshotFactory) -> None:
        bypass = dump_json({"permissions": {"defaultMode": "bypassPermissions"}})
        snapshot = snapshot_of(files={SETTINGS: bypass, MCP: bypass})

        assert found(PERMISSIONS_BYPASS, snapshot) == [(SETTINGS, 1, *BYPASS_MODE)]

    @pytest.mark.parametrize(
        ("content", "message"),
        [
            pytest.param(
                b'{"model": "a", "model": "b", '
                b'"permissions": {"defaultMode": "bypassPermissions"}, "env": {"A": "'
                + FLAG.encode()
                + b'"}}',
                'not valid JSON here: the key "model" appears more than once',
                id="repeated-key",
            ),
            pytest.param(
                b'{"n": NaN, "permissions": {"defaultMode": "bypassPermissions"}, "env": {"A": "'
                + FLAG.encode()
                + b'"}}',
                "not valid JSON here: NaN is not a JSON number",
                id="nan",
            ),
        ],
    )
    def test_reports_bypass_when_settings_not_strict_json(
        self, snapshot_of: SnapshotFactory, *, content: bytes, message: str
    ) -> None:
        """E34(f): the strict parse error is settings.valid's; the bypass is still reported."""
        snapshot = snapshot_of(files={SETTINGS: content})
        bypass = [(SETTINGS, 1, *BYPASS_MODE), (SETTINGS, 1, *FLAG_IN_CONFIG)]

        assert found(SETTINGS_VALID, snapshot) == [(SETTINGS, None, message, SYNTAX_FIX)]
        assert found(PERMISSIONS_BYPASS, snapshot) == bypass
        selection = select_rules(REGISTRY, config=snapshot.config, only=("permissions.bypass",))
        assert isinstance(selection, Selection)
        only = [
            (finding.path, finding.line, finding.message, finding.fix)
            for finding in run_rules(selection, snapshot)
            if finding.rule == "permissions.bypass"
        ]
        assert only == bypass

    def test_accepts_mode_when_not_bypass(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(
            files={SETTINGS: dump_json({"permissions": {"defaultMode": "acceptEdits"}})}
        )

        assert found(PERMISSIONS_BYPASS, snapshot) == []

    @pytest.mark.parametrize(
        ("settings", "mcp"),
        [
            pytest.param(
                dump_json({"env": {"AGENT_ARGS": f"-p {FLAG} task"}}),
                mcp_with({"x": {"command": "npx", "args": ["x-mcp@2.0.0", BARE_FLAG]}}),
                id="value",
            ),
            pytest.param(
                dump_json({BARE_FLAG: True}), dump_json({"a": {f"x{BARE_FLAG}": 1}}), id="key"
            ),
            pytest.param(deep(f'"{BARE_FLAG}"'), deep(f'{{"k": ["{FLAG}"]}}'), id="deep"),
        ],
    )
    def test_flags_skip_flag_when_in_settings_or_mcp(
        self, snapshot_of: SnapshotFactory, settings: bytes, mcp: bytes
    ) -> None:
        snapshot = snapshot_of(files={SETTINGS: settings, MCP: mcp})

        assert found(PERMISSIONS_BYPASS, snapshot) == [
            (SETTINGS, 1, *FLAG_IN_CONFIG),
            (MCP, 1, *FLAG_IN_CONFIG),
        ]

    def test_flags_skip_flag_when_escaped_in_json(self, snapshot_of: SnapshotFactory) -> None:
        # The parsed value is scanned, as the old lint scanned json.dumps of it.
        escaped = BARE_FLAG.replace("-", "\\u002d").encode()
        snapshot = snapshot_of(files={MCP: b'{"a": "' + escaped + b'"}'})

        assert found(PERMISSIONS_BYPASS, snapshot) == [(MCP, 1, *FLAG_IN_CONFIG)]

    def test_flags_skip_flag_when_top_level_not_object(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={SETTINGS: dump_json([FLAG])})

        assert found(PERMISSIONS_BYPASS, snapshot) == [(SETTINGS, 1, *FLAG_IN_CONFIG)]

    def test_flags_skip_flag_when_in_listed_script(self, snapshot_of: SnapshotFactory) -> None:
        """E34(e): the scan reads E31's known paths, the listing plus the fixed paths present, so
        a present ``Makefile`` or ``package.json`` is scanned even when git-ignored.
        """
        run = f"claude {FLAG} -p task\n".encode()
        files = {
            "scripts/x.sh": b"#!/bin/sh\n" + run,
            "scripts/sub/tool.sh": b"echo ok\n",
            ".github/workflows/ci.yml": b"jobs:\n  agent:\r\n    run: " + run,
            ".github/actions/a.yml": run,
            "Makefile": b"agent:\n\t" + run,
            "package.json": b'{\n  "scripts": {"agent": "' + run.strip() + b'"}\n}\n',
            "docs/run.sh": run,
            # A lone \r does not end a line (E29).
            "scripts/cr.sh": b"echo\r" + run,
            # Not listed: untracked and ignored, or never asked for.
            "scripts/ignored.sh": run,
        }
        listed = tuple(sorted(set(files) - {"scripts/ignored.sh", "Makefile", "package.json"}))
        # Makefile and package.json are fixed paths: present, they count unlisted (E31).
        snapshot = snapshot_of(
            files=files, listed=(*listed, "scripts/link.sh"), links={"scripts/link.sh": "x.sh"}
        )

        assert found(PERMISSIONS_BYPASS, snapshot) == [
            (".github/workflows/ci.yml", 3, *FLAG_IN_FILE),
            ("Makefile", 2, *FLAG_IN_FILE),
            ("package.json", 2, *FLAG_IN_FILE),
            ("scripts/cr.sh", 1, *FLAG_IN_FILE),
            ("scripts/x.sh", 2, *FLAG_IN_FILE),
        ]

    def test_reports_each_line_when_flag_repeated(self, snapshot_of: SnapshotFactory) -> None:
        line = f"claude {FLAG} {FLAG}\n".encode()
        snapshot = snapshot_of(files={"scripts/x.sh": line + b"echo\n" + line})

        assert found(PERMISSIONS_BYPASS, snapshot) == [
            ("scripts/x.sh", 1, *FLAG_IN_FILE),
            ("scripts/x.sh", 3, *FLAG_IN_FILE),
        ]

    @pytest.mark.parametrize(
        "content",
        [
            pytest.param(b"\xff\xfe" + FLAG.encode() + b"\n", id="not-utf8"),
            pytest.param(FLAG.encode() + b"\n\xff\n", id="not-utf8-after-flag"),
            pytest.param(FLAG.encode() + b"\n\x00\n", id="nul"),
        ],
    )
    def test_skips_file_when_not_utf8(self, snapshot_of: SnapshotFactory, content: bytes) -> None:
        snapshot = snapshot_of(files={"scripts/blob.bin": content})

        assert found(PERMISSIONS_BYPASS, snapshot) == []

    def test_flags_lint_script_name_when_scanning(self, snapshot_of: SnapshotFactory) -> None:
        # AGH-15 D7: the old lint script is gone, and so is its exception: no path is skipped
        # by name.
        line = f"# {FLAG}\n".encode()
        snapshot = snapshot_of(
            files={
                LINT_SCRIPT: line,
                "scripts/x_agent_config_lint.py": line,
                "scripts/sub/agent_config_lint.py": line,
            }
        )

        assert found(PERMISSIONS_BYPASS, snapshot) == [
            (LINT_SCRIPT, 1, *FLAG_IN_FILE),
            ("scripts/sub/agent_config_lint.py", 1, *FLAG_IN_FILE),
            ("scripts/x_agent_config_lint.py", 1, *FLAG_IN_FILE),
        ]

    def test_flags_skip_flag_when_line_is_one_mebibyte(self, snapshot_of: SnapshotFactory) -> None:
        line = b"-" * (1 << 20) + FLAG.encode() + b" " * (1 << 20)
        snapshot = snapshot_of(files={"scripts/x.sh": line, "scripts/y.sh": b"-" * (1 << 20)})

        assert found(PERMISSIONS_BYPASS, snapshot) == [("scripts/x.sh", 1, *FLAG_IN_FILE)]

    def test_reads_only_candidates_when_listing_large(self, snapshot_of: SnapshotFactory) -> None:
        run = f"{FLAG}\n".encode()
        others = {f"docs/d{index}/r.sh": run for index in range(50_000)}
        scripts = {f"scripts/s{index}.sh": run for index in range(3)}
        snapshot = snapshot_of(files=others | scripts)

        assert found(PERMISSIONS_BYPASS, snapshot) == [
            (path, 1, *FLAG_IN_FILE) for path in sorted(scripts)
        ]

    @pytest.mark.parametrize(
        "settings",
        [
            pytest.param({"permissions": ["defaultMode", "bypassPermissions"]}, id="array"),
            pytest.param({"permissions": "bypassPermissions"}, id="string"),
        ],
    )
    def test_skips_value_when_shape_wrong(
        self, snapshot_of: SnapshotFactory, settings: JsonValue
    ) -> None:
        snapshot = snapshot_of(files={SETTINGS: dump_json(settings)})

        assert found(PERMISSIONS_BYPASS, snapshot) == []


class TestMcpPinned:
    def test_flags_unpinned_server_when_latest_or_bare_npx(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # The golden mcp_pinned case: the settings' keys are not checked in .mcp.json.
        servers = (
            b'{"mcpServers": {'
            b'"zeta": {"command": "uvx", "args": ["zeta-mcp@latest"]},'
            b'"beta": {"command": "npx", "args": ["-y", "beta-mcp"]},'
            b'"alpha": {"command": "npx", "args": ["-y", "alpha-mcp@1.2.3"]},'
            b'"local": {"command": "node", "args": ["server.js"]},'
            b'"gamma": {"command": "/usr/bin/npx"},'
            b'"remote": {"type": "http", "url": "https://mcp.example.com/mcp"}'
            b'}, "allowedTools": ["x"], "permissions": {"defaultMode": "bypassPermissions"}}'
        )
        snapshot = snapshot_of(files={MCP: servers})

        assert found(MCP_PINNED, snapshot) == [
            unpinned("zeta"),
            unpinned("beta"),
            unpinned("gamma"),
        ]
        assert found(SETTINGS_VALID, snapshot) == []
        assert found(PERMISSIONS_BYPASS, snapshot) == []

    @pytest.mark.parametrize(
        "server",
        [
            pytest.param({"type": "http", "url": "https://mcp.example.com/mcp"}, id="remote"),
            pytest.param({"command": "npx", "args": ["-y", "pkg@1.2.3"]}, id="npx-pinned"),
            pytest.param({"command": "npx", "args": ["-y", "@scope/pkg@2"]}, id="npx-scoped"),
            pytest.param({"command": "uvx", "args": ["pkg"]}, id="not-npx"),
            pytest.param({"command": "node", "args": ["server.js"]}, id="local"),
        ],
    )
    def test_accepts_server_when_remote_or_pinned(
        self, snapshot_of: SnapshotFactory, server: JsonValue
    ) -> None:
        snapshot = snapshot_of(files={MCP: mcp_with({"s": server})})

        assert found(MCP_PINNED, snapshot) == []

    def test_ignores_mcp_servers_when_in_settings(self, snapshot_of: SnapshotFactory) -> None:
        unpinned_server = {"s": {"command": "npx", "args": ["s-mcp@latest"]}}
        snapshot = snapshot_of(files={SETTINGS: mcp_with(unpinned_server)})

        assert found(MCP_PINNED, snapshot) == []

    @pytest.mark.parametrize(
        "servers",
        [
            pytest.param(["npx", "pkg@latest"], id="servers-array"),
            pytest.param("npx pkg@latest", id="servers-string"),
            pytest.param({"s": "npx pkg@latest"}, id="entry-string"),
            pytest.param({"s": ["npx", "pkg@latest"]}, id="entry-array"),
            pytest.param({"s": {"command": "npx", "args": "pkg@latest"}}, id="args-string"),
            pytest.param({"s": {"command": "npx", "args": ["pkg", 1]}}, id="args-not-strings"),
            pytest.param({"s": {"command": "npx", "args": {"a": "pkg"}}}, id="args-object"),
            pytest.param({"s": {"command": ["npx"], "args": ["pkg"]}}, id="command-array"),
        ],
    )
    def test_skips_value_when_shape_wrong(
        self, snapshot_of: SnapshotFactory, servers: JsonValue
    ) -> None:
        snapshot = snapshot_of(files={MCP: mcp_with(servers)})

        assert found(MCP_PINNED, snapshot) == []

    def test_cuts_server_name_when_long(self, snapshot_of: SnapshotFactory) -> None:
        name = "n\n" + "x" * 300
        snapshot = snapshot_of(files={MCP: mcp_with({name: {"command": "npx"}})})

        assert found(MCP_PINNED, snapshot) == [unpinned(cut_echo("n\\n" + "x" * 300))]

    def test_checks_every_server_when_many(self, snapshot_of: SnapshotFactory) -> None:
        pinned: dict[str, JsonValue] = {
            f"s{index:03}": {"command": "npx", "args": [f"p{index}@1"], "env": {"A": "b"}}
            for index in range(300)
        }
        # Inserted in reverse: findings follow the file's key order, not the sorted names.
        bare: dict[str, JsonValue] = {
            f"s{index:03}": {"command": "npx"} for index in range(300)[::-1]
        }

        assert found(MCP_PINNED, snapshot_of(files={MCP: mcp_with(pinned)})) == []
        assert found(
            MCP_PINNED,
            snapshot_of(
                files={
                    MCP: b'{"mcpServers": {'
                    + b", ".join(f'"{name}": {{"command": "npx"}}'.encode() for name in bare)
                    + b"}}"
                }
            ),
        ) == [unpinned(name) for name in bare]

    @pytest.mark.parametrize(
        "mcp",
        [
            pytest.param(
                {"entries": {MCP: FileEntry(executable=False, content=None)}}, id="unread"
            ),
            pytest.param({"links": {MCP: "bad.json"}}, id="linked"),
        ],
    )
    @pytest.mark.parametrize(
        "target",
        [
            # settings.valid would flag it.
            pytest.param(b'{"mcpServers": ]', id="invalid-target"),
            # permissions.bypass and mcp.pinned would flag it.
            pytest.param(
                mcp_with({"s": {"command": "npx", "args": ["s@latest", FLAG]}}),
                id="unpinned-target",
            ),
        ],
    )
    def test_reports_nothing_when_mcp_unread_or_linked(
        self, snapshot_of: SnapshotFactory, *, mcp: dict[str, object], target: bytes
    ) -> None:
        """E34(d): a linked ``.mcp.json`` is not followed and an unread one is not guessed at,
        though each target here would be flagged if it were read as ``.mcp.json``.
        """
        snapshot = snapshot_of(files={"bad.json": target}, **mcp)

        rules = (SETTINGS_VALID, PERMISSIONS_BYPASS, MCP_PINNED)
        assert {rule.id: found(rule, snapshot) for rule in rules} == {rule.id: [] for rule in rules}


type Rules = tuple[str, ...] | list[str]

# The demo hub's managed allow rules, in their order. Written out: core cannot build them, and a
# change to the managed list must not move what these tests expect.
MANAGED_ALLOW = (
    "Bash(git status *)",
    "Bash(git diff *)",
    "Bash(git log *)",
    "Bash(git show *)",
    "Bash(gh pr view *)",
    "Bash(gh pr checks *)",
    "Bash(gh pr diff *)",
    "Bash(gh run view *)",
    "Bash(gh run list *)",
    "Bash(gh api -X GET *)",
    "mcp__Linear__get_issue",
    "mcp__Linear__list_issues",
    "mcp__Linear__list_comments",
    "mcp__Linear__list_issue_statuses",
    "mcp__Linear__list_issue_labels",
    "mcp__Linear__get_team",
    "mcp__Linear__list_teams",
    "mcp__Linear__get_user",
    "mcp__Linear__get_project",
    "mcp__Linear__list_projects",
    "mcp__claude_ai_Linear__get_issue",
    "mcp__claude_ai_Linear__list_issues",
    "mcp__claude_ai_Linear__list_comments",
    "mcp__claude_ai_Linear__list_issue_statuses",
    "mcp__claude_ai_Linear__list_issue_labels",
    "mcp__claude_ai_Linear__get_team",
    "mcp__claude_ai_Linear__list_teams",
    "mcp__claude_ai_Linear__get_user",
    "mcp__claude_ai_Linear__get_project",
    "mcp__claude_ai_Linear__list_projects",
    "mcp__github__pull_request_read",
    "mcp__github__list_pull_requests",
    "mcp__github__search_pull_requests",
    "mcp__github__issue_read",
    "mcp__github__list_issues",
    "mcp__github__search_issues",
    "mcp__github__get_file_contents",
    "mcp__github__list_commits",
    "mcp__github__get_commit",
    "mcp__github__get_me",
    "Bash(sha256sum)",
    "Bash(shasum -a 256)",
    "Bash(./hub doctor)",
    "Bash(git -C ../demo-api rev-parse --show-toplevel)",
    "Bash(git -C ../demo-api symbolic-ref refs/remotes/origin/HEAD)",
    "Edit(/brain/_inbox/onboard-proposal*.md)",
)
# The managed denies of the writing forms of the allowed reads: an output file, a second method.
WRITE_DENIES = (
    "Bash(git diff *--output*)",
    "Bash(git log *--output*)",
    "Bash(git show *--output*)",
    "Bash(gh api -X GET * -X*)",
    "Bash(gh api -X GET * --method*)",
    "Bash(gh api -X GET -X*)",
    "Bash(gh api -X GET --method*)",
)
# The demo hub's managed deny rules, in their order.
MANAGED_DENY = (
    "Read(**/*.pem)",
    "Read(**/*.key)",
    "Bash(git push --force*)",
    "Bash(git push -f *)",
    "Bash(git push * main)",
    "Bash(git push origin HEAD:main*)",
    "Bash(git push * master)",
    "Bash(git push origin HEAD:master*)",
    "Bash(terraform *)",
    "Bash(aws *)",
    *WRITE_DENIES,
    "Bash(security *)",
    "Bash(ssh *)",
    "Bash(sh)",
    "Bash(bash)",
)
WRITING_FIX = (
    "narrow or remove the rule in .claude/settings.project.json, then run hub sync; for a rule"
    " that is not there, run hub sync alone"
)


def allows_write(rule: str, command: str) -> Shown:
    return (
        SETTINGS,
        None,
        f"permissions.allow rule `{rule}` lets a command that writes run with no prompt, such as"
        f" `{command}`",
        WRITING_FIX,
    )


def warned(snapshot: DoctorSnapshot) -> list[Shown]:
    findings = list(PERMISSIONS_WRITING.check(snapshot))
    assert all(finding.rule == "permissions.writing" for finding in findings)
    assert all(finding.severity is Severity.WARNING for finding in findings)
    return [(finding.path, finding.line, finding.message, finding.fix) for finding in findings]


def permissions_with(allow: Rules, deny: Rules) -> bytes:
    return dump_json({"permissions": {"allow": [*allow], "deny": [*deny]}})


class TestPermissionsWriting:
    """``permissions.writing``: one warning for each ``permissions.allow`` rule of the merged
    ``.claude/settings.json`` that lets a command of the writing corpus run with no prompt.
    """

    def test_declares_design_fields_when_writing_rule_read(self) -> None:
        assert PERMISSIONS_WRITING.id == "permissions.writing"
        assert PERMISSIONS_WRITING.severity is Severity.WARNING
        # settings.json is a fixed path: the rule needs no other read.
        assert PERMISSIONS_WRITING.reads == frozenset()
        assert PERMISSIONS_WRITING.module is None
        assert PERMISSIONS_WRITING.summary == (
            "no permissions.allow rule lets a writing command run with no prompt"
        )

    def test_warns_writing_allow_when_project_rule_matches_write(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        allow = [*MANAGED_ALLOW, "Bash(python3 scripts/*)"]
        snapshot = snapshot_of(files={SETTINGS: permissions_with(allow, MANAGED_DENY)})

        assert warned(snapshot) == [
            (
                ".claude/settings.json",
                None,
                "permissions.allow rule `Bash(python3 scripts/*)` lets a command that writes run"
                " with no prompt, such as `python3 scripts/../write.py`",
                "narrow or remove the rule in .claude/settings.project.json, then run hub sync;"
                " for a rule that is not there, run hub sync alone",
            )
        ]

    def test_warns_writing_allow_when_gh_api_rule_is_broad(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        allow = [*MANAGED_ALLOW, "Bash(gh api *)"]
        snapshot = snapshot_of(files={SETTINGS: permissions_with(allow, MANAGED_DENY)})

        assert warned(snapshot) == [
            allows_write("Bash(gh api *)", "gh api -X POST repos/o/r/issues -f title=t")
        ]

    def test_reports_nothing_when_only_managed_allow(self, snapshot_of: SnapshotFactory) -> None:
        snapshot = snapshot_of(files={SETTINGS: permissions_with(MANAGED_ALLOW, MANAGED_DENY)})

        assert warned(snapshot) == []
        assert len(MANAGED_ALLOW) == 46
        assert len(MANAGED_DENY) == 21

    def test_warns_managed_reads_when_write_denies_missing(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # The pair of the managed-only case: the write denies are what keeps that list silent.
        deny = [rule for rule in MANAGED_DENY if rule not in WRITE_DENIES]
        snapshot = snapshot_of(files={SETTINGS: permissions_with(MANAGED_ALLOW, deny)})

        assert warned(snapshot) == [
            allows_write("Bash(git diff *)", "git diff --output=f"),
            allows_write("Bash(git log *)", "git log --output=f"),
            allows_write("Bash(git show *)", "git show --output=f"),
            allows_write(
                "Bash(gh api -X GET *)", "gh api -X GET -X POST repos/o/r/issues -f title=t"
            ),
        ]

    def test_warns_each_rule_once_when_rule_matches_many_writes(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # Not sorted: findings follow the file's order, and the repeated rule warns once.
        allow = [
            "Bash(gh api *)",
            "Bash(make *)",
            "Bash",
            "Bash(python3 scripts/*)",
            "Bash(gh api *)",
        ]
        gh_api = allows_write("Bash(gh api *)", "gh api -X POST repos/o/r/issues -f title=t")
        python3 = allows_write("Bash(python3 scripts/*)", "python3 scripts/../write.py")

        # The corpus starts with the three --output commands, which a managed deny stops.
        assert warned(snapshot_of(files={SETTINGS: permissions_with(allow, MANAGED_DENY)})) == [
            gh_api,
            allows_write("Bash", "git push origin b"),
            python3,
        ]
        assert warned(snapshot_of(files={SETTINGS: permissions_with(allow, [])})) == [
            gh_api,
            allows_write("Bash", "git diff --output=f"),
            python3,
        ]

    def test_reports_nothing_when_rule_matches_no_corpus_command(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        # The rule's limits: it judges Bash rules only, and only against the corpus, so a rule
        # for a tool that writes, or for a command the corpus does not hold, gives no warning.
        allow = [
            "Bash(make *)",
            "Bash(npm test *)",
            "Write",
            "Edit(/src/**)",
            "mcp__github__merge_pull_request",
            "Bash(git status && git push origin b)",
        ]
        snapshot = snapshot_of(files={SETTINGS: permissions_with(allow, [])})

        assert warned(snapshot) == []

    @pytest.mark.parametrize(
        "settings",
        [
            pytest.param({"permissions": ["allow", "Bash(gh api *)"]}, id="permissions-array"),
            pytest.param({"permissions": "Bash(gh api *)"}, id="permissions-string"),
            pytest.param({"permissions": {"allow": "Bash(gh api *)"}}, id="allow-string"),
            pytest.param({"permissions": {"allow": {"Bash(gh api *)": True}}}, id="allow-object"),
            pytest.param(
                {
                    "permissions": {
                        "allow": [1, None, ["Bash(gh api *)"], {"rule": "Bash(gh api *)"}]
                    }
                },
                id="allow-not-strings",
            ),
            pytest.param([{"permissions": {"allow": ["Bash(gh api *)"]}}], id="top-level-array"),
            pytest.param({"allow": ["Bash(gh api *)"]}, id="no-permissions"),
        ],
    )
    def test_skips_value_when_shape_wrong(
        self, snapshot_of: SnapshotFactory, settings: JsonValue
    ) -> None:
        snapshot = snapshot_of(files={SETTINGS: dump_json(settings)})

        assert warned(snapshot) == []

    @pytest.mark.parametrize(
        ("deny", "expected"),
        [
            # A deny value that is not a list is no deny.
            pytest.param(
                "Bash(git diff *--output*)",
                [allows_write("Bash(git diff *)", "git diff --output=f")],
                id="string",
            ),
            # A string item still applies beside an item of another type.
            pytest.param([7, "Bash(git diff *--output*)"], [], id="mixed-list"),
        ],
    )
    def test_reads_string_denies_only_when_deny_shape_wrong(
        self, snapshot_of: SnapshotFactory, *, deny: JsonValue, expected: list[Shown]
    ) -> None:
        settings = dump_json({"permissions": {"allow": ["Bash(git diff *)"], "deny": deny}})

        assert warned(snapshot_of(files={SETTINGS: settings})) == expected

    @pytest.mark.parametrize(
        "hub",
        [
            pytest.param({}, id="absent"),
            pytest.param(
                {
                    "files": {"elsewhere.json": permissions_with(["Bash(gh api *)"], [])},
                    "links": {SETTINGS: "elsewhere.json"},
                },
                id="linked",
            ),
            pytest.param(
                {"entries": {SETTINGS: FileEntry(executable=False, content=None)}}, id="unread"
            ),
            pytest.param({"files": {SETTINGS: b"{not json"}}, id="invalid-json"),
            pytest.param(
                {
                    "files": {
                        SETTINGS: b'{"a": 1, "a": 2, "permissions": {"allow": ["Bash(gh api *)"]}}'
                    }
                },
                id="not-strict-json",
            ),
        ],
    )
    def test_skips_writing_check_when_settings_absent(
        self, snapshot_of: SnapshotFactory, hub: dict[str, object]
    ) -> None:
        # A missing or invalid file is settings.weakening's and settings.valid's to report.
        assert warned(snapshot_of(**hub)) == []

    def test_cuts_rule_when_long(self, snapshot_of: SnapshotFactory) -> None:
        rule = "Bash(python3 scripts/" + "*" * 300 + ")"
        cut = "Bash(python3 scripts/" + "*" * 58 + "…"
        snapshot = snapshot_of(files={SETTINGS: permissions_with([rule], [])})

        found_warnings = warned(snapshot)

        assert len(cut) == 80
        assert found_warnings == [allows_write(cut, "python3 scripts/../write.py")]

    def test_checks_every_rule_when_many(self, snapshot_of: SnapshotFactory) -> None:
        silent = [f"Bash(tool{index:03} *)" for index in range(300)]
        # Listed longest first: findings follow the file's order, not the sorted rules.
        broad = [f"Bash({'*' * (index + 1)})" for index in range(300)[::-1]]

        assert warned(snapshot_of(files={SETTINGS: permissions_with(silent, MANAGED_DENY)})) == []
        assert warned(snapshot_of(files={SETTINGS: permissions_with(broad, MANAGED_DENY)})) == [
            allows_write(cut_echo(rule), "git push origin b") for rule in broad
        ]

    def test_agrees_with_effective_allows_when_rules_mixed(
        self, snapshot_of: SnapshotFactory
    ) -> None:
        rules = [
            *MANAGED_ALLOW,
            "Bash",
            "Bash(gh *)",
            "Bash(gh api *)",
            "Bash(python3:*)",
            "Bash(git push *)",
        ]

        for rule in rules:
            snapshot = snapshot_of(files={SETTINGS: permissions_with([rule], MANAGED_DENY)})
            # The model's verdict on the rule alone: the first corpus command it lets through.
            first = next(
                (
                    command
                    for command in WRITING_COMMANDS
                    if effective_allows([rule], MANAGED_DENY, command)
                ),
                None,
            )

            expected = [] if first is None else [allows_write(rule, first)]
            assert warned(snapshot) == expected, rule
