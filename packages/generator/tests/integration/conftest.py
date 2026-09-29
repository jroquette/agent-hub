"""Rendered hubs on disk and the interpreters that run their hooks and scripts.

Every rendered ``.py`` runs on the system ``python3``, which is 3.9 on macOS (AC-4.24): each test
that runs one takes ``hook_python`` and so runs twice, on this interpreter and on a real 3.9.
Children get an environment built from scratch and ``-I``, so nothing of this process leaks in.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.generator.render_hub import render_hub

type HubRenderer = Callable[[HubConfig], Path]

# The interpreters of ``hook_python``: this one, and the hooks' floor.
CURRENT = "current"
PYTHON39 = "3.9"
# A child that has not answered by then is hung (a FIFO read, a lost timeout), not slow.
CHILD_TIMEOUT = 60.0


def runs_python39(executable: str) -> bool:
    completed = subprocess.run(  # noqa: S603 - an interpreter found on PATH, fixed script
        [executable, "-I", "-c", "import sys; print(sys.version_info[:2] == (3, 9))"],
        capture_output=True,
        text=True,
        check=False,
        env=child_env(),
    )
    return completed.stdout.strip() == "True"


def find_python39() -> str | None:
    """The first of ``python3.9`` and ``python3`` on ``PATH`` that is Python 3.9."""
    for name in ("python3.9", "python3"):
        executable = shutil.which(name)
        if executable is not None and runs_python39(executable):
            return executable
    return None


def require_python39() -> str:
    """A Python 3.9 interpreter; skips the test without one, fails it under CI (which has one)."""
    executable = find_python39()
    if executable is None:
        message = "no Python 3.9 interpreter on PATH"
        if os.environ.get("CI"):
            pytest.fail(f"{message}, and CI must install one (.github/workflows/ci.yml)")
        pytest.skip(message)
    return executable


@pytest.fixture(params=[CURRENT, PYTHON39])
def hook_python(request: pytest.FixtureRequest) -> str:
    """The interpreter a rendered hook or script runs on: this one, then a real 3.9."""
    if request.param == CURRENT:
        return sys.executable
    return require_python39()


@pytest.fixture
def python39() -> str:
    """A real Python 3.9 (skips without one, fails under CI)."""
    return require_python39()


@pytest.fixture
def rendered_hub(tmp_path: Path, rendered_tree: Callable[..., Path]) -> HubRenderer:
    """Write ``render_hub(config)``, links included, to ``tmp_path/ws/<hub repo name>``.

    Returns that hub folder; the workspace ``ws`` beside it holds the hub the way a real one does.
    """

    def render(config: HubConfig) -> Path:
        name = config.project.hub_repo.rsplit("/", 1)[-1]
        return rendered_tree(render_hub(config), root=tmp_path / "ws" / name)

    return render


def child_env(extra: Mapping[str, str] | None = None) -> dict[str, str]:
    """A child's environment from scratch: ``PATH`` only, plus ``extra``."""
    return {"PATH": os.environ.get("PATH", os.defpath)} | dict(extra or {})


def run_child(
    python: str,
    code: str,
    *,
    path: Path,
    args: Sequence[str] = (),
    cwd: Path | None = None,
    env: Mapping[str, str] | None = None,
    timeout: float = CHILD_TIMEOUT,
) -> Any:
    """Run ``code`` on ``python`` with ``path`` first on ``sys.path``; return its stdout as JSON.

    ``-I`` keeps the environment, the user site and the working directory out of ``sys.path``;
    ``env`` is added to a from-scratch environment (``child_env``). A non-zero exit fails the test
    with the child's stderr.
    """
    prelude = f"import sys\nsys.path.insert(0, {str(path)!r})\n"
    completed = subprocess.run(  # noqa: S603 - an interpreter from hook_python, fixed script
        [python, "-I", "-c", prelude + code, *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=child_env(env),
        timeout=timeout,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.fixture
def run_python() -> Callable[..., Any]:
    """``run_child``: run a snippet on an interpreter with a rendered folder on ``sys.path``."""
    return run_child
