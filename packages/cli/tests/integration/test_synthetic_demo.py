"""The synthetic ``demo`` inits (Q-12): the lock on disk, modes, identical trees and the golden.

A sync of a fresh ``demo`` init prints ``up to date`` and writes nothing (AGH-14 AC-14.7), and a
pending ``demo`` hub synced in process and as a child writes identical trees (AC-14.16). A doctor
run on a fresh ``demo`` init, plain or committed, finds and writes nothing (AGH-11 AC-11.16).
``hub sync --adopt`` on an unadopted ``demo`` hub with hand edits lists the two changed managed
files, saves the rest, writes nothing on a rerun, and ends at a fresh init's lock once both are
restored (AGH-16 AC-16.4); the same hub adopted in process and as a child writes identical trees
(AC-16.10). The rendered CI's golden step, run in a fresh ``demo`` init through its ``./hub`` and
a ``uvx`` that resolves to the running CLI, exits 0 (AC-16.11).

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
from typer.testing import CliRunner, Result

from agent_hub.cli import adopt_command, sync_steps
from agent_hub.cli.adopt_report import ADOPT_LISTED_WAY_OUT
from agent_hub.cli.main import app
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import build_hub_lock, lock_bytes
from agent_hub.core.hub_files.rendered_file import Ownership
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.json_form import dump_json
from agent_hub.generator.render_hub import render_hub

# Found before any test puts a fake git first on PATH.
REAL_GIT = shutil.which("git")
# The conftest's golden compare, tree digest, child environment, doctor run and read filters
# (tests cannot import a conftest in importlib mode).
type LockGolden = Callable[..., None]
type TreeDigest = Callable[[Path], dict[str, Any]]
type ChildEnv = Callable[[Mapping[str, str]], dict[str, str]]
type SyncRunner = Callable[..., Result]
type DoctorRunner = Callable[..., Result]
type PathFilter = Callable[[list[Any], Path], set[str]]
type Ancestors = Callable[..., set[str]]
type CheckoutFactory = Callable[[str], Path]
# The conftest's ``Ac4Hub``: ``make``, ``guard``, ``now``, ``schema`` and ``listing``.
type Ac4Hub = Any
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
            "LC_ALL": "C",
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


def test_writes_nothing_when_sync_runs_on_fresh_init(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    *,
    demo_config_file: Path,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
) -> None:
    root = init_demo(demo_config_file, tmp_path / "hub")
    before = tree_digest(root)
    lock_mtime = (root / "hub.lock").stat().st_mtime_ns
    applied: list[object] = []
    # Plan erratum E4: with nothing pending the adapter is not called at all.
    monkeypatch.setattr(sync_steps, "apply_sync", lambda *args, **kwargs: applied.append(args))
    adapter_calls.clear()

    for _ in range(2):
        result = run_sync(root)

        assert (result.exit_code, result.stdout, result.stderr) == (0, "up to date\n", "")
    assert adapter_calls == []
    assert applied == []
    assert tree_digest(root) == before
    assert (root / "hub.lock").stat().st_mtime_ns == lock_mtime


GOLDEN_STEP_HEAD = "      - name: Golden (hub sync --check)\n        run: "


def golden_step_command(ci: str) -> str:
    """The one-line ``run:`` of the rendered workflow's golden step."""
    assert ci.count(GOLDEN_STEP_HEAD) == 1, ci
    return ci[ci.index(GOLDEN_STEP_HEAD) + len(GOLDEN_STEP_HEAD) :].split("\n", 1)[0]


def test_passes_golden_step_when_hub_fresh(
    tmp_path: Path, demo_hub: Path, *, fake_uvx_bin: Path, tree_digest: TreeDigest
) -> None:
    command = golden_step_command((demo_hub / ".github" / "workflows" / "ci.yml").read_text())
    assert command == "./hub sync --check"
    before = tree_digest(demo_hub)
    python_dir = Path(sys.executable).parent
    env = {
        "PATH": os.pathsep.join([str(fake_uvx_bin), str(python_dir), os.defpath]),
        "HOME": str(tmp_path / "home"),
        "LC_ALL": "C",
    }

    # As the runner runs a step: the workflow's shell, from the checkout's root.
    completed = subprocess.run(  # noqa: S603 - absolute sh, the rendered step, a tmp_path folder
        ["/bin/sh", "-c", command],
        cwd=demo_hub,
        env=env,
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT,
    )

    assert (completed.returncode, completed.stdout, completed.stderr) == (
        0,
        "up to date\n",
        "",
    ), completed.stderr
    assert tree_digest(demo_hub) == before


