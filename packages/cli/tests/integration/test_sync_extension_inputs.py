"""``hub sync`` and ``hub init`` with the project's extension inputs (spec D2, Q-17, Q-18, Q-20).

A ``.claude/settings.project.json`` sibling merges into ``.claude/settings.json`` at both commands;
a bad sibling exits 1 with one line and writes nothing. Agents and skills under ``plugin/demo/`` get
a managed link at the next sync; a name the base plugin also has is a conflict (exit 3), and a
name ``hub.lock`` cannot hold exits 1 (plan E9). ``init`` still refuses project entries (Q-22).
"""

import hashlib
import json
import os
import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner, Result

from agent_hub.cli.main import app
from agent_hub.cli.sync_report import CONFLICT_WAY_OUT
from agent_hub.core.json_form import dump_json

# The conftest's tree digest and in-process sync (tests cannot import a conftest in importlib
# mode).
type TreeDigest = Callable[[Path], dict[str, Any]]
type SyncRunner = Callable[..., Result]
SIBLING = ".claude/settings.project.json"
SETTINGS = ".claude/settings.json"
ADDITION = b'{"permissions": {"allow": ["Bash(make *)"]}, "env": {"X": "1"}}'
REFUSED = "refused: a project cannot set this key (it weakens the harness)"
# AC-14.24's eight siblings and the one line each gives, after the sibling's path.
BAD_SIBLINGS = [
    pytest.param(
        b"{",
        "$: not valid JSON: Expecting property name enclosed in double quotes at line 1 column 2",
        id="invalid-json",
    ),
    pytest.param(b"\xff{}", "$: not UTF-8 text: byte 0 cannot be decoded", id="not-utf8"),
    pytest.param(b"[]", "$: an array where the template has an object", id="array-root"),
    pytest.param(
        b'{"permissions": {"allow": "x"}}',
        "permissions.allow: a string where the template has an array",
        id="scalar-for-array",
    ),
    pytest.param(
        b'{"hooks": []}', "hooks: an array where the template has an object", id="array-for-object"
    ),
    pytest.param(
        b'{"env": {"A": null}}', "env.A: null is refused: the merge never deletes a key", id="null"
    ),
    pytest.param(b'{"disableAllHooks": false}', f"disableAllHooks: {REFUSED}", id="hooks-off"),
    pytest.param(
        b'{"permissions": {"defaultMode": "plan"}}',
        f"permissions.defaultMode: {REFUSED}",
        id="default-mode",
    ),
]


def run_init(config: Path, target: Path) -> Result:
    return CliRunner().invoke(app, ["init", "--config", str(config), "--dir", str(target)])


def a_target(tmp_path: Path, files: dict[str, bytes]) -> Path:
    """An ``init`` target folder holding only ``files``."""
    root = tmp_path / "target"
    for path, content in files.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_bytes(content)
    return root


def failure_lines(result: Result, *, code: int = 1) -> list[str]:
    assert result.exit_code == code, result.output
    assert result.stdout == ""
    return result.stderr.splitlines()


def success_lines(result: Result) -> list[str]:
    assert result.exit_code == 0, result.output
    assert result.stderr == ""
    return result.stdout.splitlines()


def merged_settings(template: Path) -> bytes:
    """The template's settings with ``ADDITION``: its allows first, then ``Bash(make *)``."""
    value = json.loads((template / SETTINGS).read_bytes())
    value["permissions"]["allow"].append("Bash(make *)")
    value["env"] = {"X": "1"}
    return dump_json(value)


def lock_entry(root: Path, path: str) -> dict[str, Any]:
    entry: dict[str, Any] = json.loads((root / "hub.lock").read_bytes())["files"][path]
    return entry


def sha256_of(root: Path, path: str) -> str:
    return hashlib.sha256((root / path).read_bytes()).hexdigest()


