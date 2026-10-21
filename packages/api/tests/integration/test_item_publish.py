"""The Studio's Publish on the composed app over a registered fixture hub (AGH-295, D10, D21,
S5, S7, S8, S9, A7, A20; AC-295.11 to .16 and .18).

The hub is a ``hub init`` hub whose ``plugin/``, ``.claude/`` and ``workflows/`` are replaced by
a small fixture: skill ``alpha`` (``references/r.md``, ``references/keep.md``), agent ``scout``,
two hooks in ``.claude/settings.json`` (which ``hub.lock`` manages) and one in
``plugin/demo/hooks/hooks.json``. A draft is written under ``.hub-drafts/<draft_id>/`` as the
Studio's Claude writes it, then published by a client signed in with a synthetic launch token, on
this server's Origin, through the real file writer; the versions are read back from the app's
database. Synthetic data only: each token is built from fragments at run time.
"""

import json
import os
import shutil
import sqlite3
from collections.abc import Callable, Mapping
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, Final

import pytest

from agent_hub.api.session_token import cookie_name
from agent_hub.api.settings import ApiSettings
from agent_hub.core.item_versions.hub_item_writer import HubItemWriteError, draft_unreadable
from agent_hub.core.item_versions.item_version import (
    ItemVersionMeta,
    UnitKind,
    VersionAuthor,
    VersionOrigin,
)
from agent_hub.core.item_versions.unit_content import UnitFile
from agent_hub.core.item_versions.unit_hash import file_hash, folder_hash
from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES
from agent_hub.core.testing.skill_trees import Link, TreeEntry, write_tree
from agent_hub.generator.hub_item_writer import FileSystemHubItemWriter
from agent_hub.storage.item_version_store import open_item_version_store

CATALOG: Final = "/api/v1/projects/demo/skills"
ORIGIN: Final = {"Origin": "http://127.0.0.1:7420"}
ALPHA: Final = "plugin/demo/skills/alpha"
ALPHA2: Final = "plugin/demo/skills/alpha2"
SCOUT: Final = "plugin/demo/agents/scout.md"
SETTINGS: Final = ".claude/settings.json"
PLUGIN_HOOKS: Final = "plugin/demo/hooks/hooks.json"
DRAFTS: Final = ".hub-drafts"
_ALNUM: Final = "A1b2C3d4E5f6G7h8"
TOKEN: Final = "synthetic-launch-" + "token-" + _ALNUM * 2

ALPHA_MD: Final = b"---\nname: alpha\ndescription: Checks the alpha flow.\n---\n# Alpha\n"
REFERENCE: Final = b"# R\n\nRead on demand.\n"
KEEP: Final = b"# Keep\n"
SCOUT_MD: Final = b"---\nname: scout\ndescription: Scouts the repo.\n---\nScout the repo.\n"
SCOUT_TARGET: Final = {"kind": "agent", "source": "demo", "name": "scout"}
ALPHA_TARGET: Final = {"kind": "skill", "source": "demo", "name": "alpha"}
SECOND_HOOK_TARGET: Final = {
    "kind": "hook",
    "source": "settings",
    "name": "settings-pretooluse-2",
}


