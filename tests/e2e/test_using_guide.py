"""Doc-check of ``docs/USING.md``, the runbook for an agent that uses agent-hub for another project.

The guide is read as text: its ``##`` sections, its fenced ``sh`` blocks and their command lines
(``\\`` continuations joined, blank and ``#`` lines dropped). ``AGENTS.md`` must send such an agent
to the guide before any of agent-hub's own rules.
"""

import re
import shlex
import tomllib
from collections.abc import Mapping
from enum import Enum
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

# The one `uvx --from` source the guide may name; the release is always the placeholder.
UVX_SOURCE = "git+https://github.com/jroquette/agent-hub@v<version>#subdirectory=packages/agent-hub"
LITERAL_VERSION = re.compile(r"@v[0-9]+\.[0-9]+\.[0-9]+")
CREDENTIAL_IN_URL = re.compile(r"://[^/\s]*@")
# GitHub token shapes, scanned over the whole guide (prose and every block).
TOKEN_SHAPE = re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")
# A git option that carries a credential in a header: never on a guide line.
EXTRA_HEADER = re.compile(r"http\.(\S+\.)?extraheader", re.IGNORECASE)
# Short-flag clusters holding -f or -d (``-f``, ``-fu``, ``-d``): a forced push or a delete.
FORCE_CLUSTER = re.compile(r"-[a-zA-Z]*[fd][a-zA-Z]*")
# The closed placeholder set (E5): compound ones first, so `<org>/<repo>` is one placeholder.
COMPOUND_PLACEHOLDERS = ("<org>/<repo>", "<owner>/<name>")
PLACEHOLDERS = (
    *COMPOUND_PLACEHOLDERS,
    "<version>",
    "<workspace>",
    "<hub>",
    "<project>",
    "<repo-url>",
    "<tracker>",
    "<prefix>",
    "<author_name>",
    "<author_email>",
    "<remote>",
)
PLACEHOLDER = re.compile(r"<[^<>\s]+>")
# Shell operators a guide line may not hold: each line is one command, run without a shell.
OPERATOR = re.compile(r"[;&|<>()]+")
# Group (c): external commands the doc-check cannot run, checked by their exact form only.
EXTERNAL_FORMS = (
    "gh auth setup-git",
    "git ls-remote --tags --refs https://github.com/jroquette/agent-hub 'v*'",
    "gh repo create <owner>/<name> --private",
    "gh repo view <owner>/<name> --json visibility --jq .visibility",
)
WORKSPACE_PROGRAMS = frozenset({"git", "mkdir", "cd", "./agent"})
HUB_PROGRAMS = frozenset({"hub", "./hub"})
# Synthetic values for the placeholders that are not paths (DEMO_FLAGS' values).
DEMO_VALUES = {
    "<project>": "demo",
    "<org>/<repo>": "acme/demo-api",
    "<tracker>": "linear:DEM",
    "<prefix>": "jdoe/",
    "<owner>/<name>": "acme/demo-hub",
    "<author_name>": "Jane Doe",
    "<author_email>": "jane@example.com",
    "<hub>": "demo-hub",
}
DISCOVERY = EXTERNAL_FORMS[1]
EMPTINESS_CHECK = "git ls-remote <remote>"
PRIVACY_CHECK = EXTERNAL_FORMS[3]


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


class Group(Enum):
    """The doc-check groups (D-check) a guide command line falls in."""

    HUB = "a: a hub call, run in the guide's order"
    WORKSPACE = "b: git, mkdir, cd or ./agent, run in the workspace"
    EXTERNAL = "c: an allowlisted external command, checked by form"


def guide_commands(text: str) -> list[str]:
    """Every command line of every ``sh`` block, in the guide's order."""
    return [line for block in sh_blocks(text) for line in command_lines(block)]