@pytest.mark.parametrize(("content", "problem"), BAD_SIBLINGS)
def test_refuses_sibling_when_malformed_or_weakening(
    demo_hub: Path,
    demo_config_file: Path,
    run_sync: SyncRunner,
    *,
    tmp_path: Path,
    tree_digest: TreeDigest,
    content: bytes,
    problem: str,
) -> None:
    (demo_hub / SIBLING).write_bytes(content)
    target = a_target(tmp_path, {SIBLING: content})
    before = {root: tree_digest(root) for root in (demo_hub, target)}

    synced = run_sync(demo_hub)
    initialized = run_init(demo_config_file, target)

    for result in (synced, initialized):
        assert failure_lines(result) == [f"{SIBLING}: {problem}"]
    assert {root: tree_digest(root) for root in (demo_hub, target)} == before


def test_refuses_sibling_when_not_regular_file(
    demo_hub: Path,
    demo_config_file: Path,
    run_sync: SyncRunner,
    *,
    tmp_path: Path,
    tree_digest: TreeDigest,
) -> None:
    """E36: a link (even to a good file) or a folder is never merged; no key path."""
    (demo_hub / SIBLING).unlink()
    (demo_hub / SIBLING).symlink_to("settings.json")
    target = a_target(tmp_path, {f"{SIBLING}/x": b"{}"})
    before = {root: tree_digest(root) for root in (demo_hub, target)}

    synced = run_sync(demo_hub)
    initialized = run_init(demo_config_file, target)

    for result in (synced, initialized):
        assert failure_lines(result) == [f"{SIBLING}: not a regular file"]
    assert {root: tree_digest(root) for root in (demo_hub, target)} == before


def test_updates_settings_when_sibling_changes(
    demo_hub: Path, demo_hub_template: Path, run_sync: SyncRunner
) -> None:
    (demo_hub / SIBLING).write_bytes(ADDITION)

    lines = success_lines(run_sync(demo_hub))

    assert lines == [f"updated {SETTINGS}", "updated hub.lock"]
    assert (demo_hub / SETTINGS).read_bytes() == merged_settings(demo_hub_template)
    assert lock_entry(demo_hub, SETTINGS)["sha256"] == sha256_of(demo_hub, SETTINGS)
    assert (demo_hub / SIBLING).read_bytes() == ADDITION
    assert success_lines(run_sync(demo_hub)) == ["up to date"]


def test_renders_template_settings_when_sibling_deleted(
    demo_hub: Path, demo_hub_template: Path, run_sync: SyncRunner
) -> None:
    (demo_hub / SIBLING).write_bytes(ADDITION)
    success_lines(run_sync(demo_hub))
    (demo_hub / SIBLING).unlink()

    lines = success_lines(run_sync(demo_hub))

    assert lines == [f"updated {SETTINGS}", "updated hub.lock"]
    assert (demo_hub / SETTINGS).read_bytes() == (demo_hub_template / SETTINGS).read_bytes()
    assert lock_entry(demo_hub, SETTINGS)["sha256"] == sha256_of(demo_hub, SETTINGS)
    # Seeded and in the lock: the project deleted it, and sync never brings it back.
    assert not os.path.lexists(demo_hub / SIBLING)
    assert lock_entry(demo_hub, SIBLING)["ownership"] == "seeded"


def test_merges_kept_sibling_when_init_runs(
    demo_config_file: Path,
    demo_hub_template: Path,
    run_sync: SyncRunner,
    *,
    tmp_path: Path,
) -> None:
    target = a_target(tmp_path, {SIBLING: ADDITION})

    success_lines(run_init(demo_config_file, target))

    assert (target / SIBLING).read_bytes() == ADDITION
    assert (target / SETTINGS).read_bytes() == merged_settings(demo_hub_template)
    assert lock_entry(target, SETTINGS)["sha256"] == sha256_of(target, SETTINGS)
    assert success_lines(run_sync(target)) == ["up to date"]


