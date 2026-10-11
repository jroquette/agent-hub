"""The agent-hub image and its Compose service (ADR 0022), built and run for real.

Marker ``docker``: never in ``make check``; ``make test-docker`` runs it and CI has a job for it.
Without a Docker daemon it skips, and under ``CI`` it fails. Each run uses its own Compose
project, host port, hubs root and data volume, and removes them afterwards; the image tag
``agent-hub:local`` is the one ``make up`` builds. The web app the image serves is built in the
image and compared byte for byte with the committed ``web_dist``.
"""

import filecmp
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from agent_hub.core.testing.hook_inputs import a_hook_input
from tests.e2e.conftest import REPO_ROOT, free_loopback_port

pytestmark = pytest.mark.docker

WEB_DIST = REPO_ROOT / "packages" / "api" / "src" / "agent_hub" / "api" / "web_dist"
COMPOSE_FILE = REPO_ROOT / "compose.yaml"
SERVICE = "agent-hub"
IMAGE = "agent-hub:local"
IMAGE_WEB_DIST = "/opt/venv/lib/python3.14/site-packages/agent_hub/api/web_dist"
BUILD_SECONDS = 900
UP_SECONDS = 180
COMMAND_SECONDS = 60
REQUEST_SECONDS = 10
CONTAINER_UID = "10001"
SESSION = "docker-e2e-1"
ANY_ADDRESS = "0.0.0.0"  # noqa: S104 -- the bind the test expects refused


@dataclass(frozen=True)
class Stack:
    """A running Compose project of the service, reachable at ``url`` from the host."""

    project: str
    url: str
    port: int
    hubs_root: Path
    env: Mapping[str, str]


def _docker() -> str | None:
    found = shutil.which("docker")
    if found is None:
        return None
    try:
        info = subprocess.run(
            [found, "info"], capture_output=True, text=True, timeout=COMMAND_SECONDS, check=False
        )
    except subprocess.TimeoutExpired:
        return None
    return found if info.returncode == 0 else None


def _require_docker() -> str:
    docker = _docker()
    if docker is None:
        reason = "the docker tests need a running Docker daemon"
        if os.environ.get("CI"):
            pytest.fail(reason)
        pytest.skip(reason)
    return docker


def _checked(
    command: list[str], *, env: Mapping[str, str], timeout: float = COMMAND_SECONDS
) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, f"{' '.join(command)}\n{result.stdout}\n{result.stderr}"
    return result


def _readable_dir(prefix: str) -> Path:
    """A fresh folder that the container's user (uid 10001) may read: 0755."""
    path = Path(tempfile.mkdtemp(prefix=prefix))
    path.chmod(0o755)
    return path


@pytest.fixture(scope="module")
def stack() -> Iterator[Stack]:
    docker = _require_docker()
    project = f"agent-hub-e2e-{uuid.uuid4().hex[:8]}"
    port = free_loopback_port()
    hubs_root = _readable_dir("agent-hub-hubs-")
    projects = _readable_dir("agent-hub-projects-")
    env = {
        **os.environ,
        "AGENT_HUB_PORT": str(port),
        "AGENT_HUB_HUBS_ROOT": str(hubs_root),
        "AGENT_HUB_CLAUDE_PROJECTS": str(projects),
    }
    compose = [docker, "compose", "-f", str(COMPOSE_FILE), "-p", project]
    try:
        _checked([*compose, "build"], env=env, timeout=BUILD_SECONDS)
        _checked(
            [*compose, "up", "-d", "--wait", "--wait-timeout", "120"], env=env, timeout=UP_SECONDS
        )
        yield Stack(
            project=project,
            url=f"http://127.0.0.1:{port}",
            port=port,
            hubs_root=hubs_root,
            env=env,
        )
    finally:
        subprocess.run(
            [*compose, "down", "-v", "--remove-orphans"],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            timeout=UP_SECONDS,
            check=False,
        )
        shutil.rmtree(hubs_root, ignore_errors=True)
        shutil.rmtree(projects, ignore_errors=True)


def _container(stack: Stack) -> dict[str, Any]:
    docker = _require_docker()
    compose = [docker, "compose", "-f", str(COMPOSE_FILE), "-p", stack.project]
    container_id = _checked([*compose, "ps", "-q", SERVICE], env=stack.env).stdout.strip()
    inspected = _checked([docker, "inspect", container_id], env=stack.env).stdout
    [container] = json.loads(inspected)
    return dict(container)


def _exec(stack: Stack, *command: str) -> subprocess.CompletedProcess[str]:
    docker = _require_docker()
    return subprocess.run(
        [
            docker,
            "compose",
            "-f",
            str(COMPOSE_FILE),
            "-p",
            stack.project,
            "exec",
            "-T",
            SERVICE,
            *command,
        ],
        cwd=REPO_ROOT,
        env=stack.env,
        capture_output=True,
        text=True,
        timeout=COMMAND_SECONDS,
        check=False,
    )


