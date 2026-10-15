"""The doctor of a registered hub, run in process as ``hub doctor`` runs it (D22), and its cache.

``run_doctor`` follows ``hub doctor``'s pipeline with every rule selected: ``hub.json`` read
once into its config (a pin other than the running release is a ``platform.version`` finding
and nothing else runs; an unusable file is ``config.schema`` findings), the hub's
``hub.local.json``, then the snapshot the selected rules read. The findings equal
``hub doctor --json`` run in that hub. ``DoctorCache`` keeps one run per hub for
``DOCTOR_TTL``, or until a watched file's modification time changes (``hub.json``,
``hub.lock``, ``hub.local.json``, every path the run looked at, and the ``workflows/`` folders
above them, whose times change when a workflow file is added or removed).
"""

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from agent_hub.core.doctor.config_rules import config_state
from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import Selection, run_rules, select_rules
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.local_config import LOCAL_FILE
from agent_hub.core.hub_config.problems import ROOT_PATH, ConfigProblem
from agent_hub.core.hub_files.hub_lock import HUB_LOCK_PATH
from agent_hub.core.hubs.hub_registry import HubFileReader, UnreadHubFile
from agent_hub.core.workflows.catalog import HUB_WORKFLOWS_FOLDER

DOCTOR_TTL: Final = timedelta(minutes=15)
HUB_JSON: Final = "hub.json"
# A failed config reads no file: only the config rules run, and they read hub.json alone.
_NO_FILES: Final = HubFiles(entries={}, listed=(), problem=None, paths_read=True)


@dataclass(frozen=True, kw_only=True, slots=True)
class DoctorRun:
    """The findings of one run and the hub-relative paths whose change makes them stale."""

    findings: tuple[Finding, ...]
    watched: tuple[str, ...]


def run_doctor(reader: HubFileReader, hub_path: str, *, running_version: str) -> DoctorRun:
    """Every rule of this release on the hub at ``hub_path``."""
    read = reader.read_hub_json(hub_path)
    content = (ConfigProblem(ROOT_PATH, read.message),) if isinstance(read, UnreadHubFile) else read
    config = config_state(content, running_version=running_version)
    local = reader.read_local(hub_path)
    selection = select_rules(REGISTRY, config=config, only=())
    if not isinstance(selection, Selection):
        # No ``--only`` is given, so nothing can be refused: a refusal here is a bug.
        raise TypeError(selection.message)
    snapshot = DoctorSnapshot(
        config=config,
        running_version=running_version,
        hub=_NO_FILES,
        lock=None,
        base_hooks=None,
        repos=(),
        local=local,
    )
    if not isinstance(config, ConfigFailure):
        snapshot = reader.doctor_snapshot(
            hub_path,
            config=config,
            running_version=running_version,
            selection=selection,
            local=local,
        )
    looked_at = {*snapshot.hub.entries, *snapshot.hub.listed}
    folders = {HUB_WORKFLOWS_FOLDER, *_workflow_folders(looked_at)}
    watched = tuple(sorted({HUB_JSON, HUB_LOCK_PATH, LOCAL_FILE, *looked_at, *folders}))
    return DoctorRun(findings=run_rules(selection, snapshot), watched=watched)


def _workflow_folders(paths: Iterable[str]) -> set[str]:
    """The folders under ``workflows/`` that hold ``paths``: ``workflows.valid`` reads them all."""
    found: set[str] = set()
    for path in paths:
        parts = path.split("/")
        if parts[0] == HUB_WORKFLOWS_FOLDER:
            found.update("/".join(parts[:end]) for end in range(1, len(parts)))
    return found


@dataclass(frozen=True, kw_only=True, slots=True)
class _Cached:
    run: DoctorRun
    at: datetime
    times: tuple[int | None, ...]


class DoctorCache:
    """One doctor run per hub, reused while fresh."""

    def __init__(
        self,
        reader: HubFileReader,
        *,
        running_version: str,
        clock: Callable[[], datetime],
        ttl: timedelta = DOCTOR_TTL,
    ) -> None:
        self._reader = reader
        self._running = running_version
        self._clock = clock
        self._ttl = ttl
        self._runs: dict[str, _Cached] = {}
        self._lock = threading.Lock()

    def findings(self, hub_path: str) -> tuple[Finding, ...]:
        """The hub's findings, from the cache when fresh."""
        with self._lock:
            cached = self._runs.get(hub_path)
            now = self._clock()
            if cached is not None and self._is_fresh(hub_path, cached, now=now):
                return cached.run.findings
            run = run_doctor(self._reader, hub_path, running_version=self._running)
            times = self._reader.modified_times(hub_path, run.watched)
            self._runs[hub_path] = _Cached(run=run, at=now, times=times)
            return run.findings

    def _is_fresh(self, hub_path: str, cached: _Cached, *, now: datetime) -> bool:
        if now - cached.at >= self._ttl:
            return False
        return self._reader.modified_times(hub_path, cached.run.watched) == cached.times
