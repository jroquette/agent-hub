import os
from pathlib import Path

import pytest

from agent_hub.cli.claude_launch import claude_missing_line, launch_claude
from agent_hub.cli.errors import LaunchError

VARIABLE = "CLAUDE_CODE_ADDITIONAL_DIRECTORIES_CLAUDE_MD"


class Execed(Exception):  # noqa: N818 - the recorder's stop signal, not an error
    """Raised by the recorder in place of the exec."""


def test_names_command_and_setup_when_claude_missing_line_built() -> None:
    assert claude_missing_line("start") == (
        "hub start: Claude Code (claude) is not on PATH;"
        " install it: https://docs.claude.com/en/docs/claude-code/setup"
    )


def test_writes_sections_then_execs_when_launched(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, list[str], str | None]] = []

    def record(file: str, argv: list[str]) -> None:
        calls.append((file, list(argv), os.environ.get(VARIABLE)))
        raise Execed

    monkeypatch.setattr(os, "execvp", record)
    monkeypatch.delenv(VARIABLE, raising=False)
    with_agents = tmp_path / "x"
    with_agents.mkdir()
    (with_agents / "AGENTS.md").write_bytes(b"# x\n")
    without_agents = tmp_path / "y"
    without_agents.mkdir()
    context = tmp_path / "hub" / "brain" / "auto" / "ctx.md"

    with pytest.raises(Execed):
        launch_claude(
            hub=tmp_path / "hub",
            folders=[("x/wt", with_agents), ("y/wt", without_agents)],
            context_file=context,
            extra=["prompt"],
        )

    assert context.read_bytes() == b"\n# Instructions for ../x/wt (from x/wt/AGENTS.md)\n\n# x\n"
    assert calls == [
        (
            "claude",
            [
                "claude",
                "--add-dir",
                str(with_agents),
                "--add-dir",
                str(without_agents),
                "--append-system-prompt-file",
                str(context),
                "--settings",
                f'{{"autoMemoryDirectory": "{tmp_path / "hub"}/brain/auto/workspace"}}',
                "prompt",
            ],
            "1",
        )
    ]


def test_raises_without_exec_when_context_file_unwritable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    execs: list[str] = []
    monkeypatch.setattr(os, "execvp", lambda file, _argv: execs.append(file))
    blocker = tmp_path / "brain"
    blocker.write_text("a file where the folder goes\n")
    context = blocker / "auto" / "ctx.md"

    with pytest.raises(LaunchError) as raised:
        launch_claude(hub=tmp_path, folders=[], context_file=context, extra=[])

    assert str(raised.value) == f"cannot write {context}: Not a directory"
    assert execs == []


def test_raises_when_exec_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def refuse(_file: str, _argv: list[str]) -> None:
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(os, "execvp", refuse)
    # Restored afterwards: the launch sets it before the exec.
    monkeypatch.delenv(VARIABLE, raising=False)

    with pytest.raises(LaunchError) as raised:
        launch_claude(hub=tmp_path, folders=[], context_file=tmp_path / "ctx.md", extra=[])

    assert str(raised.value) == "cannot start claude: Permission denied"