def test_finds_nothing_when_doctor_runs_on_fresh_init(
    tmp_path: Path,
    demo_hub: Path,
    demo_hub_template: Path,
    *,
    monkeypatch: pytest.MonkeyPatch,
    run_doctor: DoctorRunner,
    tree_digest: TreeDigest,
    path_reads: list[Any],
    reads_in: PathFilter,
    ancestors: Ancestors,
    under: PathFilter,
) -> None:
    # DEMO's one repo, a folder next to the hubs: a non-git checkout holding only an empty
    # AGENTS.md gives no finding (plan E3a).
    (tmp_path / "demo-api").mkdir()
    (tmp_path / "demo-api" / "AGENTS.md").write_bytes(b"")
    committed = tmp_path / "committed"
    shutil.copytree(demo_hub_template, committed, symlinks=True)
    home = tmp_path / "git-home"
    home.mkdir()
    author = ["-c", "user.name=Jane Doe", "-c", "user.email=jane@example.com"]
    git(["-c", "init.defaultBranch=main", "init", "-q"], cwd=committed, home=home)
    git(["add", "-A"], cwd=committed, home=home)
    git(
        [*author, "-c", "commit.gpgsign=false", "commit", "-q", "-m", "init"],
        cwd=committed,
        home=home,
    )
    assert git(["status", "--porcelain"], cwd=committed, home=home) == ""
    # Any git a later rule runs reads the test's config only, never the developer's.
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    for root in (demo_hub, committed):
        real_root = os.path.realpath(root)
        before = tree_digest(tmp_path)
        path_reads.clear()

        result = run_doctor(root)

        read = reads_in(path_reads, tmp_path)
        assert (result.exit_code, result.stdout, result.stderr) == (
            0,
            "0 errors, 0 warnings, 0 infos\n",
            "",
        ), root.name
        # A walk goes down from a folder it opened by name, one entry name at a time.
        walked = {path for path in read if path.startswith("<fd")}
        assert all(
            "/" not in name and name not in {".", ".."}
            for name in (path.partition(">/")[2] for path in walked)
        ), walked
        allowed = (
            ancestors(real_root, up_to=tmp_path)
            | under(path_reads, root)
            | under(path_reads, tmp_path / "demo-api")
        )
        assert read - walked <= allowed, root.name
        assert tree_digest(tmp_path) == before, root.name


def test_counts_info_when_demo_checkout_missing(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, demo_checkout: CheckoutFactory
) -> None:
    # Both checkouts are synthetic git repos with a committed README.md and AGENTS.md (AC-11.29).
    demo_checkout("demo-api")
    web = demo_checkout("demo-web")

    clean = run_doctor(demo_two_repo_hub)
    shutil.rmtree(web)
    missing = run_doctor(demo_two_repo_hub)

    assert (clean.exit_code, clean.stdout.splitlines()[-1:], clean.stderr) == (
        0,
        ["0 errors, 0 warnings, 0 infos"],
        "",
    )
    assert (missing.exit_code, missing.stdout.splitlines()[-1:], missing.stderr) == (
        0,
        ["0 errors, 0 warnings, 1 info"],
        "",
    )


APP_REPO_AGENTS = "docs/app-repo-AGENTS.md"


def test_finds_nothing_when_app_repo_agents_copied_to_checkouts(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, demo_checkout: CheckoutFactory
) -> None:
    # Each repo's AGENTS.md is the hub's starter as copied, slots unfilled (AC-76.11).
    starter = (demo_two_repo_hub / APP_REPO_AGENTS).read_bytes()
    for name in ("demo-api", "demo-web"):
        (demo_checkout(name) / "AGENTS.md").write_bytes(starter)

    result = run_doctor(demo_two_repo_hub)

    assert (result.exit_code, result.stdout, result.stderr) == (
        0,
        "0 errors, 0 warnings, 0 infos\n",
        "",
    )


