"""The hub workflows that override a built-in, and whether each pack is the built-in's as shipped.

TESTING.md: synthetic trees only, written under ``tmp_path``.
"""

from pathlib import Path

import pytest

from agent_hub.core.doctor.snapshot import WorkflowShadow
from agent_hub.generator.workflow_shadows import workflow_shadows

_SHELL = b"version: 1\nname: {name}\nnodes:\n  - id: a\n    type: shell\n    command: [true]\n"


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _pack(root: Path, pack: str, *, prompt: bytes = b"Group the notes.\n") -> Path:
    """A pack with two workflows and a prompt, under ``root``."""
    for name in ("inbox", "context"):
        _write(root / pack / f"{name}.yaml", _SHELL.replace(b"{name}", name.encode()))
    _write(root / pack / "prompts" / "group.md", prompt)
    return root / pack


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    (tmp_path / "hub").mkdir()
    return tmp_path / "hub"


@pytest.fixture
def builtin(tmp_path: Path) -> Path:
    root = tmp_path / "builtin"
    _pack(root, "brain-care")
    return root


def _shadow(name: str, *, identical: bool, pack: str = "brain-care") -> WorkflowShadow:
    return WorkflowShadow(
        name=name,
        path=f"workflows/{pack}/{name}.yaml",
        pack=f"workflows/{pack}",
        builtin_pack="brain-care",
        identical=identical,
    )


def test_finds_none_when_hub_has_no_workflows(hub: Path, builtin: Path) -> None:
    assert workflow_shadows(hub, builtin_root=builtin) == ()


def test_finds_identical_shadows_when_hub_pack_copies_builtin(hub: Path, builtin: Path) -> None:
    _pack(hub / "workflows", "brain-care")
    # Files of the hub's own beside the copy, and a built-in's caches, change nothing.
    _write(hub / "workflows" / "brain-care" / "prompts" / "mine.md", b"Mine.\n")
    _write(builtin / "brain-care" / "scripts" / "__pycache__" / "x.pyc", b"\x00")
    _write(builtin / "brain-care" / ".hidden", b"x")

    assert workflow_shadows(hub, builtin_root=builtin) == (
        _shadow("context", identical=True),
        _shadow("inbox", identical=True),
    )


def test_finds_differing_shadows_when_builtin_prompt_changed(hub: Path, builtin: Path) -> None:
    _pack(hub / "workflows", "brain-care", prompt=b"Group the notes (old).\n")

    assert workflow_shadows(hub, builtin_root=builtin) == (
        _shadow("context", identical=False),
        _shadow("inbox", identical=False),
    )


def test_finds_differing_shadow_when_hub_pack_lacks_builtin_file(hub: Path, builtin: Path) -> None:
    _write(
        hub / "workflows" / "mine" / "inbox.yaml",
        (builtin / "brain-care" / "inbox.yaml").read_bytes(),
    )

    assert workflow_shadows(hub, builtin_root=builtin) == (
        _shadow("inbox", identical=False, pack="mine"),
    )


def test_finds_differing_shadow_when_hub_file_is_link(hub: Path, builtin: Path) -> None:
    pack = _pack(hub / "workflows", "brain-care")
    copy = _write(hub / "elsewhere.md", (pack / "prompts" / "group.md").read_bytes())
    (pack / "prompts" / "group.md").unlink()
    (pack / "prompts" / "group.md").symlink_to(copy)

    assert [shadow.identical for shadow in workflow_shadows(hub, builtin_root=builtin)] == [
        False,
        False,
    ]


def test_skips_shadow_when_hub_file_does_not_load(hub: Path, builtin: Path) -> None:
    pack = _pack(hub / "workflows", "brain-care")
    (pack / "inbox.yaml").write_bytes(b"version: [\n")

    assert workflow_shadows(hub, builtin_root=builtin) == (_shadow("context", identical=False),)


def test_finds_differing_shadows_when_prompt_same_size_other_bytes(
    hub: Path, builtin: Path
) -> None:
    _pack(hub / "workflows", "brain-care", prompt=b"Group the notes!\n")

    assert [shadow.identical for shadow in workflow_shadows(hub, builtin_root=builtin)] == [
        False,
        False,
    ]


def test_reads_pack_once_and_skips_hub_file_when_sizes_differ(
    hub: Path, builtin: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A hub file of another size differs whatever its bytes, so it is never read (a big file
    # costs nothing), and the pack's two workflows share one comparison.
    _pack(hub / "workflows", "brain-care", prompt=b"Group the notes, as an older release did.\n")
    read: list[Path] = []
    real = Path.read_bytes

    def recording(path: Path) -> bytes:
        read.append(path)
        return real(path)

    monkeypatch.setattr(Path, "read_bytes", recording)

    shadows = workflow_shadows(hub, builtin_root=builtin)

    assert [shadow.identical for shadow in shadows] == [False, False]
    assert hub / "workflows" / "brain-care" / "prompts" / "group.md" not in read
    assert len(read) == len(set(read))
