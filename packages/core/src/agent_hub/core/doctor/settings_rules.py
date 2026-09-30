"""``settings.weakening``: the project's settings keep the harness (ADR 0009, spec Q-14).

A seeded ``*.project.json`` sibling may not set a key of ``REFUSED_KEYS`` (whatever its value),
and must be one JSON value ``hub sync`` can merge (E17: otherwise the rule cannot tell it sets no
refused key). ``.claude/settings.json`` is read as strictly (a file Claude Code may reject keeps
nothing), holds no refused key either (a synced file never does), and must hold each group of the
running release's base hooks block in ``hooks.<event>``, equal as in the merge (the same
``dump_json`` form, compared compactly), so ``true`` is not ``1``. A project group added next to
the base ones is its own.
"""

import json
from collections.abc import Iterable, Iterator, Mapping
from typing import Final, NamedTuple

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import RULE_MODULES, SETTINGS_WEAKENING_RULE, Severity
from agent_hub.core.hub_config.problems import ROOT_PATH, json_path
from agent_hub.core.hub_files.extension_inputs import REFUSED_KEYS
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

SETTINGS_PATH: Final = ".claude/settings.json"
SYNC_FIX: Final = "run hub sync"
PROJECT_FIX: Final = "fix or delete it: hub sync cannot merge it either"
REFUSED: Final = "refused: a project cannot set this key (it weakens the harness)"
CHANGED: Final = "a base hook group is missing or changed"
MISSING: Final = "missing; hub sync restores it"
NOT_REGULAR: Final = "not a regular file"


class _Unreadable(NamedTuple):
    """Why a settings file gives no JSON value: the finding's message."""

    message: str


def _settings_weakening(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    base = snapshot.base_hooks
    if base is None:
        return ()
    entries = snapshot.hub.entries
    return (
        *_project_findings(entries),
        *_settings_findings(
            entries.get(SETTINGS_PATH), base=base, all_read=snapshot.hub.paths_read
        ),
    )


def _loaded(entry: TreeEntry, *, strict: bool) -> JsonValue | _Unreadable:
    """The JSON value of a regular file read with its content, never through a link."""
    if not isinstance(entry, FileEntry) or entry.content is None:
        return _Unreadable(NOT_REGULAR)
    try:
        return load_json_bytes(entry.content, strict=strict)
    except InvalidJsonError as error:
        return _Unreadable(f"{ROOT_PATH}: {error.message}")


def _project_findings(entries: Mapping[str, TreeEntry]) -> Iterator[Finding]:
    for path, key_paths in REFUSED_KEYS.items():
        entry = entries.get(path)
        if entry is None:
            continue
        # Strict, as the merge reads a sibling: what it refuses, the rule cannot vouch for.
        document = _loaded(entry, strict=True)
        if isinstance(document, _Unreadable):
            yield SETTINGS_WEAKENING.finding(path=path, message=document.message, fix=PROJECT_FIX)
            continue
        for key_path in key_paths:
            if _holds(document, key_path):
                shown = json_path(key_path)
                yield SETTINGS_WEAKENING.finding(
                    path=path, message=f"{shown}: {REFUSED}", fix=f"remove {shown} from {path}"
                )


def _holds(value: JsonValue, key_path: tuple[str, ...]) -> bool:
    for key in key_path:
        if not isinstance(value, dict) or key not in value:
            return False
        value = value[key]
    return True


def _settings_findings(
    entry: TreeEntry | None, *, base: Mapping[str, JsonValue], all_read: bool
) -> tuple[Finding, ...]:
    if entry is None:
        # With a failed read, it may be the path the read failed on: the runner says so.
        return (_settings_finding(MISSING),) if all_read else ()
    document = _loaded(entry, strict=True)
    if isinstance(document, _Unreadable):
        return (_settings_finding(document.message),)
    refused = (
        _settings_finding(f"{json_path(key_path)}: {REFUSED}")
        for key_paths in REFUSED_KEYS.values()
        for key_path in key_paths
        if _holds(document, key_path)
    )
    hooks = document.get("hooks") if isinstance(document, dict) else None
    held = hooks if isinstance(hooks, dict) else {}
    changed = (
        _settings_finding(f"{json_path(('hooks', event))}: {CHANGED}")
        for event, groups in base.items()
        if not _keeps(groups, held.get(event))
    )
    return (*refused, *changed)


def _settings_finding(message: str) -> Finding:
    return SETTINGS_WEAKENING.finding(path=SETTINGS_PATH, message=message, fix=SYNC_FIX)


def _keeps(base_groups: JsonValue, groups: JsonValue) -> bool:
    """Whether ``groups`` (an event's array) holds each base group, compared by JSON form."""
    held = {_group_key(group) for group in groups} if isinstance(groups, list) else set()
    wanted = base_groups if isinstance(base_groups, list) else [base_groups]
    return all(_group_key(group) in held for group in wanted)


def _group_key(value: JsonValue) -> str:
    """The merge's equality (``dump_json``'s: ``true`` is not ``1``, ``1`` not ``1.0``), compact.

    ``dump_json``'s indent grows with the square of the depth; this key grows with the size.
    The strict parse refused NaN and infinities, and its nesting limit bounds what reaches here.
    """
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    )


SETTINGS_WEAKENING: Final = Rule(
    id=SETTINGS_WEAKENING_RULE,
    severity=Severity.ERROR,
    summary="settings.project.json sets no refused key, and settings.json keeps the base hooks",
    module=RULE_MODULES.get(SETTINGS_WEAKENING_RULE),
    reads=frozenset({Read.BASE_HOOKS}),
    check=_settings_weakening,
)
