"""The rendered ``./hub`` shim and ``./agent`` launcher (AC-15.10, AC-15.11).

The demo hub is rendered into ``<tmp>/ws/demo-hub`` and pinned to ``4.5.6``. Each case runs the
shim as ``[<shell>, <hub>/hub, …]`` under ``sh`` and ``dash`` (dash is required under ``CI``,
skipped locally without one) from ``<tmp>/elsewhere``, with a ``PATH`` that holds only a test
folder: a fake ``uvx`` (a Python logger: every argument as one JSON list item, the cwd,
``AGENT_HUB_ROOT`` and stdin) and a ``python3`` link, each only when the case wants it.
"""

import json
import os
import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.testing.builders import a_hub_document

VERSION = "4.5.6"
SOURCE = "git+https://github.com/jroquette/agent-hub@v4.5.6#subdirectory=packages/agent-hub"
SHELLS = ("sh", "dash")
INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
ACCESS_HINT = (
    "check read access to the repository (a credential, or the repository attached to this session)"
)
TIMEOUT = 30
FAKE_UVX = """\
import json, os, sys
args = sys.argv[2:]
data = sys.stdin.buffer.read()
call = {"args": args, "cwd": os.getcwd(), "root": os.environ.get("AGENT_HUB_ROOT"),
        "stdin": data.decode("utf-8", "replace")}
with open(sys.argv[1], "a", encoding="utf-8") as log:
    log.write(json.dumps(call) + "\\n")
if args[-1:] == ["--version"]:
    code = int(os.environ.get("FAKE_UVX_RESOLVE_RC", "0"))
    if code:
        sys.stderr.write("error: Failed to fetch the release\\n")
    else:
        sys.stdout.write("hub " + args[1] + "\\n")
    sys.exit(code)
if os.environ.get("FAKE_UVX_ECHO") == "1":
    sys.stdout.buffer.write(data)
sys.exit(int(os.environ.get("FAKE_UVX_RC", "0")))
"""

type Run = Callable[..., subprocess.CompletedProcess[bytes]]


@pytest.fixture(params=SHELLS)
def shell(request: pytest.FixtureRequest) -> str:
    found = shutil.which(request.param)
    if found is None:
        message = f"no {request.param} on PATH"
        if os.environ.get("CI"):
            pytest.fail(f"{message}, and CI must install one")
        pytest.skip(message)
    return found


@pytest.fixture
def hub(rendered_hub: Callable[[HubConfig], Path], demo_config: HubConfig) -> Path:
    """The rendered demo hub, pinned to VERSION."""
    root = rendered_hub(demo_config).resolve()
    write_pin(root, VERSION)
    return root


