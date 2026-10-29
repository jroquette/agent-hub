"""The four readers of the release commit in ``hub.lock`` pick the same source (AGH-606, ADR 0054).

Each case is a ``hub.json`` (the demo pinned to ``VERSION``, with or without a
``platform.repository``) and a ``hub.lock`` (absent, written by ``hub sync``'s own builder, or
that lock hand-edited). The source each case must run is written in the table: the commit source
``<repository>@<commit>`` only when the lock's version and repository match ``hub.json`` and its
commit is 40 lowercase hex, else today's tag source ``<repository>@v<version>``. Four readers
must each run that source: the CLI (``read_hub_lock`` then ``kept_release``, what ``hub sync``
keeps); the ``hub`` shim (``sh hub brief``); the SessionStart hook (on ``hook_python``); and
cloud setup's warm-up (on bash). The rendered ones run from one demo render with ``PATH``
holding only a test folder: a ``uvx`` that logs each call (``uvx <args>``) and answers, a
``python3`` link to ``hook_python``, and, for cloud setup only, a ``git`` that does nothing and
exits 0 (its access check passes; only the warm-up is read). The shim and the hook must make one
call at a commit and the resolve step then the call at a tag; cloud setup one warm-up.
"""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_files.hub_lock import HubLock, build_hub_lock, lock_bytes, read_hub_lock
from agent_hub.core.hub_files.release_commit import ReleaseCommit, kept_release
from agent_hub.core.hub_files.rendered_hub import RenderedHub
from agent_hub.core.testing.builders import a_hub_document
from agent_hub.core.testing.platform_repository_cases import CUSTOM_REPOSITORY
from agent_hub.generator.render_hub import render_hub

HOOK = "plugin/hub-workflow/hooks/session_start.py"
CLOUD_SETUP = "scripts/cloud-setup.sh"
TIMEOUT = 30
VERSION = "4.5.6"
COMMIT = "0123456789abcdef0123456789abcdef01234567"
DEFAULT_REPOSITORY = "git+https://github.com/jroquette/agent-hub"
OTHER_REPOSITORY = "git+https://github.com/acme/agent-hub"
SUBDIRECTORY = "#subdirectory=packages/agent-hub"
AGREES = "agrees"
FAKE_UVX = """#!/bin/sh
printf '%s\\n' "uvx $*" >> '{log}'
case " $* " in *" --version "*) echo "hub {version}";; *) echo "# Brief";; esac
exit 0
"""
FAKE_GIT = "#!/bin/sh\nexit 0\n"

type LockEdit = Callable[[dict[str, Any]], str | None]


def as_written(lock: dict[str, Any]) -> str:
    return json.dumps(lock, indent=2, sort_keys=True) + "\n"


def absent(_lock: dict[str, Any]) -> None:
    return None


def with_commit(commit: object) -> LockEdit:
    def edit(lock: dict[str, Any]) -> str:
        lock["platform_commit"] = commit
        return as_written(lock)

    return edit


def without_repository(lock: dict[str, Any]) -> str:
    del lock["platform_repository"]
    return as_written(lock)


def not_json(lock: dict[str, Any]) -> str:
    return as_written(lock) + "}\n"


@dataclass(frozen=True)
class LockCase:
    """A hub.json repository (None: left out), the lock sync wrote, an edit, the source to run."""

    name: str
    hub_repository: str | None
    lock_version: str = VERSION
    lock_repository: str | None = DEFAULT_REPOSITORY  # None: a lock with no commit
    edit: LockEdit = as_written
    # The source each reader must run, written out: a commit source or a tag source.
    source: str = f"{DEFAULT_REPOSITORY}@v{VERSION}{SUBDIRECTORY}"


DEFAULT_COMMIT_SOURCE = f"{DEFAULT_REPOSITORY}@{COMMIT}{SUBDIRECTORY}"
CUSTOM_TAG_SOURCE = f"{CUSTOM_REPOSITORY}@v{VERSION}{SUBDIRECTORY}"
CASES = [
    LockCase("commit-matches", None, source=DEFAULT_COMMIT_SOURCE),
    LockCase(
        "custom-commit-matches",
        CUSTOM_REPOSITORY,
        lock_repository=CUSTOM_REPOSITORY,
        source=f"{CUSTOM_REPOSITORY}@{COMMIT}{SUBDIRECTORY}",
    ),
    LockCase("no-commit", None, lock_repository=None),
    LockCase("absent", None, edit=absent),
    LockCase("version-differs", None, lock_version="4.5.5"),
    LockCase("repository-differs", None, lock_repository=OTHER_REPOSITORY),
    LockCase("custom-hub-default-lock", CUSTOM_REPOSITORY, source=CUSTOM_TAG_SOURCE),
    LockCase("commit-uppercase", None, edit=with_commit(COMMIT.upper())),
    LockCase("commit-short", None, edit=with_commit(COMMIT[:-1])),
    LockCase("commit-not-text", None, edit=with_commit(123)),
    LockCase("commit-without-repository", None, edit=without_repository),
    LockCase("not-json", None, edit=not_json),
]


def hub_document(case: LockCase) -> dict[str, Any]:
    document = a_hub_document()
    document["platform"]["version"] = VERSION
    if case.hub_repository is not None:
        document["platform"]["repository"] = case.hub_repository
    return document


