"""The guard's change-flow rules, run on the rendered ``guard.py`` (AGH-699).

Rule 1 (commits and PRs are the user's, with no AI attribution) and rule 2 (no push to a protected
branch, the user merges every PR) as the guard reads them from a Bash command's calls, from the
message files those calls name, and from GitHub MCP tool calls. The workspace is a rendered demo
hub at ``ws/demo-hub`` whose ``hub.json`` is ``HUB_JSON`` (author ``Me <me@example.com>``, default
branch ``trunk``), beside git repos each test makes under ``ws``. ``decide`` runs
``guard.decide`` on a batch of events in one child on ``hook_python``, from a folder outside the
workspace, in the harness's environment (git reads no system or global config) plus the test's.
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig

HOOKS = "plugin/hub-workflow/hooks"
HUB_JSON: dict[str, Any] = {
    "project": {
        "name": "demo",
        "hub_repo": "me/demo-hub",
        "branch_prefix": "me/",
        "default_branch": "trunk",
        "author_name": "Me",
        "author_email": "me@example.com",
    },
    "tracker": {"kind": "linear", "team": "DEM"},
    "repos": [{"dir": "app", "github": "me/app", "check_fast": "", "check": ""}],
}
# argv: hub, a file of events (JSON). Prints decide's verdict for each event, in order.
DECIDE = """
import json
from pathlib import Path
import guard
from hubhooks import load_config
hub, events = Path(sys.argv[1]), sys.argv[2]
with open(events, encoding="utf-8") as fh:
    events = json.load(fh)
cfg = load_config(hub)
print(json.dumps([guard.decide(event, cfg, None) for event in events]))
"""
# A test's own git calls: no system or global config, as in the guard's child.
GIT_ENV = {"GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": os.devnull}

type Decide = Callable[..., list[tuple[str, str] | None]]


@pytest.fixture
def ws(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The workspace; its hub is ``ws/demo-hub``, with ``HUB_JSON`` as ``hub.json``."""
    hub = rendered_hub(demo_config).resolve()
    (hub / "hub.json").write_text(json.dumps(HUB_JSON), encoding="utf-8")
    return hub.parent


@pytest.fixture
def decide(ws: Path, *, hook_python: str, run_python: Callable[..., Any], tmp_path: Path) -> Decide:
    """``decide(event, load_config(hub), None)`` for each event, in one child, in order."""
    elsewhere, home = tmp_path / "elsewhere", tmp_path / "home"
    elsewhere.mkdir()
    home.mkdir()

    def run(
        events: Sequence[Mapping[str, Any]], *, env: Mapping[str, str] | None = None
    ) -> list[tuple[str, str] | None]:
        batch = tmp_path / "events.json"
        batch.write_text(json.dumps(list(events)), encoding="utf-8")
        found = run_python(
            hook_python,
            DECIDE,
            path=ws / "demo-hub" / HOOKS,
            args=[str(ws / "demo-hub"), str(batch)],
            cwd=elsewhere,
            env={"HOME": str(home)} | dict(env or {}),
        )
        return [tuple(verdict) if verdict else None for verdict in found]

    return run


def git(cwd: Path, *args: str) -> str:
    completed = subprocess.run(  # noqa: S603 - git from PATH, fixed arguments
        ["git", *args],  # noqa: S607
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
        env={"PATH": os.environ.get("PATH", os.defpath), "HOME": str(cwd)} | GIT_ENV,
    )
    return completed.stdout


def git_repo(path: Path, branch: str, email: str | None = None) -> Path:
    """A git repo at path on an unborn ``branch``, with ``user.email`` set when given."""
    path.mkdir(parents=True, exist_ok=True)
    git(path, "init", "-q", "-b", branch)
    if email is not None:
        git(path, "config", "user.email", email)
    return path


def bash_at(command: str, cwd: Path) -> dict[str, Any]:
    return {"tool_name": "Bash", "tool_input": {"command": command}, "cwd": str(cwd)}


def tool_at(tool: str, cwd: Path, **fields: Any) -> dict[str, Any]:
    return {"tool_name": tool, "tool_input": fields, "cwd": str(cwd)}