def _json(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _command(command: str) -> dict[str, str]:
    return {"type": "command", "command": command}


def _agent(name: str, body: str = "Scout the repo.\n") -> bytes:
    return f"---\nname: {name}\ndescription: Scouts the repo.\n---\n{body}".encode()


def _settings() -> dict[str, Any]:
    """Three ``PreToolUse`` hooks in one group, a ``SessionStart`` hook and another setting."""
    pre_tool_use = [_command("python3 hooks/x1.py"), _command("X"), _command("x3")]
    return {
        "permissions": {"allow": ["Bash(make check)"]},
        "hooks": {
            "PreToolUse": [{"matcher": "Bash", "hooks": pre_tool_use}],
            "SessionStart": [{"hooks": [_command("make brief")]}],
        },
    }


def _fixture_tree() -> dict[str, TreeEntry]:
    return {
        f"{ALPHA}/SKILL.md": ALPHA_MD,
        f"{ALPHA}/references/r.md": REFERENCE,
        f"{ALPHA}/references/keep.md": KEEP,
        SCOUT: SCOUT_MD,
        SETTINGS: _json(_settings()),
        PLUGIN_HOOKS: _json({"hooks": {"Stop": [{"hooks": [_command("python3 stop.py")]}]}}),
    }


type WriterOpener = Callable[..., Any]


@pytest.fixture
def open_writer(open_composed: Callable[..., Any], composed_settings: ApiSettings) -> WriterOpener:
    """Opens the composed app with a launch token and its client signed in; ``sessions_off``
    and ``build_app`` keywords (``item_writer``) pass through."""

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


def _registered(
    app: Any, make_hub: Callable[..., Path], extra: Mapping[str, TreeEntry] | None = None
) -> Path:
    """A ``demo`` hub holding the fixture tree plus ``extra``, registered, its catalog read once
    (as the Studio has before a Publish), so every unit has its baseline."""
    hub = make_hub()
    for folder in ("plugin", ".claude", "workflows"):
        shutil.rmtree(hub / folder)
    write_tree(hub, _fixture_tree() | dict(extra or {}))
    registered = app.client.post("/api/v1/hubs", json={"path": str(hub)}, headers=ORIGIN)
    assert registered.status_code == 201, registered.text
    _get(app, CATALOG)
    return hub


type PublishHub = Callable[..., Path]


@pytest.fixture
def publish_hub(writer: Any, make_hub: Callable[..., Path]) -> PublishHub:
    """Registers the fixture hub (plus ``extra``) on the signed-in app."""

    def make(extra: Mapping[str, TreeEntry] | None = None) -> Path:
        return _registered(writer, make_hub, extra)

    return make


def _get(app: Any, path: str) -> Any:
    response = app.client.get(path)
    assert response.status_code == 200, response.text
    return response.json()


def _draft(hub: Path, draft_id: str, files: Mapping[str, bytes]) -> Path:
    """Writes the draft as the Studio's Claude does; answers its folder."""
    folder = hub / DRAFTS / draft_id
    for path, content in files.items():
        (folder / path).parent.mkdir(parents=True, exist_ok=True)
        (folder / path).write_bytes(content)
    return folder


def _publish(app: Any, draft_id: str, target: Mapping[str, str] | None, **body: bool) -> Any:
    """``POST .../skills/drafts/{draft_id}/publish`` from this server's page."""
    path = f"{CATALOG}/drafts/{draft_id}/publish"
    return app.client.post(path, json={"target": target, **body}, headers=ORIGIN)


def _versions(app: Any, unit_path: str) -> list[ItemVersionMeta]:
    """The unit's versions, oldest first."""
    store = open_item_version_store(app.settings.db_path)
    return list(reversed(store.page("demo", unit_path, limit=200)))


def _origins(app: Any, unit_path: str) -> list[tuple[VersionOrigin, str]]:
    return [(v.origin, v.content_hash) for v in _versions(app, unit_path)]


def _rows(app: Any) -> list[tuple[str, int, str]]:
    """Every stored ``(unit_path, seq, origin)``, in order."""
    with closing(sqlite3.connect(app.settings.db_path)) as connection:
        found = connection.execute(
            "SELECT unit_path, seq, origin FROM item_versions ORDER BY unit_path, seq"
        ).fetchall()
    return [(str(path), int(seq), str(origin)) for path, seq, origin in found]


def _author(hub: Path) -> VersionAuthor:
    project = json.loads((hub / "hub.json").read_bytes())["project"]
    return VersionAuthor(name=project["author_name"], email=project["author_email"])


def _tree(hub: Path) -> dict[str, tuple[bytes, bool]]:
    """Every file under the hub's ``plugin/`` and ``.claude/``: its bytes and executable bit."""
    return {
        str(path.relative_to(hub)): (path.read_bytes(), os.access(path, os.X_OK))
        for folder in ("plugin", ".claude")
        for path in sorted((hub / folder).rglob("*"))
        if path.is_file()
    }


def _refused(response: Any, code: str) -> None:
    assert response.status_code == 409, response.text
    assert response.headers["content-type"] == "application/problem+json"
    assert (response.json()["title"], response.json()["code"]) == ("Item write refused", code)


def _no_path(response: Any, hub: Path) -> None:
    assert str(hub) not in response.text
    assert DRAFTS not in response.text
    assert "plugin/" not in response.text


def test_publishes_edit_agent_when_hand_edited_first(writer: Any, publish_hub: PublishHub) -> None:
    hub = publish_hub()
    by_hand = SCOUT_MD + b"Edited by hand.\n"
    (hub / SCOUT).write_bytes(by_hand)
    published = _agent("scout", "Scout the repo, then report.\n")
    folder = _draft(hub, "agent-edt001", {"scout.md": published})

    response = _publish(writer, "agent-edt001", SCOUT_TARGET)

    assert response.status_code == 200, response.text
    answer = response.json()
    assert (answer["changed"], answer["versioned"], answer["reason"]) == (True, True, None)
    assert (hub / SCOUT).read_bytes() == published
    assert _origins(writer, SCOUT) == [
        (VersionOrigin.EXTERNAL, file_hash(SCOUT_MD)),
        (VersionOrigin.EXTERNAL, file_hash(by_hand)),
        (VersionOrigin.PUBLISH, file_hash(published)),
    ]
    version = _versions(writer, SCOUT)[-1]
    assert version.author == _author(hub)
    assert version.recorded_at == writer.settings.clock()
    assert (version.draft_id, version.first) == ("agent-edt001", False)
    assert answer["version"]["id"] == version.id
    assert answer["version"]["draft_id"] == "agent-edt001"
    assert not folder.exists()
    assert _versions(writer, SCOUT)[1].author is None


def test_publishes_new_item_when_target_null(writer: Any, publish_hub: PublishHub) -> None:
    hub = publish_hub()
    skill = b"---\nname: changelog\ndescription: Writes the changelog.\n---\n# Changelog\n"
    template = b"## Unreleased\n"
    _draft(hub, "skill-new001", {"SKILL.md": skill, "references/template.md": template})

    response = _publish(writer, "skill-new001", None)

    assert response.status_code == 200, response.text
    assert (response.json()["changed"], response.json()["versioned"]) == (True, True)
    changelog = "plugin/demo/skills/changelog"
    assert (hub / changelog / "SKILL.md").read_bytes() == skill
    assert (hub / changelog / "references" / "template.md").read_bytes() == template
    [first] = _versions(writer, changelog)
    files = (
        UnitFile(path="SKILL.md", content=skill),
        UnitFile(path="references/template.md", content=template),
    )
    assert (first.origin, first.first, first.kind) == (VersionOrigin.PUBLISH, True, UnitKind.SKILL)
    assert first.content_hash == folder_hash(files)
    assert not (hub / DRAFTS / "skill-new001").exists()
    listed = {item["id"] for item in _get(writer, CATALOG)["items"]}
    assert "skill/demo/changelog" in listed


@pytest.mark.parametrize(
    ("draft_id", "files"),
    [
        pytest.param("agent-new002", {"scout.md": _agent("scout")}, id="agent"),
        pytest.param("agent-new003", {"Scout.md": _agent("Scout")}, id="agent-other-case"),
        pytest.param("skill-new004", {"SKILL.md": ALPHA_MD + b"Again.\n"}, id="skill"),
    ],
)
def test_refuses_existing_new_item_when_name_taken(
    writer: Any, publish_hub: PublishHub, *, draft_id: str, files: dict[str, bytes]
) -> None:
    hub = publish_hub()
    folder = _draft(hub, draft_id, files)
    tree, rows = _tree(hub), _rows(writer)

    response = _publish(writer, draft_id, None)

    _refused(response, "item_exists")
    _no_path(response, hub)
    assert (_tree(hub), _rows(writer)) == (tree, rows)
    assert sorted(path.name for path in folder.iterdir()) == sorted(files)


def test_publishes_skill_folder_when_files_added_or_renamed(
    writer: Any, publish_hub: PublishHub
) -> None:
    hub = publish_hub()
    changed = ALPHA_MD + b"Now with a script.\n"
    script = b"#!/bin/sh\necho alpha\n"
    folder = _draft(
        hub,
        "skill-edt002",
        {"SKILL.md": changed, "references/r.md": REFERENCE, "scripts/s.sh": script},
    )
    (folder / "scripts" / "s.sh").chmod(0o755)

    edited = _publish(writer, "skill-edt002", ALPHA_TARGET)

    assert edited.status_code == 200, edited.text
    assert {path: _tree(hub)[path] for path in _tree(hub) if path.startswith(ALPHA)} == {
        f"{ALPHA}/SKILL.md": (changed, False),
        f"{ALPHA}/references/r.md": (REFERENCE, False),
        f"{ALPHA}/references/keep.md": (KEEP, False),
        f"{ALPHA}/scripts/s.sh": (script, True),
    }
    assert [origin for origin, _ in _origins(writer, ALPHA)] == [
        VersionOrigin.EXTERNAL,
        VersionOrigin.PUBLISH,
    ]
    assert not folder.exists()

    renamed = b"---\nname: alpha2\ndescription: Checks the alpha flow.\n---\n# Alpha 2\n"
    _draft(hub, "skill-ren001", {"SKILL.md": renamed})
    moved = _publish(writer, "skill-ren001", ALPHA_TARGET)

    assert moved.status_code == 200, moved.text
    assert not (hub / ALPHA).exists()
    assert (hub / ALPHA2 / "SKILL.md").read_bytes() == renamed
    assert (hub / ALPHA2 / "references" / "keep.md").read_bytes() == KEEP
    assert os.access(hub / ALPHA2 / "scripts" / "s.sh", os.X_OK)
    [first] = _versions(writer, ALPHA2)
    assert (first.origin, first.first, first.draft_id) == (
        VersionOrigin.PUBLISH,
        True,
        "skill-ren001",
    )
    # The old unit's versions stay stored (D19).
    assert len(_versions(writer, ALPHA)) == 2
    assert not (hub / DRAFTS / "skill-ren001").exists()


def _commands(file_json: bytes, event: str = "PreToolUse") -> list[str]:
    groups = json.loads(file_json)["hooks"][event]
    return [hook["command"] for group in groups for hook in group["hooks"]]


@pytest.mark.parametrize("hooks_file", ["kept", "missing"])
def test_merges_hooks_when_hook_drafts_published(
    writer: Any, publish_hub: PublishHub, hooks_file: str
) -> None:
    hub = publish_hub()
    draft = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [_command("Y")]}]}}
    _draft(hub, "hook-edt003", {"hooks.json": _json(draft)})

    edited = _publish(writer, "hook-edt003", SECOND_HOOK_TARGET, confirm_managed=True)

    assert edited.status_code == 200, edited.text
    written = json.loads((hub / SETTINGS).read_bytes())
    expected = _settings()
    expected["hooks"]["PreToolUse"][0]["hooks"][1] = _command("Y")
    assert written == expected
    assert [origin for origin, _ in _origins(writer, SETTINGS)] == [
        VersionOrigin.EXTERNAL,
        VersionOrigin.PUBLISH,
    ]
    assert _origins(writer, SETTINGS)[-1][1] == file_hash((hub / SETTINGS).read_bytes())

    if hooks_file == "missing":
        (hub / PLUGIN_HOOKS).unlink()
    before = [] if hooks_file == "missing" else _commands((hub / PLUGIN_HOOKS).read_bytes(), "Stop")
    check = b"#!/bin/sh\nexit 0\n"
    new_hook = {
        "hooks": {
            "Stop": [{"hooks": [_command("${CLAUDE_PLUGIN_ROOT}/scripts/check.sh")]}],
        }
    }
    folder = _draft(hub, "hook-new005", {"hooks.json": _json(new_hook), "scripts/check.sh": check})
    (folder / "scripts" / "check.sh").chmod(0o755)

    added = _publish(writer, "hook-new005", None)

    assert added.status_code == 200, added.text
    assert _commands((hub / PLUGIN_HOOKS).read_bytes(), "Stop") == [
        *before,
        "${CLAUDE_PLUGIN_ROOT}/scripts/check.sh",
    ]
    assert (hub / "plugin/demo/scripts/check.sh").read_bytes() == check
    assert os.access(hub / "plugin/demo/scripts/check.sh", os.X_OK)
    assert _origins(writer, PLUGIN_HOOKS)[-1] == (
        VersionOrigin.PUBLISH,
        file_hash((hub / PLUGIN_HOOKS).read_bytes()),
    )
    assert not folder.exists()


