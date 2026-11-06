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
