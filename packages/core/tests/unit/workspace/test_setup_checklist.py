import dataclasses

import pytest

from agent_hub.core.workspace.setup_checklist import (
    PROBE_TIMEOUT_SECONDS,
    PYTHON_MINIMUM,
    UV_MINIMUM,
    ChecklistItem,
    ProbeResult,
    State,
    gh_item,
    item_lines,
    presence_item,
    python_item,
    setup_exit,
    summary_line,
    tracker_item,
    uv_item,
    version_in,
)

UV_PATH = "/opt/tools/uv"
PYTHON_PATH = "/opt/tools/python3"
GH_PATH = "/opt/tools/gh"
UV_FIX = "curl -LsSf https://astral.sh/uv/install.sh | sh"
GIT_FIX = "install git 2.28 or newer (https://git-scm.com/downloads)"
PYTHON_FIX = "install Python 3.9 or newer as python3 (https://www.python.org/downloads/)"
CLAUDE_FIX = "install Claude Code (https://docs.anthropic.com/en/docs/claude-code/setup)"
GH_FIX = "install the GitHub CLI (https://cli.github.com), then gh auth login"
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
        ("item", "lines"),
        [
            pytest.param(
                uv_item(UV_PATH, answered(b"uv 0.9.0")),
                ["ok      uv: 0.9.0"],
                id="uv-minimum",
            ),
            pytest.param(
                uv_item(UV_PATH, answered(b"uv 0.9.5 (abc 2025-09-30)\n")),
                ["ok      uv: 0.9.5"],
                id="uv-newer",
            ),
            pytest.param(
                uv_item(UV_PATH, answered(b"uv 0.8.24")),
                ["missing uv: 0.8.24, need 0.9.0 or newer Fix: uv self update"],
                id="uv-old",
            ),
            pytest.param(
                python_item(PYTHON_PATH, answered(b"Python 3.9.0\n")),
                ["ok      python3: 3.9.0"],
                id="python-minimum",
            ),
            pytest.param(
                python_item(PYTHON_PATH, answered(b"Python 3.12.4\n")),
                ["ok      python3: 3.12.4"],
                id="python-newer",
            ),
            pytest.param(
                python_item(PYTHON_PATH, answered(b"Python 3.8.18\n")),
                [f"missing python3: 3.8.18, need 3.9 or newer Fix: {PYTHON_FIX}"],
                id="python-old",
            ),
        ],
    )
    def test_compares_minimum_when_tools_version_read(
        self, item: ChecklistItem, lines: list[str]
    ) -> None:
        assert item_lines(item) == lines

    @pytest.mark.parametrize(
        ("item", "line"),
        [
            pytest.param(uv_item(None, None), f"missing uv: not on PATH Fix: {UV_FIX}", id="uv"),
            pytest.param(
                presence_item("git", None), f"missing git: not on PATH Fix: {GIT_FIX}", id="git"
            ),
            pytest.param(
                python_item(None, None),
                f"missing python3: not on PATH Fix: {PYTHON_FIX}",
                id="python3",
            ),
            pytest.param(
                presence_item("claude", None),
                f"missing claude: not on PATH Fix: {CLAUDE_FIX}",
                id="claude",
            ),
            pytest.param(gh_item(None, None), f"missing gh: not on PATH Fix: {GH_FIX}", id="gh"),
        ],
    )
    def test_prints_absent_line_when_tools_not_on_path(
        self, item: ChecklistItem, line: str
    ) -> None:
        assert item_lines(item) == [line]

    @pytest.mark.parametrize("name", ["git", "claude"])
    def test_prints_on_path_line_when_tools_found(self, name: str) -> None:
        item = presence_item(name, f"/opt/tools/{name}")

        assert item_lines(item) == [f"ok      {name}: on PATH"]

    @pytest.mark.parametrize(
        ("item", "line"),
        [
            pytest.param(
                uv_item(UV_PATH, answered(b"uv 0.9.5", returncode=2)),
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-exit-2",
            ),
            pytest.param(
                uv_item(UV_PATH, answered(b"no version here")),
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-no-version",
            ),
            pytest.param(
                uv_item(UV_PATH, NOT_STARTED),
                "missing uv: cannot read its version Fix: uv --version",
                id="uv-not-started",
            ),
            pytest.param(
                uv_item(UV_PATH, TIMED_OUT),
                "missing uv: timed out after 10 s Fix: uv --version",
                id="uv-timeout",
            ),
            pytest.param(
                python_item(PYTHON_PATH, answered(b"Python 3.12.4", returncode=2)),
                "missing python3: cannot read its version Fix: python3 --version",
                id="python-exit-2",
            ),
            pytest.param(
                python_item(PYTHON_PATH, answered(b"\xff")),
                "missing python3: cannot read its version Fix: python3 --version",
                id="python-no-version",
            ),
            pytest.param(
                python_item(PYTHON_PATH, TIMED_OUT),
                "missing python3: timed out after 10 s Fix: python3 --version",
                id="python-timeout",
            ),
        ],
    )
    def test_prints_unreadable_line_when_tools_answer_badly(
        self, item: ChecklistItem, line: str
    ) -> None:
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