_BIG: Final = b"---\nname: scout\ndescription: Big.\n---\n" + b"x" * MAX_SKILL_FILE_BYTES
# Each publish row of the plan's error table: (draft id, draft files, target, body extra,
# status, code). ``None`` files: no draft folder; ``{}``: an empty one.
_INVALID: Final = [
    pytest.param("agent-UPPER1", {"scout.md": SCOUT_MD}, SCOUT_TARGET, {}, 400, None, id="bad-id"),
    pytest.param("agent-abs001", None, SCOUT_TARGET, {}, 404, None, id="no-folder"),
    pytest.param("agent-emp001", {}, SCOUT_TARGET, {}, 404, None, id="empty-folder"),
    pytest.param(
        "agent-unk001",
        {"ghost.md": _agent("ghost")},
        {"kind": "agent", "source": "demo", "name": "ghost"},
        {},
        404,
        None,
        id="unknown-target",
    ),
    pytest.param("agent-big001", {"scout.md": _BIG}, SCOUT_TARGET, {}, 413, None, id="too-large"),
    pytest.param(
        "agent-nam001",
        {"scout.md": b"---\nname: not a name!\ndescription: D.\n---\n"},
        SCOUT_TARGET,
        {},
        422,
        "draft_invalid",
        id="bad-name",
    ),
    pytest.param(
        "agent-mis001",
        {"notes.txt": b"no agent file\n"},
        SCOUT_TARGET,
        {},
        422,
        "draft_invalid",
        id="no-main-file",
    ),
    pytest.param(
        "skill-knd001",
        {"SKILL.md": b"---\nname: scout\ndescription: D.\n---\n"},
        SCOUT_TARGET,
        {},
        422,
        "draft_invalid",
        id="kind-differs",
    ),
    pytest.param(
        "hook-obj001",
        {"hooks.json": b'{"hooks": []}'},
        SECOND_HOOK_TARGET,
        {"confirm_managed": True},
        422,
        "draft_invalid",
        id="not-hooks-object",
    ),
    pytest.param(
        "agent-hid001",
        {"scout.md": SCOUT_MD, ".notes.md": b"hidden\n"},
        SCOUT_TARGET,
        {},
        422,
        "draft_invalid",
        id="hidden-name",
    ),
    pytest.param(
        "agent-bdy001",
        {"scout.md": _agent("scout", "New.\n")},
        SCOUT_TARGET,
        {"force": True},
        422,
        None,
        id="unknown-field",
    ),
    pytest.param(
        "agent-bdy002",
        {"scout.md": _agent("scout", "New.\n")},
        SCOUT_TARGET,
        {"confirm_managed": "true"},
        422,
        None,
        id="not-strict-bool",
    ),
    pytest.param(
        "agent-bdy003",
        {"scout.md": _agent("scout", "New.\n")},
        {"kind": "workflow", "source": "demo", "name": "scout"},
        {},
        422,
        None,
        id="target-kind",
    ),
    pytest.param(
        "agent-bdy004",
        {"scout.md": _agent("scout", "New.\n")},
        {"kind": "agent", "source": "../demo", "name": "scout"},
        {},
        422,
        None,
        id="target-source",
    ),
]


