"""The read-only gate, run on the rendered ``readonly_gate.py`` (AGH-141).

The workspace is synthetic: a rendered demo hub at ``ws/demo-hub`` whose ``hub.json`` lists one
repo, ``app``, a git repo beside it; both are committed. The hook runs as Claude Code runs it, a
file on ``hook_python`` with a SubagentStart or SubagentStop event on stdin, from a folder outside
every hub, in an environment from scratch: ``HOME`` and ``TMPDIR`` under ``tmp_path`` (so the
gate's state stays there), a git identity of the test's own, no system git config, and the event
server's URL on a port nothing listens on. Agent definitions are written by the test; transcripts
are synthetic JSON lines.
"""

import hashlib
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

HOOK = "plugin/hub-workflow/hooks/readonly_gate.py"
SESSION = "s1"
STATE_PREFIX = "hub-readonly-"
# Where each agent definition folder is, relative to the hub (O-1).
HUB_AGENTS = ".claude/agents"
PROJECT_AGENTS = "plugin/demo/agents"
BASE_AGENTS = "plugin/hub-workflow/agents"
# A run of blanks inside a frontmatter value, well within the gate's 16 KiB of frontmatter.
BLANK_RUN = " " * 6000
# A state older than the gate's 12 h is stale.
STALE_AGE = 13 * 60 * 60

type RunEntryPoint = Callable[..., subprocess.CompletedProcess[bytes]]


@dataclass(frozen=True)
class GateWorkspace:
    """The workspace ``root`` (``ws``), its ``hub`` and ``app``, the gate's ``tmp`` and the env."""

    root: Path
    hub: Path
    app: Path
    tmp: Path
    home: Path
    env: Mapping[str, str]

    def git(self, *args: str, cwd: Path) -> None:
        git = shutil.which("git")
        assert git is not None
        subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
            [git, *args],
            cwd=cwd,
            check=True,
            capture_output=True,
            env={"PATH": os.environ.get("PATH", os.defpath), **self.env},
        )

    def commit_all(self, repo: Path) -> None:
        self.git("add", "-A", cwd=repo)
        self.git("commit", "-q", "--allow-empty", "-m", "test: snapshot", cwd=repo)


