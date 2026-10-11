import dataclasses
from collections.abc import Callable

import pytest

from agent_hub.core.hub_config.effective_identity import IdentityKey, Source, Sourced
from agent_hub.core.hub_config.workspace_repos import WorkspaceRepo
from agent_hub.core.workspace.setup_checklist import (
    PROBE_TIMEOUT_SECONDS,
    PYTHON_MINIMUM,
    UV_MINIMUM,
    ChecklistItem,
    IdentityGap,
    ProbeResult,
    RepoOutcome,
    State,
    doctor_item,
    gh_item,
    git_lacks_item,
    gitignore_item,
    identity_missing_item,
    identity_resolved_item,
    identity_text,
    identity_written_item,
    invalid_prefix_item,
    item_lines,
    presence_item,
    python_item,
    repo_item,
    setup_exit,
    summary_line,
    tracker_item,
    uv_item,
    version_in,
    write_error_item,
)

UV_PATH = "/opt/tools/uv"
PYTHON_PATH = "/opt/tools/python3"
GH_PATH = "/opt/tools/gh"
UV_FIX = "curl -LsSf https://astral.sh/uv/install.sh | sh"
GIT_FIX = "install git 2.28 or newer (https://git-scm.com/downloads)"
PYTHON_FIX = "install Python 3.9 or newer as python3 (https://www.python.org/downloads/)"
CLAUDE_FIX = "install Claude Code (https://docs.anthropic.com/en/docs/claude-code/setup)"
GH_FIX = "install the GitHub CLI (https://cli.github.com), then gh auth login"
type VersionedProbe = Callable[[str | None, ProbeResult | None], ChecklistItem]
TOOL_PATHS: dict[VersionedProbe, str] = {uv_item: UV_PATH, python_item: PYTHON_PATH}
TIMED_OUT = ProbeResult(returncode=None, stdout=b"", is_timed_out=True)
NOT_STARTED = ProbeResult(returncode=None, stdout=b"", is_timed_out=False)


def answered(stdout: bytes, returncode: int = 0) -> ProbeResult:
    return ProbeResult(returncode=returncode, stdout=stdout, is_timed_out=False)


def ok_item(item: str = "uv") -> ChecklistItem:
    return ChecklistItem(state=State.OK, item=item, detail="fine", fix=None)


def missing_item(item: str = "gh") -> ChecklistItem:
    return ChecklistItem(state=State.MISSING, item=item, detail="absent", fix="install it")


