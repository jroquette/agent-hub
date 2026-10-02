"""The module files of a rendered hub, run as a hub user runs them (AGH-17, spec D5).

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
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
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
            (("bench",), "bench"),
            (("bench-validate",), "bench --validate"),
        ],
        ids=["bench-args", "bench", "bench-validate"],
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
        self,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
        fake_uv_bin: Path,
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
        self,
        all_modules_config: HubConfig,
        rendered_hub: Callable[[HubConfig], Path],
        fake_uv_bin: Path,
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

    def test_parses_with_bash_n_when_rendered(
        self, all_modules_config: HubConfig, rendered_hub: Callable[[HubConfig], Path]
    ) -> None:
        root = rendered_hub(all_modules_config)

        completed = run_bash(root, "-n", CONTRACT_SYNC)

        assert completed.returncode == 0, completed.stderr


def rendered_text(config: HubConfig, path: str) -> str:
    rendered = {file.path: file for file in render_hub(config).files}
    return rendered[path].content.decode("utf-8")


def run_bash(root: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    bash = shutil.which("bash")
    assert bash is not None, "the module scripts run on bash: install it"
    env = {"PATH": os.environ.get("PATH", os.defpath), "HOME": str(root.parent / "home")}
    return subprocess.run(  # noqa: S603 - absolute bash, a rendered script, no shell
        [bash, *arguments],
        capture_output=True,
        text=True,
        check=False,
        timeout=TIMEOUT,
        cwd=root,
        env=env,
    )
