"""The rendered hooks and scripts lint clean for Python 3.9 (AC-4.24, erratum E5).

Hooks and scripts run on the system ``python3`` (3.9 on macOS). The repo's ruff config targets
3.14 and never sees a ``.tmpl``, so the demo render is written to ``tmp_path`` and checked with
``--isolated`` (no config file applies) at ``--target-version py39``: ``E9`` and ``F`` catch
syntax and name errors, ``B`` likely bugs, ``UP`` typing forms a 3.9 hub should not carry.
Long lines (``E501``) are not a 3.9 hazard and are not selected.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.generator.render_hub import render_hub

PY39_RULES = "E9,F,B,UP"


def test_passes_py39_lint_when_rendered_tree_checked(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    rendered = render_hub(HubConfig.model_validate(a_hub_document()))
    python_files: list[Path] = []
    for file in rendered.files:
        target = tmp_path / "hub" / file.path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(file.content)
        if target.suffix == ".py":
            python_files.append(target)
    # Named one by one: a file given on the command line is checked even where a rendered
    # .gitignore or a default exclude would skip it.
    command = [sys.executable, "-m", "ruff", "check", "--isolated", "--no-cache"]
    options = ["--target-version", "py39", "--select", PY39_RULES, "--output-format", "concise"]

    result = run([*command, *options, *map(str, python_files)], cwd=tmp_path)

    assert python_files
    assert result.returncode == 0, result.stdout + result.stderr