def test_links_project_entries_when_added(demo_hub: Path, run_sync: SyncRunner) -> None:
    """Q-17: a regular file under ``agents``, a folder under ``skills``; ``.gitkeep`` never."""
    (demo_hub / "plugin/demo/skills/review").mkdir()
    (demo_hub / "plugin/demo/skills/review/SKILL.md").write_bytes(b"# Review\n")
    (demo_hub / "plugin/demo/agents/triager.md").write_bytes(b"# Triager\n")

    lines = success_lines(run_sync(demo_hub))

    added = {
        ".claude/agents/triager.md": "../../plugin/demo/agents/triager.md",
        ".claude/skills/review": "../../plugin/demo/skills/review",
    }
    assert lines == [*(f"created {path}" for path in added), "updated hub.lock"]
    for path, target in added.items():
        assert os.readlink(demo_hub / path) == target
        assert lock_entry(demo_hub, path) == {"ownership": "managed", "symlink": target}
    for folder in ("agents", "skills"):
        assert not os.path.lexists(demo_hub / f".claude/{folder}/.gitkeep")

    shutil.rmtree(demo_hub / "plugin/demo/skills/review")

    assert success_lines(run_sync(demo_hub)) == [
        "deleted .claude/skills/review",
        "updated hub.lock",
    ]
    assert not os.path.lexists(demo_hub / ".claude/skills/review")


def test_exits_conflict_when_name_in_both_plugins(
    demo_hub: Path, run_sync: SyncRunner, tree_digest: TreeDigest
) -> None:
    # ``planner.md`` is also a base agent; ``triager.md`` alone would be linked.
    (demo_hub / "plugin/demo/agents/planner.md").write_bytes(b"# Ours\n")
    (demo_hub / "plugin/demo/agents/triager.md").write_bytes(b"# Triager\n")
    before = tree_digest(demo_hub)

    lines = failure_lines(run_sync(demo_hub), code=3)

    both = "plugin/hub-workflow/agents/planner.md and plugin/demo/agents/planner.md"
    assert lines == [f".claude/agents/planner.md: in both plugins ({both})", CONFLICT_WAY_OUT]
    assert tree_digest(demo_hub) == before


@pytest.mark.parametrize(
    ("name", "shown"),
    [
        pytest.param("a\\b.md", "plugin/demo/agents/a\\b.md", id="backslash"),
        pytest.param("a\nb.md", '"plugin/demo/agents/a\\nb.md"', id="newline"),
    ],
)
def test_refuses_entry_when_name_unlinkable(
    demo_hub: Path,
    demo_config_file: Path,
    run_sync: SyncRunner,
    *,
    tmp_path: Path,
    tree_digest: TreeDigest,
    name: str,
    shown: str,
) -> None:
    """E9, E34: sync and init exit 1 naming the entry (escaped), and write nothing."""
    (demo_hub / "plugin/demo/agents" / name).write_bytes(b"# Agent\n")
    target = a_target(tmp_path, {f"plugin/demo/agents/{name}": b"# Agent\n"})
    before = {root: tree_digest(root) for root in (demo_hub, target)}
    reason = "holds a backslash" if "\\" in name else "not printable"

    synced = run_sync(demo_hub)
    initialized = run_init(demo_config_file, target)

    for result in (synced, initialized):
        assert failure_lines(result) == [f"{shown}: cannot be linked: {reason}"]
    assert {root: tree_digest(root) for root in (demo_hub, target)} == before


def test_refuses_project_entry_when_init_runs(
    demo_config_file: Path, tmp_path: Path, tree_digest: TreeDigest
) -> None:
    """Q-22: at init a project agent is still unknown; only the sibling has an effect."""
    target = a_target(tmp_path, {"plugin/demo/agents/triager.md": b"# Triager\n"})
    before = tree_digest(target)

    lines = failure_lines(run_init(demo_config_file, target))

    assert lines == ["plugin/demo/agents/triager.md: not part of the hub; run hub sync --adopt"]
    assert tree_digest(target) == before


def test_exits_conflict_when_project_link_path_taken(
    demo_hub: Path, run_sync: SyncRunner, tree_digest: TreeDigest
) -> None:
    """Q-20: each listed name's link path is looked at.

    So a file the project put there is never replaced.
    """
    (demo_hub / "plugin/demo/agents/triager.md").write_bytes(b"# Triager\n")
    (demo_hub / ".claude/agents/triager.md").write_bytes(b"# Our own copy\n")
    before = tree_digest(demo_hub)

    lines = failure_lines(run_sync(demo_hub), code=3)

    assert lines == [".claude/agents/triager.md: a file where a link belongs", CONFLICT_WAY_OUT]
    assert tree_digest(demo_hub) == before
