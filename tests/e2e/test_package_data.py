import os
import shutil
import zipfile
from collections.abc import Callable
from pathlib import Path
from subprocess import CompletedProcess

SHIPPED_SCHEMA = "agent_hub/core/hub_config/hub.schema.json"


def test_ships_hub_schema_when_core_wheel_built(
    tmp_path: Path, run: Callable[..., CompletedProcess[str]]
) -> None:
    uv = os.environ.get("UV") or shutil.which("uv")
    assert uv is not None, "uv must be on PATH (run the tests with uv run)"
    command = [uv, "build", "--package", "agent-hub-core", "--wheel", "--out-dir", str(tmp_path)]

    result = run(command)

    assert result.returncode == 0, result.stderr
    [wheel] = tmp_path.glob("agent_hub_core-*.whl")
    with zipfile.ZipFile(wheel) as archive:
        assert SHIPPED_SCHEMA in archive.namelist()
