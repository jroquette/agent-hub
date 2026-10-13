"""Synthetic skill trees for the Skills tab's tests (AGH-164): the AC-164.1 fixture hub, the
``/feature``-shaped body (AC-164.18, P5), and the ways to put a tree in a ``FakeHub`` or on disk.

A tree maps hub-relative paths to ``bytes`` (a regular file), ``Link`` (a link with its target
text) or ``Fifo`` (a named pipe). ``InMemorySkillTree`` and ``DiskSkillTree`` are the
``skill_tree`` fixtures ``SkillSourcesContract`` runs against. Synthetic data only.
"""

import hashlib
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

from agent_hub.core.hub_files.hub_lock import (
    HubLock,
    LockEntry,
    ManagedFileEntry,
    ManagedLinkEntry,
    SeededEntry,
    lock_bytes,
    read_hub_lock,
)
from agent_hub.core.hubs.hub_registry import HubFileReader
from agent_hub.core.testing.hub_fakes import FakeHub, FakeHubFileReader


@dataclass(frozen=True, slots=True)
class Link:
    """A link whose target is ``target`` (as ``readlink`` gives it)."""

    target: str


@dataclass(frozen=True, slots=True)
class Fifo:
    """A named pipe: opening it for reading would block."""


type TreeEntry = bytes | Link | Fifo

# The project of the fixture hub: ``plugin/demo`` is its own plugin.
FIXTURE_PROJECT: Final = "demo"
# The number of steps ``a_feature_shaped_body`` has by the shared step rule (P5).
FEATURE_BODY_STEPS: Final = 5
FIXTURE_PLATFORM_VERSION: Final = "0.13.0"

_ALPHA = """---
name: alpha
description: Checks the alpha flow before a release.
argument-hint: "<issue id>"
---
# Alpha

Run it before a release.

## Steps

1. **Review**: ask the `evaluator` agent to check the change.
2. **Next**: run `/beta` when the review passes.

See [r](references/r.md); `scripts/s.sh` runs at invocation.
"""

_BETA = """---
name: beta
description: Writes the beta notes.
disable-model-invocation: true
---
# Beta

Write the notes.
"""

_GAMMA = """---
name: gamma
description: Project checks the model runs on its own.
user-invocable: false
---
# Gamma

Check the project.
"""

_DELTA = """---
name: delta
description: An extra plugin's skill.
---
# Delta
"""

_LOCAL_ONE = """---
name: local-one
description: A local skill kept in .claude.
---
# Local one
"""

_EVALUATOR = """---
name: evaluator
description: Checks a delivery against its spec.
tools: Read, Grep
model: sonnet
---
You are the evaluator. Read the spec, then the diff.
"""

_SCOUT = """---
name: scout
description: Looks around the project's repos.
tools: Read
---
You are the scout.
"""

_LOCAL_AGENT = """---
name: local-agent
description: A local agent kept in .claude.
---
You are a local agent.
"""

_PRE_TOOL_USE = "python3 plugin/hub-workflow/hooks/guard.py"
_SESSION_START = "make brain-brief"
_STOP = "python3 ${CLAUDE_PLUGIN_ROOT}/hooks/stop_gate.py"


def _command_hook(command: str, *, matcher: str | None = None) -> dict[str, object]:
    group: dict[str, object] = {"hooks": [{"type": "command", "command": command}]}
    if matcher is not None:
        group["matcher"] = matcher
    return group


def _json(document: object) -> bytes:
    return (json.dumps(document, indent=2) + "\n").encode()


def _settings() -> bytes:
    return _json(
        {
            "enabledPlugins": {"hub-workflow@agent-hub": False},
            "hooks": {
                "PreToolUse": [_command_hook(_PRE_TOOL_USE, matcher="Bash")],
                "SessionStart": [_command_hook(_SESSION_START)],
            },
        }
    )


def _lock(tree: Mapping[str, TreeEntry]) -> bytes:
    files: dict[str, LockEntry] = {}
    for path, entry in sorted(tree.items()):
        managed = path.startswith("plugin/hub-workflow/") or path == ".claude/settings.json"
        if isinstance(entry, bytes) and managed:
            sha = hashlib.sha256(entry).hexdigest()
            files[path] = ManagedFileEntry(ownership="managed", sha256=sha, executable=False)
        elif isinstance(entry, Link) and path == ".claude/skills/alpha":
            files[path] = ManagedLinkEntry(ownership="managed", symlink=entry.target)
    files[".claude/settings.project.json"] = SeededEntry(ownership="seeded")
    lock = HubLock(
        lock_version=1,
        platform_version=FIXTURE_PLATFORM_VERSION,
        schema_version=1,
        modules=(),
        files=dict(sorted(files.items())),
    )
    return lock_bytes(lock)