def write_pin(hub: Path, version: object) -> None:
    document = a_hub_document()
    document["platform"]["version"] = version
    (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")


@pytest.fixture
def bin_dir(tmp_path: Path) -> Path:
    folder = tmp_path / "bin"
    folder.mkdir()
    return folder


@pytest.fixture
def log(tmp_path: Path) -> Path:
    return tmp_path / "uvx-calls.jsonl"


def install_uvx(bin_dir: Path, log: Path) -> None:
    script = bin_dir.parent / "fake_uvx.py"
    script.write_text(FAKE_UVX, encoding="utf-8")
    uvx = bin_dir / "uvx"
    uvx.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{script}" "{log}" "$@"\n')
    uvx.chmod(0o755)


def link_tool(bin_dir: Path, name: str, target: str | None = None) -> None:
    found = target or shutil.which(name)
    assert found is not None, f"the shim tests need {name}"
    (bin_dir / name).symlink_to(os.path.realpath(found))


@pytest.fixture
def run(tmp_path: Path, bin_dir: Path, shell: str) -> Run:
    """Run ``<shell> <script> args`` from ``<tmp>/elsewhere`` with ``PATH`` = the test folder."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def call(
        script: Path, *args: str, stdin: bytes = b"", env: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - a shell found on PATH, a rendered script
            [shell, str(script), *args],
            input=stdin,
            capture_output=True,
            check=False,
            cwd=elsewhere,
            env={"PATH": str(bin_dir)} | (env or {}),
            timeout=TIMEOUT,
        )

    return call


@pytest.fixture
def tools(bin_dir: Path, log: Path) -> None:
    """Both tools the shim needs: the fake ``uvx`` and ``python3``."""
    install_uvx(bin_dir, log)
    link_tool(bin_dir, "python3", sys.executable)


def calls(log: Path) -> list[dict[str, Any]]:
    if not log.exists():
        return []
    return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]


def stderr_lines(completed: subprocess.CompletedProcess[bytes]) -> list[str]:
    return completed.stderr.decode().splitlines()


def test_prints_install_hint_when_uvx_missing(
    hub: Path, run: Run, *, bin_dir: Path, log: Path
) -> None:
    link_tool(bin_dir, "python3", sys.executable)

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 127
    assert stderr_lines(completed) == [f"hub: uv is not installed; see {INSTALL_URL}"]
    assert calls(log) == []


def test_names_python_when_python_missing(hub: Path, run: Run, *, bin_dir: Path, log: Path) -> None:
    install_uvx(bin_dir, log)

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 127
    lines = stderr_lines(completed)
    assert len(lines) == 1
    assert "python3" in lines[0]
    assert calls(log) == []


@pytest.mark.parametrize(
    ("pin", "named"),
    [
        (None, "hub.json"),
        ("not json", "hub.json"),
        ("no version", "platform.version"),
        ("1.2", "platform.version"),
    ],
    ids=["absent", "not-json", "no-version", "short"],
)
def test_exits_one_when_pin_unreadable(
    hub: Path, run: Run, *, tools: None, log: Path, pin: str | None, named: str
) -> None:
    if pin is None:
        (hub / "hub.json").unlink()
    elif pin == "not json":
        (hub / "hub.json").write_text("{not json\n")
    elif pin == "no version":
        document = a_hub_document()
        del document["platform"]["version"]
        (hub / "hub.json").write_text(json.dumps(document))
    else:
        write_pin(hub, pin)

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 1
    lines = stderr_lines(completed)
    assert len(lines) == 1, lines
    assert named in lines[0]
    assert calls(log) == []


def test_names_access_when_resolve_fails(hub: Path, run: Run, *, tools: None, log: Path) -> None:
    completed = run(hub / "hub", "brief", env={"FAKE_UVX_RESOLVE_RC": "2"})

    assert completed.returncode == 1
    # uv's own reason first, then the shim's line naming the source and the access.
    assert stderr_lines(completed) == [
        "error: Failed to fetch the release",
        f"hub: cannot run agent-hub {VERSION} from {SOURCE}; {ACCESS_HINT}",
    ]
    assert [call["args"] for call in calls(log)] == [["--from", SOURCE, "hub", "--version"]]


@pytest.mark.parametrize("code", [0, 3, 4])
def test_passes_exit_code_through_when_real_call_exits(
    hub: Path, run: Run, *, tools: None, log: Path, code: int
) -> None:
    completed = run(hub / "hub", "sync", env={"FAKE_UVX_RC": str(code)})

    assert completed.returncode == code
    assert completed.stderr == b""
    assert [call["args"] for call in calls(log)] == [
        ["--from", SOURCE, "hub", "--version"],
        ["--from", SOURCE, "hub", "sync"],
    ]


def test_passes_arguments_byte_identical_when_called(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    arguments = ["a b", "it's", '"quoted"', "*", "", "--", "$HOME", "back\\slash", "new\nline"]

    completed = run(hub / "hub", *arguments)

    assert completed.returncode == 0, completed.stderr
    assert calls(log)[-1]["args"] == ["--from", SOURCE, "hub", *arguments]


def test_passes_stdin_when_called(hub: Path, run: Run, *, tools: None, log: Path) -> None:
    data = b"line one\nline two\n"

    completed = run(hub / "hub", "collect", "-", stdin=data, env={"FAKE_UVX_ECHO": "1"})

    assert completed.returncode == 0, completed.stderr
    assert completed.stdout == data
    # The resolve step reads nothing: the whole input reaches the real call.
    assert [call["stdin"] for call in calls(log)] == ["", data.decode()]


def test_keeps_cwd_and_exports_root_when_called(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path
) -> None:
    link = tmp_path / "linked-hub"
    link.symlink_to(hub)

    for script in (hub / "hub", link / "hub"):
        assert run(script, "brief").returncode == 0

    real = [call for call in calls(log) if call["args"][-1] == "brief"]
    # The caller's folder is kept (no cd); the hub is named by its real path.
    assert [(call["cwd"], call["root"]) for call in real] == [
        (str(tmp_path / "elsewhere"), str(hub)),
        (str(tmp_path / "elsewhere"), str(hub)),
    ]


def test_reads_new_pin_when_hub_json_edited(hub: Path, run: Run, *, tools: None, log: Path) -> None:
    assert run(hub / "hub", "brief").returncode == 0
    write_pin(hub, "4.5.7")

    assert run(hub / "hub", "brief").returncode == 0

    sources = [call["args"][1] for call in calls(log)]
    assert sources == [
        SOURCE,
        SOURCE,
        SOURCE.replace("4.5.6", "4.5.7"),
        SOURCE.replace("4.5.6", "4.5.7"),
    ]


def test_execs_hub_agent_when_agent_runs(
    hub: Path, run: Run, *, tools: None, bin_dir: Path, log: Path, tmp_path: Path
) -> None:
    lines = (hub / "agent").read_text().splitlines()
    assert lines[0] == "#!/bin/sh"
    assert lines[-1] == 'exec "$(dirname "$0")/hub" agent "$@"'
    assert len(lines) <= 3
    assert all(line.startswith("#") for line in lines[1:-1])
    link_tool(bin_dir, "dirname")

    completed = run(hub / "agent", "x", "y z")

    assert completed.returncode == 0, completed.stderr
    assert calls(log)[-1] == {
        "args": ["--from", SOURCE, "hub", "agent", "x", "y z"],
        "cwd": str(tmp_path / "elsewhere"),
        "root": str(hub),
        "stdin": "",
    }
