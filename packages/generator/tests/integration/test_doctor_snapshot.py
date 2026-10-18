"""The doctor's snapshot builder on real folders (plan F.2): what each selected read fills.

``hub doctor``'s own tests (cli integration) pin the command's behaviour; these pin the builder the
command and the control plane share, with git and the developer's prefix injected.
"""

import json
import os
from pathlib import Path

import pytest

from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, select_rules
from agent_hub.core.doctor.snapshot import LockAbsent
from agent_hub.core.hub_config.effective_identity import IdentityKey, Source, Sourced
from agent_hub.core.hub_config.local_config import LocalConfig
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ConfigProblem
from agent_hub.core.testing.builders import a_hub_document, a_second_repo
from agent_hub.core.workflows.catalog import check_workflows
from agent_hub.generator.doctor_snapshot import build_doctor_snapshot, item_leftovers

RUNNING = "4.5.6"
NO_RULES = Selection(rules=(), notes=(), severities={})


@pytest.fixture
def hub_root(tmp_path: Path) -> Path:
    root = tmp_path / "demo-hub"
    root.mkdir()
    return root


def a_config() -> HubConfig:
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    document["repos"].append(a_second_repo())
    return HubConfig.model_validate(document)


def every_rule(config: HubConfig) -> Selection:
    selection = select_rules(REGISTRY, config=config, only=())
    assert isinstance(selection, Selection)
    return selection


def test_reads_present_repos_only_when_repos_selected(hub_root: Path) -> None:
    config = a_config()
    checkout = hub_root.parent / "demo-api"
    checkout.mkdir()
    (checkout / "AGENTS.md").write_text("# demo-api\n", encoding="utf-8")

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    by_dir = {repo.dir: repo.files for repo in snapshot.repos}
    assert list(by_dir) == ["demo-api", "demo-web"]
    assert by_dir["demo-web"] is None
    assert by_dir["demo-api"] is not None
    assert "AGENTS.md" in by_dir["demo-api"].entries


def test_reads_nothing_when_no_rule_selected(hub_root: Path) -> None:
    called: list[bool] = []

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=a_config(),
        running=RUNNING,
        selection=NO_RULES,
        local=LocalConfig(),
        branch_prefix=lambda: called.append(True) or None,
    )

    assert snapshot.lock is None
    assert snapshot.repos == ()
    assert snapshot.base_hooks is None
    assert snapshot.branch_prefix is None
    assert snapshot.workflows is None
    assert called == []


def test_gives_absent_lock_when_hub_has_no_lock(hub_root: Path) -> None:
    config = a_config()
    (hub_root / "hub.json").write_text(json.dumps(a_hub_document()), encoding="utf-8")

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.lock == LockAbsent()
    assert snapshot.base_hooks is not None
    assert snapshot.running_version == RUNNING


def test_gives_no_lock_when_lock_unreadable(hub_root: Path) -> None:
    config = a_config()
    lock = hub_root / "hub.lock"
    lock.write_text("{}", encoding="utf-8")
    os.chmod(lock, 0)
    if os.access(lock, os.R_OK):
        pytest.skip("running as a user that reads any file")

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.lock is None


def test_uses_prefix_injected_when_identity_read_and_local_valid(hub_root: Path) -> None:
    config = a_config()
    prefix = Sourced("dev/", Source.GIT, IdentityKey.BRANCH_PREFIX)

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=lambda: prefix,
    )

    assert snapshot.branch_prefix == prefix


def test_skips_prefix_injected_when_local_file_invalid(hub_root: Path) -> None:
    config = a_config()
    called: list[bool] = []
    problems = (ConfigProblem("$", "not valid JSON"),)

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=problems,
        branch_prefix=lambda: called.append(True) or None,
    )

    assert snapshot.branch_prefix is None
    assert snapshot.local == problems
    assert called == []


