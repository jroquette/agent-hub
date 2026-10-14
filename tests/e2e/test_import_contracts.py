"""The `.importlinter` contracts enforce the dependency rule (ADR 0001, ADR 0008): cli is the
composition root, nothing imports it, api sits below it and imports no cli, cli reaches api only
from its web command, and the adapters stay independent of each other.

The tests run the real lint-imports with the repo's contracts, renamed onto a scratch root
package in tmp_path, so a scratch import never touches the real packages."""

import os
import re
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

import pytest

ROOT = "agent_hub"
SCRATCH_ROOT = "scratch_hub"
PACKAGES = (
    "core",
    "storage",
    "collector",
    "generator",
    "tracker_linear",
    "hub_git",
    "claude_sessions",
    "cli",
    "api",
)
COMPOSITION_ROOT = "cli is the composition root"
API_THROUGH_WEB = "cli reaches api only through web_command"
CORE_INDEPENDENT = "core imports nothing internal"
SDK_CONFINED = "only claude_sessions imports the Claude Agent SDK"
CLI_NO_CLAUDE_SESSIONS = "cli never imports claude_sessions"
# A third-party module, so the scratch source imports it as is (not under the scratch root).
SDK = "claude_agent_sdk"
LINT_IMPORTS = str(Path(sys.executable).parent / "lint-imports")


def _write_scratch_root(tmp_path: Path, *, importer: str, imported: str) -> None:
    """The scratch root package: every package empty but one module, which imports another.

    ``importer`` is a package (``cli``) or one of its modules (``cli.web_command``).
    """
    root = tmp_path / SCRATCH_ROOT
    root.mkdir()
    (root / "__init__.py").write_text("")
    for name in PACKAGES:
        (root / name).mkdir()
        (root / name / "__init__.py").write_text("")
    package, _, module = importer.partition(".")
    source = root / package / (f"{module}.py" if module else "__init__.py")
    target = imported if imported == SDK else f"{SCRATCH_ROOT}.{imported}"
    source.write_text(f"import {target}\n")


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
        ("tracker_linear", "cli"),
        ("tracker_linear", "storage"),
        ("tracker_linear", "collector"),
        ("tracker_linear", "generator"),
        ("storage", "tracker_linear"),
        ("collector", "tracker_linear"),
        ("generator", "tracker_linear"),
        ("api", "cli"),
        ("storage", "api"),
        ("collector", "api"),
        ("generator", "api"),
        ("tracker_linear", "api"),
        ("hub_git", "cli"),
        ("hub_git", "storage"),
        ("hub_git", "api"),
        ("storage", "hub_git"),
        ("claude_sessions", "cli"),
        ("claude_sessions", "api"),
        ("claude_sessions", "storage"),
        ("storage", "claude_sessions"),
        ("hub_git", "claude_sessions"),
    ],
)
def test_breaks_composition_root_contract_when_adapter_imports_upward_or_sideways(
    lint_imports: Callable[[str, str], CompletedProcess[str]], importer: str, imported: str
) -> None:
    result = lint_imports(importer, imported)

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{COMPOSITION_ROOT} BROKEN" in result.stdout, result.stdout
    assert f"{SCRATCH_ROOT}.{importer} -> {SCRATCH_ROOT}.{imported}" in result.stdout


@pytest.mark.parametrize(
    "imported", ["generator", "tracker_linear", "hub_git", "claude_sessions", "api"]
)
def test_breaks_core_contract_when_core_imports_adapter(
    lint_imports: Callable[[str, str], CompletedProcess[str]], imported: str
) -> None:
    result = lint_imports("core", imported)

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{CORE_INDEPENDENT} BROKEN" in result.stdout, result.stdout
    assert f"{SCRATCH_ROOT}.core -> {SCRATCH_ROOT}.{imported}" in result.stdout


@pytest.mark.parametrize("imported", ["storage", "collector", "generator", "tracker_linear"])
def test_keeps_every_contract_when_cli_wires_adapter(
    lint_imports: Callable[[str, str], CompletedProcess[str]], imported: str
) -> None:
    result = lint_imports("cli", imported)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{COMPOSITION_ROOT} KEPT" in result.stdout, result.stdout


@pytest.mark.parametrize("importer", ["cli", "cli.run_command"])
def test_breaks_web_command_contract_when_other_cli_module_imports_api(
    lint_imports: Callable[[str, str], CompletedProcess[str]], importer: str
) -> None:
    result = lint_imports(importer, "api")

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{API_THROUGH_WEB} BROKEN" in result.stdout, result.stdout


