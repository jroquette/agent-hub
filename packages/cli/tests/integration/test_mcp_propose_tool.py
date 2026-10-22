"""``hub mcp``'s ``propose`` tool on a real hub: a hub pull request adding one inbox note, through
real git against a bare ``origin`` and a fake ``gh`` (spec D-note, D-branch, D-propose-checks,
D-propose-write, D-pr, D-availability, E-2, E-4, E-5, AM-2).

The server is the one ``hub mcp`` builds (``build_server`` over ``hub_context``, with the
``GitBrainChangeRequests`` that ``serve`` gives it), driven in process by ``mcp.Client`` (E-2),
on the ``proposal_hub`` fixture: project ``demo``, ``hub.json``'s author ``Jane Doe`` and branch
prefix ``jdoe/``, ``origin`` = ``acme/demo-hub`` rewritten to a bare repository under
``tmp_path``.
"""

import io
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import anyio
import pytest
from mcp import Client
from mcp.types import CallToolResult, TextContent

from agent_hub.cli.mcp_command import hub_context
from agent_hub.core.json_form import dump_json
from agent_hub.hub_git.brain_change_requests import GitBrainChangeRequests
from agent_hub.hub_git.git_runner import GitRunner
from agent_hub.mcp_server.hub_context import HubContext
from agent_hub.mcp_server.server import build_server

pytestmark = pytest.mark.disable_socket

# The conftest's hub factory and its value (tests cannot import a conftest in importlib mode).
type ProposalHubFactory = Callable[..., Any]

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
TITLE = "Worktrees need a fresh fetch"
SLUG = "worktrees-need-a-fresh-fetch"
BRANCH = f"jdoe/learning-propose-{SLUG}"
NOTE_PATH = f"brain/_inbox/2026-10-21-{SLUG}.md"
FIRST_PARAGRAPH = "Create each worktree from a freshly fetched origin/main."
BODY = f"{FIRST_PARAGRAPH}\n\nOtherwise the branch starts behind and the PR shows old commits."
AUTHOR = "Jane Doe <jane@example.com>"
ATTRIBUTION = ("Co-Authored-By", "Generated with", "Claude")


def proposal(**overrides: Any) -> dict[str, Any]:
    """``propose``'s arguments: the spec's AC-392.8 proposal, with ``overrides``."""
    arguments: dict[str, Any] = {"title": TITLE, "body": BODY, "kind": "playbook"}
    arguments["external"] = False
    arguments.update(overrides)
    return arguments


def context_of(environ: Mapping[str, str]) -> HubContext:
    """What ``hub mcp`` resolves at start for ``environ``."""
    return hub_context(environ)


def served(
    environ: Mapping[str, str], *calls: dict[str, Any], hub: HubContext | None = None
) -> list[CallToolResult]:
    """The results of ``propose`` with each of ``calls``, in one session of the server
    ``hub mcp`` builds for ``environ`` (or for ``hub``, already resolved), its ``git`` and
    ``gh`` run with ``environ`` as ``serve`` runs them."""
    server = build_server(
        hub or context_of(environ),
        change_requests=GitBrainChangeRequests(GitRunner(environ=environ)),
        clock=lambda: NOW,
        log=io.StringIO(),
    )

    async def session() -> list[CallToolResult]:
        async with Client(server) as client:
            return [await client.call_tool("propose", arguments) for arguments in calls]

    return anyio.run(session)


def text_of(result: CallToolResult) -> str:
    [content] = result.content
    assert isinstance(content, TextContent)
    return content.text


def found_by(result: CallToolResult) -> dict[str, Any]:
    """The answer of a successful call, the same object as structured content and as text."""
    assert not result.is_error, text_of(result)
    assert result.structured_content is not None
    assert json.loads(text_of(result)) == result.structured_content
    return result.structured_content


def pull_request_creates(world: Any) -> list[list[str]]:
    return [argv for argv in world.gh_calls() if argv[:2] == ["pr", "create"]]