def lock_text(case: LockCase, rendered: RenderedHub) -> str | None:
    """The lock ``hub sync``'s builder writes for the case's version and repository, then edited."""
    document = a_hub_document()
    document["platform"]["version"] = case.lock_version
    config = HubConfig.model_validate(document)
    release = (
        None
        if case.lock_repository is None
        else ReleaseCommit(commit=COMMIT, repository=case.lock_repository)
    )
    lock = json.loads(lock_bytes(build_hub_lock(rendered=rendered, config=config, release=release)))
    assert lock["platform_version"] == case.lock_version
    assert lock.get("platform_repository") == case.lock_repository
    return case.edit(lock)


def calls_of(source: str, last: str) -> list[str]:
    """A run's uvx calls: a warm-up (``--version``) is one call; a brief is one call at a commit,
    and the resolve step then the call at a tag."""
    call = f"uvx --from {source} hub {last}"
    if last != "--version" and "@v" in source:
        return [f"uvx --from {source} hub --version", call]
    return [call]


def logged(log: Path) -> list[str]:
    lines = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    log.unlink(missing_ok=True)
    return lines


def which(name: str) -> str:
    found = shutil.which(name)
    assert found is not None, f"the parity test runs {name}: install it"
    return os.path.realpath(found)


def run_tool(argv: list[str], *, cwd: Path, env: dict[str, str], stdin: str = "") -> Any:
    return subprocess.run(  # noqa: S603 - an absolute shell or interpreter, a rendered file
        argv,
        input=stdin,
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        env=env,
        timeout=TIMEOUT,
    )


def cli_verdict(text: str | None, document: dict[str, Any], expected: str) -> str:
    """The source ``hub sync`` keeps: the lock's commit when ``kept_release`` gives one."""
    config = HubConfig.model_validate(document)
    lock = None if text is None else read_hub_lock(text.encode())
    kept = kept_release(lock, config) if isinstance(lock, HubLock) else None
    tag = f"{config.platform.effective_repository}@v{VERSION}{SUBDIRECTORY}"
    source = tag if kept is None else f"{kept.repository}@{kept.commit}{SUBDIRECTORY}"
    return AGREES if source == expected else source


def run_verdict(lines: list[str], expected: list[str], completed: Any) -> str:
    if lines == expected:
        return AGREES
    return f"exit {completed.returncode}: {lines!r} {completed.stderr!r}"


def install(folder: Path, *, log: Path, python: str, git: bool) -> Path:
    folder.mkdir()
    (folder / "uvx").write_text(FAKE_UVX.format(log=log, version=VERSION), encoding="utf-8")
    (folder / "uvx").chmod(0o755)
    (folder / "python3").symlink_to(os.path.realpath(python))
    if git:
        (folder / "git").write_text(FAKE_GIT, encoding="utf-8")
        (folder / "git").chmod(0o755)
    return folder


def test_agrees_on_source_when_shim_hook_cloud_setup_and_cli_read_a_lock(
    *,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    hook_python: str,
    run_hook_file: Callable[..., Any],
    tmp_path: Path,
) -> None:
    hub = rendered_hub(demo_config).resolve()
    rendered = render_hub(demo_config)
    log = tmp_path / "uvx.log"
    bin_dir = install(tmp_path / "bin", log=log, python=hook_python, git=False)
    cloud_bin = install(tmp_path / "cloud-bin", log=log, python=hook_python, git=True)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    event = json.dumps({"session_id": "abcdef123456", "cwd": str(hub), "source": "startup"})
    verdicts: dict[str, dict[str, str]] = {"cli": {}, "shim": {}, "hook": {}, "cloud setup": {}}
    for case in CASES:
        document = hub_document(case)
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        text = lock_text(case, rendered)
        (hub / "hub.lock").unlink(missing_ok=True)
        if text is not None:
            (hub / "hub.lock").write_text(text, encoding="utf-8")
        assert (hub / "hub.lock").exists() == (text is not None)

        verdicts["cli"][case.name] = cli_verdict(text, document, case.source)
        shim = run_tool(
            [which("sh"), str(hub / "hub"), "brief"], cwd=elsewhere, env={"PATH": str(bin_dir)}
        )
        verdicts["shim"][case.name] = run_verdict(logged(log), calls_of(case.source, "brief"), shim)
        hook = run_hook_file(
            hook_python,
            hub / HOOK,
            stdin=event.encode(),
            cwd=hub.parent,
            env={"PATH": str(bin_dir), "HOME": str(home)},
        )
        verdicts["hook"][case.name] = run_verdict(logged(log), calls_of(case.source, "brief"), hook)
        cloud = run_tool(
            [which("bash"), str(hub / CLOUD_SETUP)],
            cwd=elsewhere,
            env={"PATH": str(cloud_bin), "HOME": str(home), "GIT_CONFIG_NOSYSTEM": "1"},
        )
        verdicts["cloud setup"][case.name] = run_verdict(
            logged(log), calls_of(case.source, "--version"), cloud
        )

    expected = {case.name: AGREES for case in CASES}
    assert len(expected) == len(CASES) == 12
    # Both paths are in the table, so a reader that always picks one cannot pass.
    assert {"@v" in case.source for case in CASES} == {True, False}
    for reader, given in verdicts.items():
        assert given == expected, reader