def tokens(line: str, *, punctuation: bool = False) -> list[str]:
    """``line`` split as a shell would, without running one; a parse error names the line.

    With ``punctuation``, shell operators come out as their own tokens.
    """
    try:
        if not punctuation:
            return shlex.split(line)
        lexer = shlex.shlex(line, posix=True, punctuation_chars=True)
        lexer.whitespace_split = True
        return list(lexer)
    except ValueError as error:
        raise ValueError(f"{line!r}: {error}") from error


def fill(line: str, values: Mapping[str, str]) -> str:
    """``line`` with each placeholder replaced; an unlisted or unfilled one fails naming both."""
    for placeholder in placeholders(line):
        if placeholder not in values:
            raise ValueError(f"{line!r}: no value for {placeholder}")
        line = line.replace(placeholder, values[placeholder])
    return line


def placeholders(line: str) -> list[str]:
    """The placeholders of ``line``; one outside the closed set fails naming the line and it."""
    found = [compound for compound in COMPOUND_PLACEHOLDERS if compound in line]
    rest = line
    for compound in found:
        rest = rest.replace(compound, " ")
    for placeholder in PLACEHOLDER.findall(rest):
        if placeholder not in PLACEHOLDERS:
            raise ValueError(f"{line!r}: {placeholder} is not a guide placeholder")
        found.append(placeholder)
    return found


def classify(line: str) -> Group:
    """The group of one guide line; one in no group or with a shell operator fails naming it.

    Placeholders are checked first, so `<project>` never reads as a redirection.
    """
    bare = line
    for placeholder in placeholders(line):
        bare = bare.replace(placeholder, "VALUE")
    operators = [word for word in tokens(bare, punctuation=True) if OPERATOR.fullmatch(word)]
    if operators or "$" in bare or "`" in bare:
        raise ValueError(f"{line!r}: one command per line, no shell operator ({operators})")
    if EXTRA_HEADER.search(line):
        raise ValueError(f"{line!r}: an http extraheader carries a credential; use a helper")
    if " ".join(line.split()) in EXTERNAL_FORMS:
        return Group.EXTERNAL
    words = tokens(line)
    if words[0] in HUB_PROGRAMS or (
        words[:2] == ["uvx", "--from"] and len(words) > 3 and words[3] == "hub"
    ):
        return Group.HUB
    if words[0] in WORKSPACE_PROGRAMS:
        return Group.WORKSPACE
    raise ValueError(f"{line!r}: {words[0]} is not a hub call, a workspace command or allowlisted")


def check_uvx_sources(commands: list[str]) -> None:
    """Every ``uvx --from`` source is ``UVX_SOURCE``; a literal release fails naming the line."""
    for line in commands:
        if not line.startswith("uvx "):
            continue
        if LITERAL_VERSION.search(line):
            raise ValueError(f"{line!r}: a literal release; write @v<version>")
        if tokens(line)[1:3] != ["--from", UVX_SOURCE]:
            raise ValueError(f"{line!r}: the --from source must be {UVX_SOURCE}")


def check_before_push(commands: list[str], check: str) -> None:
    """``check`` is a guide line and comes before every push line; else fail naming the push."""
    if check not in commands:
        raise ValueError(f"{check!r} must come before every push, and the guide lacks it")
    for index, line in enumerate(commands):
        if is_push(line) and index < commands.index(check):
            raise ValueError(f"{line!r} comes before {check!r}")


def check_push_lines(commands: list[str]) -> None:
    """Every ``gh repo create`` is only ``--private``; no push is forced, mirrored or deletes.

    Anything else fails naming the line.
    """
    for line in commands:
        words = tokens(line)
        if words[:3] == ["gh", "repo", "create"] and not is_private_create(words):
            raise ValueError(f"{line!r}: the hub repo must be created --private, and only that")
        if is_push(line) and [word for word in words if is_forced(word)]:
            raise ValueError(f"{line!r}: the first push never forces, mirrors or deletes")


