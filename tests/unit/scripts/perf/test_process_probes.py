"""The perf suite's CLI and hook probes (``scripts/perf/process_probes.py``): the canonical row
paths, hook inputs taken from the temp hub, and ``measure`` over
an injected runner and a fake clock, so no process starts and no wall-clock time is asserted.

Seam: ``Probe(kind, path, argv, stdin)``; ``cli_probes(hub_bin, hub_dir)``;
``hook_probes(hub_dir, transcript)``; ``CLI_PATHS`` and ``HOOK_PATHS``; ``measure(probe, *, runs,
runner, clock)`` returns one duration in milliseconds per run, where ``clock`` reads seconds (like
``time.perf_counter``) and ``runner(argv, stdin=...)`` returns an object with ``returncode``; a
command that exits non-zero raises ``SuiteError`` naming the probe's path."""

import json
import re
from collections.abc import Iterator, Sequence
from pathlib import Path

import pytest

from scripts.perf.process_probes import (
    CLI_PATHS,
    HOOK_PATHS,
    Probe,
    SuiteError,
    cli_probes,
    hook_probes,
    measure,
)

# The cli and hook rows, written out by hand.
CLI_ROWS = (
    "hub --version",
    "./hub --version (local uvx stand-in)",
    "hub brief --no-network",
    "hub repo list",
    "hub env list",
    "hub action list",
    "hub scenario list",
    "hub workflow list",
)
# (path, hook script, hook_event_name, tool_name named by the path or None)
HOOK_ROWS = (
    ("guard (PreToolUse Bash)", "guard", "PreToolUse", "Bash"),
    ("event_sensor (PreToolUse, sensor closed)", "event_sensor", "PreToolUse", None),
    ("post_edit (PostToolUse Edit)", "post_edit", "PostToolUse", "Edit"),
    ("readonly_gate (PreToolUse Bash)", "readonly_gate", "PreToolUse", "Bash"),
    ("session_end", "session_end", "SessionEnd", None),
    ("stop_gate (no changes)", "stop_gate", "Stop", None),
    ("session_start (local uvx stand-in)", "session_start", "SessionStart", None),
    ("pre_compact", "pre_compact", "PreCompact", None),
)
# The builders' default transcript lives under this made-up home; no probe input may name it.
BUILDER_HOME = "/home/dev"


class FakeClock:
    """Seconds that move only when a fake run says so."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


class RecordingRunner:
    """Records each call; each run advances ``clock`` by the next step (in seconds)."""

    def __init__(self, clock: FakeClock, steps: Sequence[float], *, returncode: int = 0) -> None:
        self.clock = clock
        self.steps = list(steps)
        self.returncode = returncode
        self.calls: list[tuple[list[str], object]] = []

    def __call__(self, argv: Sequence[object], stdin: object = None, **_: object) -> Completed:
        self.calls.append(([str(part) for part in argv], stdin))
        self.clock.now += self.steps[len(self.calls) - 1] if self.steps else 0.001
        return Completed(self.returncode)


def _layout(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A temp root holding the hub (with ``brain/index.md``) and the synthetic transcript."""
    root = tmp_path / "perf-root"
    hub = root / "hub"
    (hub / "brain").mkdir(parents=True)
    (hub / "brain" / "index.md").write_text("# Perf hub\n", "utf-8")
    transcript = root / "claude" / "projects" / "-work-perf-api" / "perf-00000.jsonl"
    transcript.parent.mkdir(parents=True)
    transcript.write_text('{"type": "user"}\n', "utf-8")
    hub_bin = tmp_path / "venv-bin" / "hub"
    assert (hub / "brain" / "index.md").is_file()
    assert transcript.is_file()
    return hub, transcript, hub_bin


def _probe(probes: Sequence[Probe], path: str) -> Probe:
    found = [probe for probe in probes if probe.path == path]
    assert len(found) == 1, [probe.path for probe in probes]
    return found[0]


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _payload(probe: Probe) -> dict[str, object]:
    assert probe.stdin is not None, probe.path
    payload = json.loads(probe.stdin)
    assert isinstance(payload, dict)
    return payload


def test_lists_the_canonical_cli_and_hook_paths_when_probes_are_built(tmp_path: Path) -> None:
    hub, transcript, hub_bin = _layout(tmp_path)

    cli = cli_probes(hub_bin, hub)
    hooks = hook_probes(hub, transcript)

    assert sorted(CLI_PATHS) == sorted(CLI_ROWS)
    assert sorted(HOOK_PATHS) == sorted(row[0] for row in HOOK_ROWS)
    assert sorted(probe.path for probe in cli) == sorted(CLI_ROWS)
    assert sorted(probe.path for probe in hooks) == sorted(row[0] for row in HOOK_ROWS)
    assert {probe.kind for probe in cli} == {"cli"}
    assert {probe.kind for probe in hooks} == {"hook"}
    assert [str(a) for a in _probe(cli, "hub --version").argv] == [str(hub_bin), "--version"]
    assert [str(a) for a in _probe(cli, CLI_ROWS[1]).argv] == [str(hub / "hub"), "--version"]
    brief = [str(a) for a in _probe(cli, "hub brief --no-network").argv]
    assert brief[0] == str(hub_bin)
    assert {"brief", "--no-network"} <= set(brief)
    for path in CLI_ROWS[3:]:
        assert [str(a) for a in _probe(cli, path).argv] == [str(hub_bin), *path.split()[1:]]
    for path, script, _event, _tool in HOOK_ROWS:
        argv = [str(a) for a in _probe(hooks, path).argv]
        assert len(argv) == 2
        assert Path(argv[0]).name == "python3"
        assert argv[1] == str(hub / "plugin" / "hub-workflow" / "hooks" / f"{script}.py")


