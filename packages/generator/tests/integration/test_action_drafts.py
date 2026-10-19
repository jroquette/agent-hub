"""Draft actions: an action is committed only when its document and script equal the hub's
``HEAD`` (AC-350.11, docs/design/scenarios.md); real git in a ``tmp_path`` hub.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from agent_hub.generator.action_discovery import discover_actions

REAL_GIT = shutil.which("git")
ACTION = """\
version: 1
name: {name}
description: A demo read
effect: read
runtime: sh
script: scripts/{name}.sh
output_format: {{type: object}}
"""


@pytest.fixture(autouse=True)
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No user or system git config reaches a test's git."""
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", str(tmp_path))
    (home / ".gitconfig").write_text(
        "[user]\n\tname = Demo Author\n\temail = demo@example.com\n"
        "[maintenance]\n\tauto = false\n[gc]\n\tauto = 0\n",
        encoding="utf-8",
    )


def git(hub: Path, *arguments: str) -> None:
    assert REAL_GIT is not None, "git is needed for the draft cases"
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [REAL_GIT, *arguments], cwd=hub, check=True, capture_output=True
    )


def an_action(hub: Path, pack: str, name: str) -> None:
    script = hub / "actions" / pack / "scripts" / f"{name}.sh"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text("#!/bin/sh\necho '{}'\n", encoding="utf-8")
    (hub / "actions" / pack / f"{name}.yaml").write_text(ACTION.format(name=name), "utf-8")


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    hub = tmp_path / "demo-hub"
    hub.mkdir()
    for name in ("get-order", "get-invoice", "get-cover", "get-quote"):
        an_action(hub, "orders", name)
    return hub


def drafts(hub: Path) -> dict[str, bool]:
    found = discover_actions(hub)
    assert found.problems == ()
    return {entry.document.name: entry.draft for entry in found.actions}


def test_marks_draft_when_action_untracked_or_changed(hub: Path) -> None:
    git(hub, "init", "-q", "-b", "main")
    git(hub, "add", "actions/orders/get-order.yaml", "actions/orders/scripts/get-order.sh")
    git(hub, "add", "actions/orders/get-invoice.yaml", "actions/orders/scripts/get-invoice.sh")
    git(hub, "add", "actions/orders/get-cover.yaml", "actions/orders/scripts/get-cover.sh")
    git(hub, "commit", "-q", "-m", "actions")
    script = hub / "actions" / "orders" / "scripts" / "get-invoice.sh"
    script.write_text("#!/bin/sh\necho '{\"changed\": true}'\n", encoding="utf-8")
    (hub / "actions" / "orders" / "get-cover.yaml").write_text(
        ACTION.format(name="get-cover") + "timeout: 1m\n", encoding="utf-8"
    )
    git(hub, "add", "actions/orders/get-cover.yaml")

    assert drafts(hub) == {
        "get-cover": True,  # changed and staged, not committed
        "get-invoice": True,  # script changed
        "get-order": False,
        "get-quote": True,  # untracked
    }


def test_clears_draft_when_action_committed(hub: Path) -> None:
    git(hub, "init", "-q", "-b", "main")
    git(hub, "add", "actions")
    git(hub, "commit", "-q", "-m", "actions")
    (hub / "notes.md").write_text("an unrelated change\n", encoding="utf-8")

    assert set(drafts(hub).values()) == {False}


def test_marks_every_action_draft_when_hub_not_git(hub: Path) -> None:
    assert set(drafts(hub).values()) == {True}


def test_marks_pack_draft_when_helper_uncommitted(hub: Path) -> None:
    # A helper a script sources is part of every action of its pack.
    an_action(hub, "queues", "get-queue")
    helper = hub / "actions" / "orders" / "scripts" / "lib" / "common.sh"
    helper.parent.mkdir(parents=True)
    helper.write_text("DEMO=1\n", encoding="utf-8")
    git(hub, "init", "-q", "-b", "main")
    git(hub, "add", "actions")
    git(hub, "commit", "-q", "-m", "actions")
    assert set(drafts(hub).values()) == {False}

    helper.write_text("DEMO=2\n", encoding="utf-8")
    (hub / "actions" / "queues" / "scripts" / "new.sh").write_text("DEMO=3\n", encoding="utf-8")

    found = {entry.ref: entry.draft for entry in discover_actions(hub).actions}
    assert found == {
        "orders/get-cover": True,
        "orders/get-invoice": True,
        "orders/get-order": True,
        "orders/get-quote": True,
        "queues/get-queue": True,
    }
    git(hub, "add", "actions")
    git(hub, "commit", "-q", "-m", "helpers")
    assert set(drafts(hub).values()) == {False}