def test_serves_api_and_app_on_host_loopback_when_compose_up(stack: Stack) -> None:
    with httpx.Client(base_url=stack.url, timeout=REQUEST_SECONDS) as client:
        status = client.get("/api/v1/collector/status")
        root = client.get("/")

    assert status.status_code == 200, status.text
    assert status.json()["db_path"] == "/data/agent-hub.db"
    assert root.status_code == 200
    assert "<!doctype html>" in root.text.lower()
    bindings = _container(stack)["HostConfig"]["PortBindings"]["7420/tcp"]
    assert [binding["HostIp"] for binding in bindings] == ["127.0.0.1"]


def test_reads_back_hook_event_when_envelope_posted(stack: Stack) -> None:
    hook = a_hook_input("SessionStart", session_id=SESSION, cwd="/work/demo-api")
    envelope = {
        "v": 1,
        "project": "demo",
        "repo": "demo-api",
        "run": None,
        "step": None,
        "attempt": None,
        "sent_at": datetime.now(UTC).isoformat(),
        "hook": hook,
    }
    with httpx.Client(base_url=stack.url, timeout=REQUEST_SECONDS) as client:
        posted = client.post("/api/v1/events/hooks", json=envelope)
        sessions = client.get("/api/v1/sessions").json()["items"]

    assert posted.status_code == 202, posted.text
    assert SESSION in [session["id"] for session in sessions]


def test_registers_hub_at_host_path_when_hubs_root_mounted(stack: Stack) -> None:
    hub = stack.hubs_root / "demo-hub"
    hub_exe = Path(sys.executable).with_name("hub")
    init = [
        str(hub_exe),
        "init",
        "demo",
        "--repos",
        "acme/demo-api",
        "--tracker",
        "linear:DEM",
        "--branch-prefix",
        "jdoe/",
        "--hub-repo",
        "acme/demo-hub",
        "--author-name",
        "Jane Doe",
        "--author-email",
        "jane@example.com",
        "--dir",
        str(hub),
    ]
    _checked(init, env=stack.env)
    with httpx.Client(base_url=stack.url, timeout=REQUEST_SECONDS) as client:
        registered = client.post("/api/v1/hubs", json={"path": str(hub)})
        hubs = client.get("/api/v1/hubs").json()["items"]

    assert registered.status_code == 201, registered.text
    assert [item["path"] for item in hubs] == [str(hub)]


def test_runs_as_unprivileged_user_on_read_only_root_when_started(stack: Stack) -> None:
    host_config = _container(stack)["HostConfig"]
    uid = _exec(stack, "id", "-u")
    write = _exec(stack, "touch", "/opt/venv/written")

    assert uid.stdout.strip() == CONTAINER_UID
    assert host_config["ReadonlyRootfs"] is True
    assert host_config["CapDrop"] == ["ALL"]
    assert "no-new-privileges:true" in host_config["SecurityOpt"]
    assert write.returncode != 0
    assert "Read-only file system" in write.stderr


def test_refuses_address_outside_loopback_when_run_outside_container(stack: Stack) -> None:
    """The image's own variable is what allows its bind: without it the same command exits 2."""
    refused = _exec(
        stack, "env", "-u", "AGENT_HUB_IN_CONTAINER", "hub", "web", "--host", ANY_ADDRESS
    )

    assert refused.returncode == 2
    assert "needs AGENT_HUB_IN_CONTAINER=1" in refused.stderr


def test_serves_committed_web_app_when_image_built(stack: Stack, tmp_path: Path) -> None:
    """The image's web app comes from its own web stage (npm ci, vite build), not from the
    committed copy; it must equal that copy byte for byte."""
    docker = _require_docker()
    created = _checked([docker, "create", IMAGE], env=stack.env).stdout.strip()
    try:
        _checked(
            [docker, "cp", f"{created}:{IMAGE_WEB_DIST}", str(tmp_path / "web_dist")], env=stack.env
        )
    finally:
        _checked([docker, "rm", created], env=stack.env)

    assert _same_tree(tmp_path / "web_dist", WEB_DIST)


def _same_tree(left: Path, right: Path) -> bool:
    compared = filecmp.dircmp(left, right)
    if compared.left_only or compared.right_only or compared.funny_files:
        return False
    _, mismatch, errors = filecmp.cmpfiles(left, right, compared.common_files, shallow=False)
    if mismatch or errors:
        return False
    return all(_same_tree(left / name, right / name) for name in compared.common_dirs)