class TestLines:
    @pytest.mark.parametrize(
        ("item", "lines"),
        [
            pytest.param(
                ChecklistItem(state=State.OK, item="uv", detail="0.9.5", fix=None),
                ["ok      uv: 0.9.5"],
                id="ok",
            ),
            pytest.param(
                ChecklistItem(state=State.OK, item="uv", detail="0.9.5", fix="uv self update"),
                ["ok      uv: 0.9.5 Fix: uv self update"],
                id="ok-with-fix",
            ),
            pytest.param(
                ChecklistItem(
                    state=State.MISSING,
                    item="gh",
                    detail="gh auth status exited 1",
                    fix="gh auth login",
                ),
                ["missing gh: gh auth status exited 1 Fix: gh auth login"],
                id="missing-with-fix",
            ),
            pytest.param(
                ChecklistItem(state=State.MISSING, item="identity", detail="no prefix", fix=None),
                ["missing identity: no prefix"],
                id="missing",
            ),
            pytest.param(
                ChecklistItem(
                    state=State.OK,
                    item="hub doctor",
                    detail="0 errors, 1 warning, 0 infos",
                    fix=None,
                    sub_lines=(
                        "warning makefile.override Makefile.project:12: redefines target 'check'",
                        "  kept indent",
                    ),
                ),
                [
                    "ok      hub doctor: 0 errors, 1 warning, 0 infos",
                    "        warning makefile.override Makefile.project:12: redefines target"
                    " 'check'",
                    "          kept indent",
                ],
                id="sub-lines",
            ),
            pytest.param(
                ChecklistItem(
                    state=State.MISSING,
                    item="hub doctor",
                    detail="1 error, 0 warnings, 0 infos",
                    fix="fix each error below, then ./hub doctor",
                    sub_lines=("error lock.drift hub.lock: stale",),
                ),
                [
                    "missing hub doctor: 1 error, 0 warnings, 0 infos"
                    " Fix: fix each error below, then ./hub doctor",
                    "        error lock.drift hub.lock: stale",
                ],
                id="missing-sub-lines",
            ),
        ],
    )
    def test_pads_state_to_eight_columns_when_line_built(
        self, item: ChecklistItem, lines: list[str]
    ) -> None:
        assert item_lines(item) == lines

    @pytest.mark.parametrize(
        ("items", "line"),
        [
            pytest.param([ok_item()] * 10, "setup: 10 ok", id="all-ok"),
            pytest.param(
                [
                    dataclasses.replace(missing_item(), sub_lines=("one", "two", "three")),
                    missing_item("tracker"),
                    *[ok_item()] * 8,
                ],
                "setup: 2 missing, 8 ok",
                id="some-missing",
            ),
            pytest.param([missing_item()], "setup: 1 missing, 0 ok", id="all-missing"),
        ],
    )
    def test_counts_items_not_sub_lines_when_summary_built(
        self, items: list[ChecklistItem], line: str
    ) -> None:
        assert summary_line(items) == line

    def test_exits_one_when_any_item_missing(self) -> None:
        assert setup_exit([ok_item(), missing_item(), ok_item()]) == 1
        assert setup_exit([missing_item()]) == 1

    def test_exits_zero_when_every_item_ok(self) -> None:
        assert setup_exit([ok_item(), ok_item("git")]) == 0
        assert setup_exit([]) == 0

    def test_refuses_assignment_when_item_built(self) -> None:
        item = ok_item()

        with pytest.raises(dataclasses.FrozenInstanceError):
            item.detail = "changed"

    def test_spells_states_when_enum_read(self) -> None:
        assert [str(state) for state in State] == ["ok", "missing"]


