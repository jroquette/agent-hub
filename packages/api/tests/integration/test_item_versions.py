"""Item versions on the composed app over a registered fixture hub (AGH-295, D2, D5, D9, S1, S2).

The hub is a ``hub init`` hub whose ``plugin/``, ``.claude/`` and ``workflows/`` are replaced by
the spec's fixture: skills ``alpha`` (with ``references/r.md``) and ``beta``, agent ``scout``, two
hooks in ``.claude/settings.json``, one in ``.claude/settings.project.json`` and one in
``plugin/demo/hooks/hooks.json``, and the hub workflow ``workflows/demo/review.yaml`` (it
overrides the built-in ``review``). Every read is a GET on the real file adapter; the versions are
read back from the app's database through ``open_item_version_store`` (and the table itself, to
see every unit). Synthetic data only: each token is built from fragments at run time.
"""

import json
import os
import shutil
import sqlite3
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any, Final

import pytest

from agent_hub.core.item_versions.item_version import ItemVersionMeta, VersionOrigin
from agent_hub.core.item_versions.unit_content import UnitFile
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.skill_trees import Link, TreeEntry, write_tree
from agent_hub.storage.item_version_store import open_item_version_store

CATALOG: Final = "/api/v1/projects/demo/skills"
SCOUT_DETAIL: Final = f"{CATALOG}/agent/demo/scout"
ORIGIN: Final = {"Origin": "http://127.0.0.1:7420"}
ALPHA: Final = "plugin/demo/skills/alpha"
BETA: Final = "plugin/demo/skills/beta"
SCOUT: Final = "plugin/demo/agents/scout.md"
SETTINGS: Final = ".claude/settings.json"
PROJECT_SETTINGS: Final = ".claude/settings.project.json"
PLUGIN_HOOKS: Final = "plugin/demo/hooks/hooks.json"
TOOLKIT_UNITS: Final = {ALPHA, BETA, SCOUT, SETTINGS, PROJECT_SETTINGS, PLUGIN_HOOKS}
WORKFLOWS: Final = "/api/v1/workflows"
REVIEW: Final = "workflows/demo/review.yaml"
REVIEW_DETAIL: Final = f"{WORKFLOWS}/demo/review"
# A built-in the fixture hub does not override (D14).
BUILTIN_DETAIL: Final = f"{WORKFLOWS}/demo/deliver"
READERS: Final = 10
WAIT_SECONDS: Final = 30.0
_ALNUM: Final = "A1b2C3d4E5f6G7h8"

ALPHA_MD: Final = b"---\nname: alpha\ndescription: Checks the alpha flow.\n---\n# Alpha\n"
REFERENCE: Final = b"# R\n\nRead on demand.\n"
BETA_MD: Final = b"---\nname: beta\ndescription: Writes the beta notes.\n---\n# Beta\n"
SCOUT_MD: Final = b"---\nname: scout\ndescription: Scouts the repo.\n---\nScout the repo.\n"
REVIEW_YAML: Final = (
    b"version: 1\nname: review\nrevision: 1\n"
    b"nodes:\n  - {id: lint, type: shell, command: [make, lint]}\n"
)


def _json(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _hook(command: str) -> dict[str, object]:
    return {"hooks": [{"type": "command", "command": command}]}


def _settings(pre_tool_use: str = "python3 hooks/guard.py") -> bytes:
    return _json(
        {"hooks": {"PreToolUse": [_hook(pre_tool_use)], "SessionStart": [_hook("make brief")]}}
    )


def _fixture_tree() -> dict[str, TreeEntry]:
    return {
        f"{ALPHA}/SKILL.md": ALPHA_MD,
        f"{ALPHA}/references/r.md": REFERENCE,
        f"{BETA}/SKILL.md": BETA_MD,
        SCOUT: SCOUT_MD,
        SETTINGS: _settings(),
        # Not in settings.json, so it is its own (not synced) item of the project file.
        PROJECT_SETTINGS: _json({"hooks": {"Stop": [_hook("make stop-check")]}}),
        PLUGIN_HOOKS: _json({"hooks": {"Stop": [_hook("python3 hooks/stop.py")]}}),
        REVIEW: REVIEW_YAML,
    }


type VersionsHub = Callable[..., Path]


@pytest.fixture
def versions_hub(composed: Any, make_hub: Callable[..., Path]) -> VersionsHub:
    """Registers a ``demo`` hub holding the fixture tree plus ``extra`` entries."""

    def make(extra: Mapping[str, TreeEntry] | None = None) -> Path:
        hub = make_hub()
        for folder in ("plugin", ".claude", "workflows"):
            shutil.rmtree(hub / folder)
        write_tree(hub, _fixture_tree() | dict(extra or {}))
        registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=ORIGIN)
        assert registered.status_code == 201, registered.text
        return hub

    return make


