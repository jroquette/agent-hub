"""The rendered CI step ``Repos beside the hub``, run the way Actions runs it (AGH-699 A-13, AGH-801).

The step clones each repo of ``hub.json`` at its default branch into ``../<dir>``, beside the hub,
where ``hub doctor``'s repo rules (``brain.leak``, ``links.dead``) look for it. With
``HUB_REPOS_READ_TOKEN`` set it maps that repo's GitHub URL to one carrying the token through git
config in the step's own environment (never in an argument, a file or ``GITHUB_ENV``), and a repo
it cannot clone fails it. Without that token (unset or empty) a repo it cannot clone is skipped with
one notice line: doctor then reports it as not checked out, an info. It never clones with the
platform credential the job's environment may carry. A token outside GitHub's character set or an
unusable ``repos`` value fails it.

Each case runs the step's ``run: |`` block on ``bash`` with Actions' default flags in
``tmp_path/ws/hub``; the repos' GitHub URLs reach local repositories through a global git config
under the test's ``HOME`` (``url.<origin>.insteadOf``), so git never reaches the network."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document, a_second_repo
from agent_hub.generator.render_hub import render_hub

TIMEOUT = 60
CI = ".github/workflows/ci.yml"
STEP = "      - name: Repos beside the hub\n"
RUN_HEAD = "        run: |\n"
BLOCK_INDENT = " " * 10
BASH_FLAGS = ("--noprofile", "--norc", "-eo", "pipefail")
SYSTEM_PATH = ("/usr/bin", "/bin", "/usr/sbin", "/sbin")
# A synthetic token, built from fragments so no token-shaped literal sits in the source.
TOKEN = "gh" + "p_" + "x" * 36
REFUSAL = "HUB_REPOS_READ_TOKEN: unexpected characters\n"
SKIP_NOTICE = (
    "::notice::Repos beside the hub: skipped acme/demo-web (trunk): cannot clone it without"
    " HUB_REPOS_READ_TOKEN, so its repo rules run locally only"
)
BAD_REPO_LINE = (
    "Repos beside the hub: repos[1] in hub.json needs a dir, an owner/name github and a branch\n"
)
# A git that logs its arguments and its GIT_CONFIG_* environment, then runs the real one.
LOGGING_GIT = """#!/bin/sh
{{ printf 'argv:'; printf ' %s' "$@"; printf '\\n'; env | grep '^GIT_CONFIG_' | sort; }} >> "{log}"
exec "{git}" "$@"
"""


def repos_block(ci: str) -> str:
    """The step's ``run: |`` block as bash reads it: its lines at the block's indent, dedented."""
    step = ci[ci.index(STEP) :]
    body = step[step.index(RUN_HEAD) + len(RUN_HEAD) :]
    lines: list[str] = []
    for line in body.splitlines(keepends=True):
        if line.strip() and not line.startswith(BLOCK_INDENT):
            break
        lines.append(line.removeprefix(BLOCK_INDENT))
    assert lines, ci
    return "".join(lines)


def demo_ci() -> str:
    config = HubConfig.model_validate(a_hub_document())
    return next(file for file in render_hub(config).files if file.path == CI).content.decode()


def real_git() -> str:
    found = shutil.which("git")
    assert found is not None, "the repos step runs git: install it"
    return os.path.realpath(found)


def git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, no shell
        [real_git(), *arguments],
        capture_output=True,
        text=True,
        check=True,
        cwd=cwd,
        env={
            "PATH": os.pathsep.join(SYSTEM_PATH),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Jane Doe",
            "GIT_AUTHOR_EMAIL": "jane@example.com",
            "GIT_COMMITTER_NAME": "Jane Doe",
            "GIT_COMMITTER_EMAIL": "jane@example.com",
        },
        timeout=TIMEOUT,
    )
    return completed.stdout.strip()


class Workspace:
    """``tmp_path/ws/hub`` holding ``hub.json``, origins under ``tmp_path/origins`` and a
    ``HOME`` whose git config sends each repo's GitHub URL to its origin."""

    def __init__(self, tmp_path: Path, document: dict[str, Any]) -> None:
        self.tmp_path = tmp_path
        self.workspace = tmp_path / "ws"
        self.hub = self.workspace / "hub"
        self.hub.mkdir(parents=True)
        (self.hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        self.home = tmp_path / "home"
        self.home.mkdir()
        self.bin = tmp_path / "bin"
        self.bin.mkdir()
        (self.bin / "python3").symlink_to(os.path.realpath(sys.executable))
        self.git_log = tmp_path / "git.log"

    def origin(self, github: str, branch: str) -> Path:
        """A repository with one commit on ``branch``, reached as ``https://github.com/<github>``."""
        origin = self.tmp_path / "origins" / github
        origin.mkdir(parents=True)
        git(origin, "init", "-q", "-b", branch)
        (origin / "README.md").write_text(f"# {github}\n", encoding="utf-8")
        git(origin, "add", "README.md")
        git(origin, "commit", "-q", "-m", "init")
        with (self.home / ".gitconfig").open("a", encoding="utf-8") as config:
            config.write(f'[url "{origin}"]\n\tinsteadOf = https://github.com/{github}.git\n')
        return origin

    def log_git_calls(self) -> None:
        wrapper = self.bin / "git"
        wrapper.write_text(LOGGING_GIT.format(log=self.git_log, git=real_git()), encoding="utf-8")
        wrapper.chmod(0o755)

    def run_step(
        self, token: str | None = None, job_env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        """Run the block; ``job_env`` is what earlier steps put in the job's environment."""
        env = {
            **(job_env or {}),
            "PATH": os.pathsep.join((str(self.bin), *SYSTEM_PATH)),
            "HOME": str(self.home),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_ALLOW_PROTOCOL": "file",
            "GIT_CEILING_DIRECTORIES": str(self.tmp_path),
        }
        if token is not None:
            env["TOKEN"] = token
        bash = shutil.which("bash")
        assert bash is not None, "the repos step runs on bash: install it"
        return subprocess.run(  # noqa: S603 - absolute bash, the rendered block, no shell
            [os.path.realpath(bash), *BASH_FLAGS, "-c", repos_block(demo_ci())],
            capture_output=True,
            text=True,
            check=False,
            cwd=self.hub,
            env=env,
            timeout=TIMEOUT,
        )

    def branch_of(self, directory: str) -> str:
        return git(self.workspace / directory, "rev-parse", "--abbrev-ref", "HEAD")


def two_repo_document() -> dict[str, Any]:
    """``demo-api`` on the project's ``main``, ``demo-web`` on its own ``trunk``."""
    document = a_hub_document()
    web = a_second_repo()
    web["default_branch"] = "trunk"
    document["repos"].append(web)
    return document


@pytest.fixture
def workspace(tmp_path: Path) -> Workspace:
    found = Workspace(tmp_path, two_repo_document())
    found.origin("acme/demo-api", "main")
    found.origin("acme/demo-web", "trunk")
    return found


def test_clones_each_repo_beside_hub_when_step_runs(workspace: Workspace) -> None:
    completed = workspace.run_step()

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "Repos beside the hub: cloned acme/demo-api (main) into ../demo-api",
        "Repos beside the hub: cloned acme/demo-web (trunk) into ../demo-web",
    ]
    assert workspace.branch_of("demo-api") == "main"
    assert workspace.branch_of("demo-web") == "trunk"
    assert (workspace.workspace / "demo-web" / "README.md").read_text() == "# acme/demo-web\n"


def test_maps_each_repo_to_token_in_step_environment_when_token_given(
    workspace: Workspace,
) -> None:
    workspace.log_git_calls()

    completed = workspace.run_step(TOKEN)

    assert completed.returncode == 0, completed.stderr
    calls = workspace.git_log.read_text(encoding="utf-8")
    # Each clone's call, with the GIT_CONFIG_* pair it ran with (one repo's mapping at a time).
    clones = [
        [line for line in call.splitlines()[1:] if not line.startswith("GIT_CONFIG_NOSYSTEM")]
        for call in calls.split("argv: ")
        if call.startswith("clone ")
    ]
    assert clones == [
        [
            "GIT_CONFIG_COUNT=1",
            f"GIT_CONFIG_KEY_0=url.https://x-access-token:{TOKEN}@github.com/{github}.insteadOf",
            f"GIT_CONFIG_VALUE_0=https://github.com/{github}",
        ]
        for github in ("acme/demo-api", "acme/demo-web")
    ]
    # Only git's environment carries the token: no argument, no output.
    assert [line for line in calls.splitlines() if line.startswith("argv:") and TOKEN in line] == []
    assert TOKEN not in completed.stdout + completed.stderr


def test_fails_naming_repo_when_token_given_and_clone_fails(tmp_path: Path) -> None:
    found = Workspace(tmp_path, two_repo_document())
    found.origin("acme/demo-api", "main")

    completed = found.run_step(TOKEN)

    # A configured credential that cannot read a repo is a misconfiguration.
    assert completed.returncode == 1
    assert completed.stderr.endswith(
        "Repos beside the hub: cannot clone acme/demo-web (trunk) into ../demo-web;"
        " HUB_REPOS_READ_TOKEN needs read access to it\n"
    )
    assert found.branch_of("demo-api") == "main"
    assert TOKEN not in completed.stdout + completed.stderr


@pytest.mark.parametrize("token", [None, ""], ids=["unset", "empty"])
def test_skips_repo_with_notice_when_no_token_and_clone_fails(
    token: str | None, tmp_path: Path
) -> None:
    found = Workspace(tmp_path, two_repo_document())
    found.origin("acme/demo-api", "main")

    completed = found.run_step(token)

    # The step passes, so the golden step and make check run; doctor reports the info.
    assert completed.returncode == 0, completed.stderr
    assert completed.stdout.splitlines() == [
        "Repos beside the hub: cloned acme/demo-api (main) into ../demo-api",
        SKIP_NOTICE,
    ]
    assert found.branch_of("demo-api") == "main"
    assert not (found.workspace / "demo-web").exists()


def test_writes_nothing_to_job_environment_when_token_given(workspace: Workspace) -> None:
    github_env = workspace.tmp_path / "github-env"

    completed = workspace.run_step(TOKEN, {"GITHUB_ENV": str(github_env)})

    assert completed.returncode == 0, completed.stderr
    assert not github_env.exists()


@pytest.mark.parametrize("token", [None, TOKEN], ids=["no-token", "token"])
def test_ignores_platform_mapping_in_job_environment_when_cloning(
    token: str | None, workspace: Workspace
) -> None:
    # The platform credential step's GIT_CONFIG_* in the job's environment, here mapping a
    # repo's URL: the clones never use it, so AGENT_HUB_READ_TOKEN stays platform-only.
    platform = "https://x-access-token:platform@github.com/acme/demo-api"
    job_env = {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"url.{platform}.insteadOf",
        "GIT_CONFIG_VALUE_0": "https://github.com/acme/demo-api",
    }
    workspace.log_git_calls()

    completed = workspace.run_step(token, job_env)

    assert completed.returncode == 0, completed.stderr
    assert "platform@" not in workspace.git_log.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "token", [TOKEN + "\nLD_PRELOAD=/x", TOKEN + "@evil.example/", TOKEN + "-x"]
)
def test_refuses_token_when_characters_unexpected(token: str, workspace: Workspace) -> None:
    completed = workspace.run_step(token)

    assert completed.returncode == 1
    assert (completed.stdout, completed.stderr) == ("", REFUSAL)
    assert not (workspace.workspace / "demo-api").exists()


@pytest.mark.parametrize(
    "repo",
    [
        {"dir": "../escape", "github": "acme/demo-web"},
        {"dir": "demo-web", "github": "https://evil.example/x"},
        {"dir": "demo-web", "github": "acme/demo-web", "default_branch": "--upload-pack=x"},
        "demo-web",
    ],
    ids=["dir", "github", "branch", "not-an-object"],
)
def test_exits_one_naming_entry_when_repo_value_unusable(repo: object, tmp_path: Path) -> None:
    document = a_hub_document()
    document["repos"].append(repo)
    found = Workspace(tmp_path, document)
    found.origin("acme/demo-api", "main")

    completed = found.run_step()

    # Nothing is cloned and the value is never echoed.
    assert completed.returncode == 1
    assert (completed.stdout, completed.stderr) == ("", BAD_REPO_LINE)
    assert sorted(path.name for path in found.workspace.iterdir()) == ["hub"]


def test_clones_nothing_when_hub_has_no_repos(tmp_path: Path) -> None:
    document = a_hub_document()
    document["repos"] = []
    found = Workspace(tmp_path, document)

    completed = found.run_step()

    assert completed.returncode == 0, completed.stderr
    assert (completed.stdout, completed.stderr) == ("", "")