class TestTools:
    def test_states_bounds_when_module_read(self) -> None:
        assert PROBE_TIMEOUT_SECONDS == 10.0
        assert UV_MINIMUM == (0, 9, 0)
        assert PYTHON_MINIMUM == (3, 9, 0)

    def test_refuses_assignment_when_probe_result_built(self) -> None:
        result = answered(b"uv 0.9.5")

        with pytest.raises(dataclasses.FrozenInstanceError):
            result.returncode = 1

    @pytest.mark.parametrize(
        ("stdout", "version"),
        [
            pytest.param(b"uv 0.9.5 (abc 2025-09-30)", (0, 9, 5), id="uv"),
            pytest.param(b"Python 3.12.4\n", (3, 12, 4), id="python"),
            pytest.param(b"Python 3.14.0rc1", (3, 14, 0), id="release-candidate"),
            pytest.param(b"tool 1.2 then 4.5.6 and 7.8.9", (4, 5, 6), id="first-full"),
            pytest.param(b"garbage", None, id="garbage"),
            pytest.param(b"\xff", None, id="not-utf8"),
            pytest.param(b"", None, id="empty"),
            pytest.param("v ١.٢.٣".encode(), None, id="non-ascii-digits"),
        ],
    )
    def test_parses_version_when_tools_print_one(
        self, stdout: bytes, version: tuple[int, int, int] | None
    ) -> None:
        assert version_in(stdout) == version

    @pytest.mark.parametrize(
        ("stdout", "version"),
        [
            pytest.param(b"1" * 5000 + b".0.0", None, id="past-int-digit-limit"),
            pytest.param(b"9" * 100_000, None, id="long-digit-run"),
            pytest.param(b"uv 999999.999999.999999", (999_999, 999_999, 999_999), id="six-digits"),
            pytest.param(b"uv 1234567.0.0", None, id="seven-digit-major"),
            pytest.param(b"uv 0.1234567.0", None, id="seven-digit-minor"),
            pytest.param(b"uv 0.0.1234567", None, id="seven-digit-patch"),
        ],
    )
    def test_reads_no_version_when_tools_print_huge_numbers(
        self, stdout: bytes, version: tuple[int, int, int] | None
    ) -> None:
        assert version_in(stdout) == version

    def test_shows_short_version_when_tools_print_widest_one(self) -> None:
        item = uv_item(UV_PATH, answered(b"uv 999999.999999.999999"))

        assert item_lines(item) == ["ok      uv: 999999.999999.999999"]
        assert len(item.detail) <= 20

    @pytest.mark.parametrize(
        ("probe", "stdout", "lines"),
        [
            pytest.param(uv_item, b"uv 0.9.0", ["ok      uv: 0.9.0"], id="uv-minimum"),
            pytest.param(
                uv_item, b"uv 0.9.5 (abc 2025-09-30)\n", ["ok      uv: 0.9.5"], id="uv-newer"
            ),
            pytest.param(
                uv_item,
                b"uv 0.8.24",
                ["missing uv: 0.8.24, need 0.9.0 or newer Fix: uv self update"],
                id="uv-old",
            ),
            pytest.param(
                python_item, b"Python 3.9.0\n", ["ok      python3: 3.9.0"], id="python-minimum"
            ),
            pytest.param(
                python_item, b"Python 3.12.4\n", ["ok      python3: 3.12.4"], id="python-newer"
            ),
            pytest.param(
                python_item,
                b"Python 3.8.18\n",
                [f"missing python3: 3.8.18, need 3.9 or newer Fix: {PYTHON_FIX}"],
                id="python-old",
            ),
        ],
    )
    def test_compares_minimum_when_tools_version_read(
        self, probe: VersionedProbe, stdout: bytes, lines: list[str]
    ) -> None:
        item = probe(TOOL_PATHS[probe], answered(stdout))

        assert item_lines(item) == lines

    @pytest.mark.parametrize(
        ("name", "line"),
        [
            pytest.param("uv", f"missing uv: not on PATH Fix: {UV_FIX}", id="uv"),
            pytest.param("git", f"missing git: not on PATH Fix: {GIT_FIX}", id="git"),
            pytest.param(
                "python3", f"missing python3: not on PATH Fix: {PYTHON_FIX}", id="python3"
            ),
            pytest.param("claude", f"missing claude: not on PATH Fix: {CLAUDE_FIX}", id="claude"),
            pytest.param("gh", f"missing gh: not on PATH Fix: {GH_FIX}", id="gh"),
        ],
    )
    def test_prints_absent_line_when_tools_not_on_path(self, name: str, line: str) -> None:
        match name:
            case "uv":
                item = uv_item(None, None)
            case "python3":
                item = python_item(None, None)
            case "gh":
                item = gh_item(None, None)
            case "git" | "claude":
                item = presence_item(name, None)

        assert item_lines(item) == [line]

    @pytest.mark.parametrize("name", ["git", "claude"])
    def test_prints_on_path_line_when_tools_found(self, name: str) -> None:
        item = presence_item(name, f"/opt/tools/{name}")

        assert item_lines(item) == [f"ok      {name}: on PATH"]

    @pytest.mark.parametrize(
        ("probe", "result", "line"),
        [
            pytest.param(
                uv_item,
                answered(b"uv 0.9.5", returncode=2),
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-exit-2",
            ),
            pytest.param(
                uv_item,
                answered(b"no version here"),
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-no-version",
            ),
            pytest.param(
                uv_item,
                NOT_STARTED,
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-not-started",
            ),
            pytest.param(
                uv_item,
                TIMED_OUT,
                "missing uv: timed out after 10 s Fix: uv --version",
                id="uv-timeout",
            ),
            pytest.param(
                python_item,
                answered(b"Python 3.12.4", returncode=2),
                "missing python3: cannot read its version Fix: python3 --version",
                id="python-exit-2",
            ),
            pytest.param(
                python_item,
                answered(b"\xff"),
                "missing python3: cannot read its version Fix: python3 --version",
                id="python-no-version",
            ),
            pytest.param(
                python_item,
                TIMED_OUT,
                "missing python3: timed out after 10 s Fix: python3 --version",
                id="python-timeout",
            ),
        ],
    )
    def test_prints_unreadable_line_when_tools_answer_badly(
        self, probe: VersionedProbe, result: ProbeResult, line: str
    ) -> None:
        item = probe(TOOL_PATHS[probe], result)

        assert item_lines(item) == [line]

    @pytest.mark.parametrize(
        ("result", "line"),
        [
            pytest.param(answered(b""), "ok      gh: logged in", id="logged-in"),
            pytest.param(
                answered(b"", returncode=1),
                "missing gh: gh auth status exited 1 Fix: gh auth login",
                id="exit-1",
            ),
            pytest.param(
                answered(b"", returncode=4),
                "missing gh: gh auth status exited 4 Fix: gh auth login",
                id="exit-4",
            ),
            pytest.param(
                TIMED_OUT, "missing gh: timed out after 10 s Fix: gh auth login", id="timeout"
            ),
            pytest.param(
                NOT_STARTED,
                "missing gh: cannot run gh auth status Fix: gh auth login",
                id="not-started",
            ),
        ],
    )
    def test_prints_gh_line_when_tools_auth_varies(self, result: ProbeResult, line: str) -> None:
        assert item_lines(gh_item(GH_PATH, result)) == [line]

    @pytest.mark.parametrize(
        ("transport", "is_key_set", "has_claude", "line"),
        [
            pytest.param(
                "api",
                True,
                False,
                "ok      tracker: LINEAR_API_KEY set (transport api)",
                id="api-key",
            ),
            pytest.param(
                "api",
                False,
                True,
                "missing tracker: LINEAR_API_KEY is not set (transport api)"
                " Fix: export LINEAR_API_KEY=<your Linear API key>,"
                ' or set tracker.transport "mcp" in hub.local.json',
                id="api-no-key",
            ),
            pytest.param(
                "mcp",
                False,
                True,
                "ok      tracker: transport mcp: Linear through claude -p"
                " (its Linear MCP server is not checked)",
                id="mcp-claude",
            ),
            pytest.param(
                "mcp",
                True,
                False,
                f"missing tracker: transport mcp needs claude on PATH Fix: {CLAUDE_FIX}",
                id="mcp-no-claude",
            ),
        ],
    )
    def test_prints_tracker_line_when_tools_transport_given(
        self, transport: str, *, is_key_set: bool, has_claude: bool, line: str
    ) -> None:
        item = tracker_item(
            transport=transport,
            is_key_set=is_key_set,
            has_claude=has_claude,
        )

        assert item_lines(item) == [line]