def a_skills_fixture_tree() -> dict[str, TreeEntry]:
    """The AC-164.1 hub of project ``demo``.

    ``plugin/hub-workflow`` (skills ``alpha`` with ``references/r.md`` and ``scripts/s.sh``,
    ``beta``; agent ``evaluator``; one hook in ``hooks/hooks.json``), ``plugin/demo`` (skill
    ``gamma``, agent ``scout``), ``plugin/extra/skills/delta``, ``.claude/skills/alpha`` linked to
    ``../../plugin/hub-workflow/skills/alpha``, a real ``.claude/skills/local-one`` and
    ``.claude/agents/local-agent.md``, two hooks in ``settings.json`` (the ``SessionStart`` one
    also in ``settings.project.json``), and a ``hub.lock`` listing the ``hub-workflow`` files and
    ``settings.json`` as managed with their sha256. Modes: ``beta`` user-only, ``gamma``
    model-only, the others both. ``alpha`` names agent ``evaluator`` and skill ``/beta``.
    """
    tree: dict[str, TreeEntry] = {
        "plugin/hub-workflow/skills/alpha/SKILL.md": _ALPHA.encode(),
        "plugin/hub-workflow/skills/alpha/references/r.md": b"# R\n\nRead on demand.\n",
        "plugin/hub-workflow/skills/alpha/scripts/s.sh": b"#!/bin/sh\necho alpha\n",
        "plugin/hub-workflow/skills/beta/SKILL.md": _BETA.encode(),
        "plugin/hub-workflow/agents/evaluator.md": _EVALUATOR.encode(),
        "plugin/hub-workflow/hooks/hooks.json": _json({"hooks": {"Stop": [_command_hook(_STOP)]}}),
        "plugin/demo/skills/gamma/SKILL.md": _GAMMA.encode(),
        "plugin/demo/agents/scout.md": _SCOUT.encode(),
        "plugin/extra/skills/delta/SKILL.md": _DELTA.encode(),
        ".claude/skills/alpha": Link("../../plugin/hub-workflow/skills/alpha"),
        ".claude/skills/local-one/SKILL.md": _LOCAL_ONE.encode(),
        ".claude/agents/local-agent.md": _LOCAL_AGENT.encode(),
        ".claude/settings.json": _settings(),
        ".claude/settings.project.json": _json(
            {"hooks": {"SessionStart": [_command_hook(_SESSION_START)]}}
        ),
    }
    tree["hub.lock"] = _lock(tree)
    return tree


def a_feature_shaped_body() -> str:
    """A body shaped like the hub's ``/feature`` (AC-164.18), with the cases the shared step
    rule must agree on (P5): a nested ordered item, a numbered line in a fenced block inside a
    step and one at column 0 in a fence; ``FEATURE_BODY_STEPS`` steps in all. The web builders
    hold the same text (``aFeatureShapedBody``)."""
    return """# Feature

Turn an idea into a delivered feature.

## Steps

1. **Spec**: the `requirements-analyst` agent writes `spec.md`.
   1. A nested item is not a step.
2. **Gate: user approves the spec**. Stop until they do.
3. **Plan**: run `/create-plan` on the approved spec.
4. **Implement** in a worktree; run `make check` before the PR.
   ```bash
   1. not a step inside a fence
   ```
5. **Doctor**: run `./hub doctor` and fix what it finds.

```text
6. not a step either
```

## Notes

- Ask the user when the scope is unclear.
"""


def fake_hub_of(tree: Mapping[str, TreeEntry], **fields: object) -> FakeHub:
    """A ``FakeHub`` holding ``tree`` under the skill roots, its ``hub.lock`` read as the lock
    when the tree has one; ``fields`` set any other ``FakeHub`` field."""
    files = {path: entry for path, entry in tree.items() if isinstance(entry, bytes)}
    links = {path: entry.target for path, entry in tree.items() if isinstance(entry, Link)}
    specials = frozenset(path for path, entry in tree.items() if isinstance(entry, Fifo))
    hub = FakeHub(skill_files=files, skill_links=links, skill_specials=specials)
    lock = files.get("hub.lock")
    if lock is not None:
        hub.lock = read_hub_lock(lock)
    for name, value in fields.items():
        setattr(hub, name, value)
    return hub


def write_tree(root: Path, tree: Mapping[str, TreeEntry]) -> None:
    """Write ``tree`` under the real folder ``root``: files, links (never resolved) and FIFOs."""
    for path, entry in sorted(tree.items()):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(entry, Link):
            target.symlink_to(entry.target)
        elif isinstance(entry, Fifo):
            os.mkfifo(target)
        else:
            target.write_bytes(entry)


@dataclass
class InMemorySkillTree:
    """The ``skill_tree`` fixture of the fake: a ``FakeHub`` at ``hub_path`` read by
    ``FakeHubFileReader``."""

    hub_path: str = "/hubs/demo-hub"
    hub: FakeHub = field(default_factory=FakeHub)
    fake: FakeHubFileReader = field(init=False)

    def __post_init__(self) -> None:
        self.fake = FakeHubFileReader({self.hub_path: self.hub})

    @property
    def reader(self) -> HubFileReader:
        """The reader under test."""
        return self.fake

    def write(self, path: str, content: bytes) -> None:
        """Add a regular file."""
        self.hub.skill_files[path] = content

    def link(self, path: str, target: str) -> None:
        """Add a link to ``target``."""
        self.hub.skill_links[path] = target

    def fifo(self, path: str) -> None:
        """Add a named pipe."""
        self.hub.skill_specials = self.hub.skill_specials | {path}


@dataclass
class DiskSkillTree:
    """The ``skill_tree`` fixture of a real adapter: a hub folder at ``root`` read by
    ``reader`` (``HubFileSystem`` in the generator's contract run)."""

    root: Path
    reader: HubFileReader

    @property
    def hub_path(self) -> str:
        """The hub folder."""
        return str(self.root)

    def write(self, path: str, content: bytes) -> None:
        """Write a regular file."""
        write_tree(self.root, {path: content})

    def link(self, path: str, target: str) -> None:
        """Make a link to ``target``."""
        write_tree(self.root, {path: Link(target)})

    def fifo(self, path: str) -> None:
        """Make a named pipe."""
        write_tree(self.root, {path: Fifo()})
