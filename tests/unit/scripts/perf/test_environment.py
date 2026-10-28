"""The perf suite's environment (``scripts/perf/environment.py``): the child environment built
from scratch, the tool bin with its ``uvx`` stand-in, the ``hub web`` argv and the temp hub
(spec AC-5). Every port and URL is passed in, and the temp hub is made over a recording runner,
so no test opens a socket or starts a process."""

import json
import os
import re
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pytest

from scripts.perf.environment import child_env, create_hub, make_tool_bin, web_argv
from scripts.perf.fixture import BRANCH_PREFIX, FEATURE_SLUG, PAGE_SESSION

# Plan C5: the variables that must point under the temp root, and the parent variables that
# must not reach a child (a proxy or a tracker token would let a call leave the machine,
# AGENT_HUB_IN_CONTAINER would widen the bind, CLAUDECODE switches doctor to its network probe).
ROOTED_VARIABLES = (
    "HOME",
    "XDG_DATA_HOME",
    "XDG_CONFIG_HOME",
    "XDG_CACHE_HOME",
    "TMPDIR",
    "UV_CACHE_DIR",
)
LEAKING_VARIABLES = {
    "HTTPS_PROXY": "http://proxy.example.com:3128",
    "HTTP_PROXY": "http://proxy.example.com:3128",
    "LINEAR_API_KEY": "lin_api_synthetic",
    "GH_TOKEN": "ghp_synthetic",
    "CLAUDECODE": "1",
    "AGENT_HUB_IN_CONTAINER": "1",
}
REAL_HOME = "/home/real-user"
REAL_DB = "/real.db"
# A loopback URL given as a value: nothing listens and nothing connects in these tests.
SENSOR_URL = "http://127.0.0.1:9"
PORT = 7431
# Plan Q3 and C5: the temp hub's init flags and its synthetic identity.
TRACKER = "linear:AGH"
HUB_REPOS = "acme/perf-api"
AUTHOR_NAME = "Perf Author"
AUTHOR_EMAIL = "perf@example.com"
HUB_NAME = "perf"
FEATURE_ISSUE_LINE = "linear: [AGH-7]"
# Claude Code's folder name for the fixture's cwd ``/work/perf-api`` (plan C6).
TRANSCRIPT_FOLDER = "-work-perf-api"
ABSOLUTE_PATH = re.compile(r"(?<![\w.])/[\w.+-]+(?:/[\w.+-]+)*")


def _root(tmp_path: Path) -> Path:
    root = tmp_path / "perf-root"
    root.mkdir()
    return root


def _env(root: Path) -> dict[str, str]:
    return child_env(root, db=root / "fixture.db", tool_bin=root / "bin", sensor_url=SENSOR_URL)


def _flag(argv: Sequence[str], flag: str) -> str:
    assert flag in argv, f"{flag} missing from {list(argv)}"
    return argv[list(argv).index(flag) + 1]


def _git_subcommand(argv: Sequence[str]) -> str:
    """The git subcommand of ``argv``, past ``-c <setting>`` and ``-C <dir>``."""
    rest = list(argv[1:])
    while rest and rest[0].startswith("-"):
        rest = rest[2:] if rest[0] in {"-c", "-C"} else rest[1:]
    return rest[0] if rest else ""


@dataclass(frozen=True)
class Call:
    argv: list[str]
    cwd: Path | None
    env: dict[str, str] | None
    feature_files: frozenset[str]