def test_keeps_every_contract_when_web_command_imports_api(
    lint_imports: Callable[[str, str], CompletedProcess[str]],
) -> None:
    result = lint_imports("cli.web_command", "api")

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{API_THROUGH_WEB} KEPT" in result.stdout, result.stdout
    assert f"{COMPOSITION_ROOT} KEPT" in result.stdout, result.stdout


@pytest.mark.parametrize(
    "imported",
    ["storage", "collector", "generator", "hub_git", "tracker_linear", "claude_sessions"],
)
def test_keeps_every_contract_when_api_wires_adapter(
    lint_imports: Callable[[str, str], CompletedProcess[str]], imported: str
) -> None:
    result = lint_imports("api", imported)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("importer", ["api", "core", "cli"])
def test_breaks_sdk_contract_when_api_imports_sdk(
    lint_imports: Callable[[str, str], CompletedProcess[str]], importer: str
) -> None:
    result = lint_imports(importer, SDK)

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{SDK_CONFINED} BROKEN" in result.stdout, result.stdout


def test_keeps_sdk_contract_when_claude_sessions_imports_sdk(
    lint_imports: Callable[[str, str], CompletedProcess[str]],
) -> None:
    result = lint_imports("claude_sessions", SDK)

    assert result.returncode == 0, result.stdout + result.stderr
    assert f"{SDK_CONFINED} KEPT" in result.stdout, result.stdout


@pytest.mark.parametrize("importer", ["cli", "cli.web_command"])
def test_breaks_cli_contract_when_cli_imports_claude_sessions(
    lint_imports: Callable[[str, str], CompletedProcess[str]], importer: str
) -> None:
    result = lint_imports(importer, "claude_sessions")

    assert result.returncode != 0, result.stdout + result.stderr
    assert f"{CLI_NO_CLAUDE_SESSIONS} BROKEN" in result.stdout, result.stdout


# AC-165.41 (E16): the platform never reads a claude.ai token or calls claude.ai or the Anthropic
# API itself; only the user's own ``claude`` children do. The one claude.ai address in platform
# code is the cloud link prefix the owner opens (``https://claude.ai/code/``), and the synthetic
# links of the test builders under it.

CLAUDE_CODE_PREFIX = "https://claude.ai/code/"
FORBIDDEN_HOSTS = ("claude.ai", "api.anthropic.com")
CREDENTIALS_FILE = ".credentials.json"
_URL = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*://(?P<host>[A-Za-z0-9.\-]+)[^\s\"'`)<>]*")
_SCANNED_SUFFIXES = frozenset({".py", ".tmpl", ".md", ".json", ".toml", ".sh", ".txt"})


def _forbidden_uses(src_root: Path) -> list[str]:
    """Each place under ``src_root`` that names a claude.ai or Anthropic API host (but the cloud
    link prefix) or Claude Code's credentials file; the built web app is the web smoke's."""
    found: list[str] = []
    for path in sorted(src_root.rglob("*")):
        if path.suffix not in _SCANNED_SUFFIXES or "web_dist" in path.parts:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in _URL.finditer(text):
            host = match["host"].lower().rstrip(".")
            named = any(host == name or host.endswith(f".{name}") for name in FORBIDDEN_HOSTS)
            if named and not match[0].startswith(CLAUDE_CODE_PREFIX):
                found.append(f"{path}: {match[0]}")
        if CREDENTIALS_FILE in text:
            found.append(f"{path}: {CREDENTIALS_FILE}")
    return found


def test_makes_no_claude_ai_calls_when_platform_sources_scanned(repo_root: Path) -> None:
    sources = [repo_root / "packages" / name / "src" for name in PACKAGES]

    found = [use for source in sources for use in _forbidden_uses(source)]

    assert found == []


def test_flags_api_host_and_credentials_when_source_names_them(tmp_path: Path) -> None:
    (tmp_path / "client.py").write_text(
        'URL = "https://api.anthropic.com/v1/messages"\n'
        'LINK = "https://claude.ai/code/session_1"\n'
        'TOKEN = "~/.claude/.credentials.json"\n'
        'ORG = "https://claude.ai/api/organizations"\n',
        encoding="utf-8",
    )

    found = _forbidden_uses(tmp_path)

    assert [use.split(": ", 1)[1] for use in found] == [
        "https://api.anthropic.com/v1/messages",
        "https://claude.ai/api/organizations",
        CREDENTIALS_FILE,
    ]