@pytest.fixture
def gate_ws(
    rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig, tmp_path: Path
) -> GateWorkspace:
    """``ws/demo-hub`` (hub.json lists ``app``) and ``ws/app``, both committed git repos."""
    hub = rendered_hub(demo_config).resolve()
    assert hub.name == "demo-hub"
    document = a_hub_document()
    document["repos"] = [{"dir": "app", "github": "acme/app"}]
    (hub / "hub.json").write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    home, temp = tmp_path / "home", tmp_path / "tmp"
    home.mkdir()
    temp.mkdir()
    git_config = tmp_path / "gitconfig"
    git_config.write_text(
        "[user]\n\tname = Test User\n\temail = test@example.com\n"
        "[init]\n\tdefaultBranch = main\n[commit]\n\tgpgsign = false\n",
        encoding="utf-8",
    )
    env = {
        "HOME": str(home),
        "TMPDIR": str(temp),
        "GIT_CONFIG_GLOBAL": str(git_config),
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    app = hub.parent / "app"
    app.mkdir()
    (app / "a.py").write_text("A = 1\n", encoding="utf-8")
    (app / ".gitignore").write_text("*.log\n.claude/worktrees/\n", encoding="utf-8")
    ws = GateWorkspace(root=hub.parent, hub=hub, app=app, tmp=temp, home=home, env=env)
    for repo in (hub, app):
        ws.git("init", "-q", cwd=repo)
        ws.commit_all(repo)
    return ws


class Gate:
    """Runs the rendered gate for a SubagentStart or SubagentStop event of one agent.

    Each run must exit 0 with an empty stderr (the fail-open backstop would hide an inner error);
    it returns the JSON object printed on stdout, or None when nothing was printed.
    """

    def __init__(
        self,
        ws: GateWorkspace,
        python: str,
        *,
        run_file: RunEntryPoint,
        run_with_constant: RunEntryPoint,
        elsewhere: Path,
    ) -> None:
        self.ws = ws
        self.python = python
        self.run_file = run_file
        self.run_with_constant = run_with_constant
        self.elsewhere = elsewhere

    def start(self, agent_type: str, **fields: Any) -> dict[str, Any] | None:
        return self.run("SubagentStart", agent_type, **fields)

    def stop(self, agent_type: str, **fields: Any) -> dict[str, Any] | None:
        return self.run("SubagentStop", agent_type, stop_hook_active=False, **fields)

    def run(
        self,
        event_name: str,
        agent_type: str,
        *,
        agent_id: str = "a1",
        constant: tuple[str, object] | None = None,
        **fields: Any,
    ) -> dict[str, Any] | None:
        event = {
            "hook_event_name": event_name,
            "session_id": SESSION,
            "cwd": str(self.ws.hub),
            "agent_id": agent_id,
            "agent_type": agent_type,
            **{
                key: str(value) if isinstance(value, Path) else value
                for key, value in fields.items()
            },
        }
        stdin = json.dumps(event).encode("utf-8")
        hook = self.ws.hub / HOOK
        if constant is None:
            completed = self.run_file(
                self.python, hook, stdin=stdin, cwd=self.elsewhere, env=self.ws.env
            )
        else:
            completed = self.run_with_constant(
                self.python,
                hook,
                constant=constant,
                stdin=stdin,
                cwd=self.elsewhere,
                env=self.ws.env,
            )
        stderr = completed.stderr.decode("utf-8", "replace")
        assert completed.returncode == 0, stderr
        assert stderr == ""
        stdout = completed.stdout.decode("utf-8")
        if not stdout.strip():
            return None
        output: dict[str, Any] = json.loads(stdout)
        return output


@pytest.fixture
def gate(
    gate_ws: GateWorkspace,
    hook_python: str,
    *,
    run_hook_file: RunEntryPoint,
    run_hook_with_constant: RunEntryPoint,
    tmp_path: Path,
) -> Gate:
    """The gate of ``gate_ws`` on ``hook_python``, run from a folder outside every hub."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return Gate(
        gate_ws,
        hook_python,
        run_file=run_hook_file,
        run_with_constant=run_hook_with_constant,
        elsewhere=elsewhere,
    )


def declare_agent(
    folder: Path,
    name: str,
    value: str | None,
    *,
    file: str | None = None,
    closed: bool = True,
) -> Path:
    """Write the agent ``name`` to ``folder/<file or name>.md``.

    ``value`` is its ``mutates_checkout`` (None: no such line); ``closed=False`` leaves the
    frontmatter without its closing ``---``.
    """
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["---", f"name: {name}", "description: A synthetic agent.", "tools: Read, Bash"]
    if value is not None:
        lines.append(f"mutates_checkout: {value}")
    if closed:
        lines.append("---")
    lines.append("")
    lines.append("Do what the prompt asks.")
    path = folder / f"{file or name}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def transcripts(
    ws: GateWorkspace, *, agent_id: str, calls: Iterable[tuple[str, Mapping[str, object]]] = ()
) -> tuple[Path, Path]:
    """The main transcript of ``SESSION`` and the agent's, each one ``tool_use`` line per call.

    The agent's is ``<main minus .jsonl>/subagents/agent-<agent_id>.jsonl``, as Claude Code
    writes it; both hold synthetic lines only.
    """
    main = ws.home / ".claude" / "projects" / "ws" / f"{SESSION}.jsonl"
    agent = main.with_suffix("") / "subagents" / f"agent-{agent_id}.jsonl"
    agent.parent.mkdir(parents=True, exist_ok=True)
    first = json.dumps({"type": "user", "message": {"role": "user", "content": "go"}})
    main.write_text(first + "\n", encoding="utf-8")
    lines = [first]
    for tool, tool_input in calls:
        call = {"type": "tool_use", "name": tool, "input": dict(tool_input)}
        lines.append(json.dumps({"type": "assistant", "message": {"content": [call]}}))
    agent.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return main, agent


def state_files(ws: GateWorkspace) -> list[str]:
    """The gate's files in ``TMPDIR`` (state, counter, record), sorted."""
    return sorted(name for name in os.listdir(ws.tmp) if name.startswith(STATE_PREFIX))


def state_name(agent_id: str) -> str:
    return f"{STATE_PREFIX}{SESSION}-{agent_id}.json"


def read_state(ws: GateWorkspace, agent_id: str) -> dict[str, Any]:
    state: dict[str, Any] = json.loads((ws.tmp / state_name(agent_id)).read_text(encoding="utf-8"))
    return state


def change_app(ws: GateWorkspace) -> None:
    """Change a tracked file of the watched repo ``app``."""
    (ws.app / "a.py").write_text("A = 2\n", encoding="utf-8")


@pytest.mark.parametrize(
    ("agent_type", "folder", "value", "closed"),
    [
        pytest.param("scout", HUB_AGENTS, None, True, id="no_key"),
        pytest.param("scout", HUB_AGENTS, "true", True, id="key_true"),
        pytest.param("ghost", HUB_AGENTS, "false", True, id="not_found"),
        pytest.param("scout", BASE_AGENTS, "false", False, id="unclosed_frontmatter"),
        pytest.param("", HUB_AGENTS, "false", True, id="empty_type"),
        pytest.param("scout", HUB_AGENTS, "false" + BLANK_RUN + "x", True, id="long_blank_run"),
    ],
)
def test_writes_no_state_when_agent_undeclared(
    gate: Gate,
    gate_ws: GateWorkspace,
    *,
    agent_type: str,
    folder: str,
    value: str | None,
    closed: bool,
) -> None:
    """AC-141.3: an undeclared agent leaves no state and prints nothing, even over a change."""
    declare_agent(gate_ws.hub / folder, "scout", value, closed=closed)

    assert gate.start(agent_type, agent_id="u1") is None
    assert state_files(gate_ws) == []
    change_app(gate_ws)
    assert gate.stop(agent_type, agent_id="u1") is None
    assert state_files(gate_ws) == []

    # Control: the base plugin's researcher, in the same hub, is declared and gets a state.
    assert gate.start("researcher", agent_id="r1") is None
    assert state_files(gate_ws) == [state_name("r1")]


@pytest.mark.parametrize(
    "folder",
    [
        pytest.param(HUB_AGENTS, id="hub_agents"),
        pytest.param(PROJECT_AGENTS, id="project_plugin"),
        pytest.param(BASE_AGENTS, id="base_plugin"),
    ],
)
def test_snapshots_when_resolve_finds_declared_agent(
    gate: Gate, gate_ws: GateWorkspace, folder: str
) -> None:
    """AC-141.4: a declared agent in any one location, matched by its frontmatter ``name`` in a
    file named otherwise, gets a start state."""
    declare_agent(gate_ws.hub / folder, "scout", "false", file="read-only-scout")
    assert not any(
        (gate_ws.hub / place / "scout.md").exists()
        for place in (HUB_AGENTS, PROJECT_AGENTS, BASE_AGENTS)
    )

    assert gate.start("scout", agent_id="a1") is None

    assert state_files(gate_ws) == [state_name("a1")]
    state = read_state(gate_ws, "a1")
    assert (state["v"], state["agent_type"], state["agent_id"], state["session_id"]) == (
        1,
        "scout",
        "a1",
        SESSION,
    )


def test_uses_first_location_when_resolve_finds_name_twice(
    gate: Gate, gate_ws: GateWorkspace
) -> None:
    """O-1: the hub's ``.claude/agents`` comes first; its definition wins even without the key."""
    declare_agent(gate_ws.hub / BASE_AGENTS, "scout", "false")
    assert gate.start("scout", agent_id="a0") is None
    assert state_files(gate_ws) == [state_name("a0")]  # control: declared while alone

    declare_agent(gate_ws.hub / HUB_AGENTS, "scout", None, file="other-scout")
    assert gate.start("scout", agent_id="a1") is None

    assert state_files(gate_ws) == [state_name("a0")]


@pytest.mark.parametrize(
    ("agent_type", "declared_in", "expected"),
    [
        pytest.param("hub-workflow:scout", BASE_AGENTS, True, id="hub_workflow"),
        pytest.param("demo:scout", PROJECT_AGENTS, True, id="project"),
        pytest.param("acme:scout", None, False, id="other"),
    ],
)
def test_strips_plugin_prefix_when_resolve_reads_namespaced_type(
    gate: Gate, gate_ws: GateWorkspace, *, agent_type: str, declared_in: str | None, expected: bool
) -> None:
    """O-1: a ``hub-workflow:`` type is looked up in the base plugin only, a project-name prefix in
    the project plugin only, and any other prefix in none. Every other folder holds an undeclared
    ``scout`` (for ``other``, every folder holds a declared one)."""
    for folder in (HUB_AGENTS, PROJECT_AGENTS, BASE_AGENTS):
        value = "false" if declared_in in (folder, None) else None
        declare_agent(gate_ws.hub / folder, "scout", value)

    assert gate.start(agent_type, agent_id="a1") is None

    assert state_files(gate_ws) == ([state_name("a1")] if expected else [])
    if expected:
        assert read_state(gate_ws, "a1")["agent_type"] == agent_type
    else:  # control: the same definitions, without the prefix, are declared
        assert gate.start("scout", agent_id="a2") is None
        assert state_files(gate_ws) == [state_name("a2")]


def test_keeps_first_snapshot_when_start_repeats_for_same_agent(
    gate: Gate, gate_ws: GateWorkspace
) -> None:
    """E-1: SubagentStart fires again when the agent resumes; the first state is the baseline."""
    main, _ = transcripts(gate_ws, agent_id="a1")
    first_size = main.stat().st_size
    assert gate.start("researcher", agent_id="a1", transcript_path=main) is None
    path = gate_ws.tmp / state_name("a1")
    before = path.read_bytes(), path.stat().st_ino
    assert json.loads(before[0])["main_offset"] == first_size

    with main.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"type": "user", "message": {"role": "user", "content": "more"}}) + "\n"
        )
    change_app(gate_ws)
    assert gate.start("researcher", agent_id="a1", transcript_path=main) is None

    assert (path.read_bytes(), path.stat().st_ino) == before
    assert state_files(gate_ws) == [state_name("a1")]