def repo_agents_warning(name: str) -> str:
    return (
        f"warning repos.agents ../{name}: no AGENTS.md at the repo root (hub agent loads none for"
        f" it) Fix: copy {APP_REPO_AGENTS} to ../{name}/AGENTS.md and fill it in;"
        " check_fast: make check-fast, check: make check"
    )


def test_warns_once_per_repo_when_app_repo_agents_absent(
    demo_two_repo_hub: Path, run_doctor: DoctorRunner, demo_checkout: CheckoutFactory
) -> None:
    # The committed AGENTS.md deleted from the work tree is not listed, so it does not count
    # (plan E5).
    for name in ("demo-api", "demo-web"):
        (demo_checkout(name) / "AGENTS.md").unlink()

    result = run_doctor(demo_two_repo_hub)

    assert (result.exit_code, result.stdout.splitlines(), result.stderr) == (
        0,
        [
            repo_agents_warning("demo-api"),
            repo_agents_warning("demo-web"),
            "0 errors, 2 warnings, 0 infos",
        ],
        "",
    )


MAKEFILE_LINE = b"local: ; @true\n"
AGENTS_LINE = b"- A rule the project wrote here.\n"


def appended_diff(render: bytes, *, path: str, line: bytes) -> list[str]:
    """Spec Q-4's diff of ``path`` when the project appended ``line`` to its render."""
    lines = render.decode().splitlines()
    start = len(lines) - 2
    return [
        f"--- {path} (on disk)",
        f"+++ {path} (render)",
        f"@@ -{start},4 +{start},3 @@",
        *(f" {kept}" for kept in lines[-3:]),
        f"-{line.decode().removesuffix(chr(10))}",
    ]


@pytest.mark.parametrize("edited", [["Makefile"], ["Makefile", "AGENTS.md"]], ids=["one", "two"])
def test_exits_conflict_when_managed_file_edited(
    demo_hub: Path,
    run_sync: SyncRunner,
    *,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
    edited: list[str],
) -> None:
    appended = {"Makefile": MAKEFILE_LINE, "AGENTS.md": AGENTS_LINE}
    renders = {path: (demo_hub / path).read_bytes() for path in edited}
    for path in edited:
        with (demo_hub / path).open("ab") as file:
            file.write(appended[path])
    before = tree_digest(demo_hub)
    adapter_calls.clear()
    # One report per path, in path order, then ADR 0009's way out.
    expected = [
        line
        for path in sorted(edited)
        for line in appended_diff(renders[path], path=path, line=appended[path])
    ]
    expected.append(
        "move the change to an extension file (hub.json, a *.project.* file, Makefile.project),"
        " restore or delete the file, then re-run hub sync"
    )

    for args in [(), ("--check",)]:
        result = run_sync(demo_hub, *args)

        assert (result.exit_code, result.stdout) == (3, ""), result.output
        assert result.stderr.splitlines() == expected
    assert adapter_calls == []
    assert tree_digest(demo_hub) == before


def test_prints_up_to_date_when_sync_reruns(
    tmp_path: Path,
    *,
    demo_config_file: Path,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
) -> None:
    root = init_demo(demo_config_file, tmp_path / "hub")
    fresh = tree_digest(root)
    (root / "AGENTS.md").unlink()
    lock = json.loads((root / "hub.lock").read_bytes())
    lock["platform_version"] = "0.0.1"
    (root / "hub.lock").write_bytes(dump_json(lock))

    applied = run_sync(root)

    assert (applied.exit_code, applied.stderr) == (0, ""), applied.output
    assert applied.stdout == "restored AGENTS.md\nupdated hub.lock\n"
    assert tree_digest(root) == fresh
    lock_mtime = (root / "hub.lock").stat().st_mtime_ns
    adapter_calls.clear()
    rerun = run_sync(root)
    assert (rerun.exit_code, rerun.stdout, rerun.stderr) == (0, "up to date\n", "")
    assert adapter_calls == []
    assert tree_digest(root) == fresh
    assert (root / "hub.lock").stat().st_mtime_ns == lock_mtime


OLDER_RENDER = b"# rendered by an older release\n"


