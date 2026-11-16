"""``hub collect --spool``: the hook sensor's spool imported without ``hub web``, all or nothing.

The spool is written as the sensor writes it into ``$XDG_STATE_HOME/agent-hub/`` under the test's
folder; transcripts are read only under ``AGENT_HUB_CLAUDE_PROJECTS``. Every value is synthetic.
"""

import json
import os
import re
from collections.abc import Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.core.events.event import Event
from agent_hub.core.testing.hook_inputs import a_hook_input, an_envelope
from agent_hub.core.testing.transcript_lines import (
    TRANSCRIPT_SESSION,
    a_text_block,
    a_user_line,
    an_assistant_line,
    transcript_text,
)
from agent_hub.storage.event_store import open_event_store

SPOOL_FILE = "hook-spool.jsonl"
# Synthetic, shaped like a key so the redaction would catch it; never a real secret.
SYNTHETIC_KEY = "sk-ant-api03-SYNTHETICsecretVALUE0123456789"


class Paths:
    def __init__(self, root: Path) -> None:
        self.state = root / "state"
        self.folder = self.state / "agent-hub"
        self.projects = root / "projects"
        self.db = root / "events.db"
        self.folder.mkdir(parents=True, mode=0o700)
        (self.projects / "-work-demo-api").mkdir(parents=True)

    def env(self) -> dict[str, str]:
        return {"XDG_STATE_HOME": str(self.state), "AGENT_HUB_CLAUDE_PROJECTS": str(self.projects)}

    def spool(self, lines: Sequence[bytes]) -> None:
        path = self.folder / SPOOL_FILE
        path.write_bytes(b"".join(line + b"\n" for line in lines))
        path.chmod(0o600)

    def left(self) -> list[str]:
        return sorted(name for name in os.listdir(self.folder) if not name.endswith(".lock"))

    def stored(self) -> list[Event]:
        return open_event_store(self.db).read_all()


@pytest.fixture
def paths(tmp_path: Path) -> Paths:
    return Paths(tmp_path)


def _collect(paths: Paths, *args: str) -> Result:
    return CliRunner().invoke(
        app, ["collect", "--spool", *args, "--db", str(paths.db)], env=paths.env()
    )


def _plain(output: str) -> str:
    # Rich colours and boxes usage errors when CI forces a terminal; keep only the words.
    without_ansi = re.sub(r"\x1b\[[0-9;]*m", "", output)
    return " ".join(re.sub(r"[─-╿]", " ", without_ansi).split())


def _tool_line(number: int) -> bytes:
    command = f"curl -H 'x-api-key: {SYNTHETIC_KEY}' https://example.invalid/{number}"
    hook = a_hook_input(
        "PreToolUse", tool_use_id=f"toolu_spool_{number}", tool_input={"command": command}
    )
    return an_envelope(hook).model_dump_json().encode()


def test_imports_spool_redacted_and_empties_it_when_spool_given(paths: Paths) -> None:
    paths.spool([_tool_line(1), _tool_line(2)])

    result = _collect(paths)

    assert result.exit_code == 0, result.output
    assert result.stdout == "appended 2, duplicates 0\n"
    rows = paths.stored()
    assert sorted(row.source_id for row in rows) == [
        "session-1:PreToolUse:toolu_spool_1",
        "session-1:PreToolUse:toolu_spool_2",
    ]
    assert SYNTHETIC_KEY not in json.dumps([row.payload for row in rows])
    assert paths.left() == []


def test_reports_only_duplicates_when_same_spool_imported_twice(paths: Paths) -> None:
    lines = [_tool_line(1), _tool_line(2)]
    paths.spool(lines)
    _collect(paths)
    paths.spool(lines)

    result = _collect(paths)

    assert result.exit_code == 0, result.output
    assert result.stdout == "appended 0, duplicates 2\n"
    assert len(paths.stored()) == 2


def test_writes_nothing_and_keeps_lines_when_spool_has_bad_line(paths: Paths) -> None:
    paths.spool([_tool_line(1), b"{not json", _tool_line(2)])

    result = _collect(paths)

    assert result.exit_code == 1
    taken = json.dumps(str(paths.folder / "hook-spool.taken.jsonl"))
    assert result.stderr == (
        f"{taken}: line 2: invalid JSON: Expecting property name enclosed in double quotes\n"
        f"{taken}: fix or delete the lines above, then run hub collect --spool again "
        "(hub web skips bad lines when it starts)\n"
    )
    assert not paths.db.exists()
    kept = b"".join((paths.folder / name).read_bytes() for name in paths.left())
    assert kept.count(b"\n") == 3


def test_adds_transcript_events_when_spooled_stop_names_transcript(paths: Paths) -> None:
    transcript = paths.projects / "-work-demo-api" / f"{TRANSCRIPT_SESSION}.jsonl"
    transcript.write_text(
        transcript_text([a_user_line("one"), an_assistant_line([a_text_block()])]),
        encoding="utf-8",
    )
    stop = an_envelope(a_hook_input("Stop", transcript_path=str(transcript)))
    paths.spool([stop.model_dump_json().encode()])

    result = _collect(paths)

    assert result.exit_code == 0, result.output
    assert result.stdout == "appended 2, duplicates 0\n"
    assert [row.source for row in paths.stored()] == ["transcript", "transcript"]


def test_appends_nothing_when_nothing_spooled(paths: Paths) -> None:
    result = _collect(paths)

    assert result.exit_code == 0, result.output
    assert result.stdout == "appended 0, duplicates 0\n"


def test_warns_of_dropped_lines_when_spool_was_trimmed(paths: Paths) -> None:
    paths.spool([b'{"dropped": 3}', _tool_line(1)])

    result = _collect(paths)

    assert result.exit_code == 0, result.output
    assert result.stdout == "appended 1, duplicates 0\n"
    assert result.stderr == "warning: the hook spool was full: 3 older events were dropped\n"


def test_exits_one_and_writes_nothing_when_spool_folder_is_link(
    paths: Paths, tmp_path: Path
) -> None:
    paths.spool([_tool_line(1)])
    moved = tmp_path / "real-state"
    paths.state.rename(moved)
    os.symlink(moved / "agent-hub", tmp_path / "linked")
    paths.state.mkdir()
    os.symlink(tmp_path / "linked", paths.folder)

    result = _collect(paths)

    assert result.exit_code == 1
    assert result.stderr.startswith("error: cannot open ")
    assert not paths.db.exists()


@pytest.mark.parametrize("other", [["events.jsonl"], ["--transcript", "t.jsonl"], ["--runs", "r"]])
def test_exits_with_usage_line_when_spool_combined_with_other_input_usage(
    paths: Paths, other: list[str]
) -> None:
    result = _collect(paths, *other)

    assert result.exit_code == 2
    assert "--spool takes no FILE, --transcript or --runs" in _plain(result.output)
    assert not paths.db.exists()
