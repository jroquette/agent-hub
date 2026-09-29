"""The six rendered hook entry points fail open: whatever the input or the hub, they exit 0,
print nothing or one JSON object, and never a traceback (AC-4.11).

Each hook runs as Claude Code runs it: a file on ``hook_python`` with the input on stdin, in an
environment built from scratch (``HOME`` and ``TMPDIR`` under ``tmp_path``).
"""

import json
import shutil
import subprocess
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

HOOKS = "plugin/hub-workflow/hooks"
ENTRY_POINTS = ("guard", "post_edit", "stop_gate", "session_start", "session_end", "pre_compact")
# Where Claude Code's plugin cache would hold the hooks: no hub.json three folders up.
PLUGIN_CACHE = "home/.claude/plugins/cache/agent-hub/hub-workflow/0.1.0/hooks"
# The hub states of AC-4.11.
NO_HUB, NO_HUB_JSON, MALFORMED, VALID = "no_hub", "no_hub_json", "malformed", "valid"
# AC-4.11's stdins; "event" is a valid event of the hook, "wrong_types" one whose every field
# has the wrong type (carried review item: a non-str ``old_string`` crashed the guard).
FIXED_STDINS: dict[str, bytes] = {
    "empty": b"",
    "list": b"[]",
    "string": b'"x"',
    "invalid_utf8": b"\xff",
    "object": b"{}",
}
# Events whose tool fields (or cwd) have the wrong type; the hooks read each as absent. One
# replaces a test file that is not UTF-8 (``NON_UTF8_TEST``, written by the test).
NON_UTF8_TEST = "tests/test_bad.py"


def tool_field_events(at: Path) -> dict[str, dict[str, Any]]:
    test_file = str(at / "tests" / "test_a.py")
    tool_inputs: dict[str, tuple[str, dict[str, Any]]] = {
        "bash_command": ("Bash", {"command": ["rm", "-rf"]}),
        "file_paths": ("Edit", {"file_path": ["x"], "notebook_path": 3, "path": {}}),
        "edit_strings": ("Edit", {"file_path": test_file, "old_string": 1, "new_string": 2}),
        "write_content": ("Write", {"file_path": test_file, "content": 5}),
        "multiedit_edits": (
            "MultiEdit",
            {"file_path": test_file, "edits": [None, 1, {"old_string": 2, "new_string": None}]},
        ),
        "multiedit_null": ("MultiEdit", {"file_path": test_file, "edits": None}),
        "grep_glob": ("Grep", {"glob": 5, "path": str(at)}),
        "webfetch_url": ("WebFetch", {"url": 5, "prompt": "x"}),
        "write_non_utf8": ("Write", {"file_path": str(at / NON_UTF8_TEST), "content": "x"}),
    }
    events: dict[str, dict[str, Any]] = {
        name: {"tool_name": tool, "tool_input": tool_input, "cwd": str(at)}
        for name, (tool, tool_input) in tool_inputs.items()
    }
    # a cwd that is not a string: the walk and the stop gate read it as absent
    return events | {"cwd_number": {"tool_name": "Bash", "tool_input": {"command": "ls"}, "cwd": 5}}


# Read as they are, never through an exception: AC-4.11's stdins, a valid event and the guard's
# wrong-typed tool fields.
HANDLED = frozenset({*FIXED_STDINS, "event", *tool_field_events(Path("/"))})
# What the guard prints when it turned an exception into an ask (never for a handled input).
GUARD_CRASH = b"could not check this call"
TRACEBACK = b"Traceback (most recent call last)"
FAILING_GIT = "#!/bin/sh\necho 'fatal: not a git repository' >&2\nexit 128\n"

type RunHook = Callable[..., subprocess.CompletedProcess[bytes]]


def valid_event(name: str, hub: Path) -> dict[str, Any]:
    """An event of hook ``name`` at ``hub``, as Claude Code sends it."""
    base = {"session_id": "abcdef123456", "cwd": str(hub), "transcript_path": ""}
    extra: dict[str, dict[str, Any]] = {
        "guard": {"tool_name": "Bash", "tool_input": {"command": "git push origin main"}},
        "post_edit": {"tool_name": "Write", "tool_input": {"file_path": str(hub / "notes.py")}},
        "stop_gate": {},
        "session_start": {"source": "compact"},
        "session_end": {"reason": "clear"},
        "pre_compact": {"trigger": "manual"},
    }
    return base | extra[name]


def wrong_types_event(hub: Path) -> dict[str, Any]:
    tool_input = {"file_path": str(hub / "tests" / "test_a.py"), "old_string": 1, "edits": 2}
    return {
        "tool_name": "Edit",
        "tool_input": tool_input,
        "cwd": 5,
        "session_id": [],
        "transcript_path": 7,
        "source": {},
        "reason": None,
    }


