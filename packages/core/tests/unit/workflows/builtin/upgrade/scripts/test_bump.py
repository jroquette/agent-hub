"""The upgrade pack's ``bump.py`` (AGH-484), in process in a temporary git repo: where the package
is, the version its lockfile holds, semver's major move, and every refusal (exit 2)."""

import importlib.util
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path
from types import ModuleType

import pytest

SCRIPT = Path(str(files("agent_hub.core").joinpath("workflows/builtin/upgrade/scripts/bump.py")))

# Named as its folder places it, so coverage of agent_hub.core measures it.
MODULE = "agent_hub.core.workflows.builtin.upgrade.scripts.bump"

ROOT_PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "httpx==0.28.1",  # the client
    "rich>=13",
]

[dependency-groups]
dev = ["pytest>=8"]

[tool.uv.workspace]
members = ["packages/core"]
"""
CORE_PYPROJECT = """\
[project]
name = "demo-core"
version = "0.1.0"
dependencies = []

[project.optional-dependencies]
http = ['HTTPX == 0.28.1']
"""
UV_LOCK = """\
version = 1
requires-python = ">=3.12"

[[package]]
name = "httpx"
version = "0.28.1"
source = { registry = "https://pypi.org/simple" }
dependencies = [
    { name = "rich" },
]

[[package]]
name = "rich"
version = "13.9.4"
source = { registry = "https://pypi.org/simple" }

[package.metadata]
requires-dist = [{ name = "httpx", specifier = "==0.28.1" }]
"""
PACKAGE_JSON = {
    "name": "web",
    "dependencies": {"react": "18.3.1", "@scope/ui": "~2.1.0"},
    "devDependencies": {"vite": "^5.4.0"},
}
PACKAGE_LOCK = {
    "lockfileVersion": 3,
    "packages": {
        "": {"name": "web"},
        "node_modules/react": {"version": "18.3.1"},
        "node_modules/@scope/ui": {"version": "2.1.3"},
        "node_modules/vite": {"version": "5.4.2"},
    },
}


def load() -> ModuleType:
    spec = importlib.util.spec_from_file_location(MODULE, SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # No __pycache__ beside the pack's files: the pack is seeded into hubs file by file.
    writes, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = writes
    return module


def git(root: Path, *args: str) -> str:
    return subprocess.run(  # noqa: S603 - git with fixed arguments, in a temporary repo
        ["git", *args],  # noqa: S607 - git from PATH
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A committed repo with a uv workspace and an npm folder ``web/``; the cwd."""
    root = tmp_path / "repo"
    for name, text in {
        "pyproject.toml": ROOT_PYPROJECT,
        "packages/core/pyproject.toml": CORE_PYPROJECT,
        "uv.lock": UV_LOCK,
        "web/package.json": json.dumps(PACKAGE_JSON, indent=2) + "\n",
        "web/package-lock.json": json.dumps(PACKAGE_LOCK, indent=2) + "\n",
        ".gitignore": "node_modules/\n",
    }.items():
        (root / name).parent.mkdir(parents=True, exist_ok=True)
        (root / name).write_text(text, encoding="utf-8")
    for key, value in {
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_AUTHOR_NAME": "Jo",
        "GIT_AUTHOR_EMAIL": "jo@example.com",
        "GIT_COMMITTER_NAME": "Jo",
        "GIT_COMMITTER_EMAIL": "jo@example.com",
    }.items():
        monkeypatch.setenv(key, value)
    git(root, "init", "-q", "-b", "main")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "init")
    monkeypatch.chdir(root)
    return root


def commit_file(root: Path, name: str, text: str) -> None:
    (root / name).parent.mkdir(parents=True, exist_ok=True)
    (root / name).write_text(text, encoding="utf-8")
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", f"add {name}")


@pytest.mark.usefixtures("repo")
def test_finds_uv_package_and_locked_version_when_uv_lock_lists_it() -> None:
    found = load().find("rich")

    assert (found.manager, found.dir, found.current) == ("uv", ".", "13.9.4")
    assert [(pin.manifest, pin.spec, pin.exact) for pin in found.pins] == [
        ("pyproject.toml", ">=13", False)
    ]


@pytest.mark.usefixtures("repo")
def test_finds_exact_pins_per_member_when_pyproject_pins_with_double_equals() -> None:
    found = load().find("httpx")

    assert (found.manager, found.current) == ("uv", "0.28.1")
    assert [(p.manifest, p.member, p.kind, p.group, p.exact) for p in found.pins] == [
        ("packages/core/pyproject.toml", "demo-core", "optional", "http", True),
        ("pyproject.toml", "demo", None, "", True),
    ]


