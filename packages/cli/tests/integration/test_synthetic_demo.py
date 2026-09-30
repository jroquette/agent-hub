"""The synthetic ``demo`` inits (Q-12): the lock on disk, modes, identical trees and the golden.

``DEMO`` is ``demo_config_file`` (the example config without modules, pinned to the running CLI)
and ``DEMO_FLAGS`` is ``demo_flags``. The golden harness of ``demo.hub.lock`` is the conftest's
``lock_golden``; its self-tests set or clear ``GOLDEN_UPDATE`` and ``CI`` themselves.
"""

import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from agent_hub.cli.main import app
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.json_form import dump_json
from agent_hub.generator.render_hub import render_hub

# Found before any test puts a fake git first on PATH.
REAL_GIT = shutil.which("git")
# The conftest's golden compare, tree digest and child environment (tests cannot import a
# conftest in importlib mode).
type LockGolden = Callable[..., None]
type TreeDigest = Callable[[Path], dict[str, Any]]
type ChildEnv = Callable[[Mapping[str, str]], dict[str, str]]
# A subprocess init differs from the in-process one in all of these but its inputs.
CHILD_HASH_SEED = "123"
CHILD_TZ = "Pacific/Kiritimati"
CHILD_UMASK = 0o027
CHILD_TIMEOUT = 60
GIT_MODE_EXECUTABLE = "100755"
GIT_MODE_LINK = "120000"
GIT_MODE_FILE = "100644"


def run_init(args: Sequence[str]) -> None:
    result = CliRunner().invoke(app, ["init", *args])
    assert result.exit_code == 0, result.stderr


def init_demo(config_file: Path, root: Path) -> Path:
    """Run ``hub init --config DEMO --dir root`` in process; return ``root``."""
    run_init(["--config", str(config_file), "--dir", str(root)])
    return root


def demo_render(document: dict[str, Any]) -> RenderedHub:
    return render_hub(HubConfig.model_validate(document))


def shape(digest: Mapping[str, Any]) -> dict[str, tuple[str, bool, Any]]:
    """A tree digest without the umask: each path's type, ``S_IXUSR`` and bytes or target."""
    return {
        path: (kind, bool(mode & stat.S_IXUSR), value)
        for path, (kind, mode, value) in digest.items()
    }


def demo_lock(document: dict[str, Any]) -> bytes:
    """The ``hub.lock`` bytes of ``document``'s render, built in memory."""
    config = HubConfig.model_validate(document)
    return lock_bytes(build_hub_lock(rendered=render_hub(config), config=config))


def test_refuses_golden_update_when_ci_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    lock_golden: LockGolden,
    demo_document: dict[str, Any],
) -> None:
    golden = tmp_path / "golden" / "demo.hub.lock"
    golden.parent.mkdir()
    golden.write_bytes(b"stale\n")
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    monkeypatch.setenv("CI", "true")

    with pytest.raises(pytest.fail.Exception, match="GOLDEN_UPDATE=1 is refused when CI is set"):
        lock_golden(demo_lock(demo_document), golden=golden)

    assert golden.read_bytes() == b"stale\n"


def test_rewrites_golden_when_update_mode_set(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    lock_golden: LockGolden,
    demo_document: dict[str, Any],
) -> None:
    golden = tmp_path / "golden" / "init" / "demo.hub.lock"
    lock = demo_lock(demo_document)
    monkeypatch.delenv("CI", raising=False)
    monkeypatch.delenv("GOLDEN_UPDATE", raising=False)

    # Compare mode: a missing golden fails and is not created.
    with pytest.raises(pytest.fail.Exception, match="missing golden"):
        lock_golden(lock, golden=golden)
    assert not golden.exists()

    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    lock_golden(lock, golden=golden)

    written = golden.read_bytes()
    assert b'"platform_version": "<VERSION>"' in written
    assert b'"platform_version": "<VERSION>"' not in lock
    # Back in compare mode, the rewritten golden passes, and a changed lock byte fails.
    monkeypatch.delenv("GOLDEN_UPDATE")
    lock_golden(lock, golden=golden)
    changed = lock.replace(b'"ownership": "seeded"', b'"ownership": "managed"', 1)
    with pytest.raises(pytest.fail.Exception, match="differs"):
        lock_golden(changed, golden=golden)
    assert golden.read_bytes() == written


def test_matches_golden_when_demo_lock_normalized(
    tmp_path: Path, lock_golden: LockGolden, *, demo_config_file: Path
) -> None:
    root = init_demo(demo_config_file, tmp_path / "hub")

    lock_golden((root / "hub.lock").read_bytes())


def test_writes_lock_v1_when_demo_initialized(
    tmp_path: Path, demo_config_file: Path, *, demo_document: dict[str, Any]
) -> None:
    root = init_demo(demo_config_file, tmp_path / "hub")
    rendered = demo_render(demo_document)

    content = (root / "hub.lock").read_bytes()
    lock = json.loads(content)
    assert content == dump_json(lock)
    assert lock.keys() == {"lock_version", "platform_version", "schema_version", "modules", "files"}
    written = json.loads((root / "hub.json").read_bytes())
    assert (lock["lock_version"], lock["schema_version"], lock["modules"]) == (1, 1, [])
    assert lock["platform_version"] == demo_document["platform"]["version"]
    assert lock["platform_version"] == written["platform"]["version"]
    expected: dict[str, Any] = {}
    for file in rendered.files:
        on_disk = root / file.path
        if file.ownership is Ownership.MANAGED:
            expected[file.path] = {
                "executable": bool(on_disk.lstat().st_mode & stat.S_IXUSR),
                "ownership": "managed",
                "sha256": hashlib.sha256(on_disk.read_bytes()).hexdigest(),
            }
        else:
            expected[file.path] = {"ownership": "seeded"}
    for link in rendered.links:
        if link.ownership is Ownership.MANAGED:
            expected[link.path] = {"ownership": "managed", "symlink": os.readlink(root / link.path)}
        else:
            expected[link.path] = {"ownership": "seeded"}
    expected["hub.json"] = {"ownership": "seeded"}
    assert lock["files"] == expected
    assert not [
        path for path in lock["files"] if path in {"hub.lock", ".git"} or path.startswith(".git/")
    ]
    # Both kinds are there, so the entry forms above are all checked.
    kinds = {tuple(sorted(entry)) for entry in lock["files"].values()}
    assert kinds == {
        ("executable", "ownership", "sha256"),
        ("ownership", "symlink"),
        ("ownership",),
    }