def test_replaces_snapshot_when_start_state_stale(gate: Gate, gate_ws: GateWorkspace) -> None:
    """E-1: a state older than 12 h is not this run's baseline; a new start replaces it."""
    main, _ = transcripts(gate_ws, agent_id="a1")
    assert gate.start("researcher", agent_id="a1", transcript_path=main) is None
    path = gate_ws.tmp / state_name("a1")
    old = time.time() - STALE_AGE
    os.utime(path, (old, old))
    inode = path.stat().st_ino

    with main.open("a", encoding="utf-8") as stream:
        stream.write(
            json.dumps({"type": "user", "message": {"role": "user", "content": "more"}}) + "\n"
        )
    assert gate.start("researcher", agent_id="a1", transcript_path=main) is None

    assert path.stat().st_ino != inode
    assert path.stat().st_mtime > old + STALE_AGE / 2
    assert read_state(gate_ws, "a1")["main_offset"] == main.stat().st_size
    assert state_files(gate_ws) == [state_name("a1")]


def test_replaces_snapshot_when_start_state_unreadable(gate: Gate, gate_ws: GateWorkspace) -> None:
    """E-1: a fresh state that is not the gate's JSON is no baseline; a new start replaces it."""
    path = gate_ws.tmp / state_name("a1")
    path.write_text("{not json", encoding="utf-8")

    assert gate.start("researcher", agent_id="a1") is None

    state = read_state(gate_ws, "a1")
    assert (state["v"], state["agent_type"], state["agent_id"]) == (1, "researcher", "a1")
    assert state_files(gate_ws) == [state_name("a1")]


