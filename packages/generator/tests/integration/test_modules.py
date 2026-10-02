"""The module files of a rendered hub, run as a hub user runs them (AGH-17, spec D5).

``TestSelection``: each module renders exactly its files; a hub written with ``cloud`` and
``bench`` holds them and their lock entries, and a sync plan of it has nothing pending (the
generator and core steps ``hub init`` and ``hub sync`` run; the CLI is not imported here).
``TestMake``: the rendered ``Makefile`` with every module selected (the spec's ALL) runs
``make check`` and the module targets through the ``./hub`` shim; a fake ``uvx`` first on
``PATH`` logs each call, so no release is fetched. ``TestContractSync``: ``make contract-sync``
in a workspace whose fake repos log their make calls (AC-17.8).
"""

import json
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.extension_inputs import NO_EXTENSIONS
from agent_hub.core.hub_files.hub_lock import (
    HUB_LOCK_PATH,
    ManagedFileEntry,
    SeededEntry,
    build_hub_lock,
    lock_bytes,
)
from agent_hub.core.hub_files.plan_sync import SyncPlan, plan_sync
from agent_hub.core.hub_files.rendered_file import Ownership, RenderedFile
from agent_hub.core.testing.builders import a_hub_document, a_second_repo
from agent_hub.generator.hub_tree import read_planned_tree
from agent_hub.generator.render_hub import render_hub

TIMEOUT = 60
# The pin a synthetic hub.json holds; the shim reads it when a recipe runs.
RUN_VERSION = "4.5.6"
# Make variables an outer make exports; they would leak into the make under test.
MAKE_ENV_LEAKS = ("MAKEFLAGS", "MFLAGS", "MAKELEVEL", "GNUMAKEFLAGS", "MAKEFILES")


def a_hub_with_pin(root: Path) -> Path:
    document = a_hub_document()
    document["platform"]["version"] = RUN_VERSION
    (root / "hub.json").write_text(json.dumps(document), encoding="utf-8")
    return root


