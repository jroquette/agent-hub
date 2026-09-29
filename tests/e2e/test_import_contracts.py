"""The `.importlinter` contracts enforce the dependency rule (ADR 0001, ADR 0008): cli is the
composition root, nothing imports it, and the adapters stay independent of each other.

The tests run the real lint-imports with the repo's contracts, renamed onto a scratch root
package in tmp_path, so a scratch import never touches the real packages."""

import os
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import pytest

ROOT = "agent_hub"
SCRATCH_ROOT = "scratch_hub"
PACKAGES = ("core", "storage", "collector", "generator", "cli")
COMPOSITION_ROOT = "cli is the composition root"
CORE_INDEPENDENT = "core imports nothing internal"
LINT_IMPORTS = str(Path(sys.executable).parent / "lint-imports")


def _write_scratch_root(tmp_path: Path, *, importer: str, imported: str) -> None:
    """The scratch root package: every package empty but one, which imports another."""
    root = tmp_path / SCRATCH_ROOT
    root.mkdir()
    (root / "__init__.py").write_text("")
    for name in PACKAGES:
        (root / name).mkdir()
        (root / name / "__init__.py").write_text("")
    (root / importer / "__init__.py").write_text(f"import {SCRATCH_ROOT}.{imported}\n")


@pytest.fixture
def lint_imports(
    tmp_path: Path, repo_root: Path, run: Callable[..., CompletedProcess[str]]
) -> Callable[[str, str], CompletedProcess[str]]:
    """Run lint-imports, with the repo's contracts renamed onto a scratch root, for one import."""

    def _lint(importer: str, imported: str) -> CompletedProcess[str]:
        _write_scratch_root(tmp_path, importer=importer, imported=imported)
        config = tmp_path / ".importlinter"
        contracts = (repo_root / ".importlinter").read_text()
        config.write_text(contracts.replace(ROOT, SCRATCH_ROOT))
        command = [LINT_IMPORTS, "--config", str(config), "--no-cache", "--no-logo"]
        return run(command, env={**os.environ, "PYTHONPATH": str(tmp_path)})

    return _lint


@pytest.mark.parametrize(
    ("importer", "imported"),
    [
        ("storage", "cli"),
        ("collector", "cli"),
        ("storage", "collector"),
        ("collector", "storage"),
        ("generator", "cli"),
        ("generator", "storage"),
        ("generator", "collector"),
        ("storage", "generator"),
        ("collector", "generator"),
    ],
)
def test_breaks_composition_root_contract_when_adapter_imports_upward_or_sideways(
    lint_imports: Callable[[str, str], CompletedProcess[str]], importer: str, imported: str
) -> None:
    result = lint_imports(importer, imported)

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{COMPOSITION_ROOT} BROKEN" in result.stdout, result.stdout
    assert f"{SCRATCH_ROOT}.{importer} -> {SCRATCH_ROOT}.{imported}" in result.stdout


def test_breaks_core_contract_when_core_imports_generator(
    lint_imports: Callable[[str, str], CompletedProcess[str]],
) -> None:
    result = lint_imports("core", "generator")

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{CORE_INDEPENDENT} BROKEN" in result.stdout, result.stdout
    assert f"{SCRATCH_ROOT}.core -> {SCRATCH_ROOT}.generator" in result.stdout


@pytest.mark.parametrize("imported", ["storage", "collector", "generator"])
def test_keeps_every_contract_when_cli_wires_adapter(
    lint_imports: Callable[[str, str], CompletedProcess[str]], imported: str
) -> None:
    result = lint_imports("cli", imported)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{COMPOSITION_ROOT} KEPT" in result.stdout, result.stdout
