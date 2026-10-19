"""Action discovery: the hub's ``actions/<pack>/`` documents, loaded strictly, their scripts kept
inside the pack by real path (AC-350.6, docs/design/scenarios.md).

TESTING.md: synthetic trees only, written under ``tmp_path``.
"""

import os
from pathlib import Path

import pytest

from agent_hub.generator.action_discovery import ActionDiscovery, discover_actions

ACTION = """\
version: 1
name: {name}
description: A demo read
effect: {effect}
runtime: sh
script: scripts/{name}.sh
inputs:
  ref: {{type: string, required: true}}
output_format:
  type: {output_type}
"""


def _write(path: Path, content: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _action(
    hub: Path,
    pack: str,
    name: str,
    *,
    effect: str = "read",
    output_type: str = "object",
    script: bool = True,
) -> Path:
    if script:
        _write(hub / "actions" / pack / "scripts" / f"{name}.sh", "#!/bin/sh\necho '{}'\n")
    text = ACTION.format(name=name, effect=effect, output_type=output_type)
    return _write(hub / "actions" / pack / f"{name}.yaml", text)


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    (tmp_path / "hub").mkdir()
    return tmp_path / "hub"


def _shown(found: ActionDiscovery) -> list[tuple[str, int | None, str | None, str]]:
    return [(p.file, p.line, p.key, p.reason) for p in found.problems]


def test_lists_actions_when_packs_hold_documents(hub: Path) -> None:
    _action(hub, "orders", "get-order")
    _action(hub, "orders", "send-message", effect="write")
    _action(hub, "queues", "send-message", effect="write")
    _write(hub / "actions" / "orders" / "README.md", "not an action\n")

    found = discover_actions(hub)

    assert found.problems == ()
    assert [(entry.ref, entry.document.effect) for entry in found.actions] == [
        ("orders/get-order", "read"),
        ("orders/send-message", "write"),
        ("queues/send-message", "write"),
    ]
    first = found.actions[0]
    assert first.document_path == "actions/orders/get-order.yaml"
    assert first.script_path == "actions/orders/scripts/get-order.sh"
    assert first.content_hash.startswith("sha256:")
    assert discover_actions(hub / "missing").actions == ()


def test_refuses_script_when_path_leaves_pack(hub: Path, tmp_path: Path) -> None:
    outside = _write(tmp_path / "outside.sh", "#!/bin/sh\n")
    _action(hub, "orders", "get-order", script=False)
    link = hub / "actions" / "orders" / "scripts" / "get-order.sh"
    link.parent.mkdir(parents=True)
    os.symlink(outside, link)
    _action(hub, "orders", "no-script", script=False)

    found = discover_actions(hub)

    assert found.actions == ()
    assert _shown(found) == [
        (
            "actions/orders/get-order.yaml",
            6,
            "script",
            "scripts/get-order.sh leaves its pack through a link",
        ),
        ("actions/orders/no-script.yaml", 6, "script", "no such file in scripts/: no-script.sh"),
    ]


def test_reports_file_line_key_when_action_invalid(hub: Path) -> None:
    _action(hub, "orders", "get-order", effect="delete")
    _write(
        hub / "actions" / "orders" / "renamed.yaml",
        ACTION.format(name="other", effect="read", output_type="object"),
    )
    _write(hub / "actions" / "orders" / "broken.yaml", "version: 1\nname: [\n")
    _write(hub / "actions" / "stray.yaml", "version: 1\n")

    found = discover_actions(hub)

    assert found.actions == ()
    shown = _shown(found)
    assert shown[0][:3] == ("actions/orders/broken.yaml", 3, None)
    assert shown[1:] == [
        (
            "actions/orders/get-order.yaml",
            4,
            "effect",
            "Input should be 'read', 'write' or 'destroy'",
        ),
        ("actions/orders/renamed.yaml", 2, "name", "name 'other' is not the file name 'renamed'"),
        ("actions/stray.yaml", None, None, "an action file belongs in a pack folder"),
    ]
    assert str(found.problems[1]) == (
        "actions/orders/get-order.yaml:4: effect: Input should be 'read', 'write' or 'destroy'"
    )


def test_refuses_output_format_when_schema_invalid(hub: Path) -> None:
    _action(hub, "orders", "get-order", output_type="objekt")

    found = discover_actions(hub)

    assert found.actions == ()
    [(file, line, key, reason)] = _shown(found)
    assert (file, line, key) == ("actions/orders/get-order.yaml", 9, "output_format")
    assert reason.startswith("not a valid JSON Schema: type: ")
