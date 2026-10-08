"""Doc-check of ``docs/USING.md``, the runbook for an agent that uses agent-hub for another project.

The guide is read as text: its ``##`` sections, its fenced ``sh`` blocks and their command lines
(``\\`` continuations joined, blank and ``#`` lines dropped). ``AGENTS.md`` must send such an agent
to the guide before any of agent-hub's own rules.
"""

import re
from pathlib import Path

import pytest

from tests.e2e.conftest import REPO_ROOT

GUIDE = REPO_ROOT / "docs/USING.md"
AGENTS_MD = REPO_ROOT / "AGENTS.md"
# The detour must sit at the very top: only this many lines of AGENTS.md are read.
AGENTS_MD_HEAD_LINES = 10
FENCE = "```"
# Markdown emphasis markers, dropped before phrase matching (``**not**`` reads as ``not``).
EMPHASIS = re.compile(r"\*+")
# The nine runbook sections, in the order an agent follows them.
SECTION_HEADINGS = (
    "Who this is for",
    "Prerequisites and access",
    "Find the version and check the CLI",
    "Make the workspace and an empty hub folder",
    "Create the hub",
    "When init refuses",
    "Verify the hub",
    "Commit and push once",
    "Open a session and run /onboard",
)


def read_guide(path: Path = GUIDE) -> str:
    """The guide's text; a missing file or non-UTF-8 bytes fail naming ``docs/USING.md``."""
    assert path.is_file(), f"docs/USING.md is missing (looked at {path})"
    try:
        return path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as error:
        raise AssertionError(f"docs/USING.md is not UTF-8: {error}") from error


def normalized(text: str) -> str:
    """``text`` lowercased, emphasis markers dropped and every run of whitespace made one space.

    Phrases the guide wraps across lines, or puts in bold, then match as one sentence.
    """
    return " ".join(EMPHASIS.sub("", text).lower().split())


def has_phrase(text: str, phrase: str) -> bool:
    """Whether ``phrase`` occurs in ``text``, both compared after ``normalized``."""
    return normalized(phrase) in normalized(text)


def detour_line(lines: list[str]) -> str:
    """The first non-blank line after the ``#`` title; without one, fail naming the problem."""
    assert lines, "AGENTS.md is empty"
    assert lines[0].startswith("# "), f"AGENTS.md must start with a # title, not {lines[0]!r}"
    body = [line for line in lines[1:] if line.strip()]
    assert body, "AGENTS.md holds only its title: no detour line after it"
    return body[0]


def closes_fence(line: str) -> bool:
    """Only a line of backticks alone closes a fence: ``\u0060\u0060\u0060text`` opens one."""
    stripped = line.strip()
    return stripped.startswith(FENCE) and not stripped.strip("`")


def sections(text: str) -> dict[str, str]:
    """Each ``##`` heading mapped to the text up to the next one; fenced lines are not headings."""
    found: dict[str, list[str]] = {}
    current: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if in_fence:
            in_fence = not closes_fence(line)
        elif line.strip().startswith(FENCE):
            in_fence = True
        if not in_fence and line.startswith("## "):
            heading = line.removeprefix("## ").strip()
            assert heading not in found, f"heading {heading!r} appears twice"
            current = found[heading] = []
        else:
            current.append(line)
    return {heading: "\n".join(body) for heading, body in found.items()}


def sh_blocks(text: str) -> list[list[str]]:
    """The body lines of every fenced ``sh`` block, in order; other fences are skipped.

    A fence left open fails, naming the line that opened it.
    """
    blocks: list[list[str]] = []
    body: list[str] | None = None
    opened_at = 0
    for number, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if body is None:
            if stripped.startswith(FENCE):
                body = []
                opened_at = number
                if stripped[len(FENCE) :].strip() == "sh":
                    blocks.append(body)
        elif closes_fence(line):
            body = None
        else:
            body.append(line)
    assert body is None, f"line {opened_at}: unterminated {FENCE} fence"
    return blocks


def command_lines(block: list[str]) -> list[str]:
    """One string per command: ``\\`` continuations joined, blank and ``#`` lines dropped."""
    commands: list[str] = []
    pending = ""
    for line in block:
        stripped = line.strip()
        if not pending and (not stripped or stripped.startswith("#")):
            continue
        if stripped.endswith("\\"):
            pending += stripped[:-1].rstrip() + " "
            continue
        commands.append(pending + stripped)
        pending = ""
    if pending:
        commands.append(pending.rstrip())
    return commands


