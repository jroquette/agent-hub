"""The doctor's snapshot builder on real folders (plan F.2): what each selected read fills.

``hub doctor``'s own tests (cli integration) pin the command's behaviour; these pin the builder the
command and the control plane share, with git and the developer's prefix injected.
"""

import json
import os
import shutil
import subprocess
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


REAL_GIT = shutil.which("git")


@pytest.fixture
def isolated_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """No user or system git config, excludes included, reaches a test's git."""
    for variable in [name for name in os.environ if name.startswith("GIT_")]:
        monkeypatch.delenv(variable)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / ".gitconfig"))
    (home / ".gitconfig").write_text("[maintenance]\n\tauto = false\n", encoding="utf-8")


@pytest.mark.usefixtures("isolated_git")
def test_reads_ignored_when_environments_env_file_in_repo(hub_root: Path) -> None:
    # AC-350.45: present, held by a declared repo and ignored there by its .gitignore, or not.
    assert REAL_GIT is not None, "git is needed for the env file cases"
    checkout = hub_root.parent / "demo-api"
    checkout.mkdir()
    subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [REAL_GIT, "init", "-q"], cwd=checkout, check=True, capture_output=True
    )
    (checkout / ".gitignore").write_text(".env.*\n", encoding="utf-8")
    (checkout / ".env.staging").write_text("DEMO_TOKEN=x\n", encoding="utf-8")
    (checkout / "config.env").write_text("DEMO_TOKEN=x\n", encoding="utf-8")
    document = a_hub_document()
    document["platform"]["version"] = RUNNING
    document["repos"].append(a_second_repo())
    document["environments"] = {
        "staging": {"access": "ask", "credentials": {"env_file": "demo-api/.env.staging"}},
        "qa": {"access": "read", "credentials": {"env_file": "demo-api/config.env"}},
        "dev": {"access": "write", "credentials": {"env_file": "demo-api/.env.dev"}},
        "box": {"access": "write", "credentials": {"env_file": "secrets/.env.box"}},
        "plain": {"access": "write"},
    }
    config = HubConfig.model_validate(document)
    selection = select_rules(REGISTRY, config=config, only=("environments.env_file",))
    assert isinstance(selection, Selection)

    snapshot = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=selection,
        local=LocalConfig(),
        branch_prefix=None,
    )

    assert snapshot.env_files is not None
    assert [
        (facts.path, facts.environment, facts.source, facts.exists, facts.holder, facts.ignored)
        for facts in snapshot.env_files
    ] == [
        ("demo-api/.env.staging", "staging", "hub.json", True, "demo-api", True),
        ("demo-api/config.env", "qa", "hub.json", True, "demo-api", False),
        ("demo-api/.env.dev", "dev", "hub.json", False, "demo-api", True),
        ("secrets/.env.box", "box", "hub.json", False, None, None),
    ]
    unselected = build_doctor_snapshot(
        str(hub_root),
        config=config,
        running=RUNNING,
        selection=NO_RULES,
        local=LocalConfig(),
        branch_prefix=None,
    )
    assert unselected.env_files is None
