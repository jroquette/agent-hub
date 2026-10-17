"""Bring a registered hub to the running release: pin it in ``hub.json``, then ``hub sync``.

The pin (``platform.version``) is rewritten in place, so the rest of ``hub.json`` keeps its
formatting; then this server's own ``hub sync`` (the running release) reapplies the templates and
writes ``hub.lock``. When the sync fails (a conflict, exit 3, or any other error) the old
``hub.json`` is put back, so the hub is left as it was. Nothing is committed: the changed files
stay in the hub's checkout for the owner to review in a hub PR.
"""

import json
import os
import re
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict

from agent_hub.api.run_launcher import own_hub_program

HUB_JSON: Final = "hub.json"
SYNC_TIMEOUT_SECONDS: Final = 120.0
GIT_TIMEOUT_SECONDS: Final = 10.0
MAX_OUTPUT_LINES: Final = 200
# The pin inside the ``platform`` object: no nested object comes before it there.
_PIN: Final = re.compile(r'("platform"\s*:\s*\{[^{}]*?"version"\s*:\s*")([^"\\]*)(")')

type Runner = Callable[[Sequence[str], Path], subprocess.CompletedProcess[str]]


class PlatformSyncResult(BaseModel):
    """What one platform sync did: the pin before and after, and ``hub sync``'s report."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    hub_id: str
    previous_version: str | None
    version: str
    ok: bool
    exit_code: int
    output: tuple[str, ...]
    changed_files: tuple[str, ...]


class PlatformSyncRequest(BaseModel):
    """The empty JSON body of the sync: a cross-site form cannot send one (S7)."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class PlatformSyncError(Exception):
    """``hub.json`` cannot be pinned (unreadable, not JSON, no ``platform`` object)."""


def _run(argv: Sequence[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AGENT_HUB_ROOT": str(cwd)}
    return subprocess.run(  # noqa: S603 -- our own hub or git, argv built here
        list(argv),
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=SYNC_TIMEOUT_SECONDS,
        check=False,
        stdin=subprocess.DEVNULL,
    )


def pinned_text(text: str, version: str) -> tuple[str | None, str]:
    """``hub.json``'s text with ``platform.version`` set to ``version``, and the old pin."""
    try:
        document = json.loads(text)
    except ValueError as error:
        raise PlatformSyncError("hub.json is not valid JSON") from error
    platform = document.get("platform") if isinstance(document, dict) else None
    if not isinstance(platform, dict):
        raise PlatformSyncError("hub.json has no platform object")
    previous = platform.get("version")
    previous = previous if isinstance(previous, str) else None
    replaced, count = _PIN.subn(lambda m: f"{m[1]}{version}{m[3]}", text, count=1)
    platform["version"] = version
    if count == 1 and json.loads(replaced) == document:
        return previous, replaced
    # The pin is not where a plain edit finds it: write the document again.
    return previous, json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def _write(path: Path, text: str) -> None:
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".hub.json.")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(text)
        Path(temporary).chmod(path.stat().st_mode & 0o777)
        Path(temporary).replace(path)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise


def _lines(*streams: str) -> tuple[str, ...]:
    lines = [line for stream in streams for line in stream.splitlines() if line.strip()]
    return tuple(lines[:MAX_OUTPUT_LINES])


def _changed_files(hub: Path, run: Runner) -> tuple[str, ...]:
    try:
        status = run(("git", "status", "--porcelain", "--untracked-files=all"), hub)
    except OSError, subprocess.TimeoutExpired:
        return ()
    if status.returncode != 0:
        return ()
    return tuple(line[3:] for line in status.stdout.splitlines() if len(line) > 3)


def sync_platform(
    hub_id: str,
    hub_path: str,
    *,
    running_version: str,
    run: Runner = _run,
    program: Sequence[str] | None = None,
) -> PlatformSyncResult:
    """Pin the hub at ``hub_path`` to ``running_version`` and run ``hub sync`` there."""
    hub = Path(hub_path)
    path = hub / HUB_JSON
    try:
        original = path.read_text(encoding="utf-8")
    except OSError as error:
        raise PlatformSyncError("hub.json cannot be read") from error
    previous, updated = pinned_text(original, running_version)
    dirty_before = set(_changed_files(hub, run))
    if updated != original:
        _write(path, updated)
    argv = (*(program or own_hub_program()), "sync")
    try:
        done = run(argv, hub)
        exit_code, output = done.returncode, _lines(done.stdout, done.stderr)
    except subprocess.TimeoutExpired:
        exit_code, output = 1, ("hub sync did not finish in time",)
    except OSError as error:
        exit_code, output = 1, (f"hub sync could not start: {error.strerror or error}",)
    ok = exit_code == 0
    if not ok and updated != original:
        _write(path, original)
    return PlatformSyncResult(
        hub_id=hub_id,
        previous_version=previous,
        version=running_version if ok else (previous or running_version),
        ok=ok,
        exit_code=exit_code,
        output=output,
        # Files already changed before the sync are the owner's, not this sync's.
        changed_files=(
            tuple(p for p in _changed_files(hub, run) if p not in dirty_before) if ok else ()
        ),
    )
