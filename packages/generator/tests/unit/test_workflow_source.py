"""The workflow source over discovery: each file shown hub-relative or ``<builtin>/``, with its
origin, and a name filter (AC-213.15, AC-213.16).

TESTING.md: synthetic trees only, written under ``tmp_path``.
"""

from pathlib import Path

from agent_hub.core.workflows.catalog import LoadProblem, WorkflowFile
from agent_hub.generator.workflow_source import DiscoveredWorkflowSource

_SHELL = (
    "version: 1\nname: {name}\nrevision: 1\nnodes:\n  - id: a\n    type: shell\n    command: [x]\n"
)


def _workflow(root: Path, pack: str, name: str, *, text: str = _SHELL) -> None:
    (root / pack).mkdir(parents=True, exist_ok=True)
    (root / pack / f"{name}.yaml").write_text(text.replace("{name}", name))


def _shown(item: WorkflowFile | LoadProblem) -> tuple[str, str]:
    if isinstance(item, LoadProblem):
        return (item.file, "problem")
    return (item.file, item.origin)


def test_gives_each_file_its_origin_when_hub_and_builtins_hold_workflows(tmp_path: Path) -> None:
    hub, builtin = tmp_path / "hub", tmp_path / "builtin"
    _workflow(hub / "workflows", "mine", "ship")
    _workflow(builtin, "base", "review")
    _workflow(builtin, "base", "ship")
    _workflow(hub / "workflows", "mine", "bad", text="nodes: [")

    items = list(DiscoveredWorkflowSource(hub, builtin_root=builtin).workflow_files())

    assert sorted(_shown(item) for item in items) == [
        ("<builtin>/base/review.yaml", "builtin"),
        ("workflows/mine/bad.yaml", "problem"),
        ("workflows/mine/ship.yaml", "hub"),
    ]


def test_keeps_one_name_when_only_given(tmp_path: Path) -> None:
    hub, builtin = tmp_path / "hub", tmp_path / "builtin"
    _workflow(hub / "workflows", "mine", "ship")
    _workflow(hub / "workflows", "mine", "lint")
    builtin.mkdir()

    items = DiscoveredWorkflowSource(hub, only="lint", builtin_root=builtin).workflow_files()

    assert [_shown(item) for item in items] == [("workflows/mine/lint.yaml", "hub")]
