"""``hub agent``: Claude Code started with every repo of ``hub.json`` attached (AC-15.8, AC-15.9).

Every run is in process; ``os.execvp`` is replaced by a recorder that raises, so ``CliRunner``
reports it as the result's exception and nothing is exec'd. ``claude`` on ``PATH`` is an empty
executable in a test folder: only its presence matters before the exec.
"""

import json
import os
import signal
import stat
from collections.abc import Iterator
from pathlib import Path
from typing import NamedTuple

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.json_form import dump_json

CONTEXT = "brain/auto/agent-context.md"
VARIABLE = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"
CLAUDE_MISSING = (
    "hub agent: Claude Code (claude) is not on PATH;"
    " install it: https://docs.claude.com/en/docs/claude-code/setup\n"
)
A_AGENTS = b"# a\nRun make check.\n"
FIFO_ALARM_SECONDS = 5


class Exec(NamedTuple):
    file: str
    argv: list[str]
    environ: dict[str, str]


class Execed(Exception):  # noqa: N818 - the recorder's stop signal, not an error
    """Raised by the recorder in place of the exec."""


@pytest.fixture
def execs(monkeypatch: pytest.MonkeyPatch) -> list[Exec]:
    """Every ``os.execvp`` call, with the environment at that moment; the call raises."""
    calls: list[Exec] = []

    def record(file: str, argv: list[str]) -> None:
        calls.append(Exec(file, list(argv), dict(os.environ)))
        raise Execed

    monkeypatch.setattr(os, "execvp", record)
    return calls


@pytest.fixture
def claude_bin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """``PATH`` = a folder holding an executable ``claude``; ``os.environ`` restored afterwards."""
    folder = tmp_path / "bin"
    folder.mkdir()
    claude = folder / "claude"
    claude.write_text("#!/bin/sh\nexit 0\n")
    claude.chmod(0o755)
    monkeypatch.setenv("PATH", str(folder))
    monkeypatch.delenv(VARIABLE, raising=False)
    saved = dict(os.environ)
    yield folder
    os.environ.clear()
    os.environ.update(saved)


def run_agent(root: Path, *args: str, monkeypatch: pytest.MonkeyPatch) -> Result:
    monkeypatch.chdir(root)
    return CliRunner().invoke(app, ["agent", *args])


def assert_execed(result: Result) -> None:
    assert isinstance(result.exception, Execed), result.output


