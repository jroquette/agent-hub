"""``hub setup``: one-command onboarding of a developer's machine (AGH-71).

Every run is in process, in a copy of the ``DEMO`` workspace (``demo_workspace``) whose git is
``env_traced_git``: each call is logged with its environment, then the real git runs. The tests
replace only the command's seams: the tool probe (``setup_tools.tool_probe``), the terminal
check of the prompt (``setup_identity.stdin_is_tty``) and the network timeout
(``setup_repos.NETWORK_TIMEOUT_SECONDS``).
"""

import json
import os
import subprocess
from collections.abc import Callable, Mapping, Sequence
from importlib.metadata import version
from pathlib import Path
from typing import Any

import pytest
from click import unstyle
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.hub_config.versions import PINNED_RELEASE_COMMAND
from agent_hub.core.workspace.setup_checklist import ProbeResult

# The conftest's fixtures (tests cannot import a conftest in importlib mode).
type Workspace = Any
type TracedGit = Any
type SetupRunner = Callable[..., Result]

OLD_PIN = "0.0.1"
SYNTHETIC_KEY = "lin" + "_api_" + "x" * 12


class FakeToolProbe:
    """Answers ``which`` from ``paths`` and ``run`` from ``results``, by tool name; records the
    ``(argv, timeout)`` of each run."""

    def __init__(self, paths: Mapping[str, str | None], results: Mapping[str, ProbeResult]) -> None:
        self.paths = dict(paths)
        self.results = dict(results)
        self.runs: list[tuple[tuple[str, ...], float]] = []

    def which(self, name: str) -> str | None:
        return self.paths.get(name)

    def run(self, argv: Sequence[str], *, timeout: float) -> ProbeResult:
        self.runs.append((tuple(argv), timeout))
        return self.results[Path(argv[0]).name]


@pytest.fixture
def run_setup(monkeypatch: pytest.MonkeyPatch) -> SetupRunner:
    """Run ``hub setup <args>`` in process with ``root`` as the current folder; ``input`` is
    its stdin."""

    def run(root: Path, *args: str, input: str | None = None) -> Result:
        monkeypatch.chdir(root)
        return CliRunner().invoke(app, ["setup", *args], input=input)

    return run


@pytest.fixture
def tools_ok() -> None:
    """Every tool present and current: replaces ``setup_tools.tool_probe`` once the command
    checks the tools; nothing to replace before that."""


def _edit_hub_json(hub: Path, change: Callable[[dict[str, Any]], None]) -> None:
    path = hub / "hub.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    change(document)
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


class TestFixtures:
    def test_logs_env_and_runs_git_when_env_traced_git_used(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, tmp_path: Path
    ) -> None:
        demo_workspace.rewrite_github()
        demo_workspace.init_hub_repo("git@github.com:acme/demo-hub.git")
        git = str(env_traced_git.bin_dir / "git")
        clone = tmp_path / "clone"
        env = {
            **os.environ,
            "GIT_TERMINAL_PROMPT": "0",
            "LINEAR_API_KEY": SYNTHETIC_KEY,
        }

        subprocess.run(  # noqa: S603 - the traced git, fixed arguments, tmp_path folders
            [git, "clone", "--quiet", "https://github.com/acme/demo-web.git", str(clone)],
            cwd=tmp_path,
            env=env,
            check=True,
        )
        origin = subprocess.run(  # noqa: S603 - the traced git, fixed arguments
            [git, "config", "--get", "remote.origin.url"],
            cwd=demo_workspace.hub,
            env={**os.environ, "GIT_DIR": str(demo_workspace.hub / ".git")},
            check=True,
            capture_output=True,
        )

        assert (clone / "README.md").read_text(encoding="utf-8") == "# demo-web\n"
        assert origin.stdout == b"git@github.com:acme/demo-hub.git\n"
        assert [tuple(call) for call in env_traced_git.calls()] == [
            (
                os.path.realpath(tmp_path),
                f"clone --quiet https://github.com/acme/demo-web.git {clone}",
                "0",
                False,
                True,
            ),
            (
                os.path.realpath(demo_workspace.hub),
                "config --get remote.origin.url",
                "unset",
                True,
                False,
            ),
        ]


class TestExit:
    @pytest.mark.parametrize(
        ("args", "problem"),
        [(("--bogus",), "No such option: --bogus"), (("extra",), "unexpected extra argument")],
        ids=["option", "argument"],
    )
    def test_exits_two_when_usage_wrong(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        args: tuple[str, ...],
        problem: str,
    ) -> None:
        result = run_setup(demo_workspace.hub, *args)

        assert result.exit_code == 2, result.output
        assert result.stdout == ""
        assert problem in unstyle(result.stderr)
        assert env_traced_git.calls() == []

    def test_exits_two_when_not_a_hub(
        self, demo_workspace: Workspace, env_traced_git: TracedGit, run_setup: SetupRunner
    ) -> None:
        elsewhere = os.path.realpath(demo_workspace.ws)

        result = run_setup(demo_workspace.ws)

        assert result.exit_code == 2
        assert result.stdout == ""
        assert result.stderr == (
            f"{elsewhere}: not a hub: no hub.json in this folder"
            " (hub setup runs in the hub folder or through ./hub)\n"
        )
        assert env_traced_git.calls() == []

    @pytest.mark.parametrize("case", ["schema", "pin-mismatch"])
    def test_exits_one_without_git_when_hub_json_invalid(
        self,
        demo_workspace: Workspace,
        env_traced_git: TracedGit,
        run_setup: SetupRunner,
        *,
        case: str,
    ) -> None:
        if case == "schema":
            (demo_workspace.hub / "hub.json").write_text('{"schema_version": 1}\n')
            expected = 'hub.json: platform: required: the pinned release, as {"version": "1.2.3"}\n'
        else:
            _edit_hub_json(
                demo_workspace.hub,
                lambda document: document["platform"].update(version=OLD_PIN),
            )
            expected = (
                f"hub.json: platform.version: this hub is pinned to {OLD_PIN} but this hub"
                f" command is {version('agent-hub-cli')}; run the pinned release:"
                f" {PINNED_RELEASE_COMMAND.format(version=OLD_PIN)}\n"
            )

        result = run_setup(demo_workspace.hub)

        assert result.exit_code == 1
        assert result.stdout == ""
        assert result.stderr == expected
        assert env_traced_git.calls() == []