def test_snapshots_when_resolve_reads_comment_after_long_blank_run(
    gate: Gate, gate_ws: GateWorkspace
) -> None:
    """A long run of blanks before a ``# comment`` is dropped with it, in ``name`` and the key."""
    name, value = "scout" + BLANK_RUN + "# the scout", "false" + BLANK_RUN + "# why"
    declare_agent(gate_ws.hub / HUB_AGENTS, name, value, file="scout")

    assert gate.start("scout", agent_id="a1") is None

    assert state_files(gate_ws) == [state_name("a1")]


def outside_tmpdir(tmp_path: Path, ws: GateWorkspace) -> set[Path]:
    """Every path under ``tmp_path`` but the gate's TMPDIR and the hooks' bytecode caches."""
    return {
        path
        for path in tmp_path.rglob("*")
        if ws.tmp not in path.parents and "__pycache__" not in path.parts
    }


def hashed(value: str) -> str:
    """The gate's file name part for an id that is not plain: ``h`` + 16 hex of its sha256."""
    return "h" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]


@pytest.mark.parametrize(
    ("session_id", "agent_id", "expected"),
    [
        pytest.param(
            SESSION, "../../escape", f"{SESSION}-{hashed('../../escape')}", id="traversal"
        ),
        pytest.param("s/1", "a1", f"{hashed('s/1')}-a1", id="slash"),
        pytest.param(SESSION, "x" * 65, f"{SESSION}-{hashed('x' * 65)}", id="too_long"),
        pytest.param(7, "a1", f"{hashed('')}-a1", id="non_str_session"),
    ],
)
def test_hashes_id_when_start_reads_unsafe_id(
    gate: Gate,
    gate_ws: GateWorkspace,
    tmp_path: Path,
    *,
    session_id: object,
    agent_id: str,
    expected: str,
) -> None:
    """An id that is not ``[A-Za-z0-9_-]{1,64}`` names the state by its hash, inside TMPDIR."""
    before = outside_tmpdir(tmp_path, gate_ws)

    assert gate.start("researcher", agent_id=agent_id, session_id=session_id) is None

    assert sorted(os.listdir(gate_ws.tmp)) == [f"{STATE_PREFIX}{expected}.json"]
    assert outside_tmpdir(tmp_path, gate_ws) - before == set()


