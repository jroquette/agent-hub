"""Item versions on the composed app over a registered fixture hub (AGH-295, D2, D5, D9, S1, S2;
the restores: D4, D12, D13, D22, S4, S9, A6).

The hub is a ``hub init`` hub whose ``plugin/``, ``.claude/`` and ``workflows/`` are replaced by
the spec's fixture: skills ``alpha`` (with ``references/r.md``) and ``beta``, agent ``scout``, two
hooks in ``.claude/settings.json``, one in ``.claude/settings.project.json`` and one in
``plugin/demo/hooks/hooks.json``, and the hub workflow ``workflows/demo/review.yaml`` (it
overrides the built-in ``review``). Every read is a GET on the real file adapter; the versions are
read back from the app's database through ``open_item_version_store`` (and the table itself, to
see every unit). The restores are posted by a client signed in with a synthetic launch token,
on this server's Origin. Synthetic data only: each token is built from fragments at run time.
"""

import json
import os
import shutil
import sqlite3
import subprocess
import threading
from collections.abc import Callable, Iterator, Mapping
from contextlib import closing, contextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError
from agent_hub.core.item_versions.item_version import (
    ItemVersionMeta,
    NewItemVersion,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.unit_content import UnitContent, UnitFile
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.readmodels.cursor import Cursor, encode_cursor
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.skill_trees import Link, TreeEntry, write_tree
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter
from agent_hub.storage.event_store import DatabaseBusyError
from agent_hub.storage.item_version_store import SqliteItemVersionStore, open_item_version_store

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
ALPHA_DETAIL: Final = f"{CATALOG}/skill/demo/alpha"
# A UUIDv7-shaped id no unit holds.
UNKNOWN_ID: Final = "0199f0a0-0000-7000-8000-000000000000"
VERSION_FIELDS: Final = {
    "id",
    "origin",
    "first",
    "author",
    "recorded_at",
    "content_hash",
    "size",
    "restored_from",
    "draft_id",
}
PACK_FILE: Final = "workflows/demo/prompts/p.md"
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


def _registered(
    composed: Any, make_hub: Callable[..., Path], extra: Mapping[str, TreeEntry] | None
) -> Path:
    """A ``demo`` hub holding the fixture tree plus ``extra`` entries, registered."""
    hub = make_hub()
    for folder in ("plugin", ".claude", "workflows"):
        shutil.rmtree(hub / folder)
    write_tree(hub, _fixture_tree() | dict(extra or {}))
    registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=ORIGIN)
    assert registered.status_code == 201, registered.text
    return hub


@pytest.fixture
def versions_hub(composed: Any, make_hub: Callable[..., Path]) -> VersionsHub:
    """Registers a ``demo`` hub holding the fixture tree plus ``extra`` entries."""

    def make(extra: Mapping[str, TreeEntry] | None = None) -> Path:
        return _registered(composed, make_hub, extra)

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
    return list(reversed(store.page("demo", unit_path, limit=200)))


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
    histories = [_get(composed, f"{CATALOG}/{item_id}/versions") for item_id in in_settings]
    stored = [v.id for v in reversed(_versions(composed, SETTINGS))]
    for history in histories:
        assert [item["id"] for item in history["items"]] == stored
        assert (history["unit_path"], history["unit_kind"], history["shared_by"]) == (
            SETTINGS,
            "hook",
            2,
        )


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
    assert len(_get(composed, f"{ALPHA_DETAIL}/versions")["items"]) == 1
    out = composed.client.get(f"{CATALOG}/skill/claude/out/versions")
    assert out.status_code == 404, out.text


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
    for item in ("agent/demo/scout", "skill/demo/many", "hook/settings/settings-stop-1"):
        history = _get(composed, f"{CATALOG}/{item}/versions")
        assert (history["state"], history["items"]) == ("too_large", []), item