def _get(composed: Any, path: str) -> Any:
    response = composed.client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _rows(composed: Any) -> list[tuple[str, int]]:
    """Every stored ``(unit_path, seq)``, in order."""
    database = composed.settings.db_path
    with closing(sqlite3.connect(database)) as connection:
        found = connection.execute(
            "SELECT unit_path, seq FROM item_versions ORDER BY unit_path, seq"
        ).fetchall()
    return [(str(path), int(seq)) for path, seq in found]


def _versions(composed: Any, unit_path: str) -> list[ItemVersionMeta]:
    """The unit's versions, oldest first."""
    store = open_item_version_store(composed.settings.db_path)
    return list(reversed(store.page("demo", unit_path)))


def _edit(path: Path, content: bytes) -> None:
    """Write ``content`` and move the mtime on, so the stat mark changes even within a tick."""
    before = path.stat().st_mtime_ns
    path.write_bytes(content)
    os.utime(path, ns=(before + 1_000_000_000, before + 1_000_000_000))


def test_records_baseline_when_catalog_and_workflows_first_read(
    composed: Any, versions_hub: VersionsHub
) -> None:
    versions_hub()
    assert _rows(composed) == []

    _get(composed, CATALOG)

    assert _rows(composed) == sorted((path, 1) for path in TOOLKIT_UNITS)

    listed = _get(composed, WORKFLOWS)

    assert ("review", "hub") in {(item["name"], item["source"]) for item in listed["items"]}
    assert _rows(composed) == sorted((path, 1) for path in {*TOOLKIT_UNITS, REVIEW})
    alpha_files = (
        UnitFile(path="SKILL.md", content=ALPHA_MD),
        UnitFile(path="references/r.md", content=REFERENCE),
    )
    expected = {
        ALPHA: (folder_hash(alpha_files), len(ALPHA_MD) + len(REFERENCE)),
        BETA: (folder_hash((UnitFile(path="SKILL.md", content=BETA_MD),)), len(BETA_MD)),
    }
    tree = _fixture_tree()
    for path in (SCOUT, SETTINGS, PROJECT_SETTINGS, PLUGIN_HOOKS, REVIEW):
        content = tree[path]
        assert isinstance(content, bytes)
        expected[path] = (file_hash(content), len(content))
    for path, (content_hash, size) in expected.items():
        [version] = _versions(composed, path)
        assert (version.origin, version.first, version.author) == (
            VersionOrigin.EXTERNAL,
            True,
            None,
        )
        assert (version.content_hash, version.size) == (content_hash, size), path


@pytest.mark.parametrize(
    "item",
    [
        pytest.param((SCOUT, SCOUT_DETAIL, SCOUT_MD + b"Then report.\n"), id="toolkit"),
        pytest.param((REVIEW, REVIEW_DETAIL, REVIEW_YAML + b"# Then report.\n"), id="workflow"),
    ],
)
def test_detail_captures_change_when_file_changed_without_catalog_read(
    composed: Any, versions_hub: VersionsHub, item: tuple[str, str, bytes]
) -> None:
    unit_path, detail, edited = item
    hub = versions_hub()
    _get(composed, detail)
    _edit(hub / unit_path, edited)

    _get(composed, detail)

    versions = _versions(composed, unit_path)
    assert [(v.seq, v.origin, v.first) for v in versions] == [
        (1, VersionOrigin.EXTERNAL, True),
        (2, VersionOrigin.EXTERNAL, False),
    ]
    assert versions[1].content_hash == file_hash(edited)
    # Only the detail's own unit was read.
    assert {path for path, _ in _rows(composed)} == {unit_path}