@pytest.mark.parametrize("mask", [0o022, 0o077], ids=["umask-022", "umask-077"])
def test_sets_modes_when_demo_initialized_under_umask(
    tmp_path: Path,
    set_umask: Callable[[int], None],
    *,
    demo_config_file: Path,
    demo_document: dict[str, Any],
    mask: int,
) -> None:
    set_umask(mask)

    root = init_demo(demo_config_file, tmp_path / "hub")

    rendered = demo_render(demo_document)
    for file in rendered.files:
        status = (root / file.path).lstat()
        assert stat.S_ISREG(status.st_mode), file.path
        assert (root / file.path).read_bytes() == file.content, file.path
        assert bool(status.st_mode & stat.S_IXUSR) is file.executable, file.path
        expected = (0o777 if file.executable else 0o666) & ~mask
        assert stat.S_IMODE(status.st_mode) == expected, file.path
    for link in rendered.links:
        assert os.readlink(root / link.path) == link.target, link.path
    assert any(file.executable for file in rendered.files)
    assert any(not file.executable for file in rendered.files)


def git(args: Sequence[str], *, cwd: Path, home: Path) -> str:
    assert REAL_GIT is not None, "git is needed to index the demo"
    # The test's own HOME and no system config: the user's git config is never read.
    completed = subprocess.run(  # noqa: S603 - absolute git, fixed arguments, a tmp_path folder
        [REAL_GIT, *args],
        cwd=cwd,
        env={"HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"},
        capture_output=True,
        text=True,
        check=True,
        timeout=CHILD_TIMEOUT,
    )
    return completed.stdout


def test_indexes_modes_in_git_when_demo_added(
    tmp_path: Path, demo_config_file: Path, *, demo_document: dict[str, Any]
) -> None:
    root = init_demo(demo_config_file, tmp_path / "hub")
    home = tmp_path / "git-home"
    home.mkdir()

    git(["-c", "init.defaultBranch=main", "init", "-q"], cwd=root, home=home)
    git(["add", "-A"], cwd=root, home=home)
    listed = git(["ls-files", "-s", "-z"], cwd=root, home=home)

    indexed = {}
    for record in listed.split("\0")[:-1]:
        head, path = record.split("\t", 1)
        indexed[path] = head.split(" ")[0]
    rendered = demo_render(demo_document)
    expected = {
        **{
            file.path: GIT_MODE_EXECUTABLE if file.executable else GIT_MODE_FILE
            for file in rendered.files
        },
        **{link.path: GIT_MODE_LINK for link in rendered.links},
        "hub.json": GIT_MODE_FILE,
        "hub.lock": GIT_MODE_FILE,
    }
    assert indexed == expected


def test_writes_identical_trees_when_demo_initialized_twice(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    tree_digest: TreeDigest,
    child_env: ChildEnv,
    set_umask: Callable[[int], None],
    no_git_path: Path,
    demo_config_file: Path,
    demo_flags: list[str],
) -> None:
    # The parent runs as if in update mode under CI: the child must inherit neither.
    monkeypatch.setenv("GOLDEN_UPDATE", "1")
    monkeypatch.setenv("CI", "true")
    # A umask other than the child's, whatever the developer's shell uses.
    set_umask(0o022)
    in_process = init_demo(demo_config_file, tmp_path / "in-process")
    child_root = tmp_path / "child"
    env = child_env(
        {
            **os.environ,
            "PATH": str(no_git_path),
            "HOME": str(tmp_path / "child-home"),
            "PYTHONHASHSEED": CHILD_HASH_SEED,
            "TZ": CHILD_TZ,
        }
    )
    assert not {"GOLDEN_UPDATE", "CI"} & env.keys()

    child = subprocess.run(  # noqa: S603 - this interpreter, fixed code, tmp_path arguments
        [
            sys.executable,
            "-c",
            "from agent_hub.cli.main import app; app(prog_name='hub')",
            "init",
            "--config",
            str(demo_config_file),
            "--dir",
            str(child_root),
        ],
        cwd=tmp_path,
        env=env,
        umask=CHILD_UMASK,
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT,
    )

    assert (child.returncode, child.stderr) == (0, ""), child.stderr
    # Another umask: the permission bits differ, the S_IXUSR bits and everything else do not.
    assert tree_digest(child_root) != tree_digest(in_process)
    assert shape(tree_digest(child_root)) == shape(tree_digest(in_process))
    assert (child_root / "hub.lock").read_bytes() == (in_process / "hub.lock").read_bytes()
    monkeypatch.setenv("PATH", str(no_git_path))
    first, second = tmp_path / "flags-1", tmp_path / "flags-2"
    run_init([*demo_flags, "--dir", str(first)])
    run_init([*demo_flags, "--dir", str(second)])
    assert tree_digest(first) == tree_digest(second)