@pytest.mark.parametrize("row", HOOK_ROWS, ids=[row[1] for row in HOOK_ROWS])
def test_feeds_hook_inputs_from_the_temp_hub_when_a_hook_runs(
    tmp_path: Path, row: tuple[str, str, str, str | None]
) -> None:
    path, _script, event, tool = row
    hub, transcript, _hub_bin = _layout(tmp_path)

    payload = _payload(_probe(hook_probes(hub, transcript), path))

    assert payload["hook_event_name"] == event
    assert payload["cwd"] == str(hub)
    assert payload["transcript_path"] == str(transcript)
    if "agent_transcript_path" in payload:
        assert payload["agent_transcript_path"] == str(transcript)
    if tool is not None:
        assert payload["tool_name"] == tool
    strings = list(_strings(payload))
    assert len(strings) > 0
    assert [s for s in strings if BUILDER_HOME in s] == []


def test_feeds_an_edit_of_a_hub_file_when_post_edit_runs(tmp_path: Path) -> None:
    hub, transcript, _hub_bin = _layout(tmp_path)

    payload = _payload(_probe(hook_probes(hub, transcript), "post_edit (PostToolUse Edit)"))

    assert payload["tool_name"] == "Edit"
    tool_input = payload["tool_input"]
    assert isinstance(tool_input, dict)
    edited = Path(tool_input["file_path"])
    assert edited.is_absolute()
    assert edited.is_relative_to(hub)
    assert edited.is_file()


def test_runs_each_command_the_requested_times_when_measured(tmp_path: Path) -> None:
    hub, transcript, _hub_bin = _layout(tmp_path)
    probe = _probe(hook_probes(hub, transcript), "guard (PreToolUse Bash)")
    assert probe.stdin is not None
    clock = FakeClock()
    runner = RecordingRunner(clock, [0.001] * 4)

    measure(probe, runs=4, runner=runner, clock=clock)

    assert len(runner.calls) == 4
    assert [argv for argv, _stdin in runner.calls] == [[str(a) for a in probe.argv]] * 4
    assert [stdin for _argv, stdin in runner.calls] == [probe.stdin] * 4


def test_records_the_fake_durations_when_the_clock_advances(tmp_path: Path) -> None:
    hub, _transcript, hub_bin = _layout(tmp_path)
    probe = _probe(cli_probes(hub_bin, hub), "hub --version")
    clock = FakeClock()
    runner = RecordingRunner(clock, [0.012, 0.034, 0.056])

    samples = measure(probe, runs=3, runner=runner, clock=clock)

    assert list(samples) == pytest.approx([12.0, 34.0, 56.0])


def test_fails_the_suite_when_a_command_exits_non_zero(tmp_path: Path) -> None:
    hub, _transcript, hub_bin = _layout(tmp_path)
    probe = _probe(cli_probes(hub_bin, hub), "hub brief --no-network")
    clock = FakeClock()
    runner = RecordingRunner(clock, [0.001] * 3, returncode=1)

    with pytest.raises(SuiteError, match=re.escape("hub brief --no-network")):
        measure(probe, runs=3, runner=runner, clock=clock)


def test_seeds_brief_cache_when_session_start_probe_is_built(tmp_path: Path) -> None:
    hub, transcript, _hub_bin = _layout(tmp_path)
    hooks = hook_probes(hub, transcript)
    probe = _probe(hooks, "session_start (local uvx stand-in)")
    clock = FakeClock()
    runner = RecordingRunner(clock, [5.0, 0.010, 0.020, 0.030])

    samples = measure(probe, runs=3, runner=runner, clock=clock)

    # Seeded once through the temp hub's uvx stand-in, so every timed run reads a cache under
    # the hook's 5 min refresh floor and starts no refresh (Q14); the seed is not timed.
    assert probe.seed == ("uvx", "hub", "brief", "--write-cache", "--no-network")
    assert [argv for argv, _stdin in runner.calls] == [
        list(probe.seed),
        *[[str(a) for a in probe.argv]] * 3,
    ]
    assert [stdin for _argv, stdin in runner.calls] == [None, *[probe.stdin] * 3]
    assert list(samples) == pytest.approx([10.0, 20.0, 30.0])
    assert [p.path for p in hooks if p.seed is not None] == [probe.path]
