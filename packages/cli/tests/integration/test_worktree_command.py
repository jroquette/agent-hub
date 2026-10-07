"""``hub worktree``: isolated worktrees for one task in every repo of the hub (AC-15.1 to AC-15.4).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``): the hub at
``ws/hub`` with default branch ``trunk``, ``demo-api`` and ``demo-web`` cloned next to it from
local bare origins, each origin one commit ahead of its clone, so a skipped fetch shows.

This module re-expresses hub ``tests/test_worktree.py`` at hub commit ``2bf5d20``. Its four cases:
``test_creates_one_worktree_per_repo_and_removes_them`` is
``test_creates_worktrees_from_fetched_base_when_name_valid``, ``TestScripts`` and ``TestRemove``;
``test_only_one_repo`` is ``test_touches_one_repo_when_only_given``;
``test_rejects_unknown_repo_and_bad_name`` is ``TestUsage`` (unknown repo, bad name, no
arguments), now exit 2 (spec § Port differences); ``test_rejects_name_without_issue_id`` is
``test_refuses_name_when_shape_wrong`` (``auth``, ``dem-auth``, ``abc-1-auth``, ``dem-1auth``).
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import worktree_command
from agent_hub.core.testing.builders import a_conventions_document

# The conftest's in-process run (tests cannot import a conftest in importlib mode).
type CommandRunner = Callable[..., Result]
type Workspace = Any

REPOS = ("demo-api", "demo-web")
NAME = "dem-7-x"
BRANCH = "jdoe/dem-7-x"
SHAPE = "name must be the issue, dem-<n>[-<desc>] (e.g. dem-7-collector)"
# The characters of the box Rich may draw around a usage error.
BOX_CHARACTERS = "│╭╮╰╯─"
SETUP = "scripts/worktree-setup.sh"
TEARDOWN = "scripts/worktree-teardown.sh"
EXECUTABLE = 0o755
PLAIN = 0o644


def logging_script(log: Path, word: str, *, exit_code: int = 0) -> bytes:
    """A POSIX ``sh`` script: logs ``$#``, ``$1``, its cwd and ``GIT_DIR`` to ``log``, says
    ``word $1``, then exits."""
    return (
        "#!/bin/sh\n"
        f'printf \'%s %s %s %s\\n\' "$#" "$1" "$(pwd)" "${{GIT_DIR-unset}}" >> "{log}"\n'
        f'echo "{word} $1"\n'
        'test -d "$1" && echo "present"\n'
        f"exit {exit_code}\n"
    ).encode()


# The six variables every worktree script gets (AGH-59), as literals, then two caller variables.
SCRIPT_VARIABLES = (
    "HUB_WORKTREE_NAME",
    "HUB_WORKTREE_BRANCH",
    "HUB_REPO_DIR",
    "HUB_HUB_DIR",
    "HUB_WORKTREE_SLOT",
    "HUB_PORT_OFFSET",
)
LOGGED_VARIABLES = (*SCRIPT_VARIABLES, "MARKER", "HUB_OTHER")


def variable_script(log: Path, env_log: Path, word: str) -> bytes:
    """``logging_script``, which also appends ``<NAME>=<value>`` (``unset`` when unset) to
    ``env_log`` for each of ``LOGGED_VARIABLES``, in that order."""
    body = logging_script(log, word).removesuffix(b"exit 0\n")
    lines = "".join(
        f'printf \'%s=%s\\n\' {name} "${{{name}-unset}}" >> "{env_log}"\n'
        for name in LOGGED_VARIABLES
    )
    return body + lines.encode() + b"exit 0\n"


def expected_variables(
    workspace: Workspace,
    repo: str,
    branch: str,
    *,
    slot: str,
    offset: str,
    extra: dict[str, str],
) -> str:
    """The env log of one script of task ``NAME`` in ``repo``: the six, then ``extra``'s values."""
    values = {
        "HUB_WORKTREE_NAME": NAME,
        "HUB_WORKTREE_BRANCH": branch,
        "HUB_REPO_DIR": os.path.realpath(workspace.ws / repo),
        "HUB_HUB_DIR": os.path.realpath(workspace.hub),
        "HUB_WORKTREE_SLOT": slot,
        "HUB_PORT_OFFSET": offset,
        **extra,
    }
    return "".join(f"{name}={values[name]}\n" for name in LOGGED_VARIABLES)


def assert_refused(result: Result, message: str) -> None:
    """Exit 2 with ``message`` as one line of the usage error on stderr, nothing on stdout."""
    assert result.exit_code == 2, result.output
    assert result.stdout == ""
    shown = unstyle(result.stderr)
    assert "Usage: hub worktree" in shown
    texts = [line.strip(BOX_CHARACTERS + " ") for line in shown.splitlines()]
    assert [text for text in texts if message in text] == [message], shown


def assert_untouched(workspace: Workspace) -> None:
    """Nothing fetched (no ``FETCH_HEAD``, ``origin/trunk`` as cloned) and nothing created."""
    for repo in REPOS:
        checkout = workspace.ws / repo
        assert not (checkout / ".git" / "FETCH_HEAD").exists()
        assert workspace.git(checkout, "rev-parse", "origin/trunk") == workspace.git(
            checkout, "rev-parse", "HEAD"
        )
        assert not (checkout / ".claude").exists()


def script_logged(worktree: Path) -> str:
    """The log line of one run: one argument, the worktree, run in it, no ``GIT_DIR``."""
    return f"1 {worktree} {worktree} unset\n"


def setup_failed(worktree: Path, how: str) -> str:
    return (
        f"hub worktree: demo-api: {SETUP} {how}; the worktree is kept: run the script again"
        f" ({worktree / SETUP} {worktree}) or remove it with"
        f" ./hub worktree --remove {NAME} --only demo-api\n"
    )


def summary(name: str, repos: str, remove: str) -> list[str]:
    return ["", f"task     : {name} (branch jdoe/{name})", f"repos    : {repos}", remove]