@pytest.mark.parametrize(("draft_id", "files", "target", "extra", "status", "code"), _INVALID)
def test_refuses_draft_when_invalid(  # noqa: PLR0913 - one row of the error table
    writer: Any,
    publish_hub: PublishHub,
    *,
    draft_id: str,
    files: dict[str, bytes] | None,
    target: dict[str, str],
    extra: dict[str, object],
    status: int,
    code: str | None,
) -> None:
    hub = publish_hub()
    if files is not None:
        (hub / DRAFTS / draft_id).mkdir(parents=True)
        _draft(hub, draft_id, files)
    tree, rows = _tree(hub), _rows(writer)

    response = writer.client.post(
        f"{CATALOG}/drafts/{draft_id}/publish",
        json={"target": target, **extra},
        headers=ORIGIN,
    )

    assert response.status_code == status, response.text
    assert response.headers["content-type"] == "application/problem+json"
    if code is not None:
        assert response.json()["code"] == code
    _no_path(response, hub)
    assert (_tree(hub), _rows(writer)) == (tree, rows)
    if files:
        assert sorted(p.name for p in (hub / DRAFTS / draft_id).iterdir()) == sorted(files)


def test_refuses_draft_when_a_draft_file_is_a_link(writer: Any, publish_hub: PublishHub) -> None:
    hub = publish_hub()
    hub_outside = hub.parent / "outside-scout.md"
    hub_outside.write_bytes(_agent("scout", "From outside.\n"))
    write_tree(hub, {f"{DRAFTS}/agent-lnk001/scout.md": Link(str(hub_outside))})
    tree, rows = _tree(hub), _rows(writer)

    response = _publish(writer, "agent-lnk001", SCOUT_TARGET)

    _refused(response, "link_in_path")
    _no_path(response, hub)
    assert (_tree(hub), _rows(writer)) == (tree, rows)