class RecordingRunner:
    """A stand-in for the process runner: records each call, makes the ``--dir`` folder for
    ``hub init`` (as the real init would), and notes which feature files exist at each call."""

    def __init__(self) -> None:
        self.calls: list[Call] = []
        self.hub_dir: Path | None = None

    def __call__(
        self,
        argv: Sequence[str],
        cwd: Path | str | None = None,
        env: Mapping[str, str] | None = None,
    ) -> subprocess.CompletedProcess[str]:
        args = [str(part) for part in argv]
        if "init" in args and not self.is_git(args):
            target = Path(_flag(args, "--dir"))
            # Only an absolute folder is made, so a relative one never lands in the checkout.
            if target.is_absolute():
                self.hub_dir = target
                target.mkdir(parents=True, exist_ok=True)
        self.calls.append(
            Call(
                argv=args,
                cwd=None if cwd is None else Path(cwd),
                env=None if env is None else dict(env),
                feature_files=self._feature_files(),
            )
        )
        return subprocess.CompletedProcess(args, 0, "", "")

    @staticmethod
    def is_git(argv: Sequence[str]) -> bool:
        return Path(argv[0]).name == "git"

    def git_calls(self) -> list[Call]:
        return [call for call in self.calls if self.is_git(call.argv)]

    def init_call(self) -> Call:
        inits = [c for c in self.calls if "init" in c.argv and not self.is_git(c.argv)]
        assert len(inits) == 1, [c.argv for c in self.calls]
        return inits[0]

    def _feature_files(self) -> frozenset[str]:
        if self.hub_dir is None:
            return frozenset()
        folder = self.hub_dir / "brain" / "features" / FEATURE_SLUG
        return frozenset(p.name for p in folder.glob("*") if p.is_file())


def _created_hub(tmp_path: Path) -> tuple[Path, dict[str, str], RecordingRunner]:
    root = _root(tmp_path)
    env = _env(root)
    runner = RecordingRunner()
    create_hub(root, runner=runner, env=env)
    assert runner.hub_dir is not None, "create_hub never ran hub init with --dir"
    return root, env, runner


@pytest.mark.parametrize("variable", ROOTED_VARIABLES)
def test_points_home_and_xdg_under_the_root_when_built(tmp_path: Path, variable: str) -> None:
    root = _root(tmp_path)

    value = Path(_env(root)[variable])

    assert value.is_absolute()
    assert value.is_relative_to(root)


def test_points_agent_hub_db_at_the_fixture_copy_when_built(tmp_path: Path) -> None:
    root = _root(tmp_path)
    copy = root / "copy" / "fixture.db"

    env = child_env(root, db=copy, tool_bin=root / "bin", sensor_url=SENSOR_URL)

    assert env["AGENT_HUB_DB"] == str(copy)


def test_points_claude_projects_under_the_root_when_built(tmp_path: Path) -> None:
    root = _root(tmp_path)

    projects = Path(_env(root)["AGENT_HUB_CLAUDE_PROJECTS"])

    assert projects.is_absolute()
    assert projects.is_relative_to(root)


def test_drops_proxy_tracker_and_claude_variables_when_the_parent_has_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in LEAKING_VARIABLES.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("AGENT_HUB_DB", REAL_DB)
    monkeypatch.setenv("HOME", REAL_HOME)
    monkeypatch.setenv("XDG_DATA_HOME", f"{REAL_HOME}/.local/share")
    assert os.environ["AGENT_HUB_DB"] == REAL_DB
    root = _root(tmp_path)
    db = root / "fixture.db"

    env = child_env(root, db=db, tool_bin=root / "bin", sensor_url=SENSOR_URL)

    assert sorted(set(LEAKING_VARIABLES) & set(env)) == []
    assert env["AGENT_HUB_DB"] == str(db)
    assert [name for name, value in env.items() if REAL_HOME in value] == []


def test_passes_the_given_sensor_url_when_built(tmp_path: Path) -> None:
    root = _root(tmp_path)
    url = "http://127.0.0.1:4119"

    env = child_env(root, db=root / "fixture.db", tool_bin=root / "bin", sensor_url=url)

    assert env["AGENT_HUB_WEB_URL"] == url


def test_puts_only_the_tool_bin_on_path_when_built(tmp_path: Path) -> None:
    root = _root(tmp_path)

    env = child_env(root, db=root / "fixture.db", tool_bin=root / "bin", sensor_url=SENSOR_URL)

    assert env["PATH"] == str(root / "bin")


def test_links_git_and_python_and_writes_a_uvx_stand_in_when_the_tool_bin_is_made(
    tmp_path: Path,
) -> None:
    real = tmp_path / "real-tools"
    real.mkdir()
    git, python3, hub_bin = real / "git", real / "python3", real / "venv-bin" / "hub"
    hub_bin.parent.mkdir()
    for tool in (git, python3, hub_bin):
        tool.write_text("#!/bin/sh\nexit 0\n", "utf-8")
        tool.chmod(0o755)
    root = _root(tmp_path)

    bin_dir = make_tool_bin(root, hub_bin=hub_bin, git=git, python3=python3)

    assert bin_dir.is_relative_to(root)
    assert sorted(p.name for p in bin_dir.iterdir()) == ["git", "python3", "uvx"]
    assert (bin_dir / "git").resolve() == git.resolve()
    assert (bin_dir / "python3").resolve() == python3.resolve()
    uvx = bin_dir / "uvx"
    assert os.access(uvx, os.X_OK)
    text = uvx.read_text("utf-8")
    assert str(hub_bin) in text
    assert sorted(set(ABSOLUTE_PATH.findall(text)) - {"/bin/sh"}) == [str(hub_bin)]