class TestUsage:
    def test_lists_name_only_and_remove_when_help_requested(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", "--help", env={"COLUMNS": "120"})

        assert result.exit_code == 0
        shown = unstyle(result.stdout)
        for text in ("NAME", "--only", "REPO", "--remove"):
            assert text in shown

    def test_refuses_when_name_missing(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree")

        assert_refused(result, "Missing argument 'NAME'.")
        assert_untouched(demo_workspace)

    def test_refuses_when_option_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--nope")

        assert_refused(result, "No such option: --nope")
        assert_untouched(demo_workspace)

    @pytest.mark.parametrize(
        "name",
        ["DEM-7", "dem7", "xyz-7", "dem-7/x", "auth", "dem-auth", "abc-1-auth", "dem-1auth"],
    )
    def test_refuses_name_when_shape_wrong(
        self, demo_workspace: Workspace, run_command: CommandRunner, name: str
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", name)

        assert_refused(result, SHAPE)
        assert_untouched(demo_workspace)

    def test_refuses_name_when_team_not_listed(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_teams("APP", "OPS")

        # A usage message stays on one line of Rich's box.
        result = run_command(demo_workspace.hub, "worktree", "xyz-1-x", env={"COLUMNS": "200"})

        assert_refused(
            result,
            "name must be the issue, <team>-<n>[-<desc>] in lowercase (e.g. app-7-collector);"
            " use one of: APP, OPS",
        )
        assert_untouched(demo_workspace)

    def test_refuses_name_when_ref_format_refused(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", "dem-7-a..b")

        assert_refused(
            result,
            "git refuses the branch name jdoe/dem-7-a..b; use a name like dem-7-collector",
        )
        assert_untouched(demo_workspace)

    def test_refuses_when_only_unknown(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "nope")

        assert_refused(result, "unknown repo in --only: nope; use one of: demo-api demo-web")
        assert_untouched(demo_workspace)

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.ws, "worktree", NAME)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{demo_workspace.ws}: not a hub: no hub.json in this folder"
            " (hub worktree runs in the hub folder or through ./hub)\n"
        )
        assert_untouched(demo_workspace)

    def test_prints_reader_lines_when_hub_json_invalid(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        (demo_workspace.hub / "hub.json").write_bytes(b"{}\n")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        lines = result.stderr.splitlines()
        assert lines
        assert all(line.startswith("hub.json: ") for line in lines), lines
        assert_untouched(demo_workspace)


class TestCreate:
    def test_creates_worktrees_from_fetched_base_when_name_valid(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        advanced = {repo: demo_workspace.origin_head(repo) for repo in REPOS}

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            *(
                f"created  {demo_workspace.worktree(repo, NAME)} ({BRANCH} from origin/trunk)"
                for repo in REPOS
            ),
            *summary(NAME, "demo-api demo-web", f"remove   : ./hub worktree --remove {NAME}"),
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == advanced[repo]

    def test_prints_exists_without_fetch_when_rerun(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0
        heads = {
            repo: demo_workspace.git(demo_workspace.worktree(repo, NAME), "rev-parse", "HEAD")
            for repo in REPOS
        }
        fetched = {
            repo: (demo_workspace.ws / repo / ".git" / "FETCH_HEAD").stat().st_mtime_ns
            for repo in REPOS
        }
        for repo in REPOS:
            demo_workspace.advance(repo)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            *(f"exists   {demo_workspace.worktree(repo, NAME)}" for repo in REPOS),
            *summary(NAME, "demo-api demo-web", f"remove   : ./hub worktree --remove {NAME}"),
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == heads[repo]
            fetch_head = demo_workspace.ws / repo / ".git" / "FETCH_HEAD"
            assert fetch_head.stat().st_mtime_ns == fetched[repo]

    def test_checks_out_existing_branch_when_branch_present(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        checkout = demo_workspace.ws / "demo-api"
        demo_workspace.git(checkout, "branch", BRANCH)
        kept = demo_workspace.git(checkout, "rev-parse", BRANCH)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        worktree = demo_workspace.worktree("demo-api", NAME)
        assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
        assert demo_workspace.git(worktree, "rev-parse", "HEAD") == kept
        assert kept != demo_workspace.origin_head("demo-api")

    def test_creates_worktrees_when_name_has_other_team(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_teams("APP", "OPS")
        name = "ops-12-x"

        result = run_command(demo_workspace.hub, "worktree", name)

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            *(
                f"created  {demo_workspace.worktree(repo, name)} (jdoe/{name} from origin/trunk)"
                for repo in REPOS
            ),
            *summary(name, "demo-api demo-web", f"remove   : ./hub worktree --remove {name}"),
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, name)
            assert demo_workspace.git(worktree, "branch", "--show-current") == f"jdoe/{name}"

    def test_touches_one_repo_when_only_given(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"created  {demo_workspace.worktree('demo-api', NAME)} ({BRANCH} from origin/trunk)",
            *summary(
                NAME, "demo-api", f"remove   : ./hub worktree --remove {NAME} --only demo-api"
            ),
        ]
        web = demo_workspace.ws / "demo-web"
        assert not (web / ".git" / "FETCH_HEAD").exists()
        assert not (web / ".claude").exists()

    def test_starts_each_repo_from_its_branch_when_repo_sets_one(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_repo_branch("demo-api", "master")
        bases = {"demo-api": "master", "demo-web": "trunk"}

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        assert result.stdout.splitlines() == [
            *(
                f"created  {demo_workspace.worktree(repo, NAME)} ({BRANCH} from origin/{base})"
                for repo, base in bases.items()
            ),
            *summary(NAME, "demo-api demo-web", f"remove   : ./hub worktree --remove {NAME}"),
        ]
        for repo, base in bases.items():
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == (
                demo_workspace.origin_head(repo, base)
            )

    def test_starts_only_repo_from_its_branch_when_only_given(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_repo_branch("demo-api", "master")

        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"created  {demo_workspace.worktree('demo-api', NAME)} ({BRANCH} from origin/master)",
            *summary(
                NAME, "demo-api", f"remove   : ./hub worktree --remove {NAME} --only demo-api"
            ),
        ]
        worktree = demo_workspace.worktree("demo-api", NAME)
        assert demo_workspace.git(worktree, "rev-parse", "HEAD") == (
            demo_workspace.origin_head("demo-api", "master")
        )
        assert not (demo_workspace.ws / "demo-web" / ".claude").exists()

    def test_names_repo_when_its_branch_missing_on_origin(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        hub_json = demo_workspace.hub / "hub.json"
        document = json.loads(hub_json.read_text())
        document["repos"][0]["default_branch"] = "master"
        hub_json.write_text(json.dumps(document, indent=2) + "\n")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.startswith("hub worktree: demo-api: could not add the worktree: ")
        assert "origin/master" in result.stderr
        assert len(result.stderr.splitlines()) == 1
        assert not demo_workspace.worktree("demo-api", NAME).exists()
        assert not (demo_workspace.ws / "demo-web" / ".claude").exists()


class TestDemoWorkspace:
    def test_renames_origin_branch_when_repo_branch_used(self, demo_workspace: Workspace) -> None:
        head = demo_workspace.origin_head("demo-api")
        clone = demo_workspace.ws / "demo-api"

        demo_workspace.use_repo_branch("demo-api", "master")

        origin = demo_workspace.origin("demo-api")
        assert demo_workspace.git(origin, "for-each-ref", "--format=%(refname)") == (
            "refs/heads/master"
        )
        assert demo_workspace.origin_head("demo-api", "master") == head
        assert demo_workspace.git(clone, "rev-parse", "origin/master") == head
        remote = demo_workspace.git(clone, "for-each-ref", "--format=%(refname)", "refs/remotes")
        assert remote.splitlines() == ["refs/remotes/origin/HEAD", "refs/remotes/origin/master"]
        repos = json.loads((demo_workspace.hub / "hub.json").read_text())["repos"]
        assert [repo.get("default_branch") for repo in repos] == ["master", None]

    def test_logs_and_runs_git_when_traced_git_used(
        self, demo_workspace: Workspace, traced_git: Any
    ) -> None:
        clone = demo_workspace.ws / "demo-api"

        completed = subprocess.run(
            ["git", "rev-parse", "--git-dir"],  # noqa: S607 - the traced git found on PATH
            cwd=clone,
            check=True,
            capture_output=True,
            text=True,
        )

        assert completed.stdout == ".git\n"
        assert traced_git.calls() == [(os.path.realpath(clone), "rev-parse --git-dir")]


class TestScripts:
    def test_runs_setup_once_when_executable(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("GIT_DIR", str(tmp_path / "decoy.git"))
        log = tmp_path / "setup.log"
        demo_workspace.advance("demo-api", {SETUP: (logging_script(log, "setup"), EXECUTABLE)})
        worktree = demo_workspace.worktree("demo-api", NAME)

        first = run_command(demo_workspace.hub, "worktree", NAME)
        again = run_command(demo_workspace.hub, "worktree", NAME)

        assert first.exit_code == 0, first.output
        assert first.stdout.splitlines()[:3] == [
            f"created  {worktree} ({BRANCH} from origin/trunk)",
            f"  demo-api: setup {worktree}",
            "  demo-api: present",
        ]
        assert again.exit_code == 0, again.output
        assert log.read_text() == script_logged(worktree)

    def test_skips_setup_when_not_executable_or_exists(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        log = tmp_path / "setup.log"
        demo_workspace.advance("demo-api", {SETUP: (logging_script(log, "setup"), PLAIN)})

        first = run_command(demo_workspace.hub, "worktree", NAME)
        (demo_workspace.worktree("demo-api", NAME) / SETUP).chmod(EXECUTABLE)
        again = run_command(demo_workspace.hub, "worktree", NAME)

        assert first.exit_code == 0, first.output
        assert again.exit_code == 0, again.output
        assert "demo-api: " not in first.stdout + again.stdout
        assert not log.exists()

    def test_stops_when_setup_fails(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        log = tmp_path / "setup.log"
        script = logging_script(log, "setup", exit_code=3)
        demo_workspace.advance("demo-api", {SETUP: (script, EXECUTABLE)})
        worktree = demo_workspace.worktree("demo-api", NAME)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stderr == setup_failed(worktree, "exited 3")
        assert result.stdout.splitlines() == [
            f"created  {worktree} ({BRANCH} from origin/trunk)",
            f"  demo-api: setup {worktree}",
            "  demo-api: present",
        ]
        assert worktree.is_dir()
        web = demo_workspace.ws / "demo-web"
        assert not (web / ".git" / "FETCH_HEAD").exists()
        assert not (web / ".claude").exists()

    def test_names_signal_when_setup_killed(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.advance("demo-api", {SETUP: (b"#!/bin/sh\nkill -KILL $$\n", EXECUTABLE)})
        worktree = demo_workspace.worktree("demo-api", NAME)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stderr == setup_failed(worktree, "was killed by signal 9")
        assert worktree.is_dir()

    def test_strips_line_ends_when_script_prints_crlf(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        script = b"#!/bin/sh\nprintf 'one\\r\\ntwo\\r\\n'\n"
        demo_workspace.advance("demo-api", {SETUP: (script, EXECUTABLE)})

        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api")

        assert result.exit_code == 0, result.output
        # Result.stdout turns "\r\n" into "\n", so the bytes are checked.
        assert result.stdout_bytes.split(b"\n")[1:3] == [b"  demo-api: one", b"  demo-api: two"]
        assert b"\r" not in result.stdout_bytes


class TestRemove:
    def test_runs_teardown_then_removes_when_remove_given(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        log = tmp_path / "teardown.log"
        teardown = logging_script(log, "teardown")
        demo_workspace.advance("demo-api", {TEARDOWN: (teardown, EXECUTABLE)})
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0
        api, web = (demo_workspace.worktree(repo, NAME) for repo in REPOS)

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"  demo-api: teardown {api}",
            "  demo-api: present",
            f"removed  {api}",
            f"removed  {web}",
        ]
        assert log.read_text() == script_logged(api)
        assert not api.exists()
        assert not web.exists()

    def test_removes_nothing_when_teardown_fails(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        teardown = logging_script(tmp_path / "teardown.log", "teardown", exit_code=4)
        demo_workspace.advance("demo-api", {TEARDOWN: (teardown, EXECUTABLE)})
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 1
        assert result.stderr == f"hub worktree: demo-api: {TEARDOWN} exited 4\n"
        assert "removed" not in result.stdout
        for repo in REPOS:
            assert demo_workspace.worktree(repo, NAME).is_dir()

    def test_skips_absent_worktree_when_removing(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        assert (
            run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-web").exit_code == 0
        )

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout == f"removed  {demo_workspace.worktree('demo-web', NAME)}\n"
        assert result.stderr == ""

    def test_keeps_worktree_when_dirty_remove_refused(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        log = tmp_path / "teardown.log"
        demo_workspace.advance(
            "demo-api", {TEARDOWN: (logging_script(log, "teardown"), EXECUTABLE)}
        )
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0
        api = demo_workspace.worktree("demo-api", NAME)
        (api / "draft.txt").write_bytes(b"work in progress\n")

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == (
            f"hub worktree: demo-api: could not remove {api}: it has modified or untracked files\n"
        )
        # The teardown never ran on a worktree that stays.
        assert not log.exists()
        assert (api / "draft.txt").is_file()
        assert demo_workspace.worktree("demo-web", NAME).is_dir()

    def test_keeps_branch_when_removed(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 0, result.output
        for repo in REPOS:
            checkout = demo_workspace.ws / repo
            demo_workspace.git(checkout, "show-ref", "--verify", "-q", f"refs/heads/{BRANCH}")


class TestRepoProblems:
    def test_exits_one_when_repo_not_cloned(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        web = demo_workspace.ws / "demo-web"
        shutil.rmtree(web / ".git")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stderr == (
            f"hub worktree: {web} is not a git checkout; clone it next to the hub\n"
        )
        assert result.stdout == (
            f"created  {demo_workspace.worktree('demo-api', NAME)} ({BRANCH} from origin/trunk)\n"
        )
        assert demo_workspace.worktree("demo-api", NAME).is_dir()

    def test_exits_one_when_fetch_fails(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        shutil.rmtree(demo_workspace.origin("demo-api"))

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr.startswith("hub worktree: demo-api: could not fetch origin: ")
        assert result.stderr.endswith("; check the network and the remote\n")
        assert len(result.stderr.splitlines()) == 1
        assert not (demo_workspace.ws / "demo-api" / ".claude").exists()

    def test_exits_one_when_git_cannot_run(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        real_run_child = worktree_command.run_child

        def refusing_fetch(argv: list[str], **options: Any) -> Any:
            if argv[1:2] == ["fetch"]:
                raise PermissionError(13, "Permission denied")
            return real_run_child(argv, **options)

        monkeypatch.setattr(worktree_command, "run_child", refusing_fetch)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == "hub worktree: demo-api: git could not run: Permission denied\n"
        assert not (demo_workspace.ws / "demo-api" / ".claude").exists()

    def test_refuses_task_folder_when_it_is_not_a_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        folder = demo_workspace.worktree("demo-api", NAME)
        folder.mkdir(parents=True)

        result = run_command(demo_workspace.hub, "worktree", NAME, env={"COLUMNS": "200"})

        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        assert result.stderr == f"hub worktree: demo-api: {folder} is not a worktree; remove it\n"
        assert list(folder.iterdir()) == []
        for repo in REPOS:
            checkout = demo_workspace.ws / repo
            assert not (checkout / ".git" / "FETCH_HEAD").exists()
            assert demo_workspace.git(checkout, "branch", "--list", BRANCH) == ""
        assert not (demo_workspace.ws / "demo-web" / ".claude").exists()

    def test_uses_main_checkout_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        hub = demo_workspace.hub
        demo_workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        demo_workspace.git(hub, "add", "-A")
        demo_workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        demo_workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        # Read from the worktree, this hub.json would exit 1: only the main checkout's is read.
        (hub_worktree / "hub.json").write_bytes(b"{}\n")

        result = run_command(
            demo_workspace.base, "worktree", NAME, env={"AGENT_HUB_ROOT": str(hub_worktree)}
        )

        assert result.exit_code == 0, result.output
        for repo in REPOS:
            assert demo_workspace.worktree(repo, NAME).is_dir()
        assert not (hub_worktree.parent / "demo-api").exists()

    def test_ignores_git_location_when_variables_set(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        decoy = demo_workspace.base / "decoy"
        decoy.mkdir()
        demo_workspace.git(decoy, "init", "-q")
        monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
        monkeypatch.setenv("GIT_WORK_TREE", str(decoy))
        monkeypatch.setenv("GIT_COMMON_DIR", str(decoy / ".git"))
        monkeypatch.setenv("GIT_INDEX_FILE", str(decoy / ".git" / "index"))

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        # The workspace's own git runs with its own environment, without these variables.
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
        assert not (decoy / ".git" / "worktrees").exists()
        assert demo_workspace.git(decoy, "branch", "--list") == ""


LOCAL_PREFIX = "me/"
LOCAL_BRANCH = f"me/{NAME}"
HUB_ONLY = (
    "hub.local.json: guard: set only in hub.json; hub.local.json holds project.branch_prefix,"
    " author_name, author_email and tracker.transport"
)


# The four lines of the no-prefix usage error, as shown once Rich's box is stripped.
NO_PREFIX_LINES = (
    "no branch prefix for this developer; set one of:",
    "hub.local.json → project.branch_prefix",
    "hub.json → project.branch_prefix",
    "git config user.email in the hub (its local part plus /)",
)
TEAM_BRANCH = f"jane/{NAME}"


def local_prefix(prefix: str = LOCAL_PREFIX) -> str:
    return json.dumps({"project": {"branch_prefix": prefix}})


def task_branches(workspace: Workspace, repo: str) -> str:
    """The names of ``repo``'s branches that end with the task's name, one per line."""
    return workspace.git(
        workspace.ws / repo, "branch", "--list", "--format=%(refname:short)", f"*{NAME}"
    )


def git_identity_reads(traced_git: Any) -> list[tuple[str, str]]:
    """``(cwd, arguments)`` of each git call of a run that reads a ``user.*`` config key."""
    return [
        (cwd, arguments)
        for cwd, arguments in traced_git.calls()
        if "config" in arguments and "user." in arguments
    ]


class TestIdentity:
    @pytest.fixture(autouse=True)
    def wide_terminal(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Each line of a usage message stays on one line of Rich's box.
        monkeypatch.setenv("COLUMNS", "200")

    def test_branches_with_local_prefix_when_local_file_sets_one(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.write_local(local_prefix())

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            *(
                f"created  {demo_workspace.worktree(repo, NAME)} ({LOCAL_BRANCH} from origin/trunk)"
                for repo in REPOS
            ),
            "",
            f"task     : {NAME} (branch {LOCAL_BRANCH})",
            "repos    : demo-api demo-web",
            f"remove   : ./hub worktree --remove {NAME}",
        ]
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == LOCAL_BRANCH

    @pytest.mark.parametrize(
        ("local", "branch"), [(None, BRANCH), (local_prefix(), LOCAL_BRANCH)], ids=["hub", "local"]
    )
    def test_reads_no_git_config_when_files_set_prefix(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        traced_git: Any,
        *,
        local: str | None,
        branch: str,
    ) -> None:
        if local is not None:
            demo_workspace.write_local(local)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert f"task     : {NAME} (branch {branch})" in result.stdout.splitlines()
        assert traced_git.calls(), "the traced git ran no call"
        assert git_identity_reads(traced_git) == []

    @pytest.mark.parametrize(
        ("document", "line"),
        [("[]", "hub.local.json: $: must be a JSON object"), ('{"guard": {}}', HUB_ONLY)],
        ids=["array", "hub-only-key"],
    )
    @pytest.mark.parametrize("remove", [False, True], ids=["create", "remove"])
    def test_refuses_with_local_lines_when_local_file_invalid(
        self,
        demo_workspace: Workspace,
        run_command: CommandRunner,
        *,
        document: str,
        line: str,
        remove: bool,
    ) -> None:
        demo_workspace.write_local(document)

        result = run_command(demo_workspace.hub, "worktree", NAME, *(["--remove"] * remove))

        assert_refused(result, line)
        assert_untouched(demo_workspace)

    def test_reads_main_checkout_local_file_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        hub = demo_workspace.hub
        demo_workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        demo_workspace.git(hub, "add", "-A")
        demo_workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        demo_workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))
        demo_workspace.write_local(local_prefix())
        # Read from the worktree, this file would refuse the run: only the main checkout's is read.
        (hub_worktree / "hub.local.json").write_text("[]", encoding="utf-8")

        result = run_command(
            demo_workspace.base, "worktree", NAME, env={"AGENT_HUB_ROOT": str(hub_worktree)}
        )

        assert result.exit_code == 0, result.output
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == LOCAL_BRANCH

    def test_branches_with_git_email_prefix_when_team_hub_has_no_file_prefix(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert f"task     : {NAME} (branch {TEAM_BRANCH})" in result.stdout.splitlines()
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == TEAM_BRANCH

    def test_refuses_without_writing_when_no_source_sets_prefix(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.drop_identity()

        result = run_command(demo_workspace.hub, "worktree", NAME)

        for line in NO_PREFIX_LINES:
            assert_refused(result, line)
        assert_untouched(demo_workspace)
        for repo in REPOS:
            assert task_branches(demo_workspace, repo) == ""

    def test_refuses_remove_without_deleting_when_no_source_sets_prefix(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.write_local(local_prefix())
        created = run_command(demo_workspace.hub, "worktree", NAME)
        assert created.exit_code == 0, created.output
        (demo_workspace.hub / "hub.local.json").unlink()
        demo_workspace.drop_identity()

        result = run_command(demo_workspace.hub, "worktree", NAME, "--remove")

        for line in NO_PREFIX_LINES:
            assert_refused(result, line)
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert worktree.is_dir()
            listed = demo_workspace.git(demo_workspace.ws / repo, "worktree", "list", "--porcelain")
            assert f"worktree {os.path.realpath(worktree)}" in listed.splitlines()
            assert task_branches(demo_workspace, repo) == LOCAL_BRANCH

    def test_names_invalid_email_when_derived_prefix_invalid(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "j+x@example.com")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        for line in (*NO_PREFIX_LINES, 'git\'s user.email gives "j+x", not a valid prefix'):
            assert_refused(result, line)
        assert_untouched(demo_workspace)

    def test_reads_git_email_once_when_team_hub_has_no_file_prefix(
        self, demo_workspace: Workspace, run_command: CommandRunner, traced_git: Any
    ) -> None:
        demo_workspace.drop_identity()
        demo_workspace.git_identity("Jane Roe", "jane@example.com")

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert git_identity_reads(traced_git) == [
            (os.path.realpath(demo_workspace.hub), "config --get user.email")
        ]


# The mixed hub (plan E1): the project's three patterns, demo-api's own branch, demo-web none.
MIXED_HUB = a_conventions_document()
PROJECT_CONVENTIONS = MIXED_HUB["project"]["conventions"]
API_CONVENTIONS = next(
    repo["conventions"] for repo in MIXED_HUB["repos"] if repo["dir"] == "demo-api"
)


def use_mixed_hub(workspace: Workspace) -> None:
    workspace.use_conventions(project=PROJECT_CONVENTIONS, repos={"demo-api": API_CONVENTIONS})


class TestConventions:
    def test_creates_branch_per_repo_when_hub_sets_conventions(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)
        branches = {"demo-api": "feature/dem-7/x", "demo-web": "jdoe/DEM-7-x"}

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stderr == ""
        assert result.stdout.splitlines()[:2] == [
            f"created  {demo_workspace.worktree(repo, NAME)} ({branch} from origin/trunk)"
            for repo, branch in branches.items()
        ]
        for repo, branch in branches.items():
            worktree = demo_workspace.worktree(repo, NAME)
            assert worktree == demo_workspace.ws / repo / ".claude" / "worktrees" / NAME
            assert demo_workspace.git(worktree, "branch", "--show-current") == branch

    def test_drops_separator_when_name_has_no_desc(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)
        branches = {"demo-api": "feature/dem-7", "demo-web": "jdoe/DEM-7"}

        result = run_command(demo_workspace.hub, "worktree", "dem-7")

        assert result.exit_code == 0, result.output
        for repo, branch in branches.items():
            worktree = demo_workspace.worktree(repo, "dem-7")
            assert demo_workspace.git(worktree, "branch", "--show-current") == branch

    def test_keeps_branches_when_conventions_worktrees_removed(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)
        branches = {"demo-api": "feature/dem-7/x", "demo-web": "jdoe/DEM-7-x"}
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0

        result = run_command(demo_workspace.hub, "worktree", "--remove", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"removed  {demo_workspace.worktree(repo, NAME)}" for repo in REPOS
        ]
        for repo, branch in branches.items():
            assert not demo_workspace.worktree(repo, NAME).exists()
            checkout = demo_workspace.ws / repo
            demo_workspace.git(checkout, "show-ref", "--verify", "-q", f"refs/heads/{branch}")

    def test_lists_each_branch_in_summary_when_branches_differ(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)

        result = run_command(demo_workspace.hub, "worktree", NAME)

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[2:] == [
            "",
            f"task     : {NAME}",
            "branch   : demo-api feature/dem-7/x",
            "branch   : demo-web jdoe/DEM-7-x",
            "repos    : demo-api demo-web",
            f"remove   : ./hub worktree --remove {NAME}",
        ]

    def test_keeps_one_task_line_when_touched_branches_agree(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)

        result = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-web")

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"created  {demo_workspace.worktree('demo-web', NAME)}"
            " (jdoe/DEM-7-x from origin/trunk)",
            "",
            f"task     : {NAME} (branch jdoe/DEM-7-x)",
            "repos    : demo-web",
            f"remove   : ./hub worktree --remove {NAME} --only demo-web",
        ]

    def test_refuses_name_when_git_rejects_configured_branch(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)

        # A usage message stays on one line of Rich's box.
        result = run_command(demo_workspace.hub, "worktree", "dem-7-a..b", env={"COLUMNS": "200"})

        assert_refused(
            result,
            "git refuses the branch name feature/dem-7/a..b; use a name like dem-7-collector",
        )
        assert_untouched(demo_workspace)

    def test_checks_only_touched_branches_when_only_given(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_conventions(
            project={"branch": "{prefix}{issue_lower}"}, repos={"demo-api": API_CONVENTIONS}
        )

        result = run_command(demo_workspace.hub, "worktree", "dem-7-a..b", "--only", "demo-web")

        assert result.exit_code == 0, result.output
        worktree = demo_workspace.worktree("demo-web", "dem-7-a..b")
        assert demo_workspace.git(worktree, "branch", "--show-current") == "jdoe/dem-7"

    def test_names_unknown_repo_first_when_name_and_only_both_wrong(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        use_mixed_hub(demo_workspace)

        result = run_command(demo_workspace.hub, "worktree", "dem-7-a..b", "--only", "nope")

        assert_refused(result, "unknown repo in --only: nope; use one of: demo-api demo-web")
        assert_untouched(demo_workspace)

    def test_refuses_second_worktree_when_issue_branch_checked_out(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        # E22: a branch without {slug} names one branch per issue, whatever the <desc>.
        demo_workspace.use_conventions(project={"branch": "{prefix}{issue_lower}"})
        assert run_command(demo_workspace.hub, "worktree", "dem-7-a").exit_code == 0
        first = os.path.realpath(demo_workspace.worktree("demo-api", "dem-7-a"))

        result = run_command(demo_workspace.hub, "worktree", "dem-7-b", env={"COLUMNS": "200"})

        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        assert result.stderr == (
            f"hub worktree: demo-api: jdoe/dem-7 is already checked out in {first}\n"
        )
        for repo in REPOS:
            assert not demo_workspace.worktree(repo, "dem-7-b").exists()
            worktree = demo_workspace.worktree(repo, "dem-7-a")
            assert demo_workspace.git(worktree, "branch", "--show-current") == "jdoe/dem-7"

    def test_refuses_rerun_when_conventions_changed_worktree_branch(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        assert run_command(demo_workspace.hub, "worktree", NAME).exit_code == 0
        heads = {
            repo: demo_workspace.git(demo_workspace.worktree(repo, NAME), "rev-parse", "HEAD")
            for repo in REPOS
        }
        use_mixed_hub(demo_workspace)

        result = run_command(demo_workspace.hub, "worktree", NAME, env={"COLUMNS": "200"})

        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        assert result.stderr == (
            f"hub worktree: demo-api: {demo_workspace.worktree('demo-api', NAME)}"
            f" is on {BRANCH}, not feature/dem-7/x\n"
        )
        for repo in REPOS:
            worktree = demo_workspace.worktree(repo, NAME)
            assert demo_workspace.git(worktree, "branch", "--show-current") == BRANCH
            assert demo_workspace.git(worktree, "rev-parse", "HEAD") == heads[repo]
            checkout = demo_workspace.ws / repo
            assert demo_workspace.git(checkout, "branch", "--list", "feature/*", "jdoe/DEM-*") == ""

    def test_creates_nothing_when_later_repo_branch_checked_out(
        self, demo_workspace: Workspace, run_command: CommandRunner
    ) -> None:
        demo_workspace.use_conventions(project={"branch": "{prefix}{issue_lower}"})
        created = run_command(demo_workspace.hub, "worktree", "dem-7-a", "--only", "demo-web")
        assert created.exit_code == 0, created.output
        first = os.path.realpath(demo_workspace.worktree("demo-web", "dem-7-a"))

        result = run_command(demo_workspace.hub, "worktree", "dem-7-b", env={"COLUMNS": "200"})

        assert result.exit_code == 1, result.output
        assert result.stdout == ""
        assert result.stderr == (
            f"hub worktree: demo-web: jdoe/dem-7 is already checked out in {first}\n"
        )
        assert not (demo_workspace.ws / "demo-api" / ".claude").exists()
        assert not (demo_workspace.ws / "demo-api" / ".git" / "FETCH_HEAD").exists()
        assert not demo_workspace.worktree("demo-web", "dem-7-b").exists()


# dem-7-x: sha256 of the name mod 50 is 34, so its ports shift by 3400.
SLOT = "34"
OFFSET = "3400"
# A caller's values for the six: each is overridden; HUB_OTHER passes through.
CALLER_VARIABLES = {
    "HUB_WORKTREE_NAME": "other",
    "HUB_WORKTREE_SLOT": "99",
    "HUB_PORT_OFFSET": "1",
    "HUB_REPO_DIR": "/nope",
    "HUB_HUB_DIR": "/nope",
    "HUB_WORKTREE_BRANCH": "x",
    "HUB_OTHER": "1",
}
# The design doc whose two ``sh`` examples (setup, then teardown) are run as the demo's scripts.
DESIGN_DOC = Path(__file__).resolve().parents[4] / "docs" / "design" / "worktree-environment.md"


def documented_scripts() -> list[str]:
    """The ```` ```sh ```` blocks of ``DESIGN_DOC``, in order (the doc must exist)."""
    assert DESIGN_DOC.is_file(), f"{DESIGN_DOC} is missing"
    text = DESIGN_DOC.read_text(encoding="utf-8")
    return re.findall(r"^```sh\n(.*?)^```$", text, flags=re.MULTILINE | re.DOTALL)


class TestScriptEnvironment:
    """The six ``HUB_*`` variables the repo's setup and teardown scripts get (AGH-59)."""

    def test_passes_task_variables_when_setup_runs(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        log, env_log = tmp_path / "setup.log", tmp_path / "setup.env"
        script = variable_script(log, env_log, "setup")
        demo_workspace.advance("demo-api", {SETUP: (script, EXECUTABLE)})
        worktree = demo_workspace.worktree("demo-api", NAME)

        result = run_command(
            demo_workspace.hub,
            "worktree",
            NAME,
            "--only",
            "demo-api",
            env={"MARKER": "kept", "HUB_OTHER": None},
        )

        assert result.exit_code == 0, result.output
        assert env_log.read_text() == expected_variables(
            demo_workspace,
            "demo-api",
            BRANCH,
            slot=SLOT,
            offset=OFFSET,
            extra={"MARKER": "kept", "HUB_OTHER": "unset"},
        )
        assert log.read_text() == script_logged(worktree)

    def test_names_main_checkout_when_run_from_hub_worktree(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        env_log = tmp_path / "setup.env"
        script = variable_script(tmp_path / "setup.log", env_log, "setup")
        demo_workspace.advance("demo-api", {SETUP: (script, EXECUTABLE)})
        hub = demo_workspace.hub
        demo_workspace.git(hub, "-c", "init.defaultBranch=main", "init", "-q")
        demo_workspace.git(hub, "add", "-A")
        demo_workspace.git(hub, "commit", "-q", "-m", "hub")
        hub_worktree = hub / ".claude" / "worktrees" / "x"
        demo_workspace.git(hub, "worktree", "add", "-q", "-b", "x", str(hub_worktree))

        result = run_command(
            demo_workspace.base,
            "worktree",
            NAME,
            "--only",
            "demo-api",
            env={"AGENT_HUB_ROOT": str(hub_worktree), "MARKER": None, "HUB_OTHER": None},
        )

        assert result.exit_code == 0, result.output
        logged = env_log.read_text()
        assert logged == expected_variables(
            demo_workspace,
            "demo-api",
            BRANCH,
            slot=SLOT,
            offset=OFFSET,
            extra={"MARKER": "unset", "HUB_OTHER": "unset"},
        )
        assert f"HUB_HUB_DIR={os.path.realpath(hub_worktree)}\n" not in logged

    def test_shares_slot_across_repos_when_branches_differ(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        use_mixed_hub(demo_workspace)
        branches = {"demo-api": "feature/dem-7/x", "demo-web": "jdoe/DEM-7-x"}
        for repo in REPOS:
            script = variable_script(tmp_path / f"{repo}.log", tmp_path / f"{repo}.env", "setup")
            demo_workspace.advance(repo, {SETUP: (script, EXECUTABLE)})

        result = run_command(
            demo_workspace.hub, "worktree", NAME, env={"MARKER": None, "HUB_OTHER": None}
        )

        assert result.exit_code == 0, result.output
        for repo, branch in branches.items():
            assert (tmp_path / f"{repo}.env").read_text() == expected_variables(
                demo_workspace,
                repo,
                branch,
                slot=SLOT,
                offset=OFFSET,
                extra={"MARKER": "unset", "HUB_OTHER": "unset"},
            )
            assert f"branch   : {repo} {branch}" in result.stdout.splitlines()

    def test_passes_setup_variables_to_teardown_when_remove_given(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        setup_env, teardown_env = tmp_path / "setup.env", tmp_path / "teardown.env"
        teardown_log = tmp_path / "teardown.log"
        setup = variable_script(tmp_path / "setup.log", setup_env, "setup")
        teardown = variable_script(teardown_log, teardown_env, "teardown")
        demo_workspace.advance(
            "demo-api", {SETUP: (setup, EXECUTABLE), TEARDOWN: (teardown, EXECUTABLE)}
        )
        unset = {"MARKER": None, "HUB_OTHER": None}
        created = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api", env=unset)
        assert created.exit_code == 0, created.output
        api = demo_workspace.worktree("demo-api", NAME)

        result = run_command(
            demo_workspace.hub, "worktree", "--remove", NAME, "--only", "demo-api", env=unset
        )

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines() == [
            f"  demo-api: teardown {api}",
            "  demo-api: present",
            f"removed  {api}",
        ]
        assert teardown_env.read_text() == setup_env.read_text()
        assert teardown_env.read_text() == expected_variables(
            demo_workspace,
            "demo-api",
            BRANCH,
            slot=SLOT,
            offset=OFFSET,
            extra={"MARKER": "unset", "HUB_OTHER": "unset"},
        )
        assert teardown_log.read_text() == script_logged(api)

    def test_overrides_caller_variables_when_scripts_run(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        setup_env, teardown_env = tmp_path / "setup.env", tmp_path / "teardown.env"
        setup = variable_script(tmp_path / "setup.log", setup_env, "setup")
        teardown = variable_script(tmp_path / "teardown.log", teardown_env, "teardown")
        demo_workspace.advance(
            "demo-api", {SETUP: (setup, EXECUTABLE), TEARDOWN: (teardown, EXECUTABLE)}
        )
        caller: dict[str, str | None] = {**CALLER_VARIABLES, "MARKER": None}

        created = run_command(
            demo_workspace.hub, "worktree", NAME, "--only", "demo-api", env=caller
        )
        removed = run_command(
            demo_workspace.hub, "worktree", "--remove", NAME, "--only", "demo-api", env=caller
        )

        assert created.exit_code == 0, created.output
        assert removed.exit_code == 0, removed.output
        expected = expected_variables(
            demo_workspace,
            "demo-api",
            BRANCH,
            slot=SLOT,
            offset=OFFSET,
            extra={"MARKER": "unset", "HUB_OTHER": "1"},
        )
        assert setup_env.read_text() == expected
        assert teardown_env.read_text() == expected

    def test_shifts_ports_when_documented_scripts_run(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        """The design doc's examples, run under ``/bin/sh`` with a fake ``docker`` first on
        ``PATH``: setup copies the main checkout's ``.env`` with shifted ports, teardown stops the
        same compose project, and the gitignored ``.env`` leaves the worktree clean to remove."""
        scripts = documented_scripts()
        assert len(scripts) == 2, scripts
        setup, teardown = (script.encode() for script in scripts)
        demo_workspace.advance(
            "demo-api",
            {
                SETUP: (setup, EXECUTABLE),
                TEARDOWN: (teardown, EXECUTABLE),
                ".gitignore": (b".env\n", PLAIN),
            },
        )
        (demo_workspace.ws / "demo-api" / ".env").write_bytes(
            b"API_PORT=8000\nCOMPOSE_PROJECT_NAME=old\nWEB_PORT=5173\nNAME=demo\n"
        )
        bin_dir, docker_log = tmp_path / "docker-bin", tmp_path / "docker.log"
        bin_dir.mkdir()
        docker = bin_dir / "docker"
        docker.write_text(f'#!/bin/sh\nprintf \'%s\\n\' "$*" >> "{docker_log}"\n')
        docker.chmod(EXECUTABLE)
        env = {"PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
        worktree = demo_workspace.worktree("demo-api", NAME)

        created = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api", env=env)
        assert created.exit_code == 0, created.output
        copied = (worktree / ".env").read_text()
        removed = run_command(
            demo_workspace.hub, "worktree", "--remove", NAME, "--only", "demo-api", env=env
        )

        assert copied == (
            "API_PORT=11400\nWEB_PORT=8573\nNAME=demo\nCOMPOSE_PROJECT_NAME=demo-api-dem-7-x\n"
        )
        assert removed.exit_code == 0, removed.output
        assert docker_log.read_text() == "compose -p demo-api-dem-7-x down\n"
        assert not worktree.exists()
        assert [line for line in copied.splitlines() if "COMPOSE_PROJECT_NAME" in line] == [
            "COMPOSE_PROJECT_NAME=demo-api-dem-7-x"
        ]

    def test_skips_env_and_docker_when_documented_scripts_run_without_them(
        self, demo_workspace: Workspace, run_command: CommandRunner, tmp_path: Path
    ) -> None:
        """The design doc's examples with no ``.env`` in the main checkout and no ``docker`` on
        ``PATH``: setup writes only the compose project name, and teardown exits 0 so the worktree
        is removed."""
        setup, teardown = (script.encode() for script in documented_scripts())
        demo_workspace.advance(
            "demo-api",
            {
                SETUP: (setup, EXECUTABLE),
                TEARDOWN: (teardown, EXECUTABLE),
                ".gitignore": (b".env\n", PLAIN),
            },
        )
        bin_dir = tmp_path / "no-docker-bin"
        bin_dir.mkdir()
        for tool in ("git", "basename"):
            found = shutil.which(tool)
            assert found is not None, tool
            (bin_dir / tool).symlink_to(found)
        env = {"PATH": str(bin_dir)}
        worktree = demo_workspace.worktree("demo-api", NAME)

        created = run_command(demo_workspace.hub, "worktree", NAME, "--only", "demo-api", env=env)
        assert created.exit_code == 0, created.output
        copied = (worktree / ".env").read_text()
        removed = run_command(
            demo_workspace.hub, "worktree", "--remove", NAME, "--only", "demo-api", env=env
        )

        assert not (demo_workspace.ws / "demo-api" / ".env").exists()
        assert copied == "COMPOSE_PROJECT_NAME=demo-api-dem-7-x\n"
        assert removed.exit_code == 0, removed.output
        assert not worktree.exists()