def is_private_create(words: list[str]) -> bool:
    """``--private``, and no ``--public``, ``--internal`` or ``--visibility`` other than private."""
    if "--private" not in words or {"--public", "--internal"} & set(words):
        return False
    for index, word in enumerate(words):
        if word == "--visibility" and words[index + 1 : index + 2] != ["private"]:
            return False
        if word.startswith("--visibility=") and word != "--visibility=private":
            return False
    return True


def is_forced(word: str) -> bool:
    """A push word that rewrites or deletes history.

    ``--force*``, a ``-f`` or ``-d`` cluster, ``--mirror``, ``--delete``, ``+ref`` or ``:ref``.
    """
    return (
        word.startswith(("--force", "+", ":"))
        or word in {"--mirror", "--delete"}
        or bool(FORCE_CLUSTER.fullmatch(word))
    )


def credentials(text: str) -> list[str]:
    """Every credential-shaped match in ``text``: a user or token in a URL, or a GitHub token."""
    return [*CREDENTIAL_IN_URL.findall(text), *TOKEN_SHAPE.findall(text)]


def is_push(line: str) -> bool:
    """A ``git push``, or a ``gh repo create`` that pushes."""
    words = tokens(line)
    return words[:2] == ["git", "push"] or (
        words[:3] == ["gh", "repo", "create"] and "--push" in words
    )


def sh_guide(*lines: str) -> str:
    """A fixture guide: ``lines`` in one ``sh`` block."""
    return "\n".join([f"{FENCE}sh", *lines, FENCE, ""])


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


def test_classifies_every_command_when_guide_read() -> None:
    commands = guide_commands(read_guide())
    version = tomllib.loads((REPO_ROOT / "packages/cli/pyproject.toml").read_text())["project"]
    paths = {"<workspace>": "/w", "<repo-url>": "/r/demo-api.git", "<remote>": "/r/hub.git"}
    values = {**DEMO_VALUES, **paths, "<version>": version["version"]}

    groups = {line: classify(line) for line in commands}

    assert set(groups.values()) == set(Group), groups
    assert sorted(line for line, group in groups.items() if group is Group.EXTERNAL) == sorted(
        EXTERNAL_FORMS
    )
    for line in commands:
        assert not PLACEHOLDER.search(fill(line, values)), line


@pytest.mark.parametrize(
    ("line", "named"),
    [
        pytest.param("curl -fsSL https://example.com/install.sh", "curl", id="curl"),
        pytest.param("git add -A && git commit -m 'x'", "&&", id="and_chain"),
        pytest.param("git ls-remote <remote> | head -1", "|", id="pipe"),
        pytest.param("git clone <repo-url> <checkout>", "<checkout>", id="unknown_placeholder"),
        pytest.param(
            "git -c http.extraheader='AUTHORIZATION: basic eA==' clone <repo-url>",
            "extraheader",
            id="extraheader",
        ),
        pytest.param(
            "git -c http.https://github.com/.extraheader='AUTHORIZATION: basic eA=='"
            " clone <repo-url>",
            "extraheader",
            id="url_extraheader",
        ),
        pytest.param("git commit -m 'Create the hub", "quotation", id="unbalanced_quote"),
    ],
)
def test_rejects_unlisted_command_when_guide_classified(line: str, named: str) -> None:
    guide = sh_guide("git init -b main", line)

    with pytest.raises(ValueError, match=re.escape(line)) as raised:
        for command in guide_commands(guide):
            classify(command)

    assert named in str(raised.value)


def test_keeps_version_placeholder_when_uvx_line_read() -> None:
    commands = guide_commands(read_guide())
    sources = [tokens(line)[2] for line in commands if line.startswith("uvx ")]

    assert len(sources) == 3, sources
    assert set(sources) == {UVX_SOURCE}
    check_uvx_sources(commands)