DECLINED_FIX = (
    "./hub setup --yes, or write hub.local.json yourself (docs/design/developer-identity.md)"
)
IDENTITY_DOC_FIX = (
    "write hub.local.json with project.branch_prefix (docs/design/developer-identity.md)"
)
GIT_PREFIX = Sourced("jane/", Source.GIT, IdentityKey.BRANCH_PREFIX, derived=True)
GIT_NAME = Sourced("Jane Roe", Source.GIT, IdentityKey.AUTHOR_NAME)
GIT_EMAIL = Sourced("jane@example.com", Source.GIT, IdentityKey.AUTHOR_EMAIL)
WEB = WorkspaceRepo("demo-web", "acme/demo-web")
API = WorkspaceRepo("demo-api", "acme/demo-api")
CLONE_FIX = (
    "check that your git credentials can read github.com/acme/demo-web (e.g. gh auth setup-git),"
    " then ./hub setup"
)


def from_hub(value: str, key: IdentityKey) -> Sourced:
    return Sourced(value, Source.HUB, key)


def from_local(value: str, key: IdentityKey, *, derived: bool = False) -> Sourced:
    return Sourced(value, Source.LOCAL, key, derived=derived)


def keyed(*values: Sourced) -> dict[IdentityKey, Sourced]:
    return {value.key: value for value in values}