def test_refuses_write_when_draft_equal_to_item(writer: Any, publish_hub: PublishHub) -> None:
    hub = publish_hub()
    stamp = (hub / SCOUT).stat().st_mtime_ns
    folder = _draft(hub, "agent-eql001", {"scout.md": SCOUT_MD})
    rows = _rows(writer)

    response = _publish(writer, "agent-eql001", SCOUT_TARGET)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "changed": False,
        "versioned": False,
        "reason": None,
        "version": None,
    }
    assert (hub / SCOUT).stat().st_mtime_ns == stamp
    assert _rows(writer) == rows
    # A7: the draft is removed all the same.
    assert not folder.exists()


def _github_token() -> str:
    return "gh" + "p_" + _ALNUM * 2 + "wxyz"


def test_reports_secret_when_published_file_matches(writer: Any, publish_hub: PublishHub) -> None:
    hub = publish_hub()
    token = _github_token()
    secret = _agent("scout", f"Use token {token} for the API.\n")
    folder = _draft(hub, "agent-sec001", {"scout.md": secret})

    response = _publish(writer, "agent-sec001", SCOUT_TARGET)

    assert response.status_code == 200, response.text
    assert response.json() == {
        "changed": True,
        "versioned": False,
        "reason": "secret",
        "version": None,
    }
    assert (hub / SCOUT).read_bytes() == secret
    assert VersionOrigin.PUBLISH not in {origin for origin, _ in _origins(writer, SCOUT)}
    assert not folder.exists()
    assert token.encode() not in Path(writer.settings.db_path).read_bytes()