def make_all_pending(root: Path) -> None:
    """The pending-changes cases at once: restore, create, update, delete and a lock header."""
    lock = json.loads((root / "hub.lock").read_bytes())
    (root / "AGENTS.md").unlink()
    (root / "CLAUDE.md").unlink()
    del lock["files"]["CLAUDE.md"]
    (root / "Makefile").write_bytes(OLDER_RENDER)
    older = {"executable": False, "sha256": hashlib.sha256(OLDER_RENDER).hexdigest()}
    lock["files"]["Makefile"].update(older)
    (root / "old").mkdir()
    (root / "old" / "file.md").write_bytes(OLDER_RENDER)
    lock["files"]["old/file.md"] = {"ownership": "managed", **older}
    lock["platform_version"] = "0.0.1"
    (root / "hub.lock").write_bytes(dump_json(lock))


def test_writes_identical_trees_when_sync_runs_twice(
    tmp_path: Path,
    demo_hub: Path,
    *,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    child_env: ChildEnv,
    set_umask: Callable[[int], None],
    lock_golden: LockGolden,
    no_git_path: Path,
) -> None:
    make_all_pending(demo_hub)
    child_root = tmp_path / "child"
    shutil.copytree(demo_hub, child_root, symlinks=True)
    # A umask other than the child's, whatever the developer's shell uses.
    set_umask(0o022)
    env = child_env(
        {
            **os.environ,
            "PATH": str(no_git_path),
            "HOME": str(tmp_path / "child-home"),
            "PYTHONHASHSEED": CHILD_HASH_SEED,
            "TZ": CHILD_TZ,
            "LC_ALL": "C",
        }
    )

    in_process = run_sync(demo_hub)
    child = subprocess.run(  # noqa: S603 - this interpreter, fixed code, a tmp_path folder
        [sys.executable, "-c", "from agent_hub.cli.main import app; app(prog_name='hub')", "sync"],
        cwd=child_root,
        env=env,
        umask=CHILD_UMASK,
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT,
    )

    assert (in_process.exit_code, in_process.stderr) == (0, ""), in_process.output
    assert (child.returncode, child.stderr) == (0, ""), child.stderr
    assert in_process.stdout.splitlines()[-1] == "updated hub.lock"
    assert child.stdout == in_process.stdout
    # The child's umask really differed: some permission bits of the written files differ.
    assert tree_digest(child_root) != tree_digest(demo_hub)
    # Nothing but those bits differs.
    assert shape(tree_digest(child_root)) == shape(tree_digest(demo_hub))
    lock = (demo_hub / "hub.lock").read_bytes()
    assert (child_root / "hub.lock").read_bytes() == lock
    # Compare only: a lock written by sync never rewrites the init golden, even in update mode.
    lock_golden(lock, update=False)