class TestIdentity:
    @pytest.mark.parametrize(
        ("values", "line"),
        [
            pytest.param(
                keyed(GIT_PREFIX, GIT_NAME, GIT_EMAIL),
                "ok      identity: wrote hub.local.json: jane/, Jane Roe <jane@example.com>"
                " (git config)",
                id="all-three",
            ),
            pytest.param(
                keyed(GIT_NAME, GIT_EMAIL),
                "ok      identity: wrote hub.local.json: Jane Roe <jane@example.com> (git config)",
                id="name-and-email",
            ),
            pytest.param(
                keyed(GIT_PREFIX),
                "ok      identity: wrote hub.local.json: jane/ (git config)",
                id="prefix-only",
            ),
            pytest.param(
                # hub.json sets only the email: the derived prefix keeps hub.json as its source.
                keyed(
                    Sourced("jane/", Source.HUB, IdentityKey.BRANCH_PREFIX, derived=True),
                    GIT_NAME,
                ),
                "ok      identity: wrote hub.local.json: jane/, Jane Roe (hub.json, git config)",
                id="prefix-from-hub-email",
            ),
            pytest.param(
                # A bidi override would reorder the terminal line: it is shown escaped.
                keyed(Sourced("Jane\u202eRoe", Source.GIT, IdentityKey.AUTHOR_NAME), GIT_EMAIL),
                "ok      identity: wrote hub.local.json: Jane\\u202eRoe <jane@example.com>"
                " (git config)",
                id="bidi-override-escaped",
            ),
        ],
    )
    def test_names_written_keys_when_identity_written(
        self, values: dict[IdentityKey, Sourced], line: str
    ) -> None:
        assert item_lines(identity_written_item(values)) == [line]

    @pytest.mark.parametrize(
        ("values", "line"),
        [
            pytest.param(
                keyed(
                    from_hub("jdoe/", IdentityKey.BRANCH_PREFIX),
                    from_hub("Jane Doe", IdentityKey.AUTHOR_NAME),
                    from_hub("jane@example.com", IdentityKey.AUTHOR_EMAIL),
                ),
                "ok      identity: jdoe/, Jane Doe <jane@example.com> (hub.json)",
                id="hub-json",
            ),
            pytest.param(
                keyed(
                    from_local("jane/", IdentityKey.BRANCH_PREFIX),
                    GIT_NAME,
                    from_local("jane@example.com", IdentityKey.AUTHOR_EMAIL),
                ),
                "ok      identity: jane/, Jane Roe <jane@example.com> (hub.local.json, git config)",
                id="local-and-git",
            ),
            pytest.param(
                keyed(
                    from_local("jane/", IdentityKey.BRANCH_PREFIX, derived=True),
                    from_hub("Jane Roe", IdentityKey.AUTHOR_NAME),
                    from_local("jane@example.com", IdentityKey.AUTHOR_EMAIL),
                ),
                "ok      identity: jane/, Jane Roe <jane@example.com> (hub.local.json, hub.json)",
                id="derived-prefix",
            ),
            pytest.param(
                keyed(
                    from_hub("Jane\u202eRoe", IdentityKey.AUTHOR_NAME),
                    from_hub("jane@example.com", IdentityKey.AUTHOR_EMAIL),
                ),
                "ok      identity: Jane\\u202eRoe <jane@example.com> (hub.json)",
                id="bidi-override-escaped",
            ),
        ],
    )
    def test_names_sources_when_identity_resolved(
        self, values: dict[IdentityKey, Sourced], line: str
    ) -> None:
        assert item_lines(identity_resolved_item(values)) == [line]

    @pytest.mark.parametrize(
        ("values", "text"),
        [
            pytest.param(keyed(GIT_PREFIX, GIT_EMAIL), "jane/, jane@example.com", id="no-name"),
            pytest.param(keyed(GIT_EMAIL), "jane@example.com", id="email-only"),
            pytest.param(keyed(GIT_NAME), "Jane Roe", id="name-only"),
            pytest.param(
                # Given out of key order: the text keeps prefix, then name and email.
                {
                    IdentityKey.AUTHOR_EMAIL: GIT_EMAIL,
                    IdentityKey.AUTHOR_NAME: GIT_NAME,
                    IdentityKey.BRANCH_PREFIX: GIT_PREFIX,
                },
                "jane/, Jane Roe <jane@example.com>",
                id="reversed",
            ),
            pytest.param(
                # C1 controls (NEL, CSI) are escaped like any other non-printable character.
                keyed(
                    Sourced("Jane\x85Roe", Source.GIT, IdentityKey.AUTHOR_NAME),
                    Sourced("jane\x9b@example.com", Source.GIT, IdentityKey.AUTHOR_EMAIL),
                ),
                "Jane\\x85Roe <jane\\x9b@example.com>",
                id="c1-controls-escaped",
            ),
            pytest.param(
                keyed(Sourced("Jane\u202eRoe", Source.GIT, IdentityKey.AUTHOR_NAME)),
                "Jane\\u202eRoe",
                id="name-only-escaped",
            ),
        ],
    )
    def test_orders_values_when_identity_text_built(
        self, values: dict[IdentityKey, Sourced], text: str
    ) -> None:
        assert identity_text(values) == text

    @pytest.mark.parametrize(
        "build",
        [
            pytest.param(identity_written_item, id="written"),
            pytest.param(identity_resolved_item, id="resolved"),
        ],
    )
    def test_refuses_item_when_identity_has_no_value(
        self, build: Callable[[dict[IdentityKey, Sourced]], ChecklistItem]
    ) -> None:
        with pytest.raises(ValueError, match="at least one identity value"):
            build({})

    @pytest.mark.parametrize(
        ("item", "lines"),
        [
            pytest.param(
                identity_missing_item(IdentityGap.DECLINED),
                [f"missing identity: hub.local.json not written (declined) Fix: {DECLINED_FIX}"],
                id="declined",
            ),
            pytest.param(
                identity_missing_item(IdentityGap.NO_TERMINAL),
                [
                    "missing identity: hub.local.json not written (stdin is not a terminal)"
                    f" Fix: {DECLINED_FIX}"
                ],
                id="no-terminal",
            ),
            pytest.param(
                git_lacks_item([IdentityKey.AUTHOR_EMAIL]),
                [
                    "missing identity: git config in the hub has no user.email"
                    " Fix: git config user.email <you@example.com>, then ./hub setup"
                ],
                id="git-lacks-email",
            ),
            pytest.param(
                git_lacks_item([IdentityKey.AUTHOR_NAME]),
                [
                    "missing identity: git config in the hub has no user.name"
                    ' Fix: git config user.name "<Your Name>", then ./hub setup'
                ],
                id="git-lacks-name",
            ),
            pytest.param(
                git_lacks_item([IdentityKey.AUTHOR_EMAIL, IdentityKey.AUTHOR_NAME]),
                [
                    "missing identity: git config in the hub has no user.name or user.email"
                    ' Fix: git config user.name "<Your Name>" and git config user.email'
                    " <you@example.com>, then ./hub setup"
                ],
                id="git-lacks-both",
            ),
            pytest.param(
                git_lacks_item([IdentityKey.AUTHOR_EMAIL], git_problem="git not found"),
                [
                    "missing identity: git config in the hub has no user.email"
                    " Fix: git config user.email <you@example.com>, then ./hub setup",
                    "        git: git not found",
                ],
                id="git-problem",
            ),
            pytest.param(
                invalid_prefix_item("j+x@example.com"),
                [
                    'missing identity: git\'s user.email gives "j+x", not a valid branch prefix'
                    f" Fix: {IDENTITY_DOC_FIX}"
                ],
                id="invalid-prefix",
            ),
            pytest.param(
                invalid_prefix_item("ja‮ne@example.com"),
                [
                    "missing identity: git's user.email gives"
                    ' "ja\\u202ene", not a valid branch prefix'
                    f" Fix: {IDENTITY_DOC_FIX}"
                ],
                id="invalid-prefix-escaped",
            ),
            pytest.param(
                identity_missing_item(
                    IdentityGap.INVALID_LOCAL,
                    sub_lines=(
                        "hub.local.json: repos: set only in hub.json",
                        "hub.local.json: project.branch_prefix: must match",
                    ),
                ),
                [
                    "missing identity: hub.local.json is invalid"
                    " Fix: fix hub.local.json (docs/design/developer-identity.md)",
                    "        hub.local.json: repos: set only in hub.json",
                    "        hub.local.json: project.branch_prefix: must match",
                ],
                id="invalid-local",
            ),
            pytest.param(
                identity_missing_item(IdentityGap.APPEARED),
                [
                    "missing identity: hub.local.json appeared while writing; left as is"
                    " Fix: ./hub setup"
                ],
                id="appeared",
            ),
            pytest.param(
                write_error_item("Operation not permitted"),
                [
                    "missing identity: could not write hub.local.json: Operation not permitted"
                    f" Fix: {DECLINED_FIX}"
                ],
                id="write-error",
            ),
            pytest.param(
                identity_missing_item(
                    IdentityGap.NO_PREFIX,
                    sub_lines=(
                        "no branch prefix for this developer; set one of:",
                        "  hub.local.json → project.branch_prefix",
                        '  hub.local.json\'s project.author_email gives "j+x", not a valid prefix',
                    ),
                ),
                [
                    "missing identity: no branch prefix",
                    "        no branch prefix for this developer; set one of:",
                    "          hub.local.json → project.branch_prefix",
                    '          hub.local.json\'s project.author_email gives "j+x",'
                    " not a valid prefix",
                ],
                id="no-prefix",
            ),
        ],
    )
    def test_gives_fix_when_identity_missing(self, item: ChecklistItem, lines: list[str]) -> None:
        assert item_lines(item) == lines

    @pytest.mark.parametrize(
        "lacking",
        [
            pytest.param([IdentityKey.BRANCH_PREFIX], id="prefix"),
            pytest.param(
                [IdentityKey.BRANCH_PREFIX, IdentityKey.AUTHOR_EMAIL], id="prefix-and-email"
            ),
            pytest.param([], id="none"),
        ],
    )
    def test_refuses_keys_when_git_lacks_no_git_key(self, lacking: list[IdentityKey]) -> None:
        with pytest.raises(ValueError, match="author_name or author_email"):
            git_lacks_item(lacking)

    def test_prints_gitignore_line_when_local_file_not_ignored(self) -> None:
        assert item_lines(gitignore_item()) == [
            "missing gitignore: hub.local.json is not ignored by git"
            " Fix: add the line hub.local.json to .gitignore and commit it"
        ]