def test_requires_managed_confirmation_when_item_managed(
    writer: Any, publish_hub: PublishHub
) -> None:
    hub = publish_hub()
    history = _get(writer, f"{CATALOG}/hook/settings/settings-pretooluse-2/versions")
    assert (history["managed"], history["unit_path"]) == (True, SETTINGS)
    draft = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [_command("Y")]}]}}
    folder = _draft(hub, "hook-man001", {"hooks.json": _json(draft)})
    before = (hub / SETTINGS).read_bytes()

    for response in (
        _publish(writer, "hook-man001", SECOND_HOOK_TARGET),
        _publish(writer, "hook-man001", SECOND_HOOK_TARGET, confirm_managed=False),
    ):
        _refused(response, "managed_confirmation_required")
    assert (hub / SETTINGS).read_bytes() == before
    assert [origin for origin, _ in _origins(writer, SETTINGS)] == [VersionOrigin.EXTERNAL]
    assert folder.exists()

    confirmed = _publish(writer, "hook-man001", SECOND_HOOK_TARGET, confirm_managed=True)

    assert confirmed.status_code == 200, confirmed.text
    assert _commands((hub / SETTINGS).read_bytes()) == ["python3 hooks/x1.py", "Y", "x3"]
    assert _origins(writer, SETTINGS)[-1][0] is VersionOrigin.PUBLISH
    assert not folder.exists()