def stdins(name: str, hub: Path) -> dict[str, bytes]:
    return (
        FIXED_STDINS
        | {
            "event": json.dumps(valid_event(name, hub)).encode(),
            "wrong_types": json.dumps(wrong_types_event(hub)).encode(),
            "wrong_tool_input": json.dumps(
                {"tool_name": "Edit", "tool_input": ["x"], "cwd": str(hub)}
            ).encode(),
        }
        | {name: json.dumps(event).encode() for name, event in tool_field_events(hub).items()}
    )


def problems_of(
    completed: subprocess.CompletedProcess[bytes], *, handled: bool = False
) -> list[str]:
    """What breaks AC-4.11 in one run: exit code, a traceback, stdout not empty or one object.

    ``handled``: the input is one the hook reads as it is (AC-4.11's own stdins, a valid event),
    so it must not even print the ``skipped`` line of an exception it turned into exit 0.
    """
    found = []
    if handled and completed.stderr:
        found.append(f"stderr: {completed.stderr.decode(errors='replace')[-300:]}")
    if handled and GUARD_CRASH in completed.stdout:
        found.append(f"guard crashed: {completed.stdout.decode(errors='replace')[-300:]}")
    if completed.returncode != 0:
        found.append(f"exit {completed.returncode}")
    if TRACEBACK in completed.stderr:
        found.append(f"traceback: {completed.stderr.decode(errors='replace')[-300:]}")
    if completed.stdout.strip():
        try:
            output = json.loads(completed.stdout)
        except ValueError:
            output = None
        if not isinstance(output, dict):
            found.append(f"stdout is not one JSON object: {completed.stdout[:200]!r}")
    return found


def scratch_env(tmp_path: Path) -> dict[str, str]:
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir(exist_ok=True)
    temp.mkdir(exist_ok=True)
    return {"HOME": str(home), "TMPDIR": str(temp)}


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub at ``ws/demo-hub``, without a ``hub.json``."""
    return rendered_hub(demo_config).resolve()


def valid_hub_json(hub: Path) -> None:
    """The builder's document, with a host to deny so the guard's host rules run."""
    document = a_hub_document()
    document["guard"]["deny_hosts"] = ["prod.example.com"]
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")


def hooks_in_state(state: str, *, hub: Path, tmp_path: Path, config: HubConfig) -> Path:
    """The hooks folder to run for hub ``state`` (the hub's own, or a plugin-cache copy)."""
    if state == NO_HUB:
        cache = tmp_path / PLUGIN_CACHE
        for file in render_hub(config).files:
            if file.path.startswith(f"{HOOKS}/"):
                target = cache / Path(file.path).name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(file.content)
        return cache
    if state == MALFORMED:
        (hub / "hub.json").write_bytes(b'{"project": {"name": ')
    elif state == VALID:
        valid_hub_json(hub)
    (hub / "notes.py").write_text("x = 1\n", encoding="utf-8")
    return hub / HOOKS


def write_non_utf8_test(at: Path) -> None:
    path = at / NON_UTF8_TEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"assert x\n\xff\n")


@pytest.mark.parametrize("state", [NO_HUB, NO_HUB_JSON, MALFORMED, VALID])
@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_exits_zero_without_traceback_when_input_or_hub_broken(
    name: str,
    state: str,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    demo_config: HubConfig,
    tmp_path: Path,
) -> None:
    hooks = hooks_in_state(state, hub=hub, tmp_path=tmp_path, config=demo_config)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    at = elsewhere if state == NO_HUB else hub
    write_non_utf8_test(at)

    problems = {
        stdin_name: found
        for stdin_name, stdin in stdins(name, at).items()
        if (
            found := problems_of(
                run_hook_file(
                    hook_python,
                    hooks / f"{name}.py",
                    stdin=stdin,
                    cwd=at,
                    env=scratch_env(tmp_path),
                ),
                handled=stdin_name in HANDLED,
            )
        )
    }

    assert problems == {}


