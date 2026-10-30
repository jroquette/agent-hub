"""The four readers of the release commit in ``hub.lock`` pick the same source (ADR 0054).

Each case is a ``hub.json`` (the demo pinned to ``VERSION``, with or without a
``platform.repository``) and a ``hub.lock`` (absent, written by ``hub sync``'s own builder, or
that lock hand-edited). The source each case must run is written in the table: the commit source
``<repository>@<commit>`` only when the lock's version and repository match ``hub.json`` and its
commit is 40 lowercase hex, else today's tag source ``<repository>@v<version>``. Four readers
must each run that source: the CLI (``read_hub_lock`` then ``kept_release``, what ``hub sync``
keeps); the ``hub`` shim (``sh hub brief``); the SessionStart hook (on ``hook_python``), whose
detached refresh runs ``hub brief --write-cache`` (ADR 0055) and is waited for until its lock
is free; and cloud setup's warm-up (on bash). The rendered ones run from one demo render with
``PATH`` holding only a test folder: a ``uvx`` that logs each call (``uvx <args>``) and answers, a
``python3`` link to ``hook_python``, and, for cloud setup only, a ``git`` that does nothing and
exits 0 (its access check passes; only the warm-up is read). The shim and the hook must make one
call at a commit and the resolve step then the call at a tag; cloud setup one warm-up; the hook
exits 0 with nothing on stderr (it fails open). Any refresh still running after a test is
killed (``no_process_left``).

The rendered readers check only the lock's ``platform_*`` fields, while the CLI validates the whole
lock: a lock whose other fields are invalid runs the commit in the shim, hook and cloud setup, and
``hub sync`` refuses it (no commit kept). That row names the CLI's own source. The second test
holds what only the rendered readers decide, the kind and size of the file: a link, a FIFO or a
lock over 1 MiB keeps the tag, a lock of exactly 1 MiB is read (``hub sync`` has its own file
checks and refuses a lock that is not a regular file).
"""

import fcntl
import json
import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

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
# The SessionStart refresh's lock (ADR 0055), and how long a case waits for the refresh to end.
REFRESH_LOCK = ".hub-cache/refresh.lock"
REFRESH_WAIT = 10.0
# The refresh's brief: it writes the cache instead of printing for the hook.
REFRESH_BRIEF = "brief --write-cache"

pytestmark = pytest.mark.usefixtures("no_process_left")

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


def bad_files_entry(lock: dict[str, Any]) -> str:
    lock["files"]["AGENTS.md"] = 123
    return as_written(lock)


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
    # The CLI's source when it differs from the rendered readers' (None: the same).
    cli_source: str | None = None


DEFAULT_TAG_SOURCE = f"{DEFAULT_REPOSITORY}@v{VERSION}{SUBDIRECTORY}"
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
    LockCase(
        "files-entry-invalid",
        None,
        edit=bad_files_entry,
        source=DEFAULT_COMMIT_SOURCE,
        cli_source=DEFAULT_TAG_SOURCE,
    ),
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


def refresh_ended(hub: Path) -> bool:
    """True once the refresh lock exists and can be taken: the refresh that held it has ended."""
    end = time.monotonic() + REFRESH_WAIT
    lock_path = hub / REFRESH_LOCK
    while not lock_path.exists():
        if time.monotonic() > end:
            return False
        time.sleep(0.01)
    with lock_path.open("r+") as lock:
        while True:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                if time.monotonic() > end:
                    return False
                time.sleep(0.01)
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
                return True


def hook_verdict(lines: list[str], expected: list[str], completed: Any) -> str:
    """The hook must also fail open: exit 0, nothing on stderr, whatever the lock holds."""
    if (completed.returncode, completed.stderr) != (0, b""):
        return f"exit {completed.returncode}: {completed.stderr!r}"
    return run_verdict(lines, expected, completed)


@dataclass(frozen=True)
class RenderedReaders:
    """The three rendered readers of one hub, each run with the fake tools on ``PATH``."""

    hub: Path
    log: Path
    bin_dir: Path
    cloud_bin: Path
    elsewhere: Path
    home: Path
    hook_python: str
    run_hook_file: Callable[..., Any]

    def verdicts(self, source: str) -> dict[str, str]:
        """Each reader's verdict on running ``source`` for the hub's current ``hub.lock``."""
        shim = run_tool(
            [which("sh"), str(self.hub / "hub"), "brief"],
            cwd=self.elsewhere,
            env={"PATH": str(self.bin_dir)},
        )
        given = {"shim": run_verdict(logged(self.log), calls_of(source, "brief"), shim)}
        event = json.dumps(
            {"session_id": "abcdef123456", "cwd": str(self.hub), "source": "startup"}
        )
        hook = self.run_hook_file(
            self.hook_python,
            self.hub / HOOK,
            stdin=event.encode(),
            cwd=self.hub.parent,
            env={"PATH": str(self.bin_dir), "HOME": str(self.home)},
        )
        # No brief cache: the hook starts its refresh, whose calls are read once it has ended.
        if not refresh_ended(self.hub):
            given["hook"] = "the refresh did not end"
        else:
            given["hook"] = hook_verdict(logged(self.log), calls_of(source, REFRESH_BRIEF), hook)
        cloud = run_tool(
            [which("bash"), str(self.hub / CLOUD_SETUP)],
            cwd=self.elsewhere,
            env={"PATH": str(self.cloud_bin), "HOME": str(self.home), "GIT_CONFIG_NOSYSTEM": "1"},
        )
        given["cloud setup"] = run_verdict(logged(self.log), calls_of(source, "--version"), cloud)
        return given