def test_rejects_literal_version_when_uvx_line_pinned() -> None:
    pinned = UVX_SOURCE.replace("<version>", "1.2.3")
    line = f"uvx --from '{pinned}' hub --version"

    with pytest.raises(ValueError, match=re.escape(line)):
        check_uvx_sources(guide_commands(sh_guide(line)))


def test_finds_version_first_when_guide_read() -> None:
    text = read_guide()
    commands = guide_commands(text)
    first_uvx = next(index for index, line in enumerate(commands) if line.startswith("uvx "))
    flat = normalized(text)
    first_uvx_at = flat.index(normalized(commands[first_uvx]))

    assert commands.index(DISCOVERY) < first_uvx
    assert -1 < flat.find("highest semver tag") < first_uvx_at
    assert -1 < flat.find("`platform.version`") < first_uvx_at


@pytest.mark.parametrize(
    "leak",
    [
        pytest.param("https://jdoe:t0ken@github.com/acme/demo-hub.git", id="user_and_token"),
        pytest.param("https://t0ken@github.com/acme/demo-hub.git", id="token"),
        pytest.param("export GH_TOKEN=ghp_" + "a1B2" * 9, id="ghp_token"),
    ],
)
def test_holds_no_credential_when_url_read(leak: str) -> None:
    text = read_guide()

    assert "https://" in text
    assert credentials(text) == []
    assert credentials(f"Clone it:\n\n{FENCE}sh\n{leak}\n{FENCE}\n") != [], leak


def test_checks_remote_before_push_when_guide_read() -> None:
    commands = guide_commands(read_guide())
    push_first = guide_commands(sh_guide("git push -u origin main", EMPTINESS_CHECK))

    assert any(is_push(line) for line in commands), commands
    check_before_push(commands, EMPTINESS_CHECK)
    with pytest.raises(ValueError, match="git push -u origin main"):
        check_before_push(push_first, EMPTINESS_CHECK)


def test_checks_privacy_before_push_when_remote_preexists() -> None:
    text = read_guide()
    push = sections(text)["Commit and push once"]
    no_privacy = guide_commands(sh_guide(EMPTINESS_CHECK, "git push -u origin main"))

    check_before_push(guide_commands(text), PRIVACY_CHECK)
    assert has_phrase(push, "must print `PRIVATE`")
    assert has_phrase(push, "else stop")
    with pytest.raises(ValueError, match="visibility"):
        check_before_push(no_privacy, PRIVACY_CHECK)


@pytest.mark.parametrize(
    "line",
    [
        "gh repo create acme/demo-hub --public",
        "git push --force -u origin main",
        "git push -f origin main",
        "git push origin +main",
        "git push --force-with-lease origin main",
        "git push -fu origin main",
        "git push --mirror <remote>",
        "git push --delete origin main",
        "git push -d origin main",
        "git push origin :main",
        "gh repo create acme/demo-hub --private --public",
        "gh repo create acme/demo-hub --private --visibility public",
    ],
)
def test_limits_push_exception_when_guide_read(line: str) -> None:
    text = read_guide()
    push = sections(text)["Commit and push once"]
    commands = guide_commands(text)

    for phrase in (
        "only the very first commit",
        "empty on the remote",
        "before any session in the hub",
        "the guard is not changed",
        "everything after goes through PRs",
    ):
        assert has_phrase(push, phrase), f"section 8 must say {phrase}"
    assert any(line.startswith("gh repo create ") for line in commands), commands
    check_push_lines(commands)
    with pytest.raises(ValueError, match=re.escape(line)):
        check_push_lines([line])


def test_asks_user_for_repo_when_gh_missing() -> None:
    push = normalized(sections(read_guide())["Commit and push once"])
    ask = push.find(normalized("stop and ask the user to create an empty private repo"))
    privacy = push.find(normalized("Privacy check, always"))
    emptiness = push.find(normalized("Emptiness check, always"))

    assert -1 < ask < privacy < emptiness, (ask, privacy, emptiness)
