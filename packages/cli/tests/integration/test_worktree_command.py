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
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import Result

from agent_hub.cli import worktree_command

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


def git_identity_reads(traced_git: Any) -> list[str]:
    """The ``git config --get user.*`` calls of a run."""
    return [arguments for _, arguments in traced_git.calls() if "config --get user." in arguments]


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
        reads = [
            (cwd, arguments)
            for cwd, arguments in traced_git.calls()
            if "config --get user." in arguments
        ]
        assert reads == [(os.path.realpath(demo_workspace.hub), "config --get user.email")]
