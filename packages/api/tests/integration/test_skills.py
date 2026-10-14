"""The Skills tab's routes on the composed app over a registered hub (AGH-164, plan Wave 4 I).

The hub is a ``hub init`` hub whose ``plugin/``, ``.claude/skills``, ``.claude/agents``, settings
files and ``hub.lock`` are replaced by the AC-164.1 tree (erratum E7), so the exact item set is
known. Every read is a GET on the real file adapter (``HubFileSystem``): nothing is written,
spawned or fetched. Synthetic data only.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Final

import pytest
import pytest_socket

from agent_hub.core.skills.skill_sources import MAX_SKILL_FILE_BYTES, SkillLimits
from agent_hub.core.testing.skill_trees import (
    Link,
    TreeEntry,
    a_skills_fixture_tree,
    write_tree,
)
from agent_hub.generator.registered_hub_files import HubFileSystem

CATALOG: Final = "/api/v1/projects/demo/skills"
ALPHA: Final = f"{CATALOG}/skill/hub-workflow/alpha"
EVALUATOR: Final = f"{CATALOG}/agent/hub-workflow/evaluator"
PRE_TOOL_USE: Final = f"{CATALOG}/hook/settings/settings-pretooluse-1"
PATHS: Final = (CATALOG, ALPHA, f"{ALPHA}/files/0123456789abcdef")
SENTINEL: Final = "SENTINEL-s9q2-never-written"
SKILL_ITEM_KEYS: Final = {
    "id",
    "kind",
    "source",
    "name",
    "description",
    "origin",
    "mode",
    "invocation",
    "source_path",
    "diagnostics_count",
    "usage",
    "linked_from",
    "active",
    "state",
}
EXPECTED_IDS: Final = {
    "skill/hub-workflow/alpha",
    "skill/hub-workflow/beta",
    "skill/demo/gamma",
    "skill/extra/delta",
    "skill/claude/local-one",
    "agent/hub-workflow/evaluator",
    "agent/demo/scout",
    "agent/claude/local-agent",
    "hook/hub-workflow/hub-workflow-stop-1",
    "hook/settings/settings-pretooluse-1",
    "hook/settings/settings-sessionstart-1",
}
SHA: Final = "5f0c2e1a9b8d7c6e5f4a3b2c1d0e9f8a7b6c5d4e"

type SkillsHub = Callable[..., Path]


def _replace_tree(hub: Path, tree: dict[str, TreeEntry]) -> None:
    for folder in ("plugin", ".claude/skills", ".claude/agents"):
        shutil.rmtree(hub / folder, ignore_errors=True)
    for path in tree:
        target = hub / path
        if target.is_symlink() or target.is_file():
            target.unlink()
    write_tree(hub, tree)


@pytest.fixture
def skills_hub(composed: Any, make_hub: Callable[..., Path]) -> SkillsHub:
    """Registers a ``demo`` hub holding the AC-164.1 tree plus ``extra`` entries."""

    def make(extra: dict[str, TreeEntry] | None = None) -> Path:
        hub = make_hub()
        _replace_tree(hub, a_skills_fixture_tree() | (extra or {}))
        registered = composed.client.post("/api/v1/hubs", json={"path": str(hub)})
        assert registered.status_code == 201, registered.text
        return hub

    return make


def _items(composed: Any) -> dict[str, Any]:
    response = composed.client.get(CATALOG)
    assert response.status_code == 200, response.text
    return {item["id"]: item for item in response.json()["items"]}


def _problem(response: Any, status: int) -> None:
    assert response.status_code == status, response.text
    assert response.headers["content-type"].startswith("application/problem+json")


def test_lists_external_plugins_when_sockets_blocked(composed: Any, skills_hub: SkillsHub) -> None:
    settings = {
        "enabledPlugins": {
            "superpowers@agent-hub": True,
            "hookify@agent-hub": False,
            "other@claude-plugins-official": True,
        }
    }
    marketplace = {
        "name": "agent-hub",
        "plugins": [
            {"name": "hub-workflow", "source": "./plugin/hub-workflow"},
            {"name": "superpowers", "source": {"source": "github", "repo": "o/sp", "sha": SHA}},
        ],
    }
    skills_hub(
        {
            ".claude/settings.json": json.dumps(settings).encode(),
            ".claude-plugin/marketplace.json": json.dumps(marketplace).encode(),
        }
    )

    # The app's event loop already runs; only its local socket pair stays allowed.
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        response = composed.client.get(CATALOG)
    finally:
        pytest_socket.enable_socket()

    assert response.status_code == 200, response.text
    assert response.json()["external_plugins"] == [
        {
            "name": "hookify",
            "marketplace": "agent-hub",
            "pin": None,
            "enabled": False,
            "content": "not in this hub",
        },
        {
            "name": "other",
            "marketplace": "claude-plugins-official",
            "pin": None,
            "enabled": True,
            "content": "not in this hub",
        },
        {
            "name": "superpowers",
            "marketplace": "agent-hub",
            "pin": SHA,
            "enabled": True,
            "content": "not in this hub",
        },
    ]


def test_answers_empty_or_unknown_when_hub_bare_or_project_unknown(
    composed: Any, make_hub: Callable[..., Path]
) -> None:
    hub = make_hub()
    shutil.rmtree(hub / "plugin")
    shutil.rmtree(hub / ".claude")
    assert composed.client.post("/api/v1/hubs", json={"path": str(hub)}).status_code == 201

    bare = composed.client.get(CATALOG)
    unknown = composed.client.get("/api/v1/projects/nowhere/skills")

    assert bare.status_code == 200, bare.text
    assert bare.json()["items"] == []
    assert bare.json()["notice"] == "No skills found in this hub; it may not be synced yet."
    _problem(unknown, 404)


def test_returns_catalog_shape_when_fixture_hub_read(composed: Any, skills_hub: SkillsHub) -> None:
    skills_hub()

    response = composed.client.get(CATALOG)

    assert response.status_code == 200, response.text
    body = response.json()
    assert {"external_plugins", "truncated", "notice", "project", "usage_days"} <= set(body)
    assert (body["project"], body["truncated"], body["usage_days"]) == ("demo", False, 30)
    items = {item["id"]: item for item in body["items"]}
    assert set(items) == EXPECTED_IDS
    for item in items.values():
        assert set(item) == SKILL_ITEM_KEYS
        assert item["description"] is None or (
            "\n" not in item["description"] and len(item["description"]) <= 200
        )
        assert not item["source_path"].startswith("/")
        assert not Path(item["source_path"]).is_absolute()
        if item["kind"] != "hook":
            assert {"count", "last_used_at"} <= set(item["usage"])
    alpha = items["skill/hub-workflow/alpha"]
    assert alpha["linked_from"] == [".claude/skills/alpha"]
    assert (alpha["origin"], alpha["mode"], alpha["invocation"]) == (
        "managed",
        "both",
        "/alpha <issue id>",
    )
    assert alpha["source_path"] == "plugin/hub-workflow/skills/alpha/SKILL.md"
    assert items["skill/hub-workflow/beta"]["mode"] == "user-only"
    assert items["skill/demo/gamma"]["mode"] == "model-only"
    assert items["skill/claude/local-one"]["origin"] == "local"
    assert items["agent/demo/scout"]["origin"] == "project-owned"
    assert items["hook/hub-workflow/hub-workflow-stop-1"]["active"] is False
    assert items["hook/settings/settings-sessionstart-1"]["origin"] == "project-owned"


def test_returns_detail_when_skill_agent_or_hook_read(composed: Any, skills_hub: SkillsHub) -> None:
    hub = skills_hub()

    alpha = composed.client.get(ALPHA)
    evaluator = composed.client.get(EVALUATOR)
    hook = composed.client.get(PRE_TOOL_USE)

    assert alpha.status_code == 200, alpha.text
    detail = alpha.json()
    skill_md = hub / "plugin/hub-workflow/skills/alpha/SKILL.md"
    assert detail["raw"] == skill_md.read_bytes().decode("utf-8")
    assert [pair["key"] for pair in detail["frontmatter"]] == [
        "name",
        "description",
        "argument-hint",
    ]
    assert all(pair["known"] for pair in detail["frontmatter"])
    assert detail["argument_hint"] == "<issue id>"
    assert detail["body"].startswith("# Alpha")
    assert detail["toc"] == [{"level": 1, "text": "Alpha"}, {"level": 2, "text": "Steps"}]
    assert [step["title"] for step in detail["structure"]["steps"]] == ["Review", "Next"]
    assert [relation["id"] for relation in detail["uses"]] == [
        "agent/hub-workflow/evaluator",
        "skill/hub-workflow/beta",
    ]
    assert {file["path"]: file["role"] for file in detail["files"]} == {
        "references/r.md": "references",
        "scripts/s.sh": "scripts",
    }
    assert detail["context_cost"]["approximate"] is True
    assert {"diagnostics", "used_by", "lock"} <= set(detail)
    assert evaluator.status_code == 200, evaluator.text
    agent = evaluator.json()
    assert (agent["tools"], agent["model"]) == (["Read", "Grep"], "sonnet")
    assert "skill/hub-workflow/alpha" in [relation["id"] for relation in agent["used_by"]]
    assert hook.status_code == 200, hook.text
    facts = hook.json()
    assert facts["source_path"] == ".claude/settings.json"
    assert (facts["hook"]["event"], facts["hook"]["matcher"], facts["hook"]["command"]) == (
        "PreToolUse",
        "Bash",
        "python3 plugin/hub-workflow/hooks/guard.py",
    )
    assert facts["body"] is None


@pytest.fixture
def adapter_calls(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[str]]:
    """The names of the ``HubFileSystem`` skill reads called while the test runs."""
    calls: list[str] = []
    for name in ("skill_sources", "read_skill_file"):
        real = getattr(HubFileSystem, name)

        def spy(self: Any, *args: Any, _real: Any = real, _name: str = name, **kw: Any) -> Any:
            calls.append(_name)
            return _real(self, *args, **kw)

        monkeypatch.setattr(HubFileSystem, name, spy)
    yield calls


@pytest.mark.parametrize(
    "path",
    [
        f"{CATALOG}/plugin/hub-workflow/alpha",
        f"{CATALOG}/skill/hub-workflow/..",
        f"{CATALOG}/skill/hub-workflow/a.b",
        f"{CATALOG}/skill/hub-workflow/a/b",
        f"{CATALOG}/skill/hub-workflow/%2e%2e",
        f"{CATALOG}/skill/hub-workflow/a%5Cb",
        f"{CATALOG}/skill/hub-workflow/{'a' * 129}",
        f"{CATALOG}/skill/../alpha",
        f"{CATALOG}/skill/a.b/alpha",
        f"{CATALOG}/skill/%2e%2e/alpha",
        f"{CATALOG}/skill/hub-workflow/alpha/files/not-an-id",
        f"{CATALOG}/skill/hub-workflow/alpha/files/..%2F..%2Fhub.json",
    ],
)
def test_refuses_bad_segments_without_reading_when_detail_read(
    *, composed: Any, skills_hub: SkillsHub, adapter_calls: list[str], path: str
) -> None:
    skills_hub()
    adapter_calls.clear()

    response = composed.client.get(path)

    assert response.status_code in {400, 404, 422}, response.text
    assert response.headers["content-type"].startswith("application/problem+json")
    assert adapter_calls == []


def test_reads_no_file_when_name_unknown(
    composed: Any, skills_hub: SkillsHub, adapter_calls: list[str]
) -> None:
    skills_hub()
    assert composed.client.get(CATALOG).status_code == 200
    adapter_calls.clear()

    response = composed.client.get(f"{CATALOG}/skill/hub-workflow/missing")

    _problem(response, 404)
    assert "read_skill_file" not in adapter_calls


@pytest.mark.parametrize(
    "path",
    [
        f"{CATALOG}/skill/hub-workflow/missing",
        f"{CATALOG}/skill/nowhere/alpha",
        f"{CATALOG}/agent/hub-workflow/alpha",
        f"{CATALOG}/hook/nowhere/nowhere-stop-1",
        f"{CATALOG}/skill/hub-workflow/missing/files/{'0' * 16}",
    ],
)
def test_refuses_unknown_name_without_reading_when_catalog_cold(
    *, composed: Any, skills_hub: SkillsHub, adapter_calls: list[str], path: str
) -> None:
    skills_hub()
    adapter_calls.clear()

    response = composed.client.get(path)

    _problem(response, 404)
    assert adapter_calls == ["skill_sources"]


def test_serves_bundled_file_when_id_issued(composed: Any, skills_hub: SkillsHub) -> None:
    skills_hub(
        {
            "plugin/hub-workflow/skills/alpha/assets/logo.bin": b"\x89PNG\x00\x01binary",
            "plugin/hub-workflow/skills/alpha/references/big.md": b"x" * (300 * 1024),
        }
    )
    files = {file["path"]: file for file in composed.client.get(ALPHA).json()["files"]}

    text = composed.client.get(f"{ALPHA}/files/{files['references/r.md']['id']}")
    binary = composed.client.get(f"{ALPHA}/files/{files['assets/logo.bin']['id']}")
    big = composed.client.get(f"{ALPHA}/files/{files['references/big.md']['id']}")
    unknown = composed.client.get(f"{ALPHA}/files/0123456789abcdef")
    elsewhere = composed.client.get(
        f"{CATALOG}/skill/hub-workflow/beta/files/{files['references/r.md']['id']}"
    )

    assert text.status_code == 200, text.text
    assert text.json() == {
        "id": files["references/r.md"]["id"],
        "path": "references/r.md",
        "role": "references",
        "size": len(b"# R\n\nRead on demand.\n"),
        "text": "# R\n\nRead on demand.\n",
        "binary": False,
    }
    assert binary.status_code == 200, binary.text
    assert (binary.json()["binary"], binary.json()["text"], binary.json()["role"]) == (
        True,
        None,
        "assets",
    )
    assert files["references/big.md"]["too_large"] is True
    _problem(big, 413)
    assert big.json()["title"] == "Skill file too large"
    _problem(unknown, 404)
    _problem(elsewhere, 404)


def _snapshot(root: Path) -> dict[str, tuple[bytes | str, int]]:
    seen: dict[str, tuple[bytes | str, int]] = {}
    for folder, dirs, files in os.walk(root):
        for name in dirs + files:
            path = Path(folder) / name
            stat = path.lstat()
            if path.is_symlink():
                content: bytes | str = os.readlink(path)
            elif path.is_file():
                content = path.read_bytes()
            else:
                content = "dir"
            seen[str(path.relative_to(root))] = (content, stat.st_mtime_ns)
    return seen


def test_stays_read_only_when_routes_read(
    *, composed: Any, skills_hub: SkillsHub, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    sentinel = tmp_path / SENTINEL
    script = f"#!/bin/sh\necho ran > {sentinel}\n".encode()
    hub = skills_hub({"plugin/hub-workflow/skills/alpha/scripts/s.sh": script})
    (hub / "plugin/hub-workflow/skills/alpha/scripts/s.sh").chmod(0o755)
    before = _snapshot(hub)
    spawned: list[str] = []

    def refuse(name: str) -> Callable[..., Any]:
        def refused(*args: Any, **kwargs: Any) -> Any:
            spawned.append(name)
            raise AssertionError(f"{name} called by a skills read")

        return refused

    monkeypatch.setattr(subprocess, "Popen", refuse("Popen"))
    monkeypatch.setattr(os, "posix_spawn", refuse("posix_spawn"))
    monkeypatch.setattr(os, "fork", refuse("fork"))
    files = composed.client.get(ALPHA).json()["files"]
    gets = [
        CATALOG,
        ALPHA,
        EVALUATOR,
        PRE_TOOL_USE,
        *(f"{ALPHA}/files/{file['id']}" for file in files),
    ]
    answers = [composed.client.get(path).status_code for path in gets]
    writes = [
        getattr(composed.client, method)(path).status_code
        for path in PATHS
        for method in ("post", "put", "patch", "delete")
    ]

    assert answers == [200] * len(gets)
    assert writes == [405] * len(writes)
    assert spawned == []
    assert not sentinel.exists()
    assert _snapshot(hub) == before


def test_truncates_when_hub_over_bounds(composed: Any, skills_hub: SkillsHub) -> None:
    limits = SkillLimits()
    padding = "Text of a long skill. " * 2_000  # ~44 KiB: 501 of them pass the 16 MiB budget
    many: dict[str, TreeEntry] = {
        f"plugin/extra/skills/s-{number:03d}/SKILL.md": (
            f"---\nname: s-{number:03d}\ndescription: Skill {number}.\n---\n# S\n\n{padding}\n"
        ).encode()
        for number in range(limits.items_per_kind + 1)
    }
    huge = b"---\nname: huge\ndescription: Too large.\n---\n" + b"x" * (300 * 1024)
    files: dict[str, TreeEntry] = {
        f"plugin/demo/skills/files/references/f-{number:03d}.md": b"# F\n"
        for number in range(limits.files_per_skill + 1)
    }
    files["plugin/demo/skills/files/SKILL.md"] = b"---\nname: files\ndescription: Many.\n---\n"
    skills_hub(many | files | {"plugin/demo/skills/huge/SKILL.md": huge})

    response = composed.client.get(CATALOG)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["truncated"] is True
    assert body["notice"]
    skills = [item for item in body["items"] if item["kind"] == "skill"]
    assert len(skills) <= limits.items_per_kind
    huge_detail = composed.client.get(f"{CATALOG}/skill/demo/huge").json()
    assert "too_large" in [diagnostic["code"] for diagnostic in huge_detail["diagnostics"]]
    assert (huge_detail["body"], huge_detail["raw"]) == (None, None)
    assert len(huge) > MAX_SKILL_FILE_BYTES
    files_detail = composed.client.get(f"{CATALOG}/skill/demo/files").json()
    assert len(files_detail["files"]) <= limits.files_per_skill
    # Reads stop at the 16 MiB budget: the last skills in catalog order are listed unread.
    assert any(
        "over_budget" in {d["code"] for d in _diagnostics(composed, item["id"])}
        for item in reversed(skills)
        if item["diagnostics_count"] > 0
    )


def _diagnostics(composed: Any, item_id: str) -> list[dict[str, Any]]:
    response = composed.client.get(f"{CATALOG}/{item_id}")
    assert response.status_code == 200, response.text
    return list(response.json()["diagnostics"])


def test_lists_duplicates_when_two_plugins_share_name(composed: Any, skills_hub: SkillsHub) -> None:
    tree = a_skills_fixture_tree()
    skills_hub(
        {
            "plugin/demo/skills/alpha/SKILL.md": tree["plugin/hub-workflow/skills/alpha/SKILL.md"],
            ".claude/skills/alpha": Link("../../plugin/hub-workflow/skills/alpha"),
        }
    )

    items = _items(composed)
    managed = composed.client.get(ALPHA)
    project = composed.client.get(f"{CATALOG}/skill/demo/alpha")

    assert {"skill/hub-workflow/alpha", "skill/demo/alpha"} <= set(items)
    assert managed.status_code == project.status_code == 200
    assert (managed.json()["source"], project.json()["source"]) == ("hub-workflow", "demo")
    for detail, other in ((managed.json(), "demo"), (project.json(), "hub-workflow")):
        duplicates = [d for d in detail["diagnostics"] if d["code"] == "duplicate_name"]
        assert len(duplicates) == 1
        assert other in duplicates[0]["message"]