def test_opens_pull_request_with_note_when_proposed(proposal_hub: ProposalHubFactory) -> None:
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    environ = dict(world.environ, CLAUDE_CODE_SESSION_ID="s-123")
    main_before = world.origin_git("rev-parse", "main")
    checkout_before = world.snapshot()

    [result] = served(environ, proposal())

    assert found_by(result) == {
        "pr_url": "https://github.com/acme/demo-hub/pull/1",
        "branch": BRANCH,
        "path": NOTE_PATH,
    }
    assert world.branches() == {"main", BRANCH}
    assert world.origin_git("rev-list", "--count", f"main..{BRANCH}") == "1\n"
    assert world.origin_git("rev-parse", f"{BRANCH}^") == main_before
    assert world.origin_git("diff", "--name-status", "main", BRANCH) == f"A\t{NOTE_PATH}\n"
    assert world.origin_git("show", f"{BRANCH}:{NOTE_PATH}") == (
        "---\n"
        "type: learning-proposal\n"
        "status: proposed\n"
        "provenance: agent\n"
        "target: brain/playbooks/\n"
        "created: 2026-10-21\n"
        "session: s-123\n"
        "---\n"
        "\n"
        f"# {TITLE}\n"
        "\n"
        f"{BODY}\n"
    )
    people = world.origin_git("log", "-1", "--format=%an <%ae>%n%cn <%ce>", BRANCH)
    assert people == f"{AUTHOR}\n{AUTHOR}\n"
    message = world.origin_git("log", "-1", "--format=%B", BRANCH)
    assert message.strip() == f"docs(brain): propose learning {SLUG}"
    [pull] = world.pulls()
    assert pull == {
        "url": "https://github.com/acme/demo-hub/pull/1",
        "head": BRANCH,
        "base": "main",
        "title": f"Learning proposal: {TITLE}",
        "body": (
            f"Adds {NOTE_PATH} (provenance agent, session s-123).\n\n```\n{FIRST_PARAGRAPH}\n```\n"
        ),
    }
    for mark in ATTRIBUTION:
        assert mark not in pull["title"]
        assert mark not in pull["body"]
        assert mark not in message
    assert world.origin_git("rev-parse", "main") == main_before
    assert world.snapshot() == checkout_before


def test_opens_external_note_without_session_when_proposed(
    proposal_hub: ProposalHubFactory,
) -> None:
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    environ = dict(world.environ)
    environ.pop("CLAUDE_CODE_SESSION_ID", None)

    [result] = served(environ, proposal(external=True))

    assert found_by(result)["path"] == NOTE_PATH
    note = world.origin_git("show", f"{BRANCH}:{NOTE_PATH}")
    assert "provenance: agent-from-external\n" in note
    assert "session:" not in note
    [pull] = world.pulls()
    assert pull["body"].startswith(f"Adds {NOTE_PATH} (provenance agent-from-external).\n")


def test_refuses_proposal_when_input_out_of_bounds(proposal_hub: ProposalHubFactory) -> None:
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    without_external = proposal()
    del without_external["external"]
    refused = [
        (proposal(title=""), "propose: the title is empty"),
        (proposal(title="t" * 121), "propose: the title is longer than 120 characters"),
        (
            proposal(title="Two\nlines"),
            "propose: the title must be one line with no control characters",
        ),
        (proposal(title="!!! ???"), "propose: the title has no letters or digits for a file name"),
        (proposal(body=""), "propose: the body is empty"),
        (proposal(body="b" * 65_537), "propose: the body is larger than 65536 bytes"),
        (proposal(kind="adr"), "propose: invalid arguments (kind)"),
        (without_external, "propose: invalid arguments (external)"),
    ]

    results = served(world.environ, *[arguments for arguments, _ in refused])

    assert [(result.is_error, text_of(result)) for result in results] == [
        (True, line) for _, line in refused
    ]
    assert world.branches() == {"main"}
    assert world.gh_calls() == []


def secret_token() -> str:
    """A GitHub token shape r1 matches, built from parts so no literal is a token."""
    return "gh" + "p_" + "A1b2C3d4E5f6G7h8" * 2 + "xyzw"


def test_refuses_secret_before_git_when_text_matches(
    proposal_hub: ProposalHubFactory, tmp_path: Path
) -> None:
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    shim_dir, log = tmp_path / "git-shim", tmp_path / "git-calls"
    shim_dir.mkdir()
    shim = shim_dir / "git"
    shim.write_text(
        f'#!/bin/sh\nprintf "%s\\n" "$*" >> "{log}"\nexec "{shutil.which("git")}" "$@"\n'
    )
    shim.chmod(0o755)
    environ = dict(world.environ, PATH=f"{shim_dir}{os.pathsep}{world.environ['PATH']}")
    # Resolved first, as ``hub mcp`` does at start; only the calls must run no git.
    hub = context_of(environ)
    log.unlink(missing_ok=True)

    results = served(
        environ,
        proposal(body=f"Use the token {secret_token()} for the fetch."),
        proposal(title=f"Token {secret_token()}"),
        hub=hub,
    )

    for result in results:
        assert result.is_error
        assert text_of(result) == "propose: the text matches a secret rule"
        assert secret_token() not in result.model_dump_json()
    assert not log.exists()
    assert world.gh_calls() == []
    assert world.branches() == {"main"}