def test_adds_nothing_when_same_content_read_again_after_touch(
    composed: Any, versions_hub: VersionsHub
) -> None:
    hub = versions_hub()
    for _ in range(2):
        _get(composed, CATALOG)
        _get(composed, SCOUT_DETAIL)
    baseline = _rows(composed)
    for path in (SCOUT, f"{ALPHA}/SKILL.md", SETTINGS):
        stamp = (hub / path).stat().st_mtime_ns + 5_000_000_000
        os.utime(hub / path, ns=(stamp, stamp))

    for _ in range(2):
        _get(composed, CATALOG)
        _get(composed, SCOUT_DETAIL)

    assert _rows(composed) == baseline == sorted((path, 1) for path in TOOLKIT_UNITS)


def test_records_two_edits_one_version_when_read_once(
    composed: Any, versions_hub: VersionsHub
) -> None:
    hub = versions_hub()
    _get(composed, CATALOG)
    first_edit = SCOUT_MD + b"An editor saved this.\n"
    second_edit = SCOUT_MD + b"A git pull, then a hub sync, wrote this.\n"
    _edit(hub / SCOUT, first_edit)
    _edit(hub / SCOUT, second_edit)

    _get(composed, CATALOG)

    versions = _versions(composed, SCOUT)
    assert [(v.seq, v.origin) for v in versions] == [
        (1, VersionOrigin.EXTERNAL),
        (2, VersionOrigin.EXTERNAL),
    ]
    stored = open_item_version_store(composed.settings.db_path).get("demo", SCOUT, versions[1].id)
    assert stored is not None
    assert stored.content == second_edit


def test_shares_hook_file_unit_when_one_hook_changed(
    composed: Any, versions_hub: VersionsHub
) -> None:
    hub = versions_hub()
    items = {item["id"]: item for item in _get(composed, CATALOG)["items"]}
    hooks = [item for item in items.values() if item["kind"] == "hook"]
    in_settings = [item["id"] for item in hooks if item["source_path"] == SETTINGS]
    assert len(in_settings) == 2
    changed = _settings(pre_tool_use="python3 hooks/guard.py --strict")
    _edit(hub / SETTINGS, changed)

    _get(composed, CATALOG)

    assert [(v.seq, v.content_hash) for v in _versions(composed, SETTINGS)] == [
        (1, file_hash(_settings())),
        (2, file_hash(changed)),
    ]
    assert [path for path, seq in _rows(composed) if seq > 1] == [SETTINGS]


def test_stores_one_version_when_ten_catalog_reads_race(
    composed: Any, versions_hub: VersionsHub
) -> None:
    hub = versions_hub()
    _get(composed, CATALOG)
    edited = SCOUT_MD + b"Raced.\n"
    _edit(hub / SCOUT, edited)
    start = threading.Barrier(READERS, timeout=WAIT_SECONDS)
    statuses: list[int] = []

    def read() -> None:
        start.wait()
        statuses.append(composed.client.get(CATALOG).status_code)

    readers = [threading.Thread(target=read, daemon=True) for _ in range(READERS)]
    for reader in readers:
        reader.start()
    for reader in readers:
        reader.join(WAIT_SECONDS)

    assert not any(reader.is_alive() for reader in readers)
    assert statuses == [200] * READERS
    assert [(v.seq, v.content_hash) for v in _versions(composed, SCOUT)] == [
        (1, file_hash(SCOUT_MD)),
        (2, file_hash(edited)),
    ]


def test_versions_target_once_when_links_read(
    composed: Any, versions_hub: VersionsHub, tmp_path: Path
) -> None:
    outside = tmp_path / "outside" / "out"
    outside.mkdir(parents=True)
    (outside / "SKILL.md").write_bytes(b"---\nname: out\ndescription: Out.\n---\n# Out\n")
    versions_hub(
        {
            ".claude/skills/alpha": Link("../../plugin/demo/skills/alpha"),
            ".claude/skills/out": Link(str(outside)),
        }
    )

    items = {item["id"]: item for item in _get(composed, CATALOG)["items"]}

    assert ".claude/skills/alpha" in items["skill/demo/alpha"]["linked_from"]
    assert "skill/claude/out" in items
    paths = [path for path, _ in _rows(composed)]
    assert paths.count(ALPHA) == 1
    assert not any(path.startswith(".claude/skills") for path in paths)