def put(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


# C-6: a bare push (no refspec, or `HEAD`/`@`) sends the branch checked out where it runs.
PUSH_REASON = "pushing to {} is not allowed; open a PR from a me/dem-<N>-<desc> branch"
PUSH_UNKNOWN_REASON = (
    "the branch this `git push` sends cannot be told (no branch checked out there, or a folder"
    " the guard cannot read); confirm it is not a protected branch"
)


def test_denies_bare_push_when_protected_branch_checked_out(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "trunk")
    web = git_repo(ws / "web", "main")
    events = [
        bash_at("git push", app),
        bash_at("git push origin HEAD", app),
        bash_at("git push -u origin HEAD", web),
        bash_at("git push --follow-tags origin", web),
        bash_at("git -C app push", ws),
        bash_at("cd app && git push origin @", ws),
    ]

    verdicts = decide(events)

    assert verdicts == [
        ("deny", PUSH_REASON.format(branch))
        for branch in ["trunk"] * 2 + ["main"] * 2 + ["trunk"] * 2
    ]


def test_passes_bare_push_when_feature_branch_checked_out(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x")
    events = [
        bash_at("git push", app),
        bash_at("git push -u origin HEAD", app),
        bash_at("git push origin HEAD:me/dem-1-x", app),
        bash_at("git push --tags", ws),
        bash_at("cd app && git push", ws),
    ]

    assert decide(events) == [None] * len(events)


def test_asks_when_pushed_branch_cannot_be_told(ws: Path, decide: Decide) -> None:
    detached = git_repo(ws / "app", "me/dem-1-x")
    git(
        detached,
        "-c",
        "user.name=T",
        "-c",
        "user.email=t@example.com",
        "commit",
        "-q",
        "--allow-empty",
        "-m",
        "x",
    )
    git(detached, "checkout", "-q", "--detach")
    events = [
        bash_at("git push", ws),
        bash_at("git push origin HEAD", detached),
        bash_at('cd "$WORKTREE" && git push', ws),
        bash_at("git -C $REPO push", ws),
    ]

    assert decide(events) == [("ask", PUSH_UNKNOWN_REASON)] * len(events)


# C-6: a message file (`git commit|tag|merge -F`, `gh pr create|edit|comment|review --body-file`)
# is read when the call names it; text the same command writes was read as the command's.
COMMIT_REASON = "commits carry no AI attribution (no Co-Authored-By AI, no 'Generated with', no 🤖)"
PR_REASON = "PR text carries no AI attribution"
HELD_BY = "{}: {} holds it"
CO_AUTHORED = "feat: x\n\nCo-Authored-By: Claude Opus <noreply@anthropic.com>\n"
GENERATED = "Body\n\nGenerated with [Claude Code](https://claude.com/claude-code)\n"
UNCHECKED_REASON = "message not checked for AI attribution: {} ({}); confirm"


def test_denies_call_when_message_file_holds_attribution(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    put(app / "msg.txt", CO_AUTHORED)
    put(ws / "tmp" / "body.md", GENERATED)
    body = "../tmp/body.md"
    commits = [
        "git commit -F msg.txt",
        "git commit --file=msg.txt",
        "git commit -a --file msg.txt",
        "git commit -aF msg.txt",
        "git tag -a v1 -F msg.txt",
        "git merge --no-ff -F msg.txt me/dem-2-y",
    ]
    prs = [
        f"gh pr create --title x --body-file {body}",
        f"gh pr edit 3 --body-file={body}",
        f"gh pr comment 3 -F {body}",
        f"gh pr review 3 --approve --body-file {body}",
    ]
    inline = [
        "gh pr comment 3 --body 'Generated with [Claude Code]'",
        "git merge -m 'Co-Authored-By: Claude' x",
    ]

    verdicts = decide([bash_at(command, app) for command in commits + prs + inline])

    assert verdicts == [("deny", HELD_BY.format(COMMIT_REASON, "msg.txt"))] * len(commits) + [
        ("deny", HELD_BY.format(PR_REASON, body))
    ] * len(prs) + [("deny", PR_REASON), ("deny", COMMIT_REASON)]


def test_passes_call_when_message_file_clean_or_written_by_command(
    ws: Path, decide: Decide
) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    put(app / "msg.txt", "feat: x\n\nRefs DEM-1\n")
    put(app / "body.md", "Body\n\nThe owner reviewed it.\n")
    commands = [
        "git commit -F msg.txt",
        "git tag -a v1 --file msg.txt",
        "gh pr create --title x --body-file body.md",
        "gh pr comment 3 -F body.md",
        "printf 'feat: y\\n' > new-msg.txt && git commit -F new-msg.txt",
        "cat > new-body.md <<'EOF'\nBody\nEOF\ngh pr edit 3 --body-file new-body.md",
    ]

    assert decide([bash_at(command, app) for command in commands]) == [None] * len(commands)


def test_asks_when_message_file_unreadable_or_stdin(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    (app / "folder.md").mkdir()
    cases = [
        ("git commit -F missing.txt", "missing.txt", "cannot be read"),
        ("git commit -F -", "-", "stdin"),
        ("gh pr create --body-file -", "-", "stdin"),
        ("gh pr comment 3 -F folder.md", "folder.md", "not a regular file"),
        ('git commit -F "$MSG"', "$MSG", "a shell expansion"),
    ]

    verdicts = decide([bash_at(command, app) for command, _, _ in cases])

    assert verdicts == [("ask", UNCHECKED_REASON.format(name, cause)) for _, name, cause in cases]


# C-6: skipping the repo's hooks asks: the owner may mean it, an agent asks first.
NO_VERIFY_REASON = (
    "`git {} {}` skips the repo's git hooks (pre-commit, commit-msg, pre-push); confirm"
)
HOOKS_PATH_REASON = "core.hooksPath changes which git hooks run; confirm"


def test_asks_when_git_hooks_skipped(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    cases = [
        ("git commit --no-verify -m x", NO_VERIFY_REASON.format("commit", "--no-verify")),
        ("git commit -nm x", NO_VERIFY_REASON.format("commit", "-n")),
        ("git commit -a -n -m x", NO_VERIFY_REASON.format("commit", "-n")),
        ("git push --no-verify origin me/dem-1-x", NO_VERIFY_REASON.format("push", "--no-verify")),
        (
            "git push --follow-tags --no-verify origin me/dem-1-fix",
            NO_VERIFY_REASON.format("push", "--no-verify"),
        ),
        ("git merge --no-verify me/dem-2-y", NO_VERIFY_REASON.format("merge", "--no-verify")),
        ("git -c core.hooksPath=/dev/null commit -m x", HOOKS_PATH_REASON),
        ("git -c Core.HooksPath=.x push origin me/dem-1-x", HOOKS_PATH_REASON),
        ("git --config-env=core.hooksPath=HOOKS commit -m x", HOOKS_PATH_REASON),
        ("git config core.hooksPath .nohooks", HOOKS_PATH_REASON),
        ("git config --local --unset core.hooksPath", HOOKS_PATH_REASON),
        ("GIT_CONFIG_PARAMETERS=\"'core.hooksPath'='x'\" git commit -m x", HOOKS_PATH_REASON),
    ]

    verdicts = decide([bash_at(command, app) for command, _ in cases])

    assert verdicts == [("ask", reason) for _, reason in cases]


def test_passes_when_hooks_only_mentioned_or_read(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    commands = [
        "git commit -m 'docs: explain --no-verify'",
        "git push -n origin me/dem-1-x",
        "git merge -n me/dem-2-y",
        "git config core.hooksPath",
        "git config --get core.hooksPath",
        "git log --no-verify",
    ]

    assert decide([bash_at(command, app) for command in commands]) == [None] * len(commands)


# C-6: a file tool's write of a commit or PR message file (named `pr.md`, `*-pr.md`, `body.md`,
# `msg.txt` and the like) holding AI attribution is denied before the call ever names it.
MESSAGE_WRITE_REASON = (
    "commits and PR text carry no AI attribution: {} is a commit or PR message file and holds it"
)


def test_denies_message_file_write_when_it_holds_attribution(ws: Path, decide: Decide) -> None:
    tmp = ws / "tmp"
    events = [
        tool_at("Write", ws, file_path=str(tmp / "dem-1-pr.md"), content=GENERATED),
        tool_at("Edit", ws, file_path=str(tmp / "msg.txt"), old_string="x", new_string=CO_AUTHORED),
        tool_at("Write", ws, file_path=str(tmp / "notes.md"), content=GENERATED),
        tool_at("Write", ws, file_path=str(tmp / "dem-1-pr.md"), content="Body\n"),
    ]

    verdicts = decide(events)

    assert verdicts == [
        ("deny", MESSAGE_WRITE_REASON.format(tmp / "dem-1-pr.md")),
        ("deny", MESSAGE_WRITE_REASON.format(tmp / "msg.txt")),
        None,
        None,
    ]


# C-7: who a commit, an annotated tag or a merge is by. When the hub sets the author's email
# (hub.local.json, else hub.json), each identity git would record (from --author, GIT_AUTHOR_* and
# GIT_COMMITTER_* variables, git -c, else git config where the call runs) must be that email.
IDENTITY_REASON = (
    "commit identity: this `git {}` would record {} as its {}, not Me <me@example.com>"
    " (project.author_email of hub.json or hub.local.json); set user.email in git config,"
    " or drop the override"
)
IDENTITY_UNCHECKED_REASON = (
    "commit identity not checked: {}; confirm this `git {}` is by Me <me@example.com>"
)
OTHER = "noreply@anthropic.com"


def test_denies_commit_when_git_config_names_other_author(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", OTHER)
    cases = [
        ("git commit -m x", IDENTITY_REASON.format("commit", OTHER, "author")),
        ("git tag -a v1 -m x", IDENTITY_REASON.format("tag", OTHER, "tagger")),
        ("git merge me/dem-2-y", IDENTITY_REASON.format("merge", OTHER, "author")),
    ]

    verdicts = decide([bash_at(command, app) for command, _ in cases])

    assert verdicts == [("deny", reason) for _, reason in cases]


def test_denies_commit_when_override_names_other_author(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    cases = [
        ("git -c user.email=other@x.io commit -m x", "author"),
        ("git -c author.email=other@x.io commit -m x", "author"),
        ("git commit --author='O <other@x.io>' -m x", "author"),
        ("git commit --author 'O <other@x.io>' -m x", "author"),
        ("GIT_AUTHOR_EMAIL=other@x.io git commit -m x", "author"),
        ("env GIT_COMMITTER_EMAIL=other@x.io git commit -m x", "committer"),
        ("export GIT_AUTHOR_EMAIL=other@x.io && git commit -m x", "author"),
    ]

    verdicts = decide([bash_at(command, app) for command, _ in cases])
    from_session = decide(
        [bash_at("git commit -m x", app)], env={"GIT_COMMITTER_EMAIL": "other@x.io"}
    )

    assert verdicts == [
        ("deny", IDENTITY_REASON.format("commit", "other@x.io", role)) for _, role in cases
    ]
    assert from_session == [("deny", IDENTITY_REASON.format("commit", "other@x.io", "committer"))]


def test_passes_commit_when_identity_matches(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    web = git_repo(ws / "web", "me/dem-1-x", OTHER)
    events = [
        bash_at("git commit -am x", app),
        bash_at("git commit --author='Me <ME@example.com>' -m x", app),
        bash_at("git tag -a v1 -m x", app),
        bash_at("git -c user.email=me@example.com commit -m x", web),
        bash_at(
            "GIT_AUTHOR_EMAIL=me@example.com GIT_COMMITTER_EMAIL=me@example.com git commit -m x",
            web,
        ),
        bash_at("git tag v1", web),
        bash_at("git tag -l", web),
        bash_at("git merge --abort", web),
        bash_at("git -C app commit -m x", ws),
        bash_at("cd app && git commit -m x", ws),
        bash_at("git commit -m x", ws / "demo-hub"),
    ]

    assert decide(events) == [None] * len(events)


def test_passes_commit_when_hub_sets_no_author(ws: Path, decide: Decide) -> None:
    project = {key: value for key, value in HUB_JSON["project"].items() if key != "author_email"}
    (ws / "demo-hub" / "hub.json").write_text(json.dumps(HUB_JSON | {"project": project}))
    app = git_repo(ws / "app", "me/dem-1-x", OTHER)

    assert decide([bash_at("git commit -m x", app)]) == [None]


def test_asks_when_commit_identity_cannot_be_read(ws: Path, decide: Decide) -> None:
    broken = git_repo(ws / "app", "me/dem-1-x", "me@example.com")
    (broken / ".git" / "config").write_text("[core\n\tbare = false\n", encoding="utf-8")
    app = git_repo(ws / "web", "me/dem-1-x", "me@example.com")
    cases = [
        ("git commit -m x", broken, "commit", "git config cannot be read"),
        ("git tag -a v1 -m x", broken, "tag", "git config cannot be read"),
        ('cd "$WORKTREE" && git commit -m x', ws, "commit", "the folder it runs in cannot be told"),
        ("git commit --author=Jose -m x", app, "commit", "--author names no email"),
        (
            'GIT_AUTHOR_EMAIL="$MAIL" git commit -m x',
            app,
            "commit",
            "an email is a shell expansion",
        ),
    ]

    verdicts = decide([bash_at(command, cwd) for command, cwd, _, _ in cases])

    assert verdicts == [
        ("ask", IDENTITY_UNCHECKED_REASON.format(cause, sub)) for _, _, sub, cause in cases
    ]


# The guard's 10 s hook timeout holds a few git reads: each is cut at 2 s, and one command reads
# git at most 4 times (one read per folder and identity variables).
GIT_LIMITS = """
import json
import guard
print(json.dumps([guard.GIT_READ_TIMEOUT, guard.GIT_READS_CAP]))
"""


def test_states_git_read_limits_when_constants_read(
    ws: Path, *, hook_python: str, run_python: Callable[..., Any]
) -> None:
    assert run_python(hook_python, GIT_LIMITS, path=ws / "demo-hub" / HOOKS) == [2, 4]


# X-1: a GitHub MCP tool (`mcp__<server naming github>__<method>`) and `gh api` get the
# attribution rule on their title, body and message fields, the `claude/` rule on their branch,
# head and ref fields, and the protected-branch rule on what they write; and merging a pull
# request is the user's step, however it is asked for.
MERGE_REASON = "merging is the user's step: the user merges every PR; leave `{}` to them"
AGENT_BRANCH_REASON = "branches are me/dem-<N>-<desc>, never claude/..."


def test_denies_github_tool_when_text_holds_attribution(ws: Path, decide: Decide) -> None:
    repo = {"owner": "o", "repo": "r"}
    events = [
        tool_at(
            "mcp__github__create_pull_request",
            ws,
            **repo,
            title="feat: x",
            head="me/dem-1-x",
            base="trunk",
            body=GENERATED,
        ),
        tool_at("mcp__github__update_pull_request", ws, **repo, pullNumber=3, title="x \U0001f916"),
        tool_at(
            "mcp__github__push_files",
            ws,
            **repo,
            branch="me/dem-1-x",
            message=CO_AUTHORED,
            files=[{"path": "a.md", "content": "a"}],
        ),
        tool_at(
            "mcp__github__create_or_update_file",
            ws,
            **repo,
            branch="me/dem-1-x",
            path="a.md",
            content="a",
            message=CO_AUTHORED,
        ),
        tool_at(
            "mcp__plugin_github_github__add_issue_comment",
            ws,
            **repo,
            issue_number=3,
            body=GENERATED,
        ),
    ]

    verdicts = decide(events)

    assert verdicts == [
        ("deny", PR_REASON),
        ("deny", PR_REASON),
        ("deny", COMMIT_REASON),
        ("deny", COMMIT_REASON),
        ("deny", PR_REASON),
    ]


def test_denies_github_tool_when_branch_is_agent_or_protected(ws: Path, decide: Decide) -> None:
    repo = {"owner": "o", "repo": "r"}
    events = [
        tool_at("mcp__github__create_branch", ws, **repo, branch="claude/x", from_branch="trunk"),
        tool_at(
            "mcp__github__create_pull_request", ws, **repo, title="x", head="claude/x", base="trunk"
        ),
        tool_at("mcp__github__push_files", ws, **repo, branch="main", message="feat: x", files=[]),
        tool_at(
            "mcp__github__create_or_update_file",
            ws,
            **repo,
            branch="trunk",
            path="a.md",
            content="a",
            message="feat: x",
        ),
        tool_at(
            "mcp__github__delete_file",
            ws,
            **repo,
            branch="refs/heads/main",
            path="a.md",
            message="chore: x",
        ),
    ]

    verdicts = decide(events)

    assert verdicts == [("deny", AGENT_BRANCH_REASON)] * 2 + [
        ("deny", PUSH_REASON.format(branch)) for branch in ("main", "trunk", "main")
    ]


def test_passes_github_tool_when_clean_or_read_only(ws: Path, decide: Decide) -> None:
    repo = {"owner": "o", "repo": "r"}
    events = [
        tool_at(
            "mcp__github__create_pull_request",
            ws,
            **repo,
            title="feat: x",
            head="me/dem-1-x",
            base="trunk",
            body="Body\n",
        ),
        tool_at("mcp__github__create_branch", ws, **repo, branch="me/dem-1-x", from_branch="main"),
        tool_at(
            "mcp__github__push_files", ws, **repo, branch="me/dem-1-x", message="feat: x", files=[]
        ),
        tool_at("mcp__github__get_file_contents", ws, **repo, path="a.md", ref="main"),
        tool_at("mcp__github__list_commits", ws, **repo, sha="claude/x"),
        tool_at("mcp__github__search_code", ws, query="Generated with Claude Code"),
        tool_at("mcp__github__pull_request_read", ws, **repo, pullNumber=3, method="get"),
        tool_at("mcp__web__fetch", ws, url="https://example.com", body=GENERATED),
    ]

    assert decide(events) == [None] * len(events)


def test_denies_merge_when_agent_merges_pull_request(ws: Path, decide: Decide) -> None:
    repo = {"owner": "o", "repo": "r", "pullNumber": 12}
    mutation = (
        "mutation { enablePullRequestAutoMerge(input: {pullRequestId: 1}) { clientMutationId } }"
    )
    cases = [
        (tool_at("mcp__github__merge_pull_request", ws, **repo), "mcp__github__merge_pull_request"),
        (
            tool_at("mcp__github__enable_pr_auto_merge", ws, **repo),
            "mcp__github__enable_pr_auto_merge",
        ),
        (bash_at("gh pr merge 12", ws), "gh pr merge"),
        (bash_at("gh pr merge --auto --squash 12", ws), "gh pr merge"),
        (bash_at("gh api -X PUT repos/o/r/pulls/12/merge", ws), "gh api repos/o/r/pulls/12/merge"),
        (
            bash_at("gh api --method=PUT /repos/o/r/pulls/12/merge -f merge_method=squash", ws),
            "gh api /repos/o/r/pulls/12/merge",
        ),
        (bash_at(f"gh api graphql -f query='{mutation}'", ws), "gh api graphql"),
        (
            bash_at("gh api -X POST repos/o/r/merges -f base=trunk -f head=me/dem-1-x", ws),
            "gh api repos/o/r/merges",
        ),
    ]

    verdicts = decide([event for event, _ in cases])

    assert verdicts == [("deny", MERGE_REASON.format(shown)) for _, shown in cases]


def test_denies_gh_api_when_field_breaks_change_flow(ws: Path, decide: Decide) -> None:
    put(ws / "body.md", GENERATED)
    contents = "gh api -X PUT repos/o/r/contents/a.md -f content=eA== "
    cases = [
        (
            "gh api -X POST repos/o/r/pulls -f title=x -f body='Body. Generated with Claude Code'",
            PR_REASON,
        ),
        (
            "gh api repos/o/r/pulls -F body=@body.md -f title=x -f head=me/dem-1-x -f base=trunk",
            HELD_BY.format(PR_REASON, "body.md"),
        ),
        (
            contents + "-f message='x\n\nCo-Authored-By: Claude <c@x.io>' -f branch=me/x",
            COMMIT_REASON,
        ),
        (
            "gh api -X POST repos/o/r/pulls -f title=x -f head=claude/x -f base=trunk",
            AGENT_BRANCH_REASON,
        ),
        (
            "gh api -X POST repos/o/r/git/refs -f ref=refs/heads/claude/x -f sha=a1",
            AGENT_BRANCH_REASON,
        ),
        (contents + "-f message=x -f branch=trunk", PUSH_REASON.format("trunk")),
        ("gh api -X PATCH repos/o/r/git/refs/heads/main -f sha=a1", PUSH_REASON.format("main")),
        ("gh api --method DELETE repos/o/r/git/refs/heads/trunk", PUSH_REASON.format("trunk")),
    ]

    verdicts = decide([bash_at(command, ws) for command, _ in cases])

    assert verdicts == [("deny", reason) for _, reason in cases]


def test_passes_gh_api_when_read_or_clean(ws: Path, decide: Decide) -> None:
    commands = [
        "gh api repos/o/r/pulls/12",
        "gh api repos/o/r/pulls/12/merge",
        "gh api -X GET repos/o/r/git/refs/heads/main",
        "gh api repos/o/r/pulls -f title=x -f body='Body' -f head=me/dem-1-x -f base=trunk",
        "gh api repos/o/r/pulls/12/reviews --input review.json",
        "gh api repos/o/r/pulls --jq '.[] | select(.body | test(\"Generated with Claude\"))'",
        "gh api graphql -f query='query { viewer { login } }'",
        "gh pr view 12",
    ]

    assert decide([bash_at(command, ws) for command in commands]) == [None] * len(commands)


# C-13: a push the guard cannot read asks (branch protection is the barrier, this is defence in
# depth): a remote or refspec that is a shell expansion, git push or commit (or gh pr) inside an
# interpreter's or a shell's one-liner, and deleting a remote branch.
PUSH_HIDDEN_REASON = (
    "a `git push` remote or refspec is a shell expansion the guard cannot read; confirm the branch"
    " it pushes"
)
INTERPRETER_REASON = "`{}` runs git push or commit, or gh pr, out of the guard's sight; confirm"
PUSH_DELETE_REASON = "`git push {}` deletes a remote branch; confirm"


def test_asks_when_push_hides_behind_expansion_or_interpreter(ws: Path, decide: Decide) -> None:
    cases = [
        ("x=main; git push origin $x", PUSH_HIDDEN_REASON),
        ('git push -u origin "$BRANCH"', PUSH_HIDDEN_REASON),
        ("git push origin $(git branch --show-current)", PUSH_HIDDEN_REASON),
        ("git push origin `cat branch.txt`", PUSH_HIDDEN_REASON),
        ("git push $REMOTE me/dem-1-x", PUSH_HIDDEN_REASON),
        (
            "python3 -c \"subprocess.run(['git','push','origin','main'])\"",
            INTERPRETER_REASON.format("python3"),
        ),
        (
            "node -e \"require('child_process').execSync('gh pr create --fill')\"",
            INTERPRETER_REASON.format("node"),
        ),
        ("bash -c 'git commit -m x'", INTERPRETER_REASON.format("bash")),
        ('eval "git push origin $B"', INTERPRETER_REASON.format("eval")),
        (
            "uv run python -c \"import os; os.system('git push')\"",
            INTERPRETER_REASON.format("python"),
        ),
    ]

    verdicts = decide([bash_at(command, ws) for command, _ in cases])

    assert verdicts == [("ask", reason) for _, reason in cases]


def test_asks_when_push_deletes_remote_branch(ws: Path, decide: Decide) -> None:
    cases = [
        ("git push origin :roquettejh/agh-1-x", ":roquettejh/agh-1-x"),
        ("git push --delete origin me/dem-1-x", "--delete"),
        ("git push -d origin me/dem-1-x", "-d"),
        ("git push origin --delete me/dem-1-x", "--delete"),
    ]

    verdicts = decide([bash_at(command, ws) for command, _ in cases])

    assert verdicts == [("ask", PUSH_DELETE_REASON.format(shown)) for _, shown in cases]


def test_passes_when_push_target_literal_or_interpreter_harmless(ws: Path, decide: Decide) -> None:
    app = git_repo(ws / "app", "me/dem-1-x")
    commands = [
        "git push -u origin roquettejh/agh-1-x",
        "git push origin me/dem-1-x:me/dem-1-x",
        "echo $HOME && git push -u origin me/dem-1-x",
        'python3 -c "print(1)"',
        "python3 -m pytest -q",
        "bash scripts/check.sh",
        "git commit -m 'run bash' -m 'then python'",
    ]

    assert decide([bash_at(command, app) for command in commands]) == [None] * len(commands)
