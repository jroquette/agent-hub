"""The module files of a rendered hub, run as a hub user runs them (AGH-17, spec D5).

``TestMake``: the rendered ``Makefile`` with every module selected (the spec's ALL) runs
``make check`` and the module targets through the ``./hub`` shim; a fake ``uvx`` first on
``PATH`` logs each call, so no release is fetched.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

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
