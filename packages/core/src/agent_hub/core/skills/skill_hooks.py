"""A hub's hooks as catalog records (AGH-164, S3, S4, P7): from ``.claude/settings.json``,
``.claude/settings.project.json`` and each plugin's ``hooks/hooks.json``.

``settings.json`` is the effective list: an entry identical (event, matcher, command) to one of
``settings.project.json`` is project-owned, the others managed; a ``settings.project.json`` hook
missing from it is listed as ``not synced`` (and not active). A plugin's hooks are active only
when ``<plugin>@<marketplace>`` is ``true`` in ``enabledPlugins``. A file that is not read or not
the expected shape gives a one-line notice, never an exception; commands are inert text.
"""

import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from agent_hub.core.hubs.hub_registry import UnreadHubFile
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes
from agent_hub.core.skills.skill_sources import (
    BASE_PLUGIN,
    HOOKS_FILE,
    HOOKS_FOLDER,
    MAX_HOOKS,
    MAX_SKILL_JSON_BYTES,
    PLUGIN_FOLDER,
    PROJECT_SETTINGS_PATH,
    PROJECT_SETTINGS_SOURCE,
    SETTINGS_PATH,
    SETTINGS_SOURCE,
)
from agent_hub.core.skills.skill_view import ITEM_NAME, HookFacts, HookState, Origin

# What a hub JSON file read gave: its bytes, why it was not read, or None when not asked for.
type HubJsonContent = bytes | UnreadHubFile | None

_EVENT_NAME: Final = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_ITEM_NAME: Final = re.compile(ITEM_NAME)
_UNKNOWN_TYPE: Final = "unknown"


@dataclass(frozen=True, kw_only=True, slots=True)
class LoadedHubJson:
    """A hub JSON file as an object, or None (absent or not read); ``notice`` says, in one
    line naming the hub-relative path, why a present file was not read."""

    document: Mapping[str, JsonValue] | None = None
    notice: str | None = None


@dataclass(frozen=True, kw_only=True, slots=True)
class HookRecord:
    """One hook of the catalog: its ``source`` folder (``settings``, ``settings-project`` or the
    plugin folder), its name ``<source>-<event>-<n>`` lower-cased, the file it is in, its
    origin and what it configures."""

    source: str
    name: str
    source_path: str
    origin: Origin
    facts: HookFacts


@dataclass(frozen=True, kw_only=True, slots=True)
class HookFold:
    """Every hook in source order (``settings``, ``settings-project``, plugins by folder), the
    notices of the files not read, and ``truncated`` when more than ``MAX_HOOKS`` were seen."""

    records: tuple[HookRecord, ...] = ()
    notices: tuple[str, ...] = ()
    truncated: bool = False


@dataclass(frozen=True, slots=True)
class _Entry:
    event: str
    position: int
    matcher: str | None
    type: str
    command: str | None
    timeout: int | None

    @property
    def identity(self) -> tuple[str, str, str | None]:
        return (self.event, self.matcher or "", self.command)


def load_hub_json(path: str, content: HubJsonContent) -> LoadedHubJson:
    """``content`` (the bytes of the hub-relative ``path``) as a JSON object, at most
    ``MAX_SKILL_JSON_BYTES``; an absent file gives neither document nor notice."""
    if content is None or (isinstance(content, UnreadHubFile) and content.is_missing):
        return LoadedHubJson()
    if isinstance(content, UnreadHubFile):
        return LoadedHubJson(notice=f"{path}: not read ({content.message})")
    if len(content) > MAX_SKILL_JSON_BYTES:
        return LoadedHubJson(notice=f"{path}: not read (larger than {MAX_SKILL_JSON_BYTES} bytes)")
    try:
        document = load_json_bytes(content)
    except InvalidJsonError:
        return LoadedHubJson(notice=f"{path}: not read (not valid JSON)")
    except RecursionError:
        return LoadedHubJson(notice=f"{path}: not read (nested too deeply)")
    if not isinstance(document, dict):
        return LoadedHubJson(notice=f"{path}: not read (not a JSON object)")
    return LoadedHubJson(document=document)


class _EntryReader:
    def __init__(self, path: str) -> None:
        self.path = path
        self.problem: str | None = None

    def _refuse(self, reason: str) -> None:
        if self.problem is None:
            self.problem = f"{self.path}: some hooks not read ({reason})"

    def entries(self, document: Mapping[str, JsonValue]) -> Iterator[_Entry]:
        hooks = document.get("hooks")
        if hooks is None:
            return
        if not isinstance(hooks, dict):
            self._refuse('"hooks" is not an object')
            return
        for event, groups in hooks.items():
            if not _EVENT_NAME.fullmatch(event):
                self._refuse("an event name is not letters, digits, '-' or '_'")
            elif not isinstance(groups, list):
                self._refuse("an event's hooks are not a list")
            else:
                yield from self._event(event, groups)

    def _event(self, event: str, groups: list[JsonValue]) -> Iterator[_Entry]:
        position = 0
        for group in groups:
            hooks = group.get("hooks") if isinstance(group, dict) else None
            if not isinstance(group, dict) or not isinstance(hooks, list):
                self._refuse("a matcher group has no list of hooks")
                continue
            matcher = group.get("matcher")
            for hook in hooks:
                if not isinstance(hook, dict):
                    self._refuse("a hook is not an object")
                    continue
                position += 1
                yield _entry(
                    hook,
                    event=event,
                    position=position,
                    matcher=matcher if isinstance(matcher, str) else None,
                )