class TestRepos:
    @pytest.mark.parametrize(
        ("item", "line"),
        [
            pytest.param(
                repo_item(WEB, RepoOutcome.CLONED, scheme="ssh"),
                "ok      repo demo-web: cloned acme/demo-web into ../demo-web (ssh)",
                id="cloned-ssh",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.CLONED, scheme="https"),
                "ok      repo demo-web: cloned acme/demo-web into ../demo-web (https)",
                id="cloned-https",
            ),
            pytest.param(
                repo_item(API, RepoOutcome.FETCHED),
                "ok      repo demo-api: present, fetched",
                id="fetched",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.CLONE_FAILED, returncode=128),
                f"missing repo demo-web: clone failed (git exit 128) Fix: {CLONE_FIX}",
                id="clone-failed",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.CLONE_TIMED_OUT, timeout_seconds=600.0),
                f"missing repo demo-web: clone timed out after 600 s Fix: {CLONE_FIX}",
                id="clone-timeout",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.CLONE_TIMED_OUT, timeout_seconds=1.0),
                f"missing repo demo-web: clone timed out after 1 s Fix: {CLONE_FIX}",
                id="clone-timeout-shrunk",
            ),
            pytest.param(
                repo_item(API, RepoOutcome.FETCH_FAILED, returncode=1),
                "missing repo demo-api: fetch failed (git exit 1)"
                " Fix: git -C ../demo-api fetch origin",
                id="fetch-failed",
            ),
            pytest.param(
                repo_item(API, RepoOutcome.FETCH_TIMED_OUT, timeout_seconds=600.0),
                "missing repo demo-api: fetch timed out after 600 s"
                " Fix: git -C ../demo-api fetch origin",
                id="fetch-timeout",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.NOT_A_REPO),
                "missing repo demo-web: ../demo-web exists but is not a git repository;"
                " left untouched Fix: move ../demo-web away, then ./hub setup",
                id="not-a-repo",
            ),
            pytest.param(
                repo_item(WEB, RepoOutcome.GIT_NOT_FOUND),
                f"missing repo demo-web: git not found Fix: {GIT_FIX}",
                id="git-not-found",
            ),
        ],
    )
    def test_prints_repo_line_when_repo_outcome_known(self, item: ChecklistItem, line: str) -> None:
        assert item_lines(item) == [line]

    @pytest.mark.parametrize(
        ("outcome", "argument"),
        [
            pytest.param(RepoOutcome.CLONED, "scheme", id="cloned"),
            pytest.param(RepoOutcome.CLONE_FAILED, "returncode", id="clone-failed"),
            pytest.param(RepoOutcome.FETCH_FAILED, "returncode", id="fetch-failed"),
            pytest.param(RepoOutcome.CLONE_TIMED_OUT, "timeout_seconds", id="clone-timeout"),
            pytest.param(RepoOutcome.FETCH_TIMED_OUT, "timeout_seconds", id="fetch-timeout"),
        ],
    )
    def test_refuses_outcome_when_repo_text_lacks_argument(
        self, outcome: RepoOutcome, argument: str
    ) -> None:
        with pytest.raises(ValueError, match=f"needs {argument}"):
            repo_item(WEB, outcome)