def test_reads_hub_workflows_when_workflows_rule_selected(hub_root: Path) -> None:
    # AGH-227: `workflows.valid` reads the hub's packs and the built-ins through the source.
    config = a_config()
    pack = hub_root / "workflows" / "demo"
    pack.mkdir(parents=True)
    (pack / "lint.yaml").write_text(
        "version: 1\nname: lint\nrevision: 1\nnodes:\n  - id: a\n    type: shell\n"
        "    command: ['true']\n    promt: x\n",
        encoding="utf-8",
    )

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.workflows is not None
    catalog = check_workflows(snapshot.workflows)
    assert "issue-to-pr" in [plan.document.name for plan in catalog.plans]
    assert [(file, where) for file, _, where, _ in catalog.problems] == [
        ("workflows/demo/lint.yaml", "nodes[0].promt")
    ]


def test_lists_pack_folders_when_workflows_rule_selected(hub_root: Path) -> None:
    # The control plane's cache watches each pack folder, even one git does not list (empty).
    config = a_config()
    (hub_root / "workflows" / "empty").mkdir(parents=True)
    (hub_root / "workflows" / "loose.yaml").write_text("x\n", encoding="utf-8")
    (hub_root / "workflows" / "linked").symlink_to(hub_root / "workflows" / "empty")

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.workflow_folders == ("workflows/empty",)


def test_lists_temp_entries_when_item_leftovers_rule_selected(hub_root: Path) -> None:
    # AGH-297: a crash mid-swap leaves a stage or old folder beside a skill, never followed.
    config = a_config()
    skills = hub_root / "plugin" / "demo" / "skills"
    (skills / "alpha").mkdir(parents=True)
    (skills / ".alpha.hub-tmp-0123abcd" / "references").mkdir(parents=True)
    (skills / ".hidden").mkdir()
    agents = hub_root / ".claude" / "agents"
    agents.mkdir(parents=True)
    (agents / ".reviewer.md.hub-tmp-89abcdef").write_bytes(b"x")
    (hub_root / "workflows" / "demo").mkdir(parents=True)
    (hub_root / "workflows" / "demo" / ".lint.yaml.hub-tmp-00000000").write_bytes(b"x")
    (hub_root / "plugin" / "demo" / "scripts").mkdir()
    (hub_root / "plugin" / "demo" / "scripts" / ".check.sh.hub-tmp-22222222").write_bytes(b"x")
    (hub_root / "plugin" / "other").mkdir()
    outside = hub_root.parent / "outside"
    (outside / ".beta.hub-tmp-11111111").mkdir(parents=True)
    (hub_root / ".claude" / "skills").symlink_to(outside)

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=every_rule(config),
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.item_leftovers == (
        ".claude/agents/.reviewer.md.hub-tmp-89abcdef",
        "plugin/demo/scripts/.check.sh.hub-tmp-22222222",
        "plugin/demo/skills/.alpha.hub-tmp-0123abcd",
        "workflows/demo/.lint.yaml.hub-tmp-00000000",
    )
    # The folders where an item folder can be made are watched too (``plugin/other``).
    assert snapshot.item_folders == (
        ".claude",
        ".claude/agents",
        "plugin",
        "plugin/demo",
        "plugin/demo/scripts",
        "plugin/demo/skills",
        "plugin/other",
        "workflows/demo",
    )


def test_watches_plugin_folder_when_absent(tmp_path: Path) -> None:
    # A ``plugin`` made later changes its watched time (absent: None), so the next run rescans.
    assert item_leftovers(str(tmp_path)) == ((), ("plugin",))


def test_reads_no_item_folders_when_rule_not_selected(hub_root: Path) -> None:
    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=a_config(),
        running=RUNNING,
        selection=NO_RULES,
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.item_leftovers is None
    assert snapshot.item_folders == ()


def test_lists_draft_leftover_when_draft_removal_interrupted(hub_root: Path) -> None:
    # AGH-298: ``remove_draft`` renames a draft aside before removing it; a failed removal
    # leaves that folder in ``.hub-drafts``, which the scan lists without reading it.
    drafts = hub_root / ".hub-drafts"
    (drafts / ".skill-abc123.hub-tmp-0123abcd").mkdir(parents=True)
    (drafts / "skill-def456").mkdir()

    leftovers, folders = item_leftovers(str(hub_root))

    assert leftovers == (".hub-drafts/.skill-abc123.hub-tmp-0123abcd",)
    assert ".hub-drafts" in folders