class TestArgv:
    def test_execs_claude_when_repos_listed(
        self,
        agent_workspace: Path,
        *,
        execs: list[Exec],
        claude_bin: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        hub = agent_workspace / "hub"
        caller = dict(os.environ)

        result = run_agent(hub, "--resume", "s", "-p", "x y", monkeypatch=monkeypatch)

        assert_execed(result)
        context = hub / CONTEXT
        settings = json.dumps({"autoMemoryDirectory": f"{hub}/brain/auto/workspace"})
        assert execs == [
            Exec(
                "claude",
                [
                    "claude",
                    "--add-dir",
                    str(agent_workspace / "a"),
                    "--add-dir",
                    str(agent_workspace / "b"),
                    "--append-system-prompt-file",
                    str(context),
                    "--settings",
                    settings,
                    "--resume",
                    "s",
                    "-p",
                    "x y",
                ],
                caller | {VARIABLE: "1"},
            )
        ]
        assert result.stderr == (
            f"warning: {agent_workspace / 'c'} not found (listed in hub.json); not attached\n"
        )
        assert result.stdout == ""
        assert context.read_bytes() == (
            b"\n# Instructions for ../a (from a/AGENTS.md)\n\n" + A_AGENTS
        )

    @pytest.mark.parametrize(
        "arguments",
        [
            ["--", "x"],
            ["x", "--", "y"],
            ["-p", "--", "--", "z"],
            ["--", "--help"],
            [""],
            ["--help"],
            ["-h"],
            ["--version"],
            [],
        ],
        ids=[
            "dashes",
            "dashes-inside",
            "dashes-twice",
            "help-after-dashes",
            "empty",
            "help",
            "short-help",
            "version",
            "none",
        ],
    )
    def test_passes_arguments_verbatim_when_agent_runs(
        self,
        agent_workspace: Path,
        *,
        execs: list[Exec],
        claude_bin: Path,
        monkeypatch: pytest.MonkeyPatch,
        arguments: list[str],
    ) -> None:
        result = run_agent(agent_workspace / "hub", *arguments, monkeypatch=monkeypatch)

        assert_execed(result)
        argv = execs[0].argv
        assert argv[9:] == arguments
        assert argv[7] == "--settings"

    def test_skips_agents_md_when_not_regular_file(
        self,
        agent_workspace: Path,
        *,
        execs: list[Exec],
        claude_bin: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        agents = agent_workspace / "a" / "AGENTS.md"
        agents.unlink()
        os.mkfifo(agents)

        def blocked(_signal: int, _frame: object) -> None:
            pytest.fail("hub agent opened the FIFO")

        previous = signal.signal(signal.SIGALRM, blocked)
        signal.alarm(FIFO_ALARM_SECONDS)
        try:
            result = run_agent(agent_workspace / "hub", monkeypatch=monkeypatch)
        finally:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, previous)

        assert_execed(result)
        assert (agent_workspace / "hub" / CONTEXT).read_bytes() == b""
        assert str(agent_workspace / "a") in execs[0].argv


def test_replaces_context_when_launched_again(
    agent_workspace: Path,
    *,
    execs: list[Exec],
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = agent_workspace / "hub"
    auto = hub / "brain" / "auto"
    if auto.exists():
        for path in sorted(auto.rglob("*"), reverse=True):
            path.rmdir() if path.is_dir() else path.unlink()
        auto.rmdir()
    assert_execed(run_agent(hub, monkeypatch=monkeypatch))
    (agent_workspace / "a" / "AGENTS.md").write_bytes(b"# a, changed\n")
    (agent_workspace / "b" / "AGENTS.md").write_bytes(b"# b\n")
    document = json.loads((hub / "hub.json").read_text())
    document["repos"] = [repo for repo in document["repos"] if repo["dir"] != "a"]
    (hub / "hub.json").write_bytes(dump_json(document))

    assert_execed(run_agent(hub, monkeypatch=monkeypatch))

    assert (hub / CONTEXT).read_bytes() == b"\n# Instructions for ../b (from b/AGENTS.md)\n\n# b\n"
    assert sorted(path.name for path in auto.iterdir()) == ["agent-context.md"]
    assert stat.S_ISREG((hub / CONTEXT).lstat().st_mode)


def test_exits_one_when_claude_missing(
    agent_workspace: Path,
    *,
    execs: list[Exec],
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (claude_bin / "claude").unlink()
    hub = agent_workspace / "hub"

    result = run_agent(hub, monkeypatch=monkeypatch)

    assert result.exit_code == 1, result.output
    assert result.stderr == CLAUDE_MISSING
    assert result.stdout == ""
    assert execs == []
    assert not (hub / CONTEXT).exists()


def test_exits_two_when_not_a_hub(
    agent_workspace: Path,
    *,
    execs: list[Exec],
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = run_agent(agent_workspace, monkeypatch=monkeypatch)

    assert result.exit_code == 2
    assert result.stderr == (
        f"{agent_workspace}: not a hub: no hub.json in this folder"
        " (hub agent runs in the hub folder or through ./hub)\n"
    )
    assert execs == []


def test_uses_agent_hub_root_when_run_elsewhere(
    agent_workspace: Path,
    *,
    execs: list[Exec],
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = agent_workspace / "hub"
    monkeypatch.setenv("AGENT_HUB_ROOT", str(hub))

    result = run_agent(agent_workspace / "a", monkeypatch=monkeypatch)

    assert_execed(result)
    assert execs[0].argv[1:5] == [
        "--add-dir",
        str(agent_workspace / "a"),
        "--add-dir",
        str(agent_workspace / "b"),
    ]
    assert (hub / CONTEXT).is_file()


def test_exits_one_when_exec_fails(
    agent_workspace: Path,
    *,
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (agent_workspace / "c").mkdir()  # every repo present: the failure is the only stderr line

    def refuse(_file: str, _argv: list[str]) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "execvp", refuse)

    result = run_agent(agent_workspace / "hub", monkeypatch=monkeypatch)

    assert result.exit_code == 1, result.output
    assert result.stderr == "hub agent: cannot start claude: Permission denied\n"
    assert result.stdout == ""


def test_prints_local_lines_when_local_file_invalid(
    agent_workspace: Path,
    *,
    execs: list[Exec],
    claude_bin: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    hub = agent_workspace / "hub"
    (hub / "hub.local.json").write_text('{"project": {"name": "x"}}', encoding="utf-8")

    result = run_agent(hub, monkeypatch=monkeypatch)

    assert result.exit_code == 1, result.output
    assert result.stdout == ""
    lines = result.stderr.splitlines()
    assert len(lines) == 1, lines
    assert lines[0].startswith("hub.local.json: project.name: set only in hub.json"), lines
    assert execs == []
    assert not (hub / CONTEXT).exists()