def test_refuses_proposal_when_note_or_branch_exists(proposal_hub: ProposalHubFactory) -> None:
    world = proposal_hub(
        {"brain/now.md": b"# Now\n", "brain/_inbox/2026-10-21-note-already-there.md": b"# Note\n"}
    )
    taken = "jdoe/learning-propose-branch-already-there"
    world.git("push", "--quiet", "origin", f"main:refs/heads/{taken}")
    taken_head = world.origin_git("rev-parse", taken)

    note_there, branch_there, first, again = served(
        world.environ,
        proposal(title="Note already there"),
        proposal(title="Branch already there"),
        proposal(title="Proposed twice"),
        proposal(title="Proposed twice"),
    )

    assert note_there.is_error
    assert text_of(note_there) == (
        "propose: note exists: brain/_inbox/2026-10-21-note-already-there.md"
    )
    assert branch_there.is_error
    assert text_of(branch_there) == f"propose: branch exists: {taken}"
    twice = "jdoe/learning-propose-proposed-twice"
    assert found_by(first)["branch"] == twice
    assert again.is_error
    assert text_of(again) == f"propose: branch exists: {twice}"
    assert world.branches() == {"main", taken, twice}
    assert world.origin_git("rev-parse", taken) == taken_head
    assert [pull["head"] for pull in world.pulls()] == [twice]
    assert len(pull_request_creates(world)) == 1


def _not_github(world: Any, environ: dict[str, str]) -> None:
    del environ
    world.git("remote", "set-url", "origin", str(world.bare))


def _other_repo(world: Any, environ: dict[str, str]) -> None:
    del environ
    world.git("remote", "set-url", "origin", "https://github.com/acme/other.git")


def _no_gh(world: Any, environ: dict[str, str]) -> None:
    tools = world.gh_state.parent / "git-only"
    tools.mkdir()
    (tools / "git").symlink_to(os.path.abspath(shutil.which("git") or "git"))
    environ["PATH"] = str(tools)


def _logged_out(world: Any, environ: dict[str, str]) -> None:
    del environ
    world.switch("logged-out")


def _in_container(world: Any, environ: dict[str, str]) -> None:
    del world
    environ["AGENT_HUB_IN_CONTAINER"] = "1"


def _no_author(world: Any, environ: dict[str, str]) -> None:
    del environ
    document = json.loads((world.hub / "hub.json").read_bytes())
    del document["project"]["author_name"], document["project"]["author_email"]
    (world.hub / "hub.json").write_bytes(dump_json(document))
    # The url rewrite stays; the ``[user]`` section before it goes.
    config = world.gitconfig.read_text()
    world.gitconfig.write_text("[url" + config.split("[url", 1)[1])


@pytest.mark.parametrize(
    "unavailable",
    [
        (_not_github, "propose: Hub remote is not on GitHub"),
        (_other_repo, "propose: Hub remote is not acme/demo-hub"),
        (_no_gh, "propose: gh is not installed"),
        (_logged_out, "propose: gh is not signed in to GitHub"),
        (_in_container, "propose: Hub is read-only here"),
        (_no_author, "propose: the hub has no author"),
    ],
    ids=["not-github", "other-repo", "no-gh", "logged-out", "in-container", "no-author"],
)
def test_reports_unavailable_hub_when_proposed(
    proposal_hub: ProposalHubFactory,
    unavailable: tuple[Callable[[Any, dict[str, str]], None], str],
) -> None:
    make_unavailable, line = unavailable
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    environ = dict(world.environ)
    make_unavailable(world, environ)

    [result] = served(environ, proposal())

    assert result.is_error
    assert text_of(result) == line
    assert world.branches() == {"main"}
    assert pull_request_creates(world) == []


def test_leaves_no_branch_when_push_or_pull_request_fails(
    proposal_hub: ProposalHubFactory, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    world = proposal_hub({"brain/now.md": b"# Now\n"})
    temp = tmp_path / "temp"
    temp.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(temp))

    world.reject_pushes()
    [rejected] = served(world.environ, proposal(title="Push is rejected"))
    (world.bare / "hooks" / "pre-receive").unlink()
    world.switch("fail")
    [failed] = served(world.environ, proposal(title="Pull request fails"))

    assert rejected.is_error
    assert text_of(rejected) == "propose: could not push (step failed)"
    assert failed.is_error
    assert text_of(failed) == "propose: could not pr (step failed)"
    assert world.branches() == {"main"}
    assert world.pulls() == []
    assert [entry.name for entry in temp.iterdir() if entry.name.startswith("hub-learning-")] == []