class TestDoctor:
    @pytest.mark.parametrize(
        ("totals", "has_errors", "findings", "lines"),
        [
            pytest.param(
                "0 errors, 1 warning, 0 infos",
                False,
                [
                    "warning makefile.override Makefile.project:12: redefines target 'check'"
                    " Fix: rename the project target"
                ],
                [
                    "ok      hub doctor: 0 errors, 1 warning, 0 infos",
                    "        warning makefile.override Makefile.project:12: redefines target"
                    " 'check' Fix: rename the project target",
                ],
                id="no-errors",
            ),
            pytest.param(
                "0 errors, 1 warning, 0 infos",
                False,
                [],
                ["ok      hub doctor: 0 errors, 1 warning, 0 infos"],
                id="no-findings",
            ),
            pytest.param(
                "1 error, 0 warnings, 0 infos",
                True,
                ["error lock.drift AGENTS.md: differs from hub.lock"],
                [
                    "missing hub doctor: 1 error, 0 warnings, 0 infos"
                    " Fix: fix each error below, then ./hub doctor",
                    "        error lock.drift AGENTS.md: differs from hub.lock",
                ],
                id="errors",
            ),
        ],
    )
    def test_carries_findings_when_doctor_item_built(
        self, totals: str, *, has_errors: bool, findings: list[str], lines: list[str]
    ) -> None:
        item = doctor_item(totals=totals, has_errors=has_errors, finding_lines=findings)

        assert item_lines(item) == lines