def test_reports_too_large_when_bounds_exceeded(composed: Any, versions_hub: VersionsHub) -> None:
    padding = "x" * (300 * 1024)
    big_settings = _json({"env": {"PAD": padding}, "hooks": {"Stop": [_hook("make stop")]}})
    many = {f"plugin/demo/skills/many/r/{index:03d}.md": b"# R\n" for index in range(201)}
    versions_hub(
        {
            SCOUT: SCOUT_MD + padding.encode(),
            SETTINGS: big_settings,
            "plugin/demo/skills/many/SKILL.md": b"---\nname: many\ndescription: Many.\n---\n",
            **many,
        }
    )

    items = {item["id"] for item in _get(composed, CATALOG)["items"]}

    # Still listed and folded (the settings read cap is 1 MiB), but none is versioned.
    assert {"agent/demo/scout", "skill/demo/many", "hook/settings/settings-stop-1"} <= items
    assert len(big_settings) > MAX_SKILL_FILE_BYTES
    paths = {path for path, _ in _rows(composed)}
    assert paths.isdisjoint({SCOUT, SETTINGS, "plugin/demo/skills/many"})
    assert {ALPHA, BETA} <= paths


def _github_token() -> str:
    return "gh" + "p_" + _ALNUM * 2 + "xyzw"


def _bearer_value() -> str:
    return "eyJ" + _ALNUM * 2 + ".payload" + _ALNUM


def test_stores_nothing_when_secret_matches(composed: Any, versions_hub: VersionsHub) -> None:
    token, bearer = _github_token(), _bearer_value()
    script = f'#!/bin/sh\ncurl -H "Authorization: Bearer {bearer}" x\n'.encode()
    versions_hub(
        {
            SCOUT: SCOUT_MD + f"Push with {token}.\n".encode(),
            f"{ALPHA}/scripts/s.sh": script,
        }
    )

    _get(composed, CATALOG)
    _get(composed, SCOUT_DETAIL)

    paths = {path for path, _ in _rows(composed)}
    assert paths.isdisjoint({SCOUT, ALPHA})
    assert BETA in paths
    database = composed.settings.db_path
    stored = b"".join(
        candidate.read_bytes()
        for candidate in database.parent.iterdir()
        if candidate.name.startswith(database.name)
    )
    assert token.encode() not in stored
    assert bearer.encode() not in stored


@contextmanager
def _opened_names(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """Every name ``os.open`` is called with while the block runs (the file adapter opens
    each segment relative to its folder, so a name is a file's own name)."""
    seen: list[str] = []
    real = os.open

    def counting(path: Any, flags: int, *args: Any, **kwargs: Any) -> int:
        seen.append(os.fsdecode(path))
        return real(path, flags, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "open", counting)
        yield seen


def test_never_versioned_when_local_settings_builtin_pack_files_drafts_or_plugins(
    composed: Any, versions_hub: VersionsHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _json({"hooks": {"PreToolUse": [_hook("python3 local-guard.py")]}})
    settings = json.loads(_settings())
    settings["enabledPlugins"] = {"other@claude-plugins-official": True}
    versions_hub(
        {
            ".claude/settings.local.json": local,
            SETTINGS: _json(settings),
            ".hub-drafts/skill-a1b2c3/SKILL.md": b"---\nname: draft\ndescription: D.\n---\n",
            "workflows/demo/prompts/p.md": b"# A prompt of the pack\n",
        }
    )

    with _opened_names(monkeypatch) as opened:
        catalog = _get(composed, CATALOG)
        _get(composed, SCOUT_DETAIL)
    workflows = _get(composed, WORKFLOWS)
    builtin = _get(composed, BUILTIN_DETAIL)

    assert any(name.endswith("settings.json") for name in opened)
    assert not any(name.endswith("settings.local.json") for name in opened)
    assert [plugin["name"] for plugin in catalog["external_plugins"]] == ["other"]
    assert builtin["source"] == "builtin"
    assert {item["name"] for item in workflows["items"] if item["source"] == "builtin"}
    paths = {path for path, _ in _rows(composed)}
    assert paths == {*TOOLKIT_UNITS, REVIEW}
