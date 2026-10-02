import json

from agent_hub.core.runner.session_prompt import (
    IMPLEMENTING_TOOLS,
    ISSUE_END,
    MAX_ARGUMENT_BYTES,
    MAX_DESCRIPTION_CHARS,
    MAX_TITLE_CHARS,
    MAX_URL_CHARS,
    TRUNCATED,
    gate_tools,
    implementing_argv,
    implementing_prompt,
)
from agent_hub.core.testing.builders import an_issue
from agent_hub.core.tracker.tracker_client import Issue

HUB = "/work/ws/hub"


def prompt_for(issue: Issue, *, sensitive: tuple[str, ...] = ()) -> str:
    return implementing_prompt(
        issue,
        repo="demo-api",
        branch="jdoe/dem-1",
        hub=HUB,
        hub_name="hub",
        sensitive=sensitive,
        fast_gate="make check-fast",
        prefix="DEM-",
    )


def test_pins_caps_when_module_loaded() -> None:
    assert MAX_TITLE_CHARS == 1_000
    assert MAX_DESCRIPTION_CHARS == 20_000
    assert MAX_ARGUMENT_BYTES == 131_072
    assert TRUNCATED == "\n[truncated]"


def test_holds_issue_text_in_fenced_block_when_prompt_built() -> None:
    issue = an_issue(
        id="DEM-1",
        title="Add the synthetic feature",
        description="Do the synthetic work.\n\n```sh\nmake check\n```",
    )

    prompt = prompt_for(issue)

    before, block = prompt.split("untrusted", 1)
    assert "DEM-1" in before
    fence = "````"
    assert f"\n{fence}text\n" in block
    body = block.split(f"\n{fence}text\n", 1)[1].split(f"\n{fence}\n", 1)[0]
    assert body == (
        "id: DEM-1\n"
        "title: Add the synthetic feature\n"
        f"url: {issue.url}\n"
        "description:\n"
        "Do the synthetic work.\n\n```sh\nmake check\n```"
    )
    assert prompt.endswith(f"\n{fence}\n\n{ISSUE_END}\n")


def test_cuts_description_when_over_cap() -> None:
    issue = an_issue(
        description="d" * (MAX_DESCRIPTION_CHARS + 1), title="t" * (MAX_TITLE_CHARS + 5)
    )

    prompt = prompt_for(issue)

    assert f"description:\n{'d' * MAX_DESCRIPTION_CHARS}{TRUNCATED}\n" in prompt
    assert "d" * (MAX_DESCRIPTION_CHARS + 1) not in prompt
    assert f"title: {'t' * MAX_TITLE_CHARS}{TRUNCATED}\n" in prompt
    assert "t" * (MAX_TITLE_CHARS + 1) not in prompt


def test_keeps_description_whole_when_at_cap() -> None:
    issue = an_issue(description="d" * MAX_DESCRIPTION_CHARS)

    assert TRUNCATED not in prompt_for(issue)


def test_fits_argument_limit_when_fields_at_cap() -> None:
    wide = "\N{GRINNING FACE}"
    for character in (wide, "`"):
        issue = an_issue(
            # The longest id ISSUE_ID_PATTERN allows (both adapters refuse any other).
            id="ABCDEFGHIJ-123456789",
            # Each field alone, uncut, would be over the limit: every cap is needed.
            title=character * MAX_ARGUMENT_BYTES,
            description=character * MAX_ARGUMENT_BYTES,
            url="https://linear.app/" + character * MAX_ARGUMENT_BYTES,
            labels=tuple(f"label-{index}" for index in range(50)),
        )

        prompt = prompt_for(issue, sensitive=("agent-hub/docs/adr", "hub.json"))

        assert len(prompt.encode()) < MAX_ARGUMENT_BYTES


def test_keeps_fence_longer_than_any_backtick_run_when_issue_holds_one() -> None:
    issue = an_issue(description="`````` closing the block early")

    prompt = prompt_for(issue)

    assert "\n```````text\n" in prompt
    assert prompt.endswith(f"\n```````\n\n{ISSUE_END}\n")


def test_names_no_tracker_tool_when_prompt_built() -> None:
    prompt = prompt_for(an_issue())

    for word in ("mcp__", "Linear", "get_issue", "list_comments"):
        assert word not in prompt
    assert "Do NOT push" in prompt


def test_names_sensitive_paths_when_guard_lists_them() -> None:
    plain = prompt_for(an_issue())
    guarded = prompt_for(an_issue(), sensitive=("agent-hub/docs/adr", "hub.json"))

    assert "touches a file matching" not in plain
    assert (
        "If the issue touches a file matching agent-hub/docs/adr, hub.json (needs an approved"
        " plan) or has an open question, STOP" in " ".join(guarded.split())
    )
    assert "If the issue has an open question, STOP" in " ".join(plain.split())