class KeepDraftWriter:
    """The real writer whose ``remove_draft`` fails while ``keep`` is set, as a draft folder
    that cannot be removed does."""

    def __init__(self) -> None:
        self.real = FileSystemHubItemWriter()
        self.keep = True

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)

    def remove_draft(self, hub_path: str, draft_id: str) -> None:
        if self.keep:
            raise HubItemWriteError(f"rmtree failed at {hub_path}/.hub-drafts/{draft_id}")
        self.real.remove_draft(hub_path, draft_id)


def test_refuses_spent_draft_when_published_again_after_draft_not_removed(
    open_writer: WriterOpener, make_hub: Callable[..., Path]
) -> None:
    kept = KeepDraftWriter()
    app = open_writer(item_writer=kept)
    hub = _registered(app, make_hub)
    published = _agent("scout", "Scout the repo, then report.\n")
    folder = _draft(hub, "agent-spt001", {"scout.md": published})

    first = _publish(app, "agent-spt001", SCOUT_TARGET)

    assert first.status_code == 500, first.text
    body = first.json()
    assert (body["code"], body["published"], body["versioned"]) == (
        "draft_not_removed",
        True,
        True,
    )
    assert body["detail"] == "Published; the draft is still there. Discard it."
    _no_path(first, hub)
    assert (hub / SCOUT).read_bytes() == published
    rows = _rows(app)
    # The user edits the kept draft again and publishes it: the draft is spent (A20).
    (folder / "scout.md").write_bytes(_agent("scout", "Edited again.\n"))
    kept.keep = False

    again = _publish(app, "agent-spt001", SCOUT_TARGET)

    _refused(again, "draft_already_published")
    assert again.json()["detail"] == "This draft was already published; discard it"
    assert (hub / SCOUT).read_bytes() == published
    assert _rows(app) == rows
    assert (folder / "scout.md").read_bytes() == _agent("scout", "Edited again.\n")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param({}, id="no-body-fields"),
        pytest.param({"confirm_managed": True}, id="target-left-out"),
        pytest.param(
            {"target": {**SCOUT_TARGET, "path": "plugin/demo"}}, id="target-field-unknown"
        ),
    ],
)
def test_refuses_body_when_target_missing_or_its_field_unknown(
    writer: Any, publish_hub: PublishHub, body: dict[str, object]
) -> None:
    hub = publish_hub()
    folder = _draft(hub, "agent-bdy005", {"scout.md": _agent("scout", "New.\n")})
    tree, rows = _tree(hub), _rows(writer)

    response = writer.client.post(
        f"{CATALOG}/drafts/agent-bdy005/publish", json=body, headers=ORIGIN
    )

    assert response.status_code == 422, response.text
    found = response.json()
    # The body's validation problem, not a draft's refusal: it names the fields, no `code`.
    assert found["title"] == "Invalid request body"
    assert found["errors"]
    assert all(error["pointer"].startswith("/target") for error in found["errors"])
    assert "code" not in found
    assert (_tree(hub), _rows(writer)) == (tree, rows)
    assert (folder / "scout.md").exists()


def test_refuses_hook_edit_when_hooks_file_past_bounds(
    writer: Any, publish_hub: PublishHub
) -> None:
    # A13: the hook's file is past the 256 KiB read bound (under the 1 MiB settings cap), so
    # the draft cannot be merged into it.
    big = _settings() | {"padding": "x" * (MAX_SKILL_FILE_BYTES + 1)}
    hub = publish_hub({SETTINGS: _json(big)})
    draft = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [_command("Y")]}]}}
    folder = _draft(hub, "hook-big001", {"hooks.json": _json(draft)})
    tree, rows = _tree(hub), _rows(writer)

    response = _publish(writer, "hook-big001", SECOND_HOOK_TARGET, confirm_managed=True)

    _refused(response, "unit_unreadable")
    _no_path(response, hub)
    assert (_tree(hub), _rows(writer)) == (tree, rows)
    assert folder.exists()