def test_keeps_versions_listed_when_unit_grew_past_bounds(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub()
    items = _get(writer, CATALOG)["items"]
    [stop] = [item["id"] for item in items if item["source_path"] == PROJECT_SETTINGS]
    history = f"{CATALOG}/{stop}/versions"
    [baseline] = _versions(writer, PROJECT_SETTINGS)
    original = (hub / PROJECT_SETTINGS).read_bytes()
    padding = "x" * (300 * 1024)
    _edit(
        hub / PROJECT_SETTINGS,
        _json({"env": {"PAD": padding}, "hooks": {"Stop": [_hook("make stop-check")]}}),
    )

    grown = _get(writer, history)

    assert grown["state"] == "too_large"
    assert [item["id"] for item in grown["items"]] == [baseline.id]

    # The earlier version stays restorable (S8): the file goes back and a restore names it.
    response = _restore(writer, f"{CATALOG}/{stop}", baseline.id)

    assert response.status_code == 200, response.text
    assert (response.json()["changed"], response.json()["versioned"]) == (True, True)
    assert (hub / PROJECT_SETTINGS).read_bytes() == original
    after = _versions(writer, PROJECT_SETTINGS)
    assert [(v.origin, v.restored_from) for v in after] == [
        (VersionOrigin.EXTERNAL, None),
        (VersionOrigin.RESTORE, baseline.id),
    ]


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
    for item in ("agent/demo/scout", "skill/demo/alpha"):
        history = _get(composed, f"{CATALOG}/{item}/versions")
        assert (history["state"], history["items"]) == ("secret", []), item


def test_refuses_restore_when_versioned_unit_gains_secret(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub()
    _get(writer, SCOUT_DETAIL)
    [baseline] = _versions(writer, SCOUT)
    leaked = SCOUT_MD + f"Push with {_github_token()}.\n".encode()
    _edit(hub / SCOUT, leaked)

    history = _get(writer, f"{SCOUT_DETAIL}/versions")

    # The baseline stays listed; the disk's content is not stored (AC-295.10).
    assert history["state"] == "secret"
    assert [item["id"] for item in history["items"]] == [baseline.id]

    response = _restore(writer, SCOUT_DETAIL, baseline.id)

    _refused(response, "secret_unversioned")
    assert (hub / SCOUT).read_bytes() == leaked
    assert _versions(writer, SCOUT) == [baseline]


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
    writer: Any, writer_hub: VersionsHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    local = _json({"hooks": {"PreToolUse": [_hook("python3 local-guard.py")]}})
    settings = json.loads(_settings())
    settings["enabledPlugins"] = {"other@claude-plugins-official": True}
    hub = writer_hub(
        {
            ".claude/settings.local.json": local,
            SETTINGS: _json(settings),
            ".hub-drafts/skill-a1b2c3/SKILL.md": b"---\nname: draft\ndescription: D.\n---\n",
            PACK_FILE: b"# A prompt of the pack\n",
        }
    )

    with _opened_names(monkeypatch) as opened:
        catalog = _get(writer, CATALOG)
        _get(writer, SCOUT_DETAIL)
    workflows = _get(writer, WORKFLOWS)
    builtin = _get(writer, BUILTIN_DETAIL)

    assert any(name.endswith("settings.json") for name in opened)
    assert not any(name.endswith("settings.local.json") for name in opened)
    assert [plugin["name"] for plugin in catalog["external_plugins"]] == ["other"]
    assert builtin["source"] == "builtin"
    assert {item["name"] for item in workflows["items"] if item["source"] == "builtin"}
    paths = {path for path, _ in _rows(writer)}
    assert paths == {*TOOLKIT_UNITS, REVIEW}
    # A restore of the settings file's hooks writes that file only.
    [first] = _versions(writer, SETTINGS)
    _edit(hub / SETTINGS, _settings(pre_tool_use="python3 hooks/guard.py --strict"))
    untouched = {
        path: (hub / path).read_bytes()
        for path in (".claude/settings.local.json", ".hub-drafts/skill-a1b2c3/SKILL.md", PACK_FILE)
    }

    restored = _restore(writer, SETTINGS_HOOK, first.id, confirm_managed=True)

    assert restored.status_code == 200, restored.text
    assert (hub / SETTINGS).read_bytes() == _json(settings)
    assert {path: (hub / path).read_bytes() for path in untouched} == untouched
    assert {path for path, _ in _rows(writer)} == {*TOOLKIT_UNITS, REVIEW}


def _append_versions(composed: Any, unit_path: str, contents: list[bytes]) -> None:
    """Stores ``contents`` as the agent unit's versions 1 to n, a minute apart."""
    store = open_item_version_store(composed.settings.db_path)
    start = datetime(2026, 10, 1, tzinfo=UTC)
    for seq, content in enumerate(contents, start=1):
        store.append(
            NewItemVersion(
                project="demo",
                unit_path=unit_path,
                kind=UnitKind.AGENT,
                seq=seq,
                origin=VersionOrigin.EXTERNAL,
                first=seq == 1,
                recorded_at=start + timedelta(minutes=seq),
                content_hash=file_hash(content),
                size=len(content),
                content=content,
            )
        )


def test_list_versions_pages_newest_first_when_sixty_versions(
    composed: Any, versions_hub: VersionsHub
) -> None:
    versions_hub()
    # The newest stored version is the disk's content, so the list's capture adds nothing.
    contents = [SCOUT_MD + f"Edit {seq}.\n".encode() for seq in range(1, 60)] + [SCOUT_MD]
    _append_versions(composed, SCOUT, contents)
    history = f"{SCOUT_DETAIL}/versions"

    first = _get(composed, history)
    second = _get(composed, f"{history}?cursor={first['next_cursor']}")

    stored = [v.id for v in reversed(_versions(composed, SCOUT))]
    assert len(stored) == 60
    assert [item["id"] for item in first["items"]] == stored[:50]
    assert [item["id"] for item in second["items"]] == stored[50:]
    assert second["next_cursor"] is None
    assert (first["total_estimate"], first["state"], first["managed"]) == (60, "ok", False)
    assert (first["unit_path"], first["unit_kind"], first["shared_by"]) == (SCOUT, "agent", 1)
    newest, oldest = first["items"][0], second["items"][-1]
    assert set(newest) == VERSION_FIELDS
    assert (newest["origin"], newest["first"], newest["author"]) == ("external", False, None)
    assert (newest["content_hash"], newest["size"]) == (file_hash(SCOUT_MD), len(SCOUT_MD))
    assert newest["recorded_at"] == "2026-10-01T01:00:00.000Z"
    assert (oldest["first"], oldest["restored_from"]) == (True, None)
    assert len(_get(composed, f"{history}?limit=200")["items"]) == 60
    for path, status in (
        ("/api/v1/projects/nope/skills/agent/demo/scout/versions", 404),
        (f"{CATALOG}/agent/demo/nope/versions", 404),
        (f"{WORKFLOWS}/demo/nope/versions", 404),
        (f"{SCOUT_DETAIL}/versions/not-a-uuid", 400),
        (f"{REVIEW_DETAIL}/versions/{UNKNOWN_ID.upper()}", 400),
        (f"{history}?limit=0", 400),
        (f"{history}?limit=201", 400),
        (f"{history}?cursor=bm90LW91cnM", 400),
        # A seq past SQLite's integer range: refused before it reaches the store.
        (f"{history}?cursor={encode_cursor(Cursor(hwm=0, key=(2**63,), id='x'))}", 400),
    ):
        response = composed.client.get(path)
        assert response.status_code == status, (path, response.text)
        assert str(composed.settings.db_path.parent) not in response.text


def test_get_version_answers_content_when_id_is_the_items(
    composed: Any, versions_hub: VersionsHub
) -> None:
    hub = versions_hub({f"{ALPHA}/scripts/run.sh": b"#!/bin/sh\necho run\n"})
    (hub / ALPHA / "scripts" / "run.sh").chmod(0o755)
    _get(composed, CATALOG)
    _get(composed, WORKFLOWS)
    [alpha] = _get(composed, f"{ALPHA_DETAIL}/versions")["items"]
    [scout] = _get(composed, f"{SCOUT_DETAIL}/versions")["items"]
    [review] = _get(composed, f"{REVIEW_DETAIL}/versions")["items"]

    folder = _get(composed, f"{ALPHA_DETAIL}/versions/{alpha['id']}")
    agent = _get(composed, f"{SCOUT_DETAIL}/versions/{scout['id']}")
    workflow = _get(composed, f"{REVIEW_DETAIL}/versions/{review['id']}")

    assert (folder["id"], folder["unit_kind"]) == (alpha["id"], "skill")
    assert [(f["path"], f["executable"], f["text"]) for f in folder["files"]] == [
        ("SKILL.md", False, ALPHA_MD.decode()),
        ("references/r.md", False, REFERENCE.decode()),
        ("scripts/run.sh", True, "#!/bin/sh\necho run\n"),
    ]
    assert agent["files"] == [
        {"path": "scout.md", "executable": False, "size": len(SCOUT_MD), "text": SCOUT_MD.decode()}
    ]
    assert [(f["path"], f["text"]) for f in workflow["files"]] == [
        ("review.yaml", REVIEW_YAML.decode())
    ]
    for path in (
        f"{ALPHA_DETAIL}/versions/{scout['id']}",
        f"{SCOUT_DETAIL}/versions/{alpha['id']}",
        f"{REVIEW_DETAIL}/versions/{scout['id']}",
        f"{SCOUT_DETAIL}/versions/{UNKNOWN_ID}",
        f"{BUILTIN_DETAIL}/versions",
    ):
        response = composed.client.get(path)
        assert response.status_code == 404, (path, response.text)


# The restores (AGH-295 slice 2e): a client signed in with this launch's (synthetic) token.
TOKEN: Final = "synthetic-launch-" + "token-" + _ALNUM * 2
SETTINGS_HOOK: Final = f"{CATALOG}/hook/settings/settings-pretooluse-1"
SECOND: Final = SCOUT_MD + b"Second.\n"

type WriterOpener = Callable[..., Any]


@pytest.fixture
def open_writer(open_composed: Callable[..., Any], composed_settings: ApiSettings) -> WriterOpener:
    """Opens the composed app with a launch token and its client signed in (a restore needs the
    cookie); ``sessions_off`` and ``build_app`` keywords (``item_writer``) pass through."""

    def opened(*, sessions_off: bool = False, **options: Any) -> Any:
        settings = replace(composed_settings, session_token=TOKEN, sessions_off=sessions_off)
        app = open_composed(settings, **options)
        app.client.cookies.set(cookie_name(settings.port), TOKEN)
        return app

    return opened


@pytest.fixture
def writer(open_writer: WriterOpener) -> Any:
    """The composed app, signed in."""
    return open_writer()


@pytest.fixture
def writer_hub(writer: Any, make_hub: Callable[..., Path]) -> VersionsHub:
    """Registers the fixture hub (plus ``extra``) on the signed-in app."""

    def make(extra: Mapping[str, TreeEntry] | None = None) -> Path:
        return _registered(writer, make_hub, extra)

    return make


def _restore(app: Any, item: str, version_id: str, **body: bool) -> Any:
    """``POST {item}/versions/{version_id}/restore`` with ``body``, from this server's page."""
    path = f"{item}/versions/{version_id}/restore"
    return app.client.post(path, json=body, headers=ORIGIN)


def _origins(app: Any, unit_path: str) -> list[tuple[VersionOrigin, str]]:
    return [(v.origin, v.content_hash) for v in _versions(app, unit_path)]


def _author(hub: Path) -> VersionAuthor:
    project = json.loads((hub / "hub.json").read_bytes())["project"]
    return VersionAuthor(name=project["author_name"], email=project["author_email"])


def _two_scout_versions(app: Any, hub: Path) -> list[ItemVersionMeta]:
    """The agent read as ``SCOUT_MD``, then edited to ``SECOND`` and read again."""
    _get(app, SCOUT_DETAIL)
    _edit(hub / SCOUT, SECOND)
    _get(app, SCOUT_DETAIL)
    versions = _versions(app, SCOUT)
    assert [v.content_hash for v in versions] == [file_hash(SCOUT_MD), file_hash(SECOND)]
    return versions


def _refused(response: Any, code: str) -> None:
    assert response.status_code == 409, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert (response.json()["title"], response.json()["code"]) == ("Item write refused", code)


def test_restore_appends_version_when_earlier_version_restored(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub()
    contents = [SCOUT_MD, SECOND, SCOUT_MD + b"Third.\n"]
    for content in contents:
        _edit(hub / SCOUT, content)
        _get(writer, SCOUT_DETAIL)
    before = _versions(writer, SCOUT)
    assert [v.content_hash for v in before] == [file_hash(content) for content in contents]
    store = open_item_version_store(writer.settings.db_path)
    stored = [store.get("demo", SCOUT, v.id) for v in before]

    response = _restore(writer, SCOUT_DETAIL, before[0].id)

    assert response.status_code == 200, response.text
    answer = response.json()
    assert (answer["changed"], answer["versioned"], answer["reason"]) == (True, True, None)
    assert (hub / SCOUT).read_bytes() == SCOUT_MD
    after = _versions(writer, SCOUT)
    assert after[:3] == before
    assert [store.get("demo", SCOUT, v.id) for v in before] == stored
    restored = after[3]
    assert answer["version"]["id"] == restored.id
    assert (restored.seq, restored.origin, restored.first) == (4, VersionOrigin.RESTORE, False)
    assert (restored.restored_from, restored.content_hash) == (before[0].id, before[0].content_hash)
    assert restored.author == _author(hub)
    listed = _get(writer, f"{SCOUT_DETAIL}/versions")["items"][0]
    assert (listed["id"], listed["origin"], listed["restored_from"]) == (
        restored.id,
        "restore",
        before[0].id,
    )
    assert listed["author"] == {"name": restored.author.name, "email": restored.author.email}


def test_restore_records_external_first_when_hand_edited(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub()
    first, _ = _two_scout_versions(writer, hub)
    by_hand = SCOUT_MD + b"Edited by hand.\n"
    _edit(hub / SCOUT, by_hand)

    response = _restore(writer, SCOUT_DETAIL, first.id)

    assert response.status_code == 200, response.text
    assert _origins(writer, SCOUT) == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT_MD)),
        (VersionOrigin.EXTERNAL, file_hash(SECOND)),
        (VersionOrigin.EXTERNAL, file_hash(by_hand)),
        (VersionOrigin.RESTORE, file_hash(SCOUT_MD)),
    ]
    hand_edit = _versions(writer, SCOUT)[2]
    assert hand_edit.author is None
    # The hand edit stays restorable.
    again = _restore(writer, SCOUT_DETAIL, hand_edit.id)
    assert again.status_code == 200, again.text
    assert (hub / SCOUT).read_bytes() == by_hand
    assert _versions(writer, SCOUT)[-1].restored_from == hand_edit.id


def test_restore_managed_needs_confirmation_when_unit_managed(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub()
    history = _get(writer, f"{SETTINGS_HOOK}/versions")
    assert (history["managed"], history["unit_path"]) == (True, SETTINGS)
    [first] = _versions(writer, SETTINGS)
    changed = _settings(pre_tool_use="python3 hooks/guard.py --strict")
    _edit(hub / SETTINGS, changed)

    refused = _restore(writer, SETTINGS_HOOK, first.id)
    declined = _restore(writer, SETTINGS_HOOK, first.id, confirm_managed=False)

    for response in (refused, declined):
        _refused(response, "managed_confirmation_required")
    assert (hub / SETTINGS).read_bytes() == changed
    assert VersionOrigin.RESTORE not in {origin for origin, _ in _origins(writer, SETTINGS)}

    confirmed = _restore(writer, SETTINGS_HOOK, first.id, confirm_managed=True)

    assert confirmed.status_code == 200, confirmed.text
    assert (hub / SETTINGS).read_bytes() == _settings()
    assert _origins(writer, SETTINGS)[-1] == (VersionOrigin.RESTORE, file_hash(_settings()))


def _three_hooks(stop: str = "make stop-check") -> bytes:
    return _json(
        {
            "hooks": {
                "PreToolUse": [_hook("python3 hooks/guard.py")],
                "SessionStart": [_hook("make brief")],
                "Stop": [_hook(stop)],
            }
        }
    )


def test_restore_hook_file_writes_whole_file_when_restored(
    writer: Any, writer_hub: VersionsHub
) -> None:
    hub = writer_hub({SETTINGS: _three_hooks()})
    hooks = [
        item["id"]
        for item in _get(writer, CATALOG)["items"]
        if item["kind"] == "hook" and item["source_path"] == SETTINGS
    ]
    assert len(hooks) == 3
    [first] = _versions(writer, SETTINGS)
    _edit(hub / SETTINGS, _three_hooks(stop="make stop-check --all"))
    _get(writer, CATALOG)
    # One hook changed; another hook's history restores the whole file.
    other = next(item for item in hooks if "sessionstart" in item)
    history = _get(writer, f"{CATALOG}/{other}/versions")
    assert (history["shared_by"], len(history["items"])) == (3, 2)

    response = _restore(writer, f"{CATALOG}/{other}", first.id, confirm_managed=True)

    assert response.status_code == 200, response.text
    assert (hub / SETTINGS).read_bytes() == _three_hooks()
    assert _origins(writer, SETTINGS)[-1] == (VersionOrigin.RESTORE, file_hash(_three_hooks()))


def _folder(root: Path) -> dict[str, tuple[bytes, bool]]:
    """Every file under ``root``: its bytes and whether it is executable."""
    return {
        str(path.relative_to(root)): (path.read_bytes(), os.access(path, os.X_OK))
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_restore_folder_and_workflow_match_version_when_restored(
    writer: Any, writer_hub: VersionsHub
) -> None:
    script = b"#!/bin/sh\necho s\n"
    prompt = b"# A prompt of the pack\n"
    hub = writer_hub({f"{ALPHA}/scripts/s.sh": script, "workflows/demo/prompts/p.md": prompt})
    (hub / ALPHA / "scripts" / "s.sh").chmod(0o755)
    _get(writer, ALPHA_DETAIL)
    _get(writer, REVIEW_DETAIL)
    [alpha] = _versions(writer, ALPHA)
    [review] = _versions(writer, REVIEW)
    _edit(hub / ALPHA / "references" / "r.md", b"# R, changed\n")
    (hub / ALPHA / "scripts" / "s.sh").chmod(0o644)
    (hub / ALPHA / "assets").mkdir()
    (hub / ALPHA / "assets" / "new.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    _edit(hub / REVIEW, REVIEW_YAML + b"# Edited.\n")
    edited_prompt = prompt + b"Edited too.\n"
    _edit(hub / "workflows/demo/prompts/p.md", edited_prompt)

    folder = _restore(writer, ALPHA_DETAIL, alpha.id)
    workflow = _restore(writer, REVIEW_DETAIL, review.id)

    assert (folder.status_code, workflow.status_code) == (200, 200), (folder.text, workflow.text)
    assert _folder(hub / ALPHA) == {
        "SKILL.md": (ALPHA_MD, False),
        "references/r.md": (REFERENCE, False),
        "scripts/s.sh": (script, True),
    }
    assert not (hub / ALPHA / "assets").exists()
    assert (hub / REVIEW).read_bytes() == REVIEW_YAML
    assert (hub / "workflows/demo/prompts/p.md").read_bytes() == edited_prompt
    assert _origins(writer, ALPHA)[-1] == (VersionOrigin.RESTORE, alpha.content_hash)
    assert _origins(writer, REVIEW)[-1] == (VersionOrigin.RESTORE, review.content_hash)


def test_restore_refuses_no_author_when_hub_has_no_identity(
    writer: Any, make_hub: Callable[..., Path]
) -> None:
    def no_author(document: dict[str, Any]) -> None:
        del document["project"]["author_name"], document["project"]["author_email"]

    hub = _registered(writer, lambda: make_hub(change=no_author), None)
    first, second = _two_scout_versions(writer, hub)

    response = _restore(writer, SCOUT_DETAIL, first.id)

    _refused(response, "no_author")
    assert "author" in response.json()["reason"]
    assert (hub / SCOUT).read_bytes() == SECOND
    assert _versions(writer, SCOUT) == [first, second]


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({"confirm_managed": True, "force": True}, id="unknown-field"),
        pytest.param({"confirm_managed": 1}, id="number"),
        pytest.param({"confirm_managed": "yes"}, id="text"),
        pytest.param({"confirm_managed": "true"}, id="quoted-true"),
    ],
)
def test_restore_refuses_body_when_field_unknown_or_not_strict_bool(
    writer: Any, writer_hub: VersionsHub, body: dict[str, object]
) -> None:
    hub = writer_hub()
    _get(writer, SETTINGS_HOOK)
    [first] = _versions(writer, SETTINGS)
    changed = _settings(pre_tool_use="python3 hooks/guard.py --strict")
    _edit(hub / SETTINGS, changed)

    response = writer.client.post(
        f"{SETTINGS_HOOK}/versions/{first.id}/restore", json=body, headers=ORIGIN
    )

    assert response.status_code == 422, response.text
    assert (hub / SETTINGS).read_bytes() == changed
    assert _versions(writer, SETTINGS) == [first]


def test_restore_says_written_not_recorded_when_database_busy_after_write(
    writer: Any, writer_hub: VersionsHub, monkeypatch: pytest.MonkeyPatch
) -> None:
    hub = writer_hub()
    first, second = _two_scout_versions(writer, hub)

    def busy(_store: Any, _version: Any) -> Any:
        raise DatabaseBusyError("database is locked")

    # The disk equals the last version, so the only append is the restore's, after the write.
    monkeypatch.setattr(SqliteItemVersionStore, "append", busy)
    response = _restore(writer, SCOUT_DETAIL, first.id)

    assert response.status_code == 503, response.text
    assert (response.json()["code"], response.json()["written"]) == ("written_not_recorded", True)
    assert response.headers["retry-after"] == "1"
    assert (hub / SCOUT).read_bytes() == SCOUT_MD
    assert _versions(writer, SCOUT) == [first, second]


class EdgeWriter:
    """The real writer, with a fault to inject: ``fail`` raises the writer's error (its cause
    naming the unit's path) instead of writing; ``link`` swaps the agents folder for a link to
    a copy outside the hub just before the targets are checked, as a concurrent change would."""

    def __init__(self, outside: Path) -> None:
        self.real = FileSystemHubItemWriter()
        self.outside = outside
        self.fail = False
        self.link = False

    def is_writable(self, hub_path: str, unit_paths: Any = ()) -> bool:
        return self.real.is_writable(hub_path, unit_paths)

    def check_targets(self, hub_path: str, unit_paths: Any) -> None:
        if self.link:
            agents = Path(hub_path) / "plugin/demo/agents"
            agents.rename(self.outside)
            agents.symlink_to(self.outside)
        self.real.check_targets(hub_path, unit_paths)

    def write_unit(
        self, hub_path: str, unit_path: str, content: UnitContent, *, kind: UnitKind
    ) -> None:
        if self.fail:
            raise HubItemWriteError(f"rename failed at {hub_path}/{unit_path}")
        self.real.write_unit(hub_path, unit_path, content, kind=kind)

    def write_file(
        self, hub_path: str, path: str, content: bytes, *, executable: bool = False
    ) -> None:
        self.real.write_file(hub_path, path, content, executable=executable)

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        self.real.remove_unit(hub_path, unit_path, kind=kind)


def test_write_edges_refuse_or_skip_when_link_equal_or_failing(
    open_writer: WriterOpener, make_hub: Callable[..., Path], tmp_path: Path
) -> None:
    edges = EdgeWriter(tmp_path / "outside-agents")
    app = open_writer(item_writer=edges)
    hub = _registered(app, make_hub, None)
    first, second = _two_scout_versions(app, hub)
    stamp = (hub / SCOUT).stat().st_mtime_ns

    equal = _restore(app, SCOUT_DETAIL, second.id)

    assert equal.status_code == 200, equal.text
    assert equal.json() == {"changed": False, "versioned": False, "reason": None, "version": None}
    assert (hub / SCOUT).stat().st_mtime_ns == stamp

    edges.fail = True
    failed = _restore(app, SCOUT_DETAIL, first.id)

    assert failed.status_code == 500, failed.text
    assert (failed.json()["code"], failed.json()["kind"]) == ("write_failed", "failed")
    assert str(hub) not in failed.text
    assert SCOUT not in failed.text
    assert "scout" not in failed.json()["detail"]
    assert (hub / SCOUT).read_bytes() == SECOND

    edges.fail, edges.link = False, True
    linked = _restore(app, SCOUT_DETAIL, first.id)

    _refused(linked, "link_in_path")
    assert (edges.outside / "scout.md").read_bytes() == SECOND
    assert _versions(app, SCOUT) == [first, second]


@pytest.fixture
def read_only_root(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[[Path], None]]:
    """Makes a hub folder unwritable, as a read-only mount does, and undoes it after: ``0o555``,
    and for a user that writes anywhere (root in a container) ``chattr +i``, or, where that is
    refused, the folder's write access denied as the mount would answer it."""
    locked: list[Path] = []
    immutable: list[Path] = []

    def make(root: Path) -> None:
        root.chmod(0o555)
        locked.append(root)
        if not os.access(root, os.W_OK):
            return
        chattr = shutil.which("chattr")
        if chattr is not None and _ran([chattr, "+i", str(root)]):
            immutable.append(root)
            return
        real = os.access

        def access(path: Any, mode: int, *args: Any, **kwargs: Any) -> bool:
            if mode & os.W_OK and str(path) == str(root):
                return False
            return real(path, mode, *args, **kwargs)

        monkeypatch.setattr(os, "access", access)

    yield make
    for root in immutable:
        _ran(["chattr", "-i", str(root)])
    for root in locked:
        root.chmod(0o755)


def _ran(command: list[str]) -> bool:
    return subprocess.run(command, capture_output=True, check=False).returncode == 0  # noqa: S603


def test_read_only_hub_refuses_when_folder_not_writable(
    writer: Any, writer_hub: VersionsHub, read_only_root: Callable[[Path], None]
) -> None:
    hub = writer_hub()
    first, second = _two_scout_versions(writer, hub)
    _get(writer, REVIEW_DETAIL)
    [review] = _versions(writer, REVIEW)
    _edit(hub / REVIEW, REVIEW_YAML + b"# Edited.\n")
    read_only_root(hub)

    for response in (
        _restore(writer, SCOUT_DETAIL, first.id),
        _restore(writer, REVIEW_DETAIL, review.id),
    ):
        _refused(response, "hub_read_only")
    assert (hub / SCOUT).read_bytes() == SECOND
    assert (hub / REVIEW).read_bytes() == REVIEW_YAML + b"# Edited.\n"
    assert _versions(writer, SCOUT) == [first, second]
    assert _versions(writer, REVIEW) == [review]


def test_read_only_hub_refuses_when_in_container(
    writer: Any, writer_hub: VersionsHub, open_writer: WriterOpener
) -> None:
    hub = writer_hub()
    first, second = _two_scout_versions(writer, hub)
    container = open_writer(sessions_off=True)

    signed_in = _restore(container, SCOUT_DETAIL, first.id)
    container.client.cookies.clear()
    without_cookie = _restore(container, f"{REVIEW_DETAIL}", first.id)

    for response in (signed_in, without_cookie):
        _refused(response, "hub_read_only")
    assert (hub / SCOUT).read_bytes() == SECOND
    assert _versions(container, SCOUT) == [first, second]
    assert REVIEW not in {path for path, _ in _rows(container)}
    # The history reads stay open in the container.
    assert len(_get(container, f"{SCOUT_DETAIL}/versions")["items"]) == 2


def _git(hub: Path, *arguments: str) -> str:
    done = subprocess.run(  # noqa: S603 -- a fixed git command on the test's own folder
        ["git", "-C", str(hub), *arguments],  # noqa: S607
        capture_output=True,
        check=True,
        text=True,
    )
    return done.stdout


def _git_state(hub: Path) -> tuple[str, str, bytes, str]:
    """``HEAD``, the branches, the index's bytes and the stash."""
    return (
        _git(hub, "rev-parse", "HEAD"),
        _git(hub, "for-each-ref", "refs/heads"),
        (hub / ".git" / "index").read_bytes(),
        _git(hub, "stash", "list"),
    )


# What ``hub doctor``'s tree read runs (generator/doctor_tree.py): it lists, never changes.
READ_ONLY_LISTINGS: Final = {
    ("rev-parse", "--show-toplevel"),
    ("ls-files", "-z", "--cached", "--others", "--exclude-standard"),
}


def _git_arguments(args: tuple[Any, ...]) -> tuple[str, ...]:
    """A spawned git command's arguments after its ``-c`` options."""
    command = [str(part) for part in args[0]]
    assert command[0].endswith("git"), command
    rest = command[1:]
    while rest[:1] == ["-c"]:
        rest = rest[2:]
    return tuple(rest)


def test_git_untouched_when_every_route_runs(
    open_writer: WriterOpener, make_hub: Callable[..., Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    git_reads: list[object] = []

    def read_git(_hub_path: str) -> Callable[[frozenset[str]], Mapping[str, str]]:
        def read(keys: frozenset[str]) -> Mapping[str, str]:
            git_reads.append(keys)
            return {}

        return read

    app = open_writer(read_git=read_git)
    hub = _registered(app, make_hub, None)
    _get(app, SCOUT_DETAIL)
    _get(app, REVIEW_DETAIL)
    _edit(hub / SCOUT, SECOND)
    _edit(hub / REVIEW, REVIEW_YAML + b"# Edited.\n")
    _git(hub, "init", "--quiet", "--initial-branch=main")
    _git(hub, "add", "--all")
    _git(hub, "-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "c")
    before = _git_state(hub)
    spawned: list[tuple[Any, ...]] = []
    forks: list[str] = []
    # A Popen may spawn through os.posix_spawn itself (an absolute executable path): that is
    # the same process, counted once as the Popen, so a spawn inside one is not a fork.
    in_popen = threading.local()

    def counted(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def call(*args: Any, **kwargs: Any) -> Any:
            if name != "Popen":
                if not getattr(in_popen, "depth", 0):
                    forks.append(name)
                return real(*args, **kwargs)
            spawned.append(args)
            in_popen.depth = getattr(in_popen, "depth", 0) + 1
            try:
                return real(*args, **kwargs)
            finally:
                in_popen.depth -= 1

        return call

    with monkeypatch.context() as patch:
        patch.setattr(subprocess, "Popen", counted("Popen", subprocess.Popen))
        patch.setattr(os, "posix_spawn", counted("posix_spawn", os.posix_spawn))
        patch.setattr(os, "fork", counted("fork", os.fork))
        _get(app, CATALOG)
        _get(app, WORKFLOWS)
        _get(app, REVIEW_DETAIL)
        history = _get(app, f"{SCOUT_DETAIL}/versions")
        first = history["items"][-1]["id"]
        _get(app, f"{SCOUT_DETAIL}/versions/{first}")
        workflow_first = _get(app, f"{REVIEW_DETAIL}/versions")["items"][-1]["id"]
        _get(app, f"{REVIEW_DETAIL}/versions/{workflow_first}")
        restored = _restore(app, SCOUT_DETAIL, first)
        workflow_restored = _restore(app, REVIEW_DETAIL, workflow_first)

    assert restored.status_code == 200, restored.text
    assert workflow_restored.status_code == 200, workflow_restored.text
    # The only processes are the hub card's doctor drift check listing the checkout (read-only,
    # before this feature), when a read or a restore resolves the project after the tree changed.
    assert {_git_arguments(args) for args in spawned} <= READ_ONLY_LISTINGS
    assert (forks, git_reads) == ([], [])
    assert _git_state(hub) == before
    assert sorted(_git(hub, "status", "--porcelain").splitlines()) == [
        f" M {SCOUT}",
        f" M {REVIEW}",
    ]