@pytest.mark.usefixtures("repo")
@pytest.mark.parametrize(
    ("name", "section", "spec", "current"),
    [
        ("vite", "devDependencies", "^5.4.0", "5.4.2"),
        ("react", "dependencies", "18.3.1", "18.3.1"),
        ("@scope/ui", "dependencies", "~2.1.0", "2.1.3"),
    ],
)
def test_finds_npm_package_and_lock_version_when_package_json_lists_it(
    *, name: str, section: str, spec: str, current: str
) -> None:
    found = load().find(name)

    assert (found.manager, found.dir, found.section, found.spec) == ("npm", "web", section, spec)
    assert found.current == current


@pytest.mark.parametrize(
    ("old", "new", "major"),
    [
        ("1.2.3", "2.0.0", True),
        ("0.28.1", "0.29.0", True),
        ("0.28.1", "0.28.2", False),
        ("4.15.1", "4.16.0", False),
        ("v1.9.0rc1", "1.10", False),
    ],
)
def test_flags_major_when_version_moves(*, old: str, new: str, major: bool) -> None:
    assert load().is_major(old, new) is major


@pytest.mark.usefixtures("repo")
@pytest.mark.parametrize(
    ("argv", "reason"),
    [
        (["--package", "bad name", "--to", "1.0.0", "--issue", "DEM-1"], "not a package name"),
        (["--package=-rf", "--to", "1.0.0", "--issue", "DEM-1"], "not a package name"),
        (["--package", "httpx", "--to", "1.0.0rc1", "--issue", "DEM-1"], "not a final release"),
        (["--package", "httpx", "--to", "1.0.0.0.0", "--issue", "DEM-1"], "not a final release"),
        (["--package", "httpx", "--to", "1.0.0", "--issue", "DEM 1"], "not an issue id"),
    ],
)
def test_exits_two_when_package_or_version_is_malformed(
    capsys: pytest.CaptureFixture[str], *, argv: list[str], reason: str
) -> None:
    assert load().main(argv) == 2

    out, err = capsys.readouterr()
    assert out == ""
    assert err.startswith(f"bump.py: {reason}")


def test_exits_two_when_package_is_in_no_manifest_or_several_package_folders(
    repo: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    module = load()
    missing = ["--package", "nothere", "--to", "1.0.0", "--issue", "DEM-1"]
    assert module.main(missing) == 2
    assert capsys.readouterr().err == "bump.py: nothere is in no manifest\n"

    commit_file(repo, "app/package.json", json.dumps({"devDependencies": {"vite": "5.4.2"}}))
    twice = ["--package", "vite", "--to", "6.0.0", "--issue", "DEM-1"]
    assert module.main(twice) == 2
    assert capsys.readouterr().err == "bump.py: vite is in several package folders: app, web\n"


@pytest.mark.usefixtures("repo")
@pytest.mark.parametrize(
    ("package", "to", "reason"),
    [
        ("httpx", "0.28.1", "httpx is already at 0.28.1"),
        ("vite", "5.4.2", "vite is already at 5.4.2"),
        ("vite", "5.4.2.0", "vite is already at 5.4.2.0"),
        ("rich", "13.0.0", "rich is at 13.9.4, past 13.0.0"),
    ],
)
def test_exits_two_when_already_at_the_target_version(
    capsys: pytest.CaptureFixture[str], *, package: str, to: str, reason: str
) -> None:
    before = git(Path.cwd(), "rev-parse", "HEAD")

    assert load().main(["--package", package, "--to", to, "--issue", "DEM-1"]) == 2

    assert capsys.readouterr().err == f"bump.py: {reason}\n"
    assert git(Path.cwd(), "rev-parse", "HEAD") == before


@pytest.mark.parametrize(
    ("name", "text", "reason"),
    [
        ("pyproject.toml", "[project\nname = 'x'\n", "pyproject.toml is not TOML"),
        ("pyproject.toml", "# " + "x" * (1024 * 1024), "pyproject.toml is too large"),
        ("web/package.json", "{not json", "web/package.json is not JSON"),
        ("web/package-lock.json", "[]", "web/package-lock.json is not a JSON object"),
    ],
    # Short ids: the test id lands in PYTEST_CURRENT_TEST, which git's environment carries.
    ids=["not-toml", "too-large", "not-json", "not-an-object"],
)
def test_exits_two_when_a_manifest_is_unreadable(
    repo: Path, capsys: pytest.CaptureFixture[str], *, name: str, text: str, reason: str
) -> None:
    commit_file(repo, name, text)

    assert load().main(["--package", "vite", "--to", "6.0.0", "--issue", "DEM-1"]) == 2

    assert capsys.readouterr().err == f"bump.py: {reason}\n"