BLOCK_HEAD = (
    "[hub readonly-gate] researcher (agent a1) is read-only (mutates_checkout: false) but changed:"
)
REVERT = "Revert these changes, or explain in your final report why each one was needed."


def git_output(ws: GateWorkspace, *args: str, cwd: Path) -> str:
    """git's stdout in ``cwd``, run in the workspace's environment, without its last newline."""
    git = shutil.which("git")
    assert git is not None
    completed = subprocess.run(  # noqa: S603 - git found on PATH, fixed arguments
        [git, *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        env={"PATH": os.environ.get("PATH", os.defpath), **ws.env},
    )
    return completed.stdout.decode("utf-8").rstrip("\n")


def run_researcher(gate: Gate, change: Callable[[], object]) -> dict[str, Any] | None:
    """Start the researcher ``a1`` (empty readable transcripts), run ``change``, stop it.

    The start must be silent and save the state; the stop's output is returned.
    """
    main, agent = transcripts(gate.ws, agent_id="a1")
    assert gate.start("researcher", agent_id="a1", transcript_path=main) is None
    assert state_files(gate.ws) == [state_name("a1")]
    change()
    return gate.stop("researcher", agent_id="a1", transcript_path=main, agent_transcript_path=agent)


def block_lines(output: dict[str, Any] | None) -> list[str]:
    """The reason's lines of a block (asserting it is one, with its header and its ask)."""
    assert output is not None
    assert output["decision"] == "block"
    lines: list[str] = output["reason"].splitlines()
    assert lines[0] == BLOCK_HEAD
    assert REVERT in lines
    return lines


def move_tmpdir_into_app(gate: Gate) -> None:
    """Point the gate's TMPDIR at ``app/gate-tmp``: inside the watched repo, not gitignored."""
    ws = gate.ws
    tmp = ws.app / "gate-tmp"
    tmp.mkdir()
    gate.ws = GateWorkspace(
        root=ws.root,
        hub=ws.hub,
        app=ws.app,
        tmp=tmp,
        home=ws.home,
        env={**ws.env, "TMPDIR": str(tmp)},
    )


@pytest.mark.parametrize(
    "case", ["nothing", "hub_brain", "hub_inbox", "gitignored", "state_dir_in_app"]
)
def test_stays_silent_when_run_clean(gate: Gate, gate_ws: GateWorkspace, case: str) -> None:
    """AC-141.5, E-11: nothing changed, or only the hub's ``brain/`` (tracked or new), a
    gitignored file, or the gate's own state in a TMPDIR inside the repo: silent, state deleted."""
    if case == "state_dir_in_app":
        move_tmpdir_into_app(gate)
    changes: dict[str, Callable[[], object]] = {
        "nothing": lambda: None,
        "hub_brain": lambda: (gate_ws.hub / "brain" / "now.md").write_text(
            "# Now\n\nEdited by the agent.\n", encoding="utf-8"
        ),
        "hub_inbox": lambda: (gate_ws.hub / "brain" / "_inbox" / "note.md").write_text(
            "A note.\n", encoding="utf-8"
        ),
        "gitignored": lambda: (gate_ws.app / "run.log").write_text("log\n", encoding="utf-8"),
        "state_dir_in_app": lambda: None,
    }

    def change() -> None:
        changes[case]()
        if case == "state_dir_in_app":  # control: git does see the state as a new file
            status = git_output(gate_ws, "status", "--porcelain", "-uall", cwd=gate_ws.app)
            assert f"?? gate-tmp/{state_name('a1')}" in status.splitlines()

    assert run_researcher(gate, change) is None

    assert state_files(gate.ws) == []


def test_deletes_state_when_run_clean(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.5: a clean stop removes the start state and prints nothing."""
    assert run_researcher(gate, lambda: None) is None

    assert state_files(gate_ws) == []
    assert not (gate_ws.tmp / state_name("a1")).exists()


def test_blocks_when_dirty_before_file_changed_again(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.8: a file already dirty at start and changed again is a changed path."""
    change_app(gate_ws)

    lines = block_lines(
        run_researcher(gate, lambda: (gate_ws.app / "a.py").write_text("A = 3\n", encoding="utf-8"))
    )

    assert "- app/a.py" in lines


def test_stays_silent_when_dirty_before_file_untouched(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.8: a file dirty before the start and left alone is not named."""
    change_app(gate_ws)
    status = git_output(gate_ws, "status", "--porcelain", cwd=gate_ws.app)
    assert status.splitlines() == [" M a.py"]  # control: dirty at start

    assert run_researcher(gate, lambda: None) is None

    assert state_files(gate_ws) == []


def test_names_head_moved_when_agent_commits(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.8: a commit is named as the repo's HEAD change."""
    old = git_output(gate_ws, "rev-parse", "HEAD", cwd=gate_ws.app)

    def commit() -> None:
        change_app(gate_ws)
        gate_ws.commit_all(gate_ws.app)

    lines = block_lines(run_researcher(gate, commit))

    new = git_output(gate_ws, "rev-parse", "HEAD", cwd=gate_ws.app)
    assert new != old
    assert f"- app: HEAD {old[:7]} (main) -> {new[:7]} (main)" in lines
    assert "- app/a.py" not in lines  # committed: the tree is clean again


def test_names_head_moved_when_agent_switches_branch(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.8: a branch switch is named, even when HEAD's commit stays the same."""
    old = git_output(gate_ws, "rev-parse", "HEAD", cwd=gate_ws.app)

    lines = block_lines(
        run_researcher(gate, lambda: gate_ws.git("checkout", "-q", "-b", "side", cwd=gate_ws.app))
    )

    assert f"- app: HEAD {old[:7]} (main) -> {old[:7]} (side)" in lines


def test_blocks_when_no_overlap_block_index_only_change(gate: Gate, gate_ws: GateWorkspace) -> None:
    """E-7: staging a file already dirty changes no content, but the index counts."""
    change_app(gate_ws)
    content = (gate_ws.app / "a.py").read_bytes()

    lines = block_lines(run_researcher(gate, lambda: gate_ws.git("add", "a.py", cwd=gate_ws.app)))

    assert (gate_ws.app / "a.py").read_bytes() == content
    assert git_output(gate_ws, "status", "--porcelain", cwd=gate_ws.app).splitlines() == ["M  a.py"]
    assert "- app/a.py" in lines


def test_blocks_when_dirty_before_file_mode_changed(gate: Gate, gate_ws: GateWorkspace) -> None:
    """E-7: ``chmod +x`` on a file already dirty changes no content, but its mode counts."""
    change_app(gate_ws)
    content = (gate_ws.app / "a.py").read_bytes()

    lines = block_lines(run_researcher(gate, lambda: (gate_ws.app / "a.py").chmod(0o755)))

    assert (gate_ws.app / "a.py").read_bytes() == content
    assert git_output(gate_ws, "status", "--porcelain", cwd=gate_ws.app).splitlines() == [" M a.py"]
    assert "- app/a.py" in lines


def test_blocks_when_dirty_before_file_staged_other_blob(
    gate: Gate, gate_ws: GateWorkspace
) -> None:
    """E-7: on a file staged and dirty (``MM``), staging another blob keeps its status and its
    content, but the index counts."""
    target = gate_ws.app / "a.py"
    target.write_text("A = 2\n", encoding="utf-8")
    gate_ws.git("add", "a.py", cwd=gate_ws.app)
    change_app(gate_ws)
    target.write_text("A = 3\n", encoding="utf-8")
    assert git_output(gate_ws, "status", "--porcelain", cwd=gate_ws.app).splitlines() == ["MM a.py"]
    staged = git_output(gate_ws, "rev-parse", ":a.py", cwd=gate_ws.app)

    def stage_other() -> None:
        target.write_text("A = 4\n", encoding="utf-8")
        gate_ws.git("add", "a.py", cwd=gate_ws.app)
        target.write_text("A = 3\n", encoding="utf-8")

    lines = block_lines(run_researcher(gate, stage_other))

    assert target.read_text(encoding="utf-8") == "A = 3\n"
    assert git_output(gate_ws, "status", "--porcelain", cwd=gate_ws.app).splitlines() == ["MM a.py"]
    assert git_output(gate_ws, "rev-parse", ":a.py", cwd=gate_ws.app) != staged
    assert "- app/a.py" in lines


def test_blocks_when_new_file_at_hub_root(gate: Gate, gate_ws: GateWorkspace) -> None:
    """AC-141.5 control: the hub is watched, so a new file at its root (outside ``brain/``) is
    a changed path; the silent ``hub_brain`` and ``hub_inbox`` runs are drops, not blind spots."""
    lines = block_lines(
        run_researcher(
            gate, lambda: (gate_ws.hub / "notes.txt").write_text("x\n", encoding="utf-8")
        )
    )

    status = git_output(gate_ws, "status", "--porcelain", "-uall", cwd=gate_ws.hub)
    assert "?? notes.txt" in status.splitlines()  # control: not gitignored
    assert f"- {gate_ws.hub.name}/notes.txt" in lines