def rendered_readers(
    hub: Path, *, hook_python: str, run_hook_file: Callable[..., Any], tmp_path: Path
) -> RenderedReaders:
    log = tmp_path / "uvx.log"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    home = tmp_path / "home"
    home.mkdir()
    return RenderedReaders(
        hub=hub,
        log=log,
        bin_dir=install(tmp_path / "bin", log=log, python=hook_python, git=False),
        cloud_bin=install(tmp_path / "cloud-bin", log=log, python=hook_python, git=True),
        elsewhere=elsewhere,
        home=home,
        hook_python=hook_python,
        run_hook_file=run_hook_file,
    )


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
    readers = rendered_readers(
        hub, hook_python=hook_python, run_hook_file=run_hook_file, tmp_path=tmp_path
    )
    verdicts: dict[str, dict[str, str]] = {"cli": {}, "shim": {}, "hook": {}, "cloud setup": {}}
    for case in CASES:
        document = hub_document(case)
        (hub / "hub.json").write_text(json.dumps(document), encoding="utf-8")
        text = lock_text(case, rendered)
        (hub / "hub.lock").unlink(missing_ok=True)
        if text is not None:
            (hub / "hub.lock").write_text(text, encoding="utf-8")
        assert (hub / "hub.lock").exists() == (text is not None)

        verdicts["cli"][case.name] = cli_verdict(text, document, case.cli_source or case.source)
        for reader, given in readers.verdicts(case.source).items():
            verdicts[reader][case.name] = given

    expected = {case.name: AGREES for case in CASES}
    assert len(expected) == len(CASES) == 13
    # Both paths are in the table, so a reader that always picks one cannot pass.
    assert {"@v" in case.source for case in CASES} == {True, False}
    for reader, given in verdicts.items():
        assert given == expected, reader


# The largest hub.lock the rendered readers read (1 MiB).
LOCK_CAP = 1024 * 1024


def padded(text: str, size: int) -> str:
    """``text`` (a JSON object) as valid JSON of exactly ``size`` bytes: spaces before the brace."""
    stripped = text.rstrip()
    result = stripped[:-1] + " " * (size - len(stripped.encode())) + "}"
    assert len(result.encode()) == size
    json.loads(result)
    return result


def place_link(hub: Path, text: str) -> None:
    target = hub.parent / "elsewhere.lock"
    target.write_text(text, encoding="utf-8")
    (hub / "hub.lock").symlink_to(target)


def place_fifo(hub: Path, _text: str) -> None:
    # A FIFO with no writer: a blocking read of it would hang until the timeout.
    os.mkfifo(hub / "hub.lock")


def place_over_cap(hub: Path, text: str) -> None:
    (hub / "hub.lock").write_text(padded(text, LOCK_CAP + 1), encoding="utf-8")


def place_at_cap(hub: Path, text: str) -> None:
    (hub / "hub.lock").write_text(padded(text, LOCK_CAP), encoding="utf-8")


FILE_CASES: list[tuple[str, Callable[[Path, str], None], str]] = [
    ("link", place_link, DEFAULT_TAG_SOURCE),
    ("fifo", place_fifo, DEFAULT_TAG_SOURCE),
    ("over-cap", place_over_cap, DEFAULT_TAG_SOURCE),
    ("at-cap", place_at_cap, DEFAULT_COMMIT_SOURCE),
]


def test_agrees_on_source_when_rendered_readers_read_lock_file_kind(
    *,
    rendered_hub: Callable[[HubConfig], Path],
    demo_config: HubConfig,
    hook_python: str,
    run_hook_file: Callable[..., Any],
    tmp_path: Path,
) -> None:
    hub = rendered_hub(demo_config).resolve()
    rendered = render_hub(demo_config)
    readers = rendered_readers(
        hub, hook_python=hook_python, run_hook_file=run_hook_file, tmp_path=tmp_path
    )
    matching = LockCase("commit-matches", None, source=DEFAULT_COMMIT_SOURCE)
    (hub / "hub.json").write_text(json.dumps(hub_document(matching)), encoding="utf-8")
    text = lock_text(matching, rendered)
    assert text is not None
    verdicts: dict[str, dict[str, str]] = {"shim": {}, "hook": {}, "cloud setup": {}}
    for name, place, source in FILE_CASES:
        (hub / "hub.lock").unlink(missing_ok=True)
        place(hub, text)

        for reader, given in readers.verdicts(source).items():
            verdicts[reader][name] = given

    expected = {name: AGREES for name, _, _ in FILE_CASES}
    assert len(expected) == len(FILE_CASES) == 4
    assert {"@v" in source for _, _, source in FILE_CASES} == {True, False}
    for reader, given in verdicts.items():
        assert given == expected, reader