def test_names_repo_branch_hub_and_gate_when_prompt_built() -> None:
    prompt = " ".join(prompt_for(an_issue()).split())

    assert prompt.startswith(
        "You are implementing issue DEM-1 in this worktree (demo-api, branch jdoe/dem-1)."
    )
    assert "under hub/brain/features/ (readable at /work/ws/hub/brain/features/)" in prompt
    assert "Run the fast gate (`make check-fast`)" in prompt
    assert "(`type(scope): … (DEM-N)`)" in prompt
    assert '{"status": "done" | "blocked", "summary":' in prompt


def test_lists_tools_without_mcp_when_argv_built() -> None:
    assert IMPLEMENTING_TOOLS == (
        "Read",
        "Edit",
        "Write",
        "Glob",
        "Grep",
        "TodoWrite",
        "Bash(git status:*)",
        "Bash(git diff:*)",
        "Bash(git log:*)",
        "Bash(git add:*)",
        "Bash(git commit:*)",
        "Bash(make:*)",
        "Bash(ls:*)",
        "Bash(cat:*)",
        "Bash(rg:*)",
        "Bash(grep:*)",
    )
    assert not [tool for tool in IMPLEMENTING_TOOLS if "mcp__" in tool]


def test_adds_gate_word_once_when_fast_and_full_share_it() -> None:
    assert gate_tools(["make check-fast", "make check"]) == ()
    assert gate_tools(["uv run pytest -q", "uv run --all-packages pytest"]) == ("Bash(uv:*)",)
    assert gate_tools(["tox -e fast", "./ci.sh"]) == ("Bash(./ci.sh:*)", "Bash(tox:*)")


def test_orders_argv_when_built() -> None:
    argv = implementing_argv(
        prompt="the prompt",
        max_turns=40,
        budget=3.0,
        model="sonnet",
        effort="medium",
        add_dirs=("/work/ws/hub", "/work/ws/demo-web"),
        tools=("Read", "Bash(make:*)"),
    )

    assert argv == [
        "claude",
        "-p",
        "the prompt",
        "--output-format",
        "json",
        "--max-turns",
        "40",
        "--max-budget-usd",
        "3",
        "--model",
        "sonnet",
        "--settings",
        '{"effortLevel": "medium"}',
        "--add-dir",
        "/work/ws/hub",
        "/work/ws/demo-web",
        "--allowedTools",
        "Read",
        "Bash(make:*)",
    ]
    assert json.loads(argv[12]) == {"effortLevel": "medium"}


def test_omits_add_dir_when_no_folder_given() -> None:
    argv = implementing_argv(
        prompt="p", max_turns=1, budget=0.25, model="m", effort="low", add_dirs=(), tools=("Read",)
    )

    assert "--add-dir" not in argv
    assert argv[argv.index("--max-budget-usd") + 1] == "0.25"


def test_pins_url_cap_and_end_line_when_module_loaded() -> None:
    assert MAX_URL_CHARS == 2_048
    assert ISSUE_END == (
        "End of the issue. Follow steps 1 to 5 above; your last line is the JSON verdict."
    )


def test_cuts_url_when_over_cap() -> None:
    url = "https://linear.app/" + "u" * MAX_URL_CHARS

    prompt = prompt_for(an_issue(url=url))

    assert f"url: {url[:MAX_URL_CHARS]}{TRUNCATED}\n" in prompt
    assert url[: MAX_URL_CHARS + 1] not in prompt


def test_drops_nul_when_issue_holds_one() -> None:
    issue = an_issue(title="Synthetic\x00title", description="a\x00b", url="https://x/\x00")

    prompt = prompt_for(issue)

    assert "\x00" not in prompt
    assert "title: Synthetictitle\n" in prompt
    assert "description:\nab\n" in prompt


def test_replaces_lone_surrogate_when_issue_holds_one() -> None:
    issue = an_issue(title="Synthetic \ud800 title", description="tail \udfff")

    prompt = prompt_for(issue)

    prompt.encode()  # a lone surrogate would raise here, as exec would refuse the argument
    assert "title: Synthetic \ufffd title\n" in prompt
    assert "description:\ntail \ufffd\n" in prompt


def test_writes_budget_as_exact_decimal_when_argv_built() -> None:
    def budget_shown(budget: float) -> str:
        argv = implementing_argv(
            prompt="p", max_turns=1, budget=budget, model="m", effort="low", add_dirs=(), tools=()
        )
        return argv[argv.index("--max-budget-usd") + 1]

    assert budget_shown(3) == "3"
    assert budget_shown(3.0) == "3"
    assert budget_shown(0.5) == "0.5"
    assert budget_shown(1234567) == "1234567"
    assert budget_shown(1e-7) == "0.0000001"