def run_make(root: Path, fake_uv_bin: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    make = shutil.which("make")
    assert make is not None, "the module targets run GNU make: install it"
    env = {name: value for name, value in os.environ.items() if name not in MAKE_ENV_LEAKS}
    env["PATH"] = f"{fake_uv_bin}{os.pathsep}{env.get('PATH', os.defpath)}"
    return subprocess.run(  # noqa: S603 - absolute make, fixed arguments, no shell
        [make, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
        cwd=root,
        env=env,
    )


def logged_calls(fake_uv_bin: Path) -> list[str]:
    log = fake_uv_bin / "uvx.log"
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


# AC-17.5, AC-17.6 (D5): the files each module renders, exactly.
MODULE_FILES = {
    "bench": {"mk/bench.mk"},
    "cloud": {"mk/cloud.mk", "scripts/cloud-setup.sh"},
    "contract-sync": {"mk/contract-sync.mk", "scripts/contract-sync.sh"},
    "marketplace": {
        "mk/marketplace.mk",
        ".claude-plugin/marketplace.json",
        ".claude-plugin/marketplace.project.json",
    },
}
MODULE_FILES_ALL = set().union(*MODULE_FILES.values())
SEEDED_MODULE_FILES = {".claude-plugin/marketplace.project.json"}
EXECUTABLE_MODULE_FILES = {"scripts/cloud-setup.sh", "scripts/contract-sync.sh"}


def a_config_selecting(*modules: str) -> HubConfig:
    """The demo with a second repo and ``modules`` selected (``contract-sync`` api → web)."""
    document = a_hub_document()
    document["repos"].append(a_second_repo())
    source, target = (repo["dir"] for repo in document["repos"])
    settings = {"contract-sync": {"source": source, "target": target}}
    document["modules"] = {module: settings.get(module, {}) for module in modules}
    return HubConfig.model_validate(document)


def planned_sync(root: Path, config: HubConfig) -> SyncPlan:
    """The plan ``hub sync`` makes for the hub at ``root`` (no project extension inputs)."""
    lock_content = (root / HUB_LOCK_PATH).read_bytes()
    rendered = render_hub(config)
    lock = build_hub_lock(rendered=rendered, config=config)
    paths = sorted({file.path for file in rendered.files} | {link.path for link in rendered.links})
    wanted = {file.path for file in rendered.files if file.ownership is Ownership.MANAGED}
    tree = read_planned_tree(root, paths=paths, wanted=wanted)
    plan = plan_sync(
        rendered=rendered,
        config=config,
        lock=lock,
        lock_content=lock_content,
        tree=tree,
        extensions=NO_EXTENSIONS,
    )
    assert isinstance(plan, SyncPlan), plan
    return plan


class TestSelection:
    def test_writes_module_files_and_lock_when_cloud_and_bench_synced(
        self, rendered_hub: Callable[[HubConfig], Path]
    ) -> None:
        config = a_config_selecting("cloud", "bench")
        # What ``hub init`` writes: the render, then the lock built from it.
        root = rendered_hub(config)
        (root / HUB_LOCK_PATH).write_bytes(
            lock_bytes(build_hub_lock(rendered=render_hub(config), config=config))
        )

        plan = planned_sync(root, config)

        # Up to date: nothing to write, delete or remove, and the lock bytes unchanged.
        assert (plan.pending, plan.lock_written, plan.changes) == (False, False, ())
        expected = MODULE_FILES["bench"] | MODULE_FILES["cloud"]
        on_disk = {path for path in MODULE_FILES_ALL if (root / path).exists()}
        assert on_disk == expected
        assert os.access(root / "scripts/cloud-setup.sh", os.X_OK)
        assert not os.access(root / "mk/cloud.mk", os.X_OK)
        lock = plan.lock
        assert lock.modules == ("bench", "cloud")
        for path in expected:
            entry = lock.files[path]
            assert isinstance(entry, ManagedFileEntry), path
            assert entry.executable is (path in EXECUTABLE_MODULE_FILES), path
        assert not [path for path in lock.files if path in MODULE_FILES_ALL - expected]

    @pytest.mark.parametrize("module", sorted(MODULE_FILES))
    def test_renders_only_its_files_when_module_selected_alone(self, module: str) -> None:
        base = {file.path for file in render_hub(a_config_selecting()).files}

        rendered = render_hub(a_config_selecting(module))

        paths = {file.path for file in rendered.files}
        assert paths - base == MODULE_FILES[module]
        assert base <= paths
        assert not paths & (MODULE_FILES_ALL - MODULE_FILES[module])
        for file in rendered.files:
            if file.path in MODULE_FILES[module]:
                assert file.module == module, file.path
                assert file.executable is (file.path in EXECUTABLE_MODULE_FILES), file.path
                seeded = file.path in SEEDED_MODULE_FILES
                assert file.ownership is (Ownership.SEEDED if seeded else Ownership.MANAGED)
            else:
                assert file.module is None, file.path
        lock = build_hub_lock(rendered=rendered, config=a_config_selecting(module))
        assert lock.modules == (module,)
        for path in MODULE_FILES[module]:
            kind = SeededEntry if path in SEEDED_MODULE_FILES else ManagedFileEntry
            assert isinstance(lock.files[path], kind), path


class TestMake:
    def test_passes_check_when_all_modules_rendered(
        self,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
        fake_uv_bin: Path,
    ) -> None:
        root = a_hub_with_pin(rendered_hub(all_modules_config))

        completed = run_make(root, fake_uv_bin, "check")

        assert completed.returncode == 0, completed.stderr
        assert logged_calls(fake_uv_bin)[-1].endswith(" hub doctor")

    @pytest.mark.parametrize(
        ("arguments", "hub_call"),
        [
            (("bench", "ARGS=--runs 1"), "bench --runs 1"),
            # Taken raw: make never expands a `$` of the value; the shell still splits words.
            (("bench", "ARGS=--label $HOME x"), "bench --label $HOME x"),
            (("bench",), "bench"),
            (("bench-validate",), "bench --validate"),
        ],
        ids=["bench-args", "bench-args-dollar", "bench", "bench-validate"],
    )
    def test_runs_hub_bench_when_bench_target_dry_run(
        self,
        arguments: tuple[str, ...],
        hub_call: str,
        *,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
        fake_uv_bin: Path,
    ) -> None:
        root = a_hub_with_pin(rendered_hub(all_modules_config))

        completed = run_make(root, fake_uv_bin, "-n", *arguments)

        assert completed.returncode == 0, completed.stderr
        shim = os.path.realpath(root / "hub")
        assert [line.rstrip() for line in completed.stdout.splitlines()] == [f"'{shim}' {hub_call}"]
        # A dry run calls nothing.
        assert logged_calls(fake_uv_bin) == []


# ALL's contract-sync repos (``all_modules_config``), beside the hub in the workspace.
SOURCE = "demo-api"
TARGET = "demo-web"
CONTRACT_SYNC = "scripts/contract-sync.sh"
# Words of a contract format; the template names none (spec D1).
FORMAT_WORDS = ("openapi", "swagger", "graphql", "protobuf", "jsonschema")


def a_fake_repo(workspace: Path, name: str, log: Path, *, failing: str | None = None) -> None:
    """``<workspace>/<name>`` whose ``Makefile`` logs ``<target> <name>``; ``failing`` exits 3."""
    repo = workspace / name
    repo.mkdir()
    recipes = []
    for target in ("contract-export", "contract-import"):
        status = "3" if target == failing else "0"
        recipes.append(
            f"{target}:\n\tprintf '%s\\n' '{target} {name}' >> '{log}'\n\texit {status}\n"
        )
    (repo / "Makefile").write_text("".join(recipes), encoding="utf-8")


def a_contract_workspace(
    rendered_hub: Callable[[HubConfig], Path],
    config: HubConfig,
    *,
    repos: tuple[str, ...] = (SOURCE, TARGET),
    failing: str | None = None,
) -> tuple[Path, Path]:
    """The rendered ALL hub in ``ws`` with fake ``repos`` beside it; returns the hub and the log."""
    root = a_hub_with_pin(rendered_hub(config))
    log = root.parent / "make-calls.log"
    for name in repos:
        a_fake_repo(root.parent, name, log, failing=failing)
    return root, log


def make_calls(log: Path) -> list[str]:
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


class TestContractSync:
    def test_names_source_and_target_when_rendered(self, all_modules_config: HubConfig) -> None:
        script = rendered_text(all_modules_config, CONTRACT_SYNC)

        assert f"source_dir='{SOURCE}'" in script.splitlines()
        assert f"target_dir='{TARGET}'" in script.splitlines()

    def test_runs_export_then_import_when_repos_present(
        self,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
        fake_uv_bin: Path,
    ) -> None:
        root, log = a_contract_workspace(rendered_hub, all_modules_config)

        completed = run_make(root, fake_uv_bin, "contract-sync")

        assert completed.returncode == 0, completed.stderr
        assert make_calls(log) == [f"contract-export {SOURCE}", f"contract-import {TARGET}"]

    def test_skips_import_when_export_fails(
        self, all_modules_config: HubConfig, rendered_hub: Callable[[HubConfig], Path]
    ) -> None:
        root, log = a_contract_workspace(
            rendered_hub, all_modules_config, failing="contract-export"
        )

        completed = run_bash(root, CONTRACT_SYNC)

        assert completed.returncode == 1
        assert make_calls(log) == [f"contract-export {SOURCE}"]
        assert (
            f"contract-sync: make contract-export failed in ../{SOURCE} (source); "
            f"make contract-import in ../{TARGET} did not run"
        ) in completed.stderr.splitlines()

    def test_names_target_when_import_fails(
        self, all_modules_config: HubConfig, rendered_hub: Callable[[HubConfig], Path]
    ) -> None:
        root, log = a_contract_workspace(
            rendered_hub, all_modules_config, failing="contract-import"
        )

        completed = run_bash(root, CONTRACT_SYNC)

        assert completed.returncode == 1
        assert make_calls(log) == [f"contract-export {SOURCE}", f"contract-import {TARGET}"]
        assert (
            f"contract-sync: make contract-import failed in ../{TARGET} (target)"
        ) in completed.stderr.splitlines()

    def test_keeps_hub_make_flags_out_of_repos_when_run_from_make(
        self, all_modules_config: HubConfig, rendered_hub: Callable[[HubConfig], Path]
    ) -> None:
        root, log = a_contract_workspace(rendered_hub, all_modules_config)
        # The source repo logs what its make inherited: flags, level and a variable set on them.
        (root.parent / SOURCE / "Makefile").write_text(
            "contract-export:\n"
            f"\tprintf '%s|%s|%s\\n' \"$$MAKEFLAGS\" \"$$MAKELEVEL\" '$(LEAK)' >> '{log}'\n",
            encoding="utf-8",
        )
        # What an outer `make contract-sync -k LEAK=1` exports to its recipe's shell.
        outer = {
            "MAKEFLAGS": "k -- LEAK=1",
            "MFLAGS": "-k",
            "GNUMAKEFLAGS": "LEAK=1",
            "MAKELEVEL": "1",
        }

        completed = run_bash(root, CONTRACT_SYNC, extra_env=outer)

        assert completed.returncode == 0, completed.stderr
        [inherited, import_call] = make_calls(log)
        flags, level, leak = inherited.split("|")
        # A top-level make (its recipes see level 1): no -k, no variable of the hub's make.
        assert (level, leak) == ("1", "")
        assert "k" not in flags.split(" -- ", 1)[0]
        assert "LEAK" not in flags
        assert import_call == f"contract-import {TARGET}"

    def test_runs_steps_when_workspace_path_has_space_and_cwd_elsewhere(
        self,
        tmp_path: Path,
        all_modules_config: HubConfig,
        rendered_tree: Callable[..., Path],
    ) -> None:
        workspace = tmp_path / "my work space"
        root = a_hub_with_pin(
            rendered_tree(render_hub(all_modules_config), root=workspace / "demo-hub")
        )
        log = tmp_path / "make-calls.log"
        for name in (SOURCE, TARGET):
            a_fake_repo(workspace, name, log)

        completed = run_bash(root, str(root / CONTRACT_SYNC), cwd=tmp_path)

        assert completed.returncode == 0, completed.stderr
        assert make_calls(log) == [f"contract-export {SOURCE}", f"contract-import {TARGET}"]

    @pytest.mark.parametrize("missing", [SOURCE, TARGET])
    def test_names_repo_when_dir_missing(
        self,
        missing: str,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
    ) -> None:
        present = tuple(name for name in (SOURCE, TARGET) if name != missing)
        root, log = a_contract_workspace(rendered_hub, all_modules_config, repos=present)

        completed = run_bash(root, CONTRACT_SYNC)

        assert completed.returncode == 1
        assert completed.stderr.splitlines() == [
            f"contract-sync: ../{missing} is missing; clone it beside the hub (hub.json repos)"
        ]
        # Both dirs are checked before any step runs.
        assert make_calls(log) == []

    def test_holds_no_contract_format_when_rendered(self, all_modules_config: HubConfig) -> None:
        script = rendered_text(all_modules_config, CONTRACT_SYNC)

        assert not any(word in script.lower() for word in FORMAT_WORDS)
        # No file but hub.json is named; the only repo paths are ``../<dir>`` of the two repos.
        assert set(re.findall(r"[\w.-]+\.(?:json|ya?ml|proto)\b", script)) <= {"hub.json"}
        assert set(re.findall(r"\.\./\$?\w+", script)) == {
            "../$repo_dir",
            "../$source_dir",
            "../$target_dir",
        }


def test_parses_with_bash_n_when_scripts_rendered(
    all_modules_config: HubConfig,
    rendered_hub: Callable[[HubConfig], Path],
    shell_scripts: Callable[[Iterable[RenderedFile]], list[str]],
) -> None:
    """AC-17.13: every rendered shell script parses (``bash -n``) with every module selected."""
    scripts = sorted(shell_scripts(render_hub(all_modules_config).files))
    assert {CONTRACT_SYNC, "scripts/cloud-setup.sh", "hub", "agent"} <= set(scripts)
    root = rendered_hub(all_modules_config)

    failed = {}
    for script in scripts:
        completed = run_bash(root, "-n", script)
        if completed.returncode != 0:
            failed[script] = completed.stderr

    assert failed == {}


def rendered_text(config: HubConfig, path: str) -> str:
    rendered = {file.path: file for file in render_hub(config).files}
    return rendered[path].content.decode("utf-8")


def run_bash(
    root: Path,
    *arguments: str,
    cwd: Path | None = None,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run ``bash *arguments`` in ``cwd`` (default ``root``); env: PATH, HOME and ``extra_env``."""
    bash = shutil.which("bash")
    assert bash is not None, "the module scripts run on bash: install it"
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(root.parent / "home")}
    env |= extra_env or {}
    return subprocess.run(  # noqa: S603 - absolute bash, a rendered script, no shell
        [bash, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
        cwd=root if cwd is None else cwd,
        env=env,
    )
