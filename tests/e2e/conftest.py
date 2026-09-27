"""Shared e2e fixtures: e2e tests run real tools as subprocesses from the repo root."""

import subprocess
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TIMEOUT_SECONDS = 120


@pytest.fixture
def repo_root() -> Path:
    """The repository root, where the gate configs (pyproject.toml, mypy.ini) live."""
    return REPO_ROOT


@pytest.fixture
def run() -> Callable[..., subprocess.CompletedProcess[str]]:
    """Run a command from the repo root and capture its text output; never raises on rc != 0."""

    def _run(
        command: Sequence[str],
        *,
        env: Mapping[str, str] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    return _run
