import os
import shutil
import tomllib
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

INSTALL_TIMEOUT_SECONDS = 300


def test_prints_version_when_installed_as_uv_tool(
    tmp_path: Path, repo_root: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv is not None, "uv must be on PATH (run the tests with uv run)"
    bin_dir = tmp_path / "bin"
    # Isolated tool dirs, so the test never touches the user's installed tools.
    env = {**os.environ, "UV_TOOL_DIR": str(tmp_path / "tools"), "UV_TOOL_BIN_DIR": str(bin_dir)}
    env.pop("VIRTUAL_ENV", None)
    meta_package = repo_root / "packages" / "agent-hub"
    cli_project = tomllib.loads((repo_root / "packages/cli/pyproject.toml").read_text())

    # Pin the install to uv.lock, so the test (and CI) runs the locked dependency set.
    constraints = tmp_path / "constraints.txt"
    export = run(
        [
            uv,
            "export",
            "--locked",
            "--package",
            "agent-hub",
            "--no-emit-workspace",
            "--no-hashes",
            "-o",
            str(constraints),
        ],
        env=env,
    )
    assert export.returncode == 0, export.stderr

    install = run(
        [uv, "tool", "install", "--python", "3.14", "-c", str(constraints), str(meta_package)],
        env=env,
        timeout=INSTALL_TIMEOUT_SECONDS,
    )
    assert install.returncode == 0, install.stderr
    result = run([str(bin_dir / "hub"), "--version"], env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == cli_project["project"]["version"]
