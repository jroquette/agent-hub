"""The rendered ``./hub`` shim and ``./agent`` launcher (AC-15.10, AC-15.11).

The demo render's ``hub`` and ``agent`` (rendered once per module) go into ``<tmp>/ws/demo-hub``
with a ``hub.json`` pinned to ``4.5.6``: the shim reads nothing else. Each case runs the shim as
``[<shell>, <hub>/hub, …]`` from ``<tmp>/elsewhere``: every case under ``sh``; the portability
cases (arguments, exit codes, the hub's real path, ``$0`` without a slash) also under ``dash``
(required under ``CI``, skipped locally without one) and ``bash --posix``. ``PATH`` holds only a
test folder: a fake ``uvx`` (a Python logger: every argument as one JSON list item, the cwd,
``AGENT_HUB_ROOT`` and stdin) and a ``python3`` link, each only when the case wants it. A case
may set ``platform.repository`` too; the shim reads it at every run, like the pin (AGH-49).

ADR 0054: a case may also write ``hub.lock`` (``write_lock``). With a commit whose
version and repository match ``hub.json``, the shim makes one call from
``<repository>@<commit>``; any other lock, or none, keeps the two tag calls above. The fake
``uvx`` also logs its parent's pid (``FAKE_UVX_PARENT=1``: the caller's own pid when the shim
``exec``s) and prints ``FAKE_UVX_ERR`` on stderr on the real call.
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
from agent_hub.core.hub_config.platform_repository import PLATFORM_REPOSITORY_FORM
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.hub_files.release_commit import ReleaseCommit
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import (
    CUSTOM_REPOSITORY,
    REPOSITORY_CASES,
    VALUE_PARTS,
    RepositoryCase,
)
from agent_hub.generator.render_hub import render_hub

VERSION = "4.5.6"
SOURCE = "git+https://github.com/jroquette/agent-hub@v4.5.6#subdirectory=packages/agent-hub"
# Each shell and the arguments that make it POSIX: bash in its POSIX mode. Every case runs under
# sh; the portability cases (marked with ``ALL_SHELLS``) under each.
SHELLS = {"sh": (), "dash": (), "bash": ("--posix",)}
ALL_SHELLS = pytest.mark.parametrize("shell", sorted(SHELLS), indirect=True)
INSTALL_URL = "https://docs.astral.sh/uv/getting-started/installation/"
ACCESS_HINT = (
    "check read access to the repository (a credential, or the repository attached to this session)"
)
TIMEOUT = 30
# The custom hub's source, written out so a change to how the shim builds it fails here.
CUSTOM_SOURCE = "git+https://git.acme.test/tools/agent-hub@v4.5.6#subdirectory=packages/agent-hub"
OTHER_REPOSITORY = "git+https://github.com/acme/agent-hub"
BAD_REPOSITORY_LINE = f"hub: platform.repository in hub.json must be {PLATFORM_REPOSITORY_FORM}\n"
BAD_CASES = [case for case in REPOSITORY_CASES if not case.is_valid]
# ``write_pin`` leaves ``platform.repository`` out unless a case passes one.
ABSENT = object()
FAKE_UVX = """\
import json, os, sys
args = sys.argv[2:]
data = sys.stdin.buffer.read()
call = {"args": args, "cwd": os.getcwd(), "root": os.environ.get("AGENT_HUB_ROOT"),
        "stdin": data.decode("utf-8", "replace")}
