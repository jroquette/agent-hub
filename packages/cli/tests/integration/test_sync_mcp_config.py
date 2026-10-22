"""``hub sync``'s managed ``.mcp.json``: the ``hub`` stdio server that runs ``./hub mcp`` (AGH-392,
spec D-mcp-json).

Every case runs in process on a copy of the ``DEMO`` hub (``demo_hub``), with ``demo-api``
checked out beside it where a case needs it.
"""

import hashlib
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from typer.testing import Result

pytestmark = pytest.mark.disable_socket

# The conftest's in-process runs and checkout factory (tests cannot import a conftest in
# importlib mode).
type SyncRunner = Callable[..., Result]
type DoctorRunner = Callable[..., Result]
type CheckoutFactory = Callable[[str], Path]

MCP_CONFIG = ".mcp.json"
# D-mcp-json in the JSON byte form every built file has: sorted keys, 2-space indent, newline.
MCP_BYTES = (
    b"{\n"
    b'  "mcpServers": {\n'
    b'    "hub": {\n'
    b'      "args": [\n'
    b'        "mcp"\n'
    b"      ],\n"
    b'      "command": "${CLAUDE_PROJECT_DIR:-.}/hub",\n'
    b'      "type": "stdio"\n'
    b"    }\n"
    b"  }\n"
    b"}\n"
)
DOCTOR_RULES = (
    "settings.valid",
    "permissions.bypass",
    "mcp.pinned",
    "secrets.config",
    "lock.drift",
)
CLEAN = "0 errors, 0 warnings, 0 infos"


def lock_files(hub: Path) -> dict[str, dict[str, object]]:
    files: dict[str, dict[str, object]] = json.loads((hub / "hub.lock").read_bytes())["files"]
    return files


def test_writes_mcp_config_at_hub_root_when_synced(
    tmp_path: Path, demo_hub: Path, *, demo_checkout: CheckoutFactory, run_sync: SyncRunner
) -> None:
    repo = demo_checkout("demo-api")
    (demo_hub / MCP_CONFIG).unlink()

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert (demo_hub / MCP_CONFIG).read_bytes() == MCP_BYTES
    assert lock_files(demo_hub)[MCP_CONFIG] == {
        "executable": False,
        "ownership": "managed",
        "sha256": hashlib.sha256(MCP_BYTES).hexdigest(),
    }
    assert list(repo.rglob(MCP_CONFIG)) == []
    assert sorted(tmp_path.rglob(MCP_CONFIG)) == [demo_hub / MCP_CONFIG]


def test_reports_drift_when_mcp_config_edited(demo_hub: Path, run_doctor: DoctorRunner) -> None:
    (demo_hub / MCP_CONFIG).write_bytes(b'{"mcpServers": {}}\n')

    result = run_doctor(demo_hub, "--only", "lock.drift")

    drift = [line for line in result.stdout.splitlines() if "lock.drift" in line]
    assert len(drift) == 1, result.output
    assert f"lock.drift {MCP_CONFIG}:" in drift[0]


def test_reports_conflict_when_unmanaged_mcp_config_exists(
    demo_hub: Path, run_sync: SyncRunner
) -> None:
    hand_made = b'{"mcpServers": {"mine": {"type": "stdio", "command": "mine"}}}\n'
    (demo_hub / MCP_CONFIG).write_bytes(hand_made)
    document = json.loads((demo_hub / "hub.lock").read_bytes())
    del document["files"][MCP_CONFIG]
    (demo_hub / "hub.lock").write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")

    result = run_sync(demo_hub)

    assert (result.exit_code, result.stdout) == (3, ""), result.output
    # The existing conflict report: the file named in a diff of the disk against the render.
    assert result.stderr.startswith(f"--- {MCP_CONFIG} (on disk)\n+++ {MCP_CONFIG} (render)\n")
    assert (demo_hub / MCP_CONFIG).read_bytes() == hand_made


def test_passes_doctor_rules_when_mcp_config_rendered(
    demo_hub: Path, run_doctor: DoctorRunner
) -> None:
    only = [argument for rule in DOCTOR_RULES for argument in ("--only", rule)]

    result = run_doctor(demo_hub, *only)

    assert (result.exit_code, result.stderr) == (0, ""), result.output
    assert result.stdout.splitlines() == [CLEAN]
    assert (demo_hub / MCP_CONFIG).read_bytes() == MCP_BYTES