def test_lists_differences_when_adopt_runs(
    monkeypatch: pytest.MonkeyPatch,
    demo_hub: Path,
    demo_hub_template: Path,
    *,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    adapter_calls: list[tuple[str, str]],
    ac4: Ac4Hub,
) -> None:
    # AC-16.4's hub: unadopted, two managed files changed, a seeded one edited, one deleted.
    before = tree_digest(ac4.make(demo_hub))
    guard, now, schema = ac4.guard, ac4.now, ac4.schema
    fresh_lock = (demo_hub_template / "hub.lock").read_bytes()
    fresh_files: dict[str, Any] = json.loads(fresh_lock)["files"]
    listed = {"Makefile", guard}
    applied: list[object] = []
    real_apply = adopt_command.apply_or_exit

    def spy(*args: Any, **kwargs: Any) -> None:
        applied.append(args)
        real_apply(*args, **kwargs)

    monkeypatch.setattr(adopt_command, "apply_or_exit", spy)

    first = run_sync(demo_hub, "--adopt")

    assert first.exit_code == 3, first.output
    # Q-7, in path order: the deleted file is created, every other settled path recorded as it
    # is (hub.json is the project's), the two listed paths left out, the lock last.
    joined = sorted(set(fresh_files) - listed - {"hub.json"})
    expected = [f"{'created' if path == schema else 'recorded'} {path}" for path in joined]
    assert first.stdout.splitlines() == [*expected, "updated hub.lock"]
    # Q-2: one line per listed path, then the way out.
    assert first.stderr.splitlines() == [*ac4.listing, ADOPT_LISTED_WAY_OUT]
    after = tree_digest(demo_hub)
    for path in (*listed, now):
        assert after[path] == before[path], path
    assert after[schema] == tree_digest(demo_hub_template)[schema]
    lock = json.loads((demo_hub / "hub.lock").read_bytes())
    # Q-4: every settled path is in the lock, as a fresh init records it; the listed ones are not.
    assert lock["files"] == {
        path: entry for path, entry in fresh_files.items() if path not in listed
    }
    assert len(applied) == 1

    # A second run lists the same and writes nothing: no ``up to date`` over a listing (E29).
    applied.clear()
    adapter_calls.clear()
    settled = tree_digest(demo_hub)
    second = run_sync(demo_hub, "--adopt")

    assert (second.exit_code, second.stdout, second.stderr) == (3, "", first.stderr)
    assert adapter_calls == []
    assert applied == []
    assert tree_digest(demo_hub) == settled

    # Both restored: adopted, with the lock a fresh init writes.
    shutil.copy2(demo_hub_template / "Makefile", demo_hub / "Makefile")
    os.chmod(demo_hub / guard, stat.S_IMODE((demo_hub_template / guard).stat().st_mode))
    third = run_sync(demo_hub, "--adopt")

    assert (third.exit_code, third.stderr) == (0, ""), third.output
    assert third.stdout.splitlines() == [
        "recorded Makefile",
        f"recorded {guard}",
        "updated hub.lock",
    ]
    assert (demo_hub / "hub.lock").read_bytes() == fresh_lock
    # The whole tree is a fresh init's, but for the seeded file the project edited.
    adopted = tree_digest(demo_hub)
    template = tree_digest(demo_hub_template)
    assert adopted.pop(now) != template.pop(now)
    assert adopted == template


def test_writes_identical_trees_when_adopt_runs_twice(
    tmp_path: Path,
    demo_hub: Path,
    *,
    run_sync: SyncRunner,
    tree_digest: TreeDigest,
    child_env: ChildEnv,
    set_umask: Callable[[int], None],
    no_git_path: Path,
    ac4: Ac4Hub,
) -> None:
    # AC-16.4's hub, one listed file accepted: a created file, an updated one, a listing, the lock.
    ac4.make(demo_hub)
    child_root = tmp_path / "child"
    shutil.copytree(demo_hub, child_root, symlinks=True)
    args = ["sync", "--adopt", "--accept", "Makefile"]
    # A umask other than the child's, whatever the developer's shell uses.
    set_umask(0o022)
    env = child_env(
        {
            **os.environ,
            "PATH": str(no_git_path),
            "HOME": str(tmp_path / "child-home"),
            "PYTHONHASHSEED": CHILD_HASH_SEED,
            "TZ": CHILD_TZ,
            "LC_ALL": "C",
        }
    )

    in_process = run_sync(demo_hub, *args[1:])
    child = subprocess.run(  # noqa: S603 - this interpreter, fixed code, a tmp_path folder
        [sys.executable, "-c", "from agent_hub.cli.main import app; app(prog_name='hub')", *args],
        cwd=child_root,
        env=env,
        umask=CHILD_UMASK,
        capture_output=True,
        text=True,
        check=False,
        timeout=CHILD_TIMEOUT,
    )

    assert in_process.exit_code == 3, in_process.output
    assert child.returncode == 3, child.stderr
    assert f"created {ac4.schema}" in in_process.stdout.splitlines()
    assert "updated Makefile" in in_process.stdout.splitlines()
    assert in_process.stdout.splitlines()[-1] == "updated hub.lock"
    assert (child.stdout, child.stderr) == (in_process.stdout, in_process.stderr)
    # The child's umask really differed: some permission bits of the written files differ.
    assert tree_digest(child_root) != tree_digest(demo_hub)
    # Nothing but those bits differs.
    assert shape(tree_digest(child_root)) == shape(tree_digest(demo_hub))
    assert (child_root / "hub.lock").read_bytes() == (demo_hub / "hub.lock").read_bytes()