def _entry(hook: dict[str, JsonValue], *, event: str, position: int, matcher: str | None) -> _Entry:
    kind, command, timeout = hook.get("type"), hook.get("command"), hook.get("timeout")
    return _Entry(
        event=event,
        position=position,
        matcher=matcher,
        type=kind if isinstance(kind, str) else _UNKNOWN_TYPE,
        command=command if isinstance(command, str) else None,
        timeout=timeout if isinstance(timeout, int) and not isinstance(timeout, bool) else None,
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class _Source:
    name: str
    path: str
    content: HubJsonContent


class _Fold:
    def __init__(self) -> None:
        self.records: list[HookRecord] = []
        self.notices: list[str] = []
        self.truncated = False

    def entries(self, source: _Source) -> list[_Entry]:
        loaded = load_hub_json(source.path, source.content)
        if loaded.notice is not None:
            self.notices.append(loaded.notice)
        if loaded.document is None:
            return []
        reader = _EntryReader(source.path)
        entries = list(reader.entries(loaded.document))
        if reader.problem is not None:
            self.notices.append(reader.problem)
        return entries

    def add(  # noqa: PLR0913 - one record's facts, all keyword-only
        self,
        source: _Source,
        entry: _Entry,
        *,
        origin: Origin,
        active: bool,
        state: HookState = "synced",
    ) -> None:
        if len(self.records) == MAX_HOOKS:
            self.truncated = True
            return
        name = f"{source.name}-{entry.event}-{entry.position}".lower()
        if not _ITEM_NAME.fullmatch(name):
            self.notices.append(f"{source.path}: a hook is skipped (its name is too long)")
            return
        facts = HookFacts(
            event=entry.event,
            matcher=entry.matcher,
            type=entry.type,
            command=entry.command,
            timeout=entry.timeout,
            active=active,
            state=state,
        )
        self.records.append(
            HookRecord(
                source=source.name, name=name, source_path=source.path, origin=origin, facts=facts
            )
        )


def _plugin_path(plugin: str) -> str:
    return f"{PLUGIN_FOLDER}/{plugin}/{HOOKS_FOLDER}/{HOOKS_FILE}"


def hook_records(
    settings: HubJsonContent,
    project_settings: HubJsonContent,
    plugin_hooks: Mapping[str, HubJsonContent],
    *,
    enabled: Mapping[str, bool],
    marketplace: str | None,
) -> HookFold:
    """The hooks of ``settings`` (``.claude/settings.json``), ``project_settings``
    (``.claude/settings.project.json``) and ``plugin_hooks`` (each plugin folder's
    ``hooks/hooks.json``), named, with S4 origins and states; plugin hooks active only when
    ``enabled`` holds ``<plugin>@<marketplace>: true``. At most ``MAX_HOOKS``."""
    fold = _Fold()
    effective = _Source(name=SETTINGS_SOURCE, path=SETTINGS_PATH, content=settings)
    project = _Source(
        name=PROJECT_SETTINGS_SOURCE, path=PROJECT_SETTINGS_PATH, content=project_settings
    )
    settings_entries = fold.entries(effective)
    project_entries = fold.entries(project)
    project_ids = {entry.identity for entry in project_entries}
    settings_ids = {entry.identity for entry in settings_entries}
    for entry in settings_entries:
        owned = entry.identity in project_ids
        origin = Origin.PROJECT_OWNED if owned else Origin.MANAGED
        fold.add(effective, entry, origin=origin, active=True)
    for entry in project_entries:
        if entry.identity not in settings_ids:
            fold.add(project, entry, origin=Origin.PROJECT_OWNED, active=False, state="not synced")
    for plugin in sorted(plugin_hooks):
        source = _Source(name=plugin, path=_plugin_path(plugin), content=plugin_hooks[plugin])
        origin = Origin.MANAGED if plugin == BASE_PLUGIN else Origin.PROJECT_OWNED
        active = marketplace is not None and enabled.get(f"{plugin}@{marketplace}") is True
        for entry in fold.entries(source):
            fold.add(source, entry, origin=origin, active=active)
    return HookFold(
        records=tuple(fold.records), notices=tuple(fold.notices), truncated=fold.truncated
    )
