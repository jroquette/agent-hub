"""Workflow discovery: hub packs, then built-ins, by name (AC-213.16, precedence hub > built-in);
each file loaded by the strict loader (AC-213.2); pack paths kept inside the pack.

TESTING.md: synthetic trees only, written under ``tmp_path``.
"""

import os
from pathlib import Path

import pytest

from agent_hub.generator.workflow_discovery import (
    BUILTIN_WORKFLOWS,
    MAX_ROOT_WORKFLOWS,
    PackPathError,
    WorkflowDiscovery,
    discover_workflows,
    pack_resolver,
    resolve_pack_file,
)

_SHELL = b"version: 1\nname: {name}\nnodes:\n  - id: a\n    type: shell\n    command: [true]\n"


def _write(path: Path, content: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return path


def _workflow(root: Path, pack: str, name: str) -> Path:
    return _write(root / pack / f"{name}.yaml", _SHELL.replace(b"{name}", name.encode()))


@pytest.fixture
def hub(tmp_path: Path) -> Path:
    (tmp_path / "hub").mkdir()
    return tmp_path / "hub"


@pytest.fixture
def builtin(tmp_path: Path) -> Path:
    (tmp_path / "builtin").mkdir()
    return tmp_path / "builtin"


def _discover(hub: Path, builtin: Path) -> WorkflowDiscovery:
    return discover_workflows(hub, builtin_root=builtin)


def _reasons(found: WorkflowDiscovery) -> dict[str, str]:
    return {problem.path.name: problem.reason for problem in found.problems}


def test_finds_pack_workflow_when_hub_holds_one(hub: Path, builtin: Path) -> None:
    path = _workflow(hub / "workflows", "delivery", "issue-to-pr")

    found = _discover(hub, builtin)

    assert found.problems == ()
    [workflow] = found.workflows
    assert workflow.name == "issue-to-pr"
    assert workflow.pack == "delivery"
    assert workflow.origin == "hub"
    assert workflow.path == path
    assert workflow.pack_root == hub / "workflows" / "delivery"
    assert workflow.document["nodes"] == [{"id": "a", "type": "shell", "command": [True]}]


def test_finds_json_workflow_when_pack_holds_one(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/p/w.json", b'{"version": 1, "name": "w", "nodes": []}')

    [workflow] = _discover(hub, builtin).workflows

    assert workflow.document == {"version": 1, "name": "w", "nodes": []}


def test_finds_builtin_workflow_when_hub_has_none(hub: Path, builtin: Path) -> None:
    _workflow(builtin, "issue-to-pr", "issue-to-pr")

    [workflow] = _discover(hub, builtin).workflows

    assert (workflow.name, workflow.origin) == ("issue-to-pr", "builtin")
    assert workflow.pack_root == builtin / "issue-to-pr"


def test_hub_workflow_wins_when_builtin_has_same_name(hub: Path, builtin: Path) -> None:
    ours = _workflow(hub / "workflows", "mine", "review")
    theirs = _workflow(builtin, "review", "review")
    _workflow(builtin, "review", "deliver")

    found = _discover(hub, builtin)

    assert [(w.name, w.origin, w.path) for w in found.workflows] == [
        ("deliver", "builtin", builtin / "review/deliver.yaml"),
        ("review", "hub", ours),
    ]
    assert [w.path for w in found.overridden] == [theirs]


def test_keeps_other_workflows_when_one_file_is_broken(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/p/bad.yaml", b"name: bad\nname: again\n")
    _workflow(hub / "workflows", "p", "good")

    found = _discover(hub, builtin)

    assert [w.name for w in found.workflows] == ["good"]
    [problem] = found.problems
    assert problem.path == hub / "workflows/p/bad.yaml"
    assert problem.origin == "hub"
    assert problem.line == 2
    assert "more than once" in problem.reason
    assert problem.message.startswith(f"{problem.path}:2: ")


def test_keeps_first_pack_when_hub_packs_share_name(hub: Path, builtin: Path) -> None:
    first = _workflow(hub / "workflows", "a-pack", "review")
    _workflow(hub / "workflows", "b-pack", "review")

    found = _discover(hub, builtin)

    assert [w.path for w in found.workflows] == [first]
    assert "by a-pack/review.yaml" in _reasons(found)["review.yaml"]
    assert str(hub) not in _reasons(found)["review.yaml"]


def test_reports_problem_when_name_differs_from_file_name(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/p/w.yaml", b"version: 1\nname: other\nnodes: []\n")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert "other" in _reasons(found)["w.yaml"]


def test_reads_linked_file_when_link_stays_in_pack(hub: Path, builtin: Path) -> None:
    pack = hub / "workflows/p"
    _workflow(pack, "drafts", "w")
    os.symlink("drafts/w.yaml", pack / "w.yaml")

    [workflow] = _discover(hub, builtin).workflows

    assert workflow.name == "w"


def test_reports_problem_when_linked_file_leaves_pack(hub: Path, builtin: Path) -> None:
    outside = _workflow(hub, "elsewhere", "w")
    (hub / "workflows/p").mkdir(parents=True)
    os.symlink(outside, hub / "workflows/p/w.yaml")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert "leaves" in _reasons(found)["w.yaml"]


def test_reports_problem_when_pack_folder_is_link(hub: Path, builtin: Path) -> None:
    _workflow(hub, "elsewhere", "w")
    (hub / "workflows").mkdir()
    os.symlink(hub / "elsewhere", hub / "workflows/linked")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert "link" in _reasons(found)["linked"]


def test_reports_problem_when_workflow_file_sits_outside_pack(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/w.yaml", b"name: w\n")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert "pack" in _reasons(found)["w.yaml"]


def test_reports_problem_when_workflow_file_is_fifo(hub: Path, builtin: Path) -> None:
    (hub / "workflows/p").mkdir(parents=True)
    os.mkfifo(hub / "workflows/p/w.yaml")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert "regular" in _reasons(found)["w.yaml"]


def test_skips_entries_when_hidden_or_not_workflows(hub: Path, builtin: Path) -> None:
    root = hub / "workflows"
    _workflow(root, ".hidden", "secret")
    _write(root / "p/.draft.yaml", b"name: [\n")
    _write(root / "p/README.md", b"# notes\n")
    _write(root / "p/prompts/implement.md", b"Implement.\n")
    _write(root / "p/fixtures/ok.yaml", b"workflow: w\n")
    _write(root / "README.md", b"# packs\n")
    _workflow(root, "p", "w")

    found = _discover(hub, builtin)

    assert [w.name for w in found.workflows] == ["w"]
    assert found.problems == ()


def test_returns_nothing_when_no_workflow_folders_exist(tmp_path: Path) -> None:
    found = discover_workflows(tmp_path / "hub", builtin_root=tmp_path / "absent")

    assert found == WorkflowDiscovery(workflows=(), overridden=(), problems=())


def test_points_at_core_package_data_when_builtin_root_defaulted() -> None:
    assert BUILTIN_WORKFLOWS.parts[-4:] == ("agent_hub", "core", "workflows", "builtin")


def test_resolves_prompt_when_path_is_inside_folder(tmp_path: Path) -> None:
    prompt = _write(tmp_path / "pack/prompts/steps/implement.md", b"Implement.\n")

    assert resolve_pack_file(tmp_path / "pack", "prompts", "steps/implement.md") == prompt


def test_resolves_script_when_link_stays_in_pack(tmp_path: Path) -> None:
    shared = _write(tmp_path / "pack/shared/check.py", b"print(1)\n")
    (tmp_path / "pack/scripts").mkdir()
    os.symlink("../shared/check.py", tmp_path / "pack/scripts/check.py")

    assert resolve_pack_file(tmp_path / "pack", "scripts", "check.py") == shared


@pytest.mark.parametrize(
    ("relative", "match"),
    [
        ("../workflow.yaml", "'..'"),
        ("a/../../x.md", "'..'"),
        ("/etc/hosts", "not a relative path"),
        ("", "not a relative path"),
        ("a\\b.md", "not a relative path"),
        ("a\0b", "not a relative path"),
    ],
)
def test_refuses_path_when_it_could_escape_folder(
    tmp_path: Path, relative: str, match: str
) -> None:
    _write(tmp_path / "pack/workflow.yaml", b"name: w\n")
    (tmp_path / "pack/prompts").mkdir()

    with pytest.raises(PackPathError, match=match):
        resolve_pack_file(tmp_path / "pack", "prompts", relative)


def test_refuses_path_when_link_leaves_pack(tmp_path: Path) -> None:
    secret = _write(tmp_path / "secret.md", b"x\n")
    (tmp_path / "pack/prompts").mkdir(parents=True)
    os.symlink(secret, tmp_path / "pack/prompts/p.md")

    with pytest.raises(PackPathError, match="leaves"):
        resolve_pack_file(tmp_path / "pack", "prompts", "p.md")


@pytest.mark.parametrize(
    ("relative", "match"), [("missing.md", "no such file"), ("sub", "not a regular file")]
)
def test_refuses_path_when_not_a_regular_file(tmp_path: Path, relative: str, match: str) -> None:
    (tmp_path / "pack/prompts/sub").mkdir(parents=True)

    with pytest.raises(PackPathError, match=match):
        resolve_pack_file(tmp_path / "pack", "prompts", relative)


def test_keeps_other_workflows_when_file_holds_control_character(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/p/bad.yaml", b"a: \x00b\n")
    _workflow(hub / "workflows", "p", "good")

    found = _discover(hub, builtin)

    assert [w.name for w in found.workflows] == ["good"]
    [problem] = found.problems
    assert (problem.path.name, problem.line) == ("bad.yaml", 1)


def test_carries_key_lines_when_workflow_loads(hub: Path, builtin: Path) -> None:
    _workflow(hub / "workflows", "p", "w")

    [workflow] = _discover(hub, builtin).workflows

    assert workflow.lines[("name",)] == 2
    assert workflow.lines[("nodes", 0, "command")] == 6


def test_reports_one_problem_when_root_holds_too_many_files(hub: Path, builtin: Path) -> None:
    for number in range(MAX_ROOT_WORKFLOWS + 5):
        _workflow(hub / "workflows", f"pack{number // 50}", f"w{number:04d}")
    _workflow(builtin, "extra", "builtin-only")

    found = _discover(hub, builtin)

    hub_names = [w.name for w in found.workflows if w.origin == "hub"]
    assert len(hub_names) == MAX_ROOT_WORKFLOWS
    assert "builtin-only" in [w.name for w in found.workflows]
    [problem] = found.problems
    assert problem.path == hub / "workflows"
    assert str(MAX_ROOT_WORKFLOWS) in problem.reason


def test_reports_problem_when_hub_workflows_root_is_link(hub: Path, builtin: Path) -> None:
    _workflow(hub, "elsewhere/p", "w")
    os.symlink(hub / "elsewhere", hub / "workflows")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    [problem] = found.problems
    assert problem.path == hub / "workflows"
    assert "link" in problem.reason


@pytest.mark.parametrize(
    "content", [b"name: [\n", b"version: 1\nname: other\nnodes: []\n"], ids=["broken", "renamed"]
)
def test_shadows_builtin_when_hub_file_of_same_name_fails(
    hub: Path, builtin: Path, content: bytes
) -> None:
    _write(hub / "workflows/p/review.yaml", content)
    theirs = _workflow(builtin, "review", "review")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert [w.path for w in found.overridden] == [theirs]
    assert [p.path.name for p in found.problems] == ["review.yaml"]


def test_keeps_failed_first_claim_when_later_pack_reuses_name(hub: Path, builtin: Path) -> None:
    _write(hub / "workflows/a/review.yaml", b"name: [\n")
    later = _workflow(hub / "workflows", "b", "review")

    found = _discover(hub, builtin)

    assert found.workflows == ()
    assert [p.path for p in found.problems][-1] == later


def _valid(root: Path, pack: str, name: str) -> Path:
    text = f"version: 1\nname: {name}\nrevision: 1\nnodes:\n  - {{id: a, type: halt, reason: x}}\n"
    return _write(root / pack / f"{name}.yaml", text.encode())


def test_resolves_an_include_among_its_pack_workflows_when_given_a_name(
    hub: Path, builtin: Path
) -> None:
    _valid(hub / "workflows", "sdlc", "deliver")
    _valid(hub / "workflows", "sdlc", "review")
    _valid(hub / "workflows", "other", "lint")
    found = _discover(hub, builtin)
    pack = found.workflows[0].pack_root.parent / "sdlc"

    resolve = pack_resolver(found, pack)

    review = resolve("review")
    assert review is not None
    assert review.name == "review"
    assert resolve("lint") is None
    assert resolve("ghost") is None


def test_resolves_a_pack_mate_when_the_hub_overrides_its_name(hub: Path, builtin: Path) -> None:
    _valid(builtin, "sdlc", "review")
    _valid(hub / "workflows", "mine", "review")
    found = _discover(hub, builtin)

    review = pack_resolver(found, builtin / "sdlc")("review")

    assert review is not None