@pytest.mark.parametrize("name", ENTRY_POINTS)
def test_exits_zero_when_git_fails(
    name: str, *, hub: Path, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    valid_hub_json(hub)
    (hub / "notes.py").write_text("x = 1\n", encoding="utf-8")
    for checkout in (hub, hub.parent / "demo-api"):
        (checkout / ".git").mkdir(parents=True)
    (hub.parent / "demo-api" / "a.py").write_text("x = 1\n", encoding="utf-8")
    fake = tmp_path / "bin" / "git"
    fake.parent.mkdir()
    fake.write_text(FAILING_GIT, encoding="utf-8")
    fake.chmod(0o755)
    env = scratch_env(tmp_path) | {"PATH": f"{fake.parent}:/usr/bin:/bin"}

    completed = run_hook_file(
        hook_python,
        hub / HOOKS / f"{name}.py",
        stdin=json.dumps(valid_event(name, hub)).encode(),
        cwd=hub,
        env=env,
    )

    assert problems_of(completed, handled=True) == []


def make_read_only(hub: Path) -> None:
    for folder in sorted((hub / "brain").rglob("*"), reverse=True):
        if folder.is_dir():
            folder.chmod(0o555)
    (hub / "brain").chmod(0o555)


def make_writable(hub: Path) -> None:
    (hub / "brain").chmod(0o755)
    for folder in (hub / "brain").rglob("*"):
        if folder.is_dir():
            folder.chmod(0o755)


# The folder each hook writes into; "blocked" puts a file there, which fails for root too.
OUTPUT_FOLDERS = {"session_end": "brain/_inbox/sessions", "pre_compact": "brain/auto/workspace"}


@pytest.mark.parametrize("variant", ["read_only", "blocked"])
@pytest.mark.parametrize("name", sorted(OUTPUT_FOLDERS))
def test_exits_zero_when_hub_unwritable(
    name: str,
    variant: str,
    *,
    hub: Path,
    hook_python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
) -> None:
    valid_hub_json(hub)
    folder = hub / OUTPUT_FOLDERS[name]
    if variant == "blocked":
        folder.parent.mkdir(parents=True, exist_ok=True)
        folder.write_text("in the way\n", encoding="utf-8")
    else:
        make_read_only(hub)

    try:
        completed = run_hook_file(
            hook_python,
            hub / HOOKS / f"{name}.py",
            stdin=json.dumps(valid_event(name, hub)).encode(),
            cwd=hub,
            env=scratch_env(tmp_path),
        )
    finally:
        make_writable(hub)

    assert problems_of(completed) == []
    assert completed.stdout == b""
    if variant == "blocked":  # the hook says it could not write, and nothing else
        assert completed.stderr == f"[hub {name}] not written: FileExistsError\n".encode()


def git_repo(path: Path, env: Mapping[str, str]) -> None:
    git = shutil.which("git")
    assert git is not None
    path.mkdir(parents=True)
    subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
        [git, "init", "-q"], cwd=path, check=True, capture_output=True, env=env
    )


def run_failing_stop_gate(
    *,
    hub: Path,
    python: str,
    run_hook_file: RunHook,
    tmp_path: Path,
    counter_blocked: bool,
    counter: bytes | None = None,
) -> subprocess.CompletedProcess[bytes]:
    """The stop gate after a code change in ``demo-api``, whose ``check_fast`` fails; the block
    counter file holds ``counter`` when given."""
    document = a_hub_document()
    document["repos"] = [{"dir": "demo-api", "check_fast": "echo boom; exit 3"}]
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    env = scratch_env(tmp_path)
    git_repo(hub.parent / "demo-api", env)
    (hub.parent / "demo-api" / "a.py").write_text("x = 1\n", encoding="utf-8")
    session = f"fail-open-{counter_blocked}"
    if counter_blocked:  # the block counter cannot be written: its path is a folder
        (tmp_path / "tmp" / f"hub-stop-{session}.json").mkdir()
    elif counter is not None:
        (tmp_path / "tmp" / f"hub-stop-{session}.json").write_bytes(counter)
    return run_hook_file(
        python,
        hub / HOOKS / "stop_gate.py",
        stdin=json.dumps({"cwd": str(hub), "session_id": session}).encode(),
        cwd=hub,
        env=env,
    )


def test_outputs_block_when_stop_gate_blocks(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    completed = run_failing_stop_gate(
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        tmp_path=tmp_path,
        counter_blocked=False,
    )

    assert problems_of(completed, handled=True) == []
    output = json.loads(completed.stdout)
    assert output["decision"] == "block"
    assert "boom" in output["reason"]


@pytest.mark.parametrize(
    "counter",
    [b"[]", b'"x"', b'{"blocks": "x"}', b'{"blocks": null}', b'{"blocks": true}', b"\xff"],
)
def test_blocks_when_stop_counter_malformed(
    counter: bytes, *, hub: Path, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    completed = run_failing_stop_gate(
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        tmp_path=tmp_path,
        counter_blocked=False,
        counter=counter,
    )

    assert problems_of(completed, handled=True) == []
    output = json.loads(completed.stdout)
    assert output["decision"] == "block"
    assert json.loads((tmp_path / "tmp" / "hub-stop-fail-open-False.json").read_text()) == {
        "blocks": 1
    }


def test_warns_without_block_when_stop_counter_unwritable(
    hub: Path, *, hook_python: str, run_hook_file: RunHook, tmp_path: Path
) -> None:
    # Owner decision (2026-09-29): without its counter the gate cannot release after 3 blocks,
    # so it fails open: no block, a warning that check_fast still fails.
    completed = run_failing_stop_gate(
        hub=hub,
        python=hook_python,
        run_hook_file=run_hook_file,
        tmp_path=tmp_path,
        counter_blocked=True,
    )

    assert problems_of(completed, handled=True) == []
    output = json.loads(completed.stdout)
    assert "decision" not in output
    assert output["systemMessage"].startswith(
        "[hub stop-gate] check_fast still failing and the block counter could not be saved; "
        "finishing anyway. Do not claim the work is done."
    )
    assert "boom" in output["systemMessage"]
