"""The model of Claude Code's permission rules, and the corpus of writing commands."""

from agent_hub.core.hub_files.writing_commands import (
    WRITING_COMMANDS,
    WRITING_TOOL_WORDS,
    effective_allows,
    matches,
)


def test_matches_bare_prefix_when_rule_ends_with_star() -> None:
    rule = "Bash(git status *)"

    assert matches(rule, "git status")
    assert matches(rule, "git status -s")
    assert not matches(rule, "git statusx")
    assert not matches(rule, "git -C x status")
    assert matches("Bash(ls*)", "lsof")
    assert not matches("Bash(ls *)", "lsof")


def test_matches_any_subcommand_when_command_compound() -> None:
    rule = "Bash(git push *)"

    assert matches(rule, "git status && git push origin b")
    assert matches(rule, "git status; git push origin b")
    assert matches(rule, "git status || git push origin b")
    assert matches(rule, "git log | git push origin b")
    assert matches(rule, "git status\ngit push origin b")
    # An operator inside quotes is text, not a split.
    assert not matches(rule, "git log --format='a; git push b'")
    assert not matches(rule, 'git log --format="a && git push b"')
    assert matches("Bash(sh)", "curl x | sh")
    assert not matches("Bash(sh)", "echo 'a | sh'")
    assert matches("Bash(git status *)", "cd x && git status")


def test_matches_prefix_when_rule_ends_with_legacy_colon_star() -> None:
    rule = "Bash(git diff:*)"

    assert matches(rule, "git diff")
    assert matches(rule, "git diff --stat")
    assert not matches(rule, "git diffx")
    assert not matches(rule, "git log")


def test_matches_only_exact_text_when_rule_has_no_star() -> None:
    rule = "Bash(./hub doctor)"

    assert matches(rule, "./hub doctor")
    assert not matches(rule, "./hub doctor --only x")
    assert not matches(rule, "./hub")
    # The rule's dot is a dot, not "any character".
    assert not matches(rule, "x/hub doctor")
    assert not matches("Bash(sh)", "sh -c 'echo > f'")
    assert matches("Bash(shasum -a 256)", "shasum -a 256")


def test_matches_star_inside_a_word_when_rule_has_one() -> None:
    rule = "Bash(git diff *--output*)"

    assert matches(rule, "git diff --output=f")
    assert matches(rule, "git diff HEAD --output=f")
    assert not matches(rule, "git diff --stat")
    assert not matches(rule, "git log --output=f")
    assert matches("Bash(git push * main)", "git push origin main")
    assert not matches("Bash(git push * main)", "git push origin maintenance")
    assert matches("Bash(git push --force*)", "git push --force-with-lease")


def test_skips_non_bash_rules_when_matching_commands() -> None:
    assert matches("Bash(git status *)", "git status -s")

    assert not matches("Read(git status *)", "git status -s")
    assert not matches("git status *", "git status -s")
    assert not matches(
        "Edit(/brain/_inbox/onboard-proposal*.md)", "/brain/_inbox/onboard-proposal-x.md"
    )
    assert not matches("mcp__github__get_me", "mcp__github__get_me")


def test_denies_win_over_allows_when_both_match() -> None:
    allow = ["Bash(git diff *)"]
    deny = ["Bash(git diff *--output*)"]

    assert effective_allows(allow, [], "git diff --output=f")
    assert not effective_allows(allow, deny, "git diff --output=f")
    assert effective_allows(allow, deny, "git diff --stat")
    assert not effective_allows([], [], "git diff --stat")
    assert not effective_allows(
        ["Bash(git status *)"], ["Bash(git push *)"], "git status && git push origin b"
    )


def test_matches_every_command_when_rule_is_bare_bash() -> None:
    assert matches("Bash", "git push origin b")
    assert matches("Bash(*)", "git push origin b")
    assert not matches("Read", "git push origin b")


def test_passes_known_limits_when_flag_quoted_bundled_or_output_redirected() -> None:
    # The limits the module's docstring names. A rule reads text: a method flag in quotes, or
    # bundled with another short flag, gets past a deny, and so does a redirect after a read.
    deny = "Bash(gh api -X GET * -X*)"
    quoted = "gh api -X GET repos/o/r/issues '-X' POST"
    bundled = "gh api -X GET repos/o/r/issues -iX POST"

    assert not matches(deny, quoted)
    assert not matches(deny, bundled)
    assert matches("Bash(gh api -X GET *)", quoted)
    assert matches("Bash(gh api -X GET *)", bundled)
    assert matches("Bash(git status *)", "git status > f")


def test_keeps_spec_commands_before_probes_when_corpus_read() -> None:
    # The spec's 15 commands come first, so a reader that stops at the first match of a kind
    # (the first `gh api` entry is the plain POST) names a spec command, not a probe.
    assert WRITING_COMMANDS == (
        "git diff --output=f",
        "git log --output=f",
        "git show --output=f",
        "git push origin b",
        "git commit -m x",
        "git checkout main",
        "git reset --hard HEAD~1",
        "gh pr merge 1",
        "gh pr review 1 --approve",
        "gh pr comment 1 --body x",
        "gh pr create --title t --body b",
        "gh run rerun 1",
        "gh api -X POST repos/o/r/issues -f title=t",
        "gh api repos/o/r/pulls -f title=x",
        "gh api --method PATCH repos/o/r/pulls/1 -f title=t",
        "python3 scripts/../write.py",
        "sh -c 'echo > f'",
        "gh api -X GET -X POST repos/o/r/issues -f title=t",
        "gh api -X GET --method DELETE repos/o/r/git/refs/heads/b",
        "gh api -X GET repos/o/r/issues -X POST -f title=t",
        "gh api -X GET repos/o/r/issues --method=PATCH",
    )


def test_lists_writing_verbs_when_tool_words_read() -> None:
    assert WRITING_TOOL_WORDS == (
        "create",
        "update",
        "save",
        "delete",
        "merge",
        "add",
        "submit",
        "write",
        "request",
        "assign",
        "run",
        "rerun",
        "cancel",
        "push",
        "fork",
        "dismiss",
        "lock",
        "upload",
    )