def test_refuses_publish_when_hub_has_no_identity(
    writer: Any, make_hub: Callable[..., Path]
) -> None:
    def no_author(document: dict[str, Any]) -> None:
        del document["project"]["author_name"], document["project"]["author_email"]

    hub = _registered(writer, lambda: make_hub(change=no_author))
    folder = _draft(hub, "agent-aut001", {"scout.md": _agent("scout", "New.\n")})
    tree, rows = _tree(hub), _rows(writer)

    response = _publish(writer, "agent-aut001", SCOUT_TARGET)

    _refused(response, "no_author")
    assert "author" in response.json()["reason"]
    assert (_tree(hub), _rows(writer)) == (tree, rows)
    assert folder.exists()


class FaultWriter:
    """The real writer, with a fault to inject: ``old_stays`` refuses a rename's removal of the
    old unit; ``unreadable`` fails the draft's read as an I/O error does."""

    def __init__(self) -> None:
        self.real = FileSystemHubItemWriter()
        self.old_stays = False
        self.unreadable = False

    def __getattr__(self, name: str) -> Any:
        return getattr(self.real, name)

    def remove_unit(self, hub_path: str, unit_path: str, *, kind: UnitKind) -> None:
        if self.old_stays:
            raise HubItemWriteError(f"rmtree failed at {hub_path}/{unit_path}")
        self.real.remove_unit(hub_path, unit_path, kind=kind)

    def read_draft(self, hub_path: str, draft_id: str) -> Any:
        if self.unreadable:
            raise draft_unreadable()
        return self.real.read_draft(hub_path, draft_id)


def test_keeps_spent_draft_when_renamed_old_item_not_removed(
    open_writer: WriterOpener, make_hub: Callable[..., Path]
) -> None:
    faults = FaultWriter()
    faults.old_stays = True
    app = open_writer(item_writer=faults)
    hub = _registered(app, make_hub)
    renamed = b"---\nname: alpha2\ndescription: Checks the alpha flow.\n---\n# Alpha 2\n"
    folder = _draft(hub, "skill-old001", {"SKILL.md": renamed})

    response = _publish(app, "skill-old001", ALPHA_TARGET)

    assert response.status_code == 500, response.text
    assert response.json() | {"instance": None} == {
        "type": "about:blank",
        "title": "Item write failed",
        "status": 500,
        "detail": (
            "Published; the old item could not be removed and stays. The draft is still there: "
            "discard it."
        ),
        "instance": None,
        "code": "write_failed",
        "kind": "old_not_removed",
        "published": True,
        "changed": True,
        "versioned": True,
        "reason": None,
    }
    _no_path(response, hub)
    assert (hub / ALPHA2 / "SKILL.md").read_bytes() == renamed
    assert (hub / ALPHA / "SKILL.md").read_bytes() == ALPHA_MD
    assert (folder / "SKILL.md").read_bytes() == renamed
    faults.old_stays = False

    _refused(_publish(app, "skill-old001", ALPHA_TARGET), "draft_already_published")
    assert (hub / ALPHA / "SKILL.md").read_bytes() == ALPHA_MD


def test_answers_draft_read_failed_when_draft_unreadable(
    open_writer: WriterOpener, make_hub: Callable[..., Path]
) -> None:
    faults = FaultWriter()
    faults.unreadable = True
    app = open_writer(item_writer=faults)
    hub = _registered(app, make_hub)
    folder = _draft(hub, "agent-unr001", {"scout.md": _agent("scout", "New.\n")})
    tree, rows = _tree(hub), _rows(app)

    response = _publish(app, "agent-unr001", SCOUT_TARGET)

    assert response.status_code == 500, response.text
    body = response.json()
    assert (body["title"], body["code"], body["kind"]) == (
        "Draft read failed",
        "write_failed",
        "draft_unreadable",
    )
    assert body["detail"] == "The draft could not be read; nothing was written or recorded."
    _no_path(response, hub)
    assert (_tree(hub), _rows(app)) == (tree, rows)
    assert folder.exists()