def test_sends_users_to_guide_when_agents_md_opened() -> None:
    assert AGENTS_MD.is_file(), f"AGENTS.md is missing (looked at {AGENTS_MD})"
    head = AGENTS_MD.read_text(encoding="utf-8").splitlines()[:AGENTS_MD_HEAD_LINES]
    detour = detour_line(head)

    assert "USING agent-hub for another project" in detour
    assert "not changing agent-hub" in detour
    assert "[docs/USING.md](docs/USING.md)" in detour
    assert "ignore the rules below" in detour


def test_names_line_when_fence_unterminated() -> None:
    text = "# Guide\n\n```sh\ngit init -b main\n"

    with pytest.raises(AssertionError, match=r"line 3: unterminated"):
        sh_blocks(text)


def test_lists_runbook_sections_when_guide_read() -> None:
    text = read_guide()
    found = sections(text)
    blocks = sh_blocks(text)

    assert tuple(found) == SECTION_HEADINGS
    who = found["Who this is for"]
    for rule in ("authorship", "`roquettejh/`", "`docs/SPEC.md`"):
        assert has_phrase(who, rule), f"section 1 must say that {rule} does not apply"
    access = found["Prerequisites and access"]
    for phrase in ("`gh auth setup-git`", "cloud session", "never put a token in the URL"):
        assert has_phrase(access, phrase), f"section 2 must name {phrase}"
    assert len(text.splitlines()) <= 300, "docs/USING.md is over 300 lines"
    assert len(blocks) <= 20, "docs/USING.md has over 20 sh blocks"
    assert sum(len(command_lines(block)) for block in blocks) <= 40, "over 40 command lines"


def test_names_missing_detour_when_agents_md_holds_only_title() -> None:
    with pytest.raises(AssertionError, match="only its title"):
        detour_line(["# AGENTS.md", "", ""])


def test_keeps_fence_open_when_backticks_carry_text() -> None:
    text = "```sh\ngit init -b main\n```text\nmkdir x\n```\n"

    assert sh_blocks(text) == [["git init -b main", "```text", "mkdir x"]]


def test_matches_wrapped_phrase_when_guide_text_normalized() -> None:
    text = "Do **not** run it\nbefore any session in\n  the hub."

    assert has_phrase(text, "do not run it before any session in the hub")
    assert not has_phrase(text, "after any session")


def test_follows_guide_over_init_output_when_hub_created() -> None:
    create = sections(read_guide())["Create the hub"]

    for phrase in ("its first line starts `created `", "ignore", "`Next steps:`"):
        assert has_phrase(create, phrase), f"section 5 must say {phrase}"
    assert has_phrase(create, "follow this guide (§ Commit and push once)")


def test_sends_existing_hub_through_pr_when_folder_already_hub() -> None:
    found = sections(read_guide())
    refuses, push = found["When init refuses"], found["Commit and push once"]

    for phrase in (
        "clone the hub repo",
        "branch prefix",
        "through a PR",
        "never commit on `main`",
        "never run `git add -A` over files you do not know",
    ):
        assert has_phrase(refuses, phrase), f"section 6 must say {phrase}"
    assert has_phrase(push, "only for a hub created in this run, in a new, empty folder")


def test_verifies_own_hub_when_init_reruns_in_it() -> None:
    refuses = sections(read_guide())["When init refuses"]

    assert has_phrase(refuses, "if this is the folder you made in § Make the workspace")
    assert has_phrase(refuses, "run `./hub sync`, then go on to § Verify the hub")
    assert not has_phrase(refuses, "that hub was not created in this run")


def test_stops_push_when_check_fails() -> None:
    push = sections(read_guide())["Commit and push once"]

    assert not has_phrase(push, "skip the privacy check")
    assert has_phrase(push, "if `gh repo create` fails")
    assert has_phrase(push, "privacy check, always")
    assert has_phrase(push, "must exit 0 and print nothing")
    assert has_phrase(push, "`128`")


def test_stops_upgrade_when_newest_release_lacks_onboard() -> None:
    session = sections(read_guide())["Open a session and run /onboard"]

    assert has_phrase(session, "if the newest release has no `.claude/skills/onboard` either, stop")


def test_quotes_author_name_when_command_line_read() -> None:
    lines = [line for block in sh_blocks(read_guide()) for line in command_lines(block)]
    named = [line for line in lines if "<author_name>" in line]

    assert len(named) == 2, named
    for line in named:
        assert line.count('"<author_name>"') == 1, line