if os.environ.get("FAKE_UVX_ENV") == "1":
    call["uv"] = {name: os.environ.get(name) for name in
                  ("UV_CACHE_DIR", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_PYTHON_DOWNLOADS")}
if os.environ.get("FAKE_UVX_PARENT") == "1":
    call["parent"] = os.getppid()
with open(sys.argv[1], "a", encoding="utf-8") as log:
    log.write(json.dumps(call) + "\\n")
if args[-1:] == ["--version"]:
    code = int(os.environ.get("FAKE_UVX_RESOLVE_RC", "0"))
    if code:
        default = "error: Failed to fetch the release"
        sys.stderr.write(os.environ.get("FAKE_UVX_RESOLVE_ERR", default) + "\\n")
    else:
        sys.stdout.write("hub " + args[1] + "\\n")
    sys.exit(code)
if os.environ.get("FAKE_UVX_ECHO") == "1":
    sys.stdout.buffer.write(data)
if os.environ.get("FAKE_UVX_ERR"):
    sys.stderr.write(os.environ["FAKE_UVX_ERR"] + "\\n")
sys.exit(int(os.environ.get("FAKE_UVX_RC", "0")))
"""

type Run = Callable[..., subprocess.CompletedProcess[bytes]]


@pytest.fixture(params=["sh"])
def shell(request: pytest.FixtureRequest) -> list[str]:
    """The shell's command line prefix: its path, then its POSIX-mode options."""
    found = shutil.which(request.param)
    if found is None:
        message = f"no {request.param} on PATH"
        if os.environ.get("CI"):
            pytest.fail(f"{message}, and CI must install one")
        pytest.skip(message)
    return [found, *SHELLS[request.param]]


@pytest.fixture(scope="module")
def shim_files() -> dict[str, bytes]:
    """The demo render's ``hub`` and ``agent``: rendered once for the module."""
    rendered = render_hub(HubConfig.model_validate(a_hub_document()))
    files = {file.path: file for file in rendered.files if file.path in ("hub", "agent")}
    assert all(file.executable for file in files.values())
    return {path: file.content for path, file in files.items()}


@pytest.fixture
def hub(tmp_path: Path, shim_files: dict[str, bytes]) -> Path:
    """``<tmp>/ws/demo-hub`` holding the executable shim and launcher, pinned to VERSION."""
    root = (tmp_path / "ws" / "demo-hub").resolve()
    root.mkdir(parents=True)
    for name, content in shim_files.items():
        (root / name).write_bytes(content)
        (root / name).chmod(0o755)
    write_pin(root, VERSION)
    return root


def write_pin(hub: Path, version: object, *, repository: object = ABSENT) -> None:
    document = a_hub_document()
    document["platform"]["version"] = version
    if repository is not ABSENT:
        document["platform"]["repository"] = repository
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
def run(tmp_path: Path, bin_dir: Path, shell: list[str]) -> Run:
    """Run ``<shell> <script> args`` in ``<tmp>/elsewhere`` or ``cwd``; PATH: the test folder."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    def call(
        script: Path | str,
        *args: str,
        stdin: bytes = b"",
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        return subprocess.run(  # noqa: S603 - a shell found on PATH, a rendered script
            [*shell, str(script), *args],
            input=stdin,
            capture_output=True,
            check=False,
            cwd=cwd or elsewhere,
            # uv's own folders are writable test folders unless a case says otherwise.
            env={
                "PATH": str(bin_dir),
                "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
                "UV_TOOL_DIR": str(tmp_path / "uv-tools"),
            }
            | (env or {}),
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
        ("1.2.3#x", "platform.version"),
        ("1.2.3\n", "platform.version"),
        ("v1.2.3", "platform.version"),
        (1, "platform.version"),
    ],
    ids=["absent", "not-json", "no-version", "short", "fragment", "newline", "prefixed", "number"],
)
def test_exits_one_when_pin_unreadable(
    hub: Path, run: Run, *, tools: None, log: Path, pin: str | int | None, named: str
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


@ALL_SHELLS
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


@ALL_SHELLS
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


@ALL_SHELLS
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


@ALL_SHELLS
def test_reads_own_folder_when_run_without_slash(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    # `sh hub` from the hub: $0 has no slash, so the shim's folder is the cwd.
    completed = run("hub", "brief", cwd=hub)

    assert completed.returncode == 0, completed.stderr
    assert calls(log)[-1]["cwd"] == str(hub)
    assert calls(log)[-1]["root"] == str(hub)


def case_name(case: RepositoryCase) -> str:
    return case.name


@ALL_SHELLS
def test_runs_custom_source_when_hub_sets_repository(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    write_pin(hub, VERSION, repository=CUSTOM_REPOSITORY)

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 0, completed.stderr
    assert [call["args"] for call in calls(log)] == [
        ["--from", CUSTOM_SOURCE, "hub", "--version"],
        ["--from", CUSTOM_SOURCE, "hub", "brief"],
    ]


def test_reads_new_repository_when_hub_json_edited(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    assert run(hub / "hub", "brief").returncode == 0
    write_pin(hub, VERSION, repository=OTHER_REPOSITORY)

    assert run(hub / "hub", "brief").returncode == 0

    other = SOURCE.replace("jroquette", "acme")
    assert [call["args"][1] for call in calls(log)] == [SOURCE, SOURCE, other, other]


@ALL_SHELLS
@pytest.mark.parametrize("case", BAD_CASES, ids=case_name)
def test_exits_one_without_uvx_when_repository_bad(
    hub: Path, run: Run, *, tools: None, log: Path, case: RepositoryCase
) -> None:
    write_pin(hub, VERSION, repository=case.value)

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 1
    assert calls(log) == []
    # One fixed line: the key and the accepted form, never the value (D-bad, E10).
    assert completed.stderr.decode() == BAD_REPOSITORY_LINE
    assert completed.stdout == b""
    for part in VALUE_PARTS:
        assert part.encode() not in completed.stderr + completed.stdout, part


def test_exits_one_in_fixed_line_when_hub_json_nested_deeply(
    hub: Path,
    run: Run,
    *,
    bin_dir: Path,
    log: Path,
    deep_nesting: Callable[[str], Any],
) -> None:
    # The parser raises RecursionError or returns a list, by interpreter and stack (conftest).
    nesting = deep_nesting(sys.executable)
    install_uvx(bin_dir, log)
    link_tool(bin_dir, "python3", nesting.python)
    (hub / "hub.json").write_text(nesting.text, encoding="utf-8")

    completed = run(hub / "hub", "brief")

    if nesting.raises:
        expected = f"hub: cannot read hub.json as JSON: {hub / 'hub.json'}\n"
    else:
        # A list is a document without a platform: the pin is checked first.
        expected = "hub: platform.version in hub.json must be X.Y.Z\n"
    assert completed.returncode == 1
    assert completed.stderr.decode() == expected
    assert completed.stdout == b""
    assert calls(log) == []


def test_names_version_first_when_version_and_repository_bad(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    write_pin(hub, "1.2", repository="git+ssh://git@github.com/acme/agent-hub")

    completed = run(hub / "hub", "brief")

    # The pin is checked first, as the SessionStart hook does (E13).
    assert completed.returncode == 1
    assert completed.stderr.decode() == "hub: platform.version in hub.json must be X.Y.Z\n"
    assert completed.stdout == b""
    assert calls(log) == []


# AGH-134: inside the Claude Code sandbox uv cannot write its own folders; the shim moves them.
UV_ENV = ("UV_CACHE_DIR", "UV_TOOL_DIR", "UV_TOOL_BIN_DIR", "UV_PYTHON_DOWNLOADS")
WRITE_ERROR = (
    "error: Failed to initialize cache at `/home/u/.cache/uv`\n"
    "  Caused by: failed to create directory `/home/u/.cache/uv`: Operation not permitted"
    " (os error 1)"
)
WRITE_HINT = (
    f"hub: cannot run agent-hub {VERSION}: uv could not write its cache or tool folder, which is"
    " not a repository access problem; inside a Claude Code sandbox only the workspace and"
    " $TMPDIR are writable: set UV_CACHE_DIR and UV_TOOL_DIR to a folder there, or run ./hub"
    " outside the sandbox"
)
NO_PYTHON = "error: No interpreter found for Python >=3.14 in managed installations or search path"


def unwritable(tmp_path: Path) -> str:
    """A folder no one can create: its parent is a regular file."""
    blocker = tmp_path / "blocker"
    blocker.write_text("")
    return str(blocker / "uv")


def test_keeps_uv_folders_when_writable(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path
) -> None:
    completed = run(hub / "hub", "brief", env={"FAKE_UVX_ENV": "1"})

    assert completed.returncode == 0, completed.stderr
    assert [call["uv"] for call in calls(log)] == [
        {
            "UV_CACHE_DIR": str(tmp_path / "uv-cache"),
            "UV_TOOL_DIR": str(tmp_path / "uv-tools"),
            "UV_TOOL_BIN_DIR": None,
            "UV_PYTHON_DOWNLOADS": None,
        }
    ] * 2
    assert not (hub / ".hub-uv").exists()


@pytest.mark.parametrize("variable", ["UV_CACHE_DIR", "UV_TOOL_DIR"])
def test_moves_uv_folders_into_hub_when_one_unwritable(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path, variable: str
) -> None:
    completed = run(hub / "hub", "brief", env={"FAKE_UVX_ENV": "1", variable: unwritable(tmp_path)})

    assert completed.returncode == 0, completed.stderr
    own = hub / ".hub-uv"
    assert [call["uv"] for call in calls(log)] == [
        {
            "UV_CACHE_DIR": str(own / "cache"),
            "UV_TOOL_DIR": str(own / "tools"),
            "UV_TOOL_BIN_DIR": str(own / "bin"),
            "UV_PYTHON_DOWNLOADS": "never",
        }
    ] * 2
    # The folder ignores itself, so a hub's own .gitignore needs no line for it.
    assert (own / ".gitignore").read_text().splitlines()[-1] == "*"


def test_keeps_caller_python_downloads_when_uv_folders_moved(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path
) -> None:
    env = {
        "FAKE_UVX_ENV": "1",
        "UV_CACHE_DIR": unwritable(tmp_path),
        "UV_PYTHON_DOWNLOADS": "automatic",
    }

    assert run(hub / "hub", "brief", env=env).returncode == 0

    assert {call["uv"]["UV_PYTHON_DOWNLOADS"] for call in calls(log)} == {"automatic"}


@pytest.mark.parametrize(
    "error",
    [
        WRITE_ERROR,
        "error: Could not create temporary file in `/home/u/.local/share/uv/tools/.tmpAbc`",
        "error: failed to open file `/x/.lock`: Read-only file system (os error 30)",
        "error: failed to create directory `/x`: Permission denied (os error 13)",
    ],
    ids=["cache-eperm", "tool-temp", "read-only", "eacces"],
)
def test_names_uv_folder_not_access_when_uv_cannot_write(
    hub: Path, run: Run, *, tools: None, log: Path, error: str
) -> None:
    env = {"FAKE_UVX_RESOLVE_RC": "2", "FAKE_UVX_RESOLVE_ERR": error}

    completed = run(hub / "hub", "brief", env=env)

    assert completed.returncode == 1
    assert stderr_lines(completed) == [*error.splitlines(), WRITE_HINT]
    assert ACCESS_HINT not in completed.stderr.decode()
    assert len(calls(log)) == 1


def test_names_python_install_when_no_interpreter(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path
) -> None:
    env = {
        "FAKE_UVX_RESOLVE_RC": "2",
        "FAKE_UVX_RESOLVE_ERR": NO_PYTHON,
        "UV_CACHE_DIR": unwritable(tmp_path),
    }

    completed = run(hub / "hub", "brief", env=env)

    assert completed.returncode == 1
    assert stderr_lines(completed) == [
        NO_PYTHON,
        f"hub: cannot run agent-hub {VERSION}: uv found no Python it may use and downloads none"
        " here (UV_PYTHON_DOWNLOADS=never); run uv python install 3.14 outside the Claude Code"
        " sandbox, then retry",
    ]


# The commit path (ADR 0054). A lock whose version and repository match hub.json and
# whose commit is 40 lowercase hex runs one ``exec``'d call from the commit; every other lock keeps
# the tag path above, byte for byte.
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
# Written out, as SOURCE is, so a change to how the shim builds it fails here.
COMMIT_SOURCE = (
    "git+https://github.com/jroquette/agent-hub@0123456789abcdef0123456789abcdef01234567"
    "#subdirectory=packages/agent-hub"
)
# The largest hub.lock the shim reads (1 MiB); a larger one is not read.
LOCK_CAP = 1024 * 1024
TAG_CALLS = [["--from", SOURCE, "hub", "--version"], ["--from", SOURCE, "hub", "brief"]]


@pytest.fixture(scope="module")
def demo_render() -> RenderedHub:
    return render_hub(HubConfig.model_validate(a_hub_document()))


def lock_document(
    rendered: RenderedHub,
    *,
    version: str = VERSION,
    commit: str | None = COMMIT,
    repository: str = DEFAULT_REPOSITORY,
) -> dict[str, Any]:
    """The lock ``hub sync`` writes for the demo pinned to ``version``; with ``commit`` (None: no
    commit) read from ``repository``."""
    document = a_hub_document()
    document["platform"]["version"] = version
    config = HubConfig.model_validate(document)
    release = None if commit is None else ReleaseCommit(commit=commit, repository=repository)
    lock: dict[str, Any] = json.loads(
        lock_bytes(build_hub_lock(rendered=rendered, config=config, release=release))
    )
    assert lock["platform_version"] == version
    assert lock.get("platform_commit") == commit
    return lock


def write_lock(hub: Path, lock: dict[str, Any]) -> str:
    text = json.dumps(lock, indent=2, sort_keys=True) + "\n"
    (hub / "hub.lock").write_text(text, encoding="utf-8")
    return text


def assert_runs_tag_source(hub: Path, run: Run, log: Path) -> None:
    """Today's tag path: the resolve step, then the real call, both from ``@v<version>``."""
    completed = run(hub / "hub", "brief")

    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == b""
    assert [call["args"] for call in calls(log)] == TAG_CALLS


@ALL_SHELLS
def test_runs_lock_commit_source_when_lock_matches_pin(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    write_lock(hub, lock_document(demo_render))

    completed = run(hub / "hub", "--version")

    assert completed.returncode == 0, completed.stderr
    assert [call["args"] for call in calls(log)] == [["--from", COMMIT_SOURCE, "hub", "--version"]]


@ALL_SHELLS
@pytest.mark.parametrize("code", [0, 3, 4])
def test_calls_uvx_once_when_lock_has_commit(
    hub: Path,
    run: Run,
    *,
    tools: None,
    log: Path,
    tmp_path: Path,
    demo_render: RenderedHub,
    code: int,
) -> None:
    write_lock(hub, lock_document(demo_render))
    data = b"line one\nline two\n"
    env = {"FAKE_UVX_RC": str(code), "FAKE_UVX_ECHO": "1", "FAKE_UVX_PARENT": "1"}

    completed = run(hub / "hub", "sync", "a b", stdin=data, env=env)

    # One call, exec'd: its parent is this test's process, it gets the whole stdin, the caller's
    # folder and the hub's root, and its exit code is the shim's.
    assert completed.returncode == code
    assert completed.stderr == b""
    assert completed.stdout == data
    assert calls(log) == [
        {
            "args": ["--from", COMMIT_SOURCE, "hub", "sync", "a b"],
            "cwd": str(tmp_path / "elsewhere"),
            "root": str(hub),
            "stdin": data.decode(),
            "parent": os.getpid(),
        }
    ]


@ALL_SHELLS
def test_names_cache_folder_without_uvx_when_no_folder_is_writable(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path, demo_render: RenderedHub
) -> None:
    write_lock(hub, lock_document(demo_render))
    # Neither uv's own cache folder nor the hub's fallback can be created: .hub-uv is a file.
    (hub / ".hub-uv").write_text("", encoding="utf-8")
    assert (hub / ".hub-uv").is_file()

    completed = run(hub / "hub", "brief", env={"UV_CACHE_DIR": unwritable(tmp_path)})

    assert completed.returncode == 1
    assert stderr_lines(completed) == [WRITE_HINT]
    assert calls(log) == []


@ALL_SHELLS
def test_shows_uv_error_once_when_commit_call_fails(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    write_lock(hub, lock_document(demo_render))
    error = "error: Failed to fetch the release"

    completed = run(hub / "hub", "brief", env={"FAKE_UVX_RC": "2", "FAKE_UVX_ERR": error})

    # uv's own text is the cause: no classified line after it, no second (diagnosis) call.
    assert completed.returncode == 2
    assert stderr_lines(completed) == [error]
    assert [call["args"] for call in calls(log)] == [["--from", COMMIT_SOURCE, "hub", "brief"]]


@ALL_SHELLS
def test_uses_tag_source_when_lock_has_no_commit(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    lock = lock_document(demo_render, commit=None)
    assert "platform_commit" not in lock
    write_lock(hub, lock)

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_is_absent(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    assert not (hub / "hub.lock").exists()

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_version_differs_from_pin(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    # The pin was edited in hub.json and not synced yet: the lock's commit is the old release's.
    write_lock(hub, lock_document(demo_render, version="4.5.5"))

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_repository_differs(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    # hub.json uses the default repository; the commit was read from another one.
    write_lock(hub, lock_document(demo_render, repository=OTHER_REPOSITORY))

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_is_malformed(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    text = write_lock(hub, lock_document(demo_render))
    # The matching commit is there, but the file is not JSON: extra data after the object.
    (hub / "hub.lock").write_text(text + "}\n", encoding="utf-8")
    assert COMMIT in (hub / "hub.lock").read_text(encoding="utf-8")

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_is_a_fifo(
    hub: Path, run: Run, *, tools: None, log: Path
) -> None:
    # A FIFO with no writer would block a read for good: the shim never opens it.
    os.mkfifo(hub / "hub.lock")

    assert_runs_tag_source(hub, run, log)


@ALL_SHELLS
def test_uses_tag_source_when_lock_is_too_large(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    text = json.dumps(lock_document(demo_render), sort_keys=True)
    # Valid JSON holding the matching commit, one byte over the cap (spaces before the last brace).
    padded = text[:-1] + " " * (LOCK_CAP + 1 - len(text)) + "}"
    (hub / "hub.lock").write_text(padded, encoding="utf-8")
    assert (hub / "hub.lock").stat().st_size == LOCK_CAP + 1
    assert json.loads(padded)["platform_commit"] == COMMIT

    assert_runs_tag_source(hub, run, log)


def padded_lock(rendered: RenderedHub, size: int) -> str:
    """The matching lock as valid JSON of exactly ``size`` bytes: spaces before the last brace."""
    text = json.dumps(lock_document(rendered), sort_keys=True)
    padded = text[:-1] + " " * (size - len(text)) + "}"
    assert len(padded.encode()) == size
    assert json.loads(padded)["platform_commit"] == COMMIT
    return padded


@ALL_SHELLS
def test_runs_lock_commit_source_when_lock_is_exactly_the_cap(
    hub: Path, run: Run, *, tools: None, log: Path, demo_render: RenderedHub
) -> None:
    # The cap itself is still read: only a larger file keeps the tag.
    (hub / "hub.lock").write_text(padded_lock(demo_render, LOCK_CAP), encoding="utf-8")
    assert (hub / "hub.lock").stat().st_size == LOCK_CAP

    completed = run(hub / "hub", "brief")

    assert completed.returncode == 0, completed.stderr
    assert [call["args"] for call in calls(log)] == [["--from", COMMIT_SOURCE, "hub", "brief"]]


@ALL_SHELLS
def test_uses_tag_source_when_lock_is_a_link(
    hub: Path, run: Run, *, tools: None, log: Path, tmp_path: Path, demo_render: RenderedHub
) -> None:
    # A link to a matching lock is not read: only a regular file at hub.lock is.
    target = tmp_path / "elsewhere.lock"
    target.write_text(
        json.dumps(lock_document(demo_render), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (hub / "hub.lock").symlink_to(target)
    assert json.loads((hub / "hub.lock").read_text(encoding="utf-8"))["platform_commit"] == COMMIT

    assert_runs_tag_source(hub, run, log)


LOGGER = '#!/bin/sh\nprintf \'%s\\n\' "{name} $*" >> "{log}"\nexit 0\n'


@ALL_SHELLS
def test_calls_no_tag_source_or_git_when_lock_has_commit(
    hub: Path,
    run: Run,
    *,
    tools: None,
    log: Path,
    bin_dir: Path,
    tmp_path: Path,
    demo_render: RenderedHub,
) -> None:
    # git and gh loggers on PATH: the shim's foreground reads no release from the network.
    write_lock(hub, lock_document(demo_render))
    network_log = tmp_path / "network-calls.log"
    for name in ("git", "gh"):
        (bin_dir / name).write_text(LOGGER.format(name=name, log=network_log), encoding="utf-8")
        (bin_dir / name).chmod(0o755)

    completed = run(hub / "hub", "--version")

    assert completed.returncode == 0, completed.stderr
    sources = [call["args"][1] for call in calls(log)]
    assert sources == [COMMIT_SOURCE]
    assert not any("@v" in source for source in sources)
    assert not network_log.exists()