def test_binds_hub_web_to_loopback_when_the_argv_is_built(tmp_path: Path) -> None:
    hub_bin = tmp_path / "venv-bin" / "hub"
    db = tmp_path / "perf-root" / "fixture.db"

    argv = web_argv(hub_bin, port=PORT, db=db)

    assert argv[:2] == [str(hub_bin), "web"]
    assert _flag(argv, "--host") == "127.0.0.1"
    assert _flag(argv, "--port") == str(PORT)
    assert _flag(argv, "--db") == str(db)
    assert "--no-open" in argv


def test_runs_hub_init_with_every_flag_when_creating_the_hub(tmp_path: Path) -> None:
    root, _env_, runner = _created_hub(tmp_path)

    init = runner.init_call().argv

    assert init[init.index("init") + 1] == HUB_NAME
    assert _flag(init, "--tracker") == TRACKER
    assert _flag(init, "--branch-prefix") == BRANCH_PREFIX
    assert _flag(init, "--repos") == HUB_REPOS
    assert _flag(init, "--author-name") == AUTHOR_NAME
    assert _flag(init, "--author-email") == AUTHOR_EMAIL
    assert Path(_flag(init, "--dir")).is_relative_to(root)


def test_commits_the_hub_with_a_synthetic_identity_when_creating_the_hub(tmp_path: Path) -> None:
    _root_, _env_, runner = _created_hub(tmp_path)

    git = runner.git_calls()

    subcommands = [_git_subcommand(call.argv) for call in git]
    assert [s for s in subcommands if s in {"init", "add", "commit"}] == ["init", "add", "commit"]
    add = git[subcommands.index("add")]
    assert "-A" in add.argv
    commit = git[subcommands.index("commit")]
    settings = [commit.argv[i + 1] for i, arg in enumerate(commit.argv[:-1]) if arg == "-c"]
    names = [s.removeprefix("user.name=") for s in settings if s.startswith("user.name=")]
    emails = [s.removeprefix("user.email=") for s in settings if s.startswith("user.email=")]
    assert len(names) == 1
    assert names[0].strip() != ""
    assert len(emails) == 1
    assert emails[0].endswith("@example.com")
    for call in git:
        assert call.cwd == runner.hub_dir
        assert call.env is not None
        assert call.env.get("GIT_CONFIG_GLOBAL") == "/dev/null"
        assert call.env.get("GIT_CONFIG_NOSYSTEM") == "1"


def test_writes_the_feature_folder_when_creating_the_hub(tmp_path: Path) -> None:
    _root_, _env_, runner = _created_hub(tmp_path)
    assert runner.hub_dir is not None
    folder = runner.hub_dir / "brain" / "features" / FEATURE_SLUG

    commits = [c for c in runner.git_calls() if _git_subcommand(c.argv) == "commit"]

    assert len(commits) == 1
    assert {"spec.md", "features.json"} <= commits[0].feature_files
    assert FEATURE_ISSUE_LINE in (folder / "spec.md").read_text("utf-8")
    record = json.loads((folder / "features.json").read_text("utf-8"))
    assert isinstance(record, dict)


def test_writes_a_synthetic_transcript_under_the_root_when_creating_the_hub(
    tmp_path: Path,
) -> None:
    root, env, _runner = _created_hub(tmp_path)
    projects = Path(env["AGENT_HUB_CLAUDE_PROJECTS"])
    transcript = projects / TRANSCRIPT_FOLDER / f"{PAGE_SESSION}.jsonl"

    lines = transcript.read_text("utf-8").splitlines()

    assert transcript.is_relative_to(root)
    assert len(lines) >= 1
    assert all(isinstance(json.loads(line), dict) for line in lines)
