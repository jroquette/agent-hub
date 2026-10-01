"""``settings.valid``, ``permissions.bypass`` and ``mcp.pinned`` (spec AC-11.22, Q-8).

The port of the hub's old config lint script's settings, bypass and MCP checks. Both JSON
files are fixed paths, read only as regular files (a link is never followed, D3):
``.claude/settings.json`` strictly for ``settings.valid``, as ``settings.weakening`` reads it
(E25), and as the old lint read it for ``permissions.bypass`` (E34 f); ``.mcp.json`` as the old
lint read it (E34 b). A linked or unread file gives no finding (E34 d). A finding in either
file is at line 1, as the old lint put it, except a parse error, at the parser's line when it
has one (E6).

- ``settings.valid``: each file parses and its top level is an object (E11); settings hold no
  deprecated key, one finding per key in sorted order.
- ``permissions.bypass``: settings' ``permissions.defaultMode`` is not ``bypassPermissions``; no key
  or string of either file holds the skip-permissions flag; nor does a line of a UTF-8 file of
  the hub's files (E31, E34 e: the listing and the fixed paths present) under ``scripts/`` or
  ``.github/workflows/``, or ``Makefile`` or ``package.json``; no path is skipped by name (the
  old lint script's own exception went with it, AGH-15 D7). A file that is not text is skipped
  (Q-19).
- ``mcp.pinned``: each ``.mcp.json`` server, in key order, is not ``@latest`` and, run by
  ``npx``, names a version (``@<digit>``); settings' ``mcpServers`` are not checked.

A value of the wrong type (``permissions``, ``mcpServers``, a server, its ``args``) is skipped
(E11). JSON is walked with a stack, so a deep value costs no recursion, and each file's lines are
scanned once.
"""

import re
from collections.abc import Callable, Iterator
from typing import Final

from agent_hub.core.doctor.config_lint import file_text, known_paths, text_lines
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.settings_rules import SETTINGS_PATH, load_settings
from agent_hub.core.doctor.snapshot import DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.doctor_rules import (
    MCP_PINNED_RULE,
    PERMISSIONS_BYPASS_RULE,
    RULE_MODULES,
    SETTINGS_VALID_RULE,
    Severity,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import one_line
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

MCP_PATH: Final = ".mcp.json"
# The old lint's deprecated settings keys, in the order their findings come.
DEPRECATED_KEYS: Final = ("allowedTools", "ignorePatterns")
BYPASS_MODE: Final = "bypassPermissions"
CONFIG_FLAG: Final = "dangerously-skip-permissions"
FILE_FLAG: Final = f"--{CONFIG_FLAG}"
SCANNED_FOLDERS: Final = ("scripts/", ".github/workflows/")
SCANNED_FILES: Final = frozenset({"Makefile", "package.json"})
NPX: Final = "npx"
LATEST: Final = "@latest"

SYNTAX_FIX: Final = "fix the syntax"
NOT_OBJECT_MESSAGE: Final = "must be a JSON object"
NOT_OBJECT_FIX: Final = "make the top level a JSON object"
DEPRECATED_FIX: Final = "use `permissions.allow` / `permissions.deny`"
BYPASS_MODE_MESSAGE: Final = f"`{BYPASS_MODE}` in shared settings"
BYPASS_MODE_FIX: Final = "use acceptEdits/auto; bypass only in a firewalled container"
CONFIG_FLAG_MESSAGE: Final = f"`{FILE_FLAG}` in config"
CONFIG_FLAG_FIX: Final = "remove it"
FILE_FLAG_MESSAGE: Final = f"`{FILE_FLAG}`"
FILE_FLAG_FIX: Final = "run agents with an allowlist and the sandbox instead"
PIN_FIX: Final = "pin an exact version (pkg@1.2.3) or use the official remote URL"

_VERSION: Final = re.compile(r"@\d")
type _Loaders = tuple[tuple[str, Callable[[bytes], JsonValue]], ...]
# settings.valid reads settings.json strictly, as settings.weakening does (E25).
_STRICT_LOADERS: Final[_Loaders] = ((SETTINGS_PATH, load_settings), (MCP_PATH, load_json_bytes))
# permissions.bypass reads both leniently, as the old lint did: a strict-parse error is
# settings.valid's and never hides a bypass, even when only this rule runs (E34 f).
_LENIENT_LOADERS: Final[_Loaders] = ((SETTINGS_PATH, load_json_bytes), (MCP_PATH, load_json_bytes))


class _Absent:
    """No regular file with content at a path: nothing to check (a failed read is E24's)."""


def _settings_valid(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    for path, document in _documents(snapshot.hub, loaders=_STRICT_LOADERS):
        if isinstance(document, InvalidJsonError):
            yield SETTINGS_VALID.finding(
                path=path, line=document.line, message=document.message, fix=SYNTAX_FIX
            )
        elif not isinstance(document, dict):
            yield SETTINGS_VALID.finding(path=path, message=NOT_OBJECT_MESSAGE, fix=NOT_OBJECT_FIX)
        elif path == SETTINGS_PATH:
            yield from (
                SETTINGS_VALID.finding(
                    path=path,
                    line=1,
                    message=f"deprecated settings key `{key}`",
                    fix=DEPRECATED_FIX,
                )
                for key in DEPRECATED_KEYS
                if key in document
            )


def _permissions_bypass(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    yield from _config_bypass(snapshot.hub)
    yield from _file_bypass(snapshot.hub, config=snapshot.hub_config)


def _config_bypass(hub: HubFiles) -> Iterator[Finding]:
    for path, document in _documents(hub, loaders=_LENIENT_LOADERS):
        if isinstance(document, InvalidJsonError):
            continue
        if path == SETTINGS_PATH and _is_bypass_mode(document):
            yield _bypass(path, line=1, message=BYPASS_MODE_MESSAGE, fix=BYPASS_MODE_FIX)
        if _holds_text(document, CONFIG_FLAG):
            yield _bypass(path, line=1, message=CONFIG_FLAG_MESSAGE, fix=CONFIG_FLAG_FIX)


def _file_bypass(hub: HubFiles, *, config: HubConfig) -> Iterator[Finding]:
    for path in _scanned_paths(hub, config=config):
        text = file_text(hub.entries.get(path))
        # One pass over the text first: most files never name the flag.
        if not isinstance(text, str) or FILE_FLAG not in text:
            continue
        for number, line in enumerate(text_lines(text), start=1):
            if FILE_FLAG in line:
                yield _bypass(path, line=number, message=FILE_FLAG_MESSAGE, fix=FILE_FLAG_FIX)


def _mcp_pinned(snapshot: DoctorSnapshot) -> Iterator[Finding]:
    document = _document(snapshot.hub, path=MCP_PATH, load=load_json_bytes)
    servers = document.get("mcpServers") if isinstance(document, dict) else None
    if not isinstance(servers, dict):
        return
    for name, server in servers.items():
        if _is_unpinned(server):
            yield MCP_PINNED.finding(
                path=MCP_PATH,
                line=1,
                message=f"MCP server `{cut_echo(one_line(name))}` is not version-pinned",
                fix=PIN_FIX,
            )


def _documents(
    hub: HubFiles, *, loaders: _Loaders
) -> Iterator[tuple[str, JsonValue | InvalidJsonError]]:
    """Each JSON file present as a regular file with content, in path order, parsed or not."""
    for path, load in loaders:
        document = _document(hub, path=path, load=load)
        if not isinstance(document, _Absent):
            yield path, document


def _document(
    hub: HubFiles, *, path: str, load: Callable[[bytes], JsonValue]
) -> JsonValue | InvalidJsonError | _Absent:
    entry = hub.entries.get(path)
    if not isinstance(entry, FileEntry) or entry.content is None:
        return _Absent()
    try:
        return load(entry.content)
    except InvalidJsonError as error:
        return error


def _is_bypass_mode(document: JsonValue) -> bool:
    permissions = document.get("permissions") if isinstance(document, dict) else None
    return isinstance(permissions, dict) and permissions.get("defaultMode") == BYPASS_MODE


def _holds_text(value: JsonValue, needle: str) -> bool:
    """Whether a key or string anywhere in ``value`` holds ``needle``; walked with a stack.

    The old lint searched ``json.dumps`` of the value: an ASCII needle with no quote or
    backslash can only match inside one key or string there, so this is the same test.
    """
    pending: list[JsonValue] = [value]
    while pending:
        item = pending.pop()
        if isinstance(item, str):
            if needle in item:
                return True
        elif isinstance(item, dict):
            pending.extend(item.keys())
            pending.extend(item.values())
        elif isinstance(item, list):
            pending.extend(item)
    return False


def _scanned_paths(hub: HubFiles, *, config: HubConfig) -> list[str]:
    """The hub's files the flag scan reads, once each, sorted (a fixed path may be listed)."""
    paths = dict.fromkeys(known_paths(hub, config=config))
    return sorted(
        path for path in paths if path.startswith(SCANNED_FOLDERS) or path in SCANNED_FILES
    )


def _is_unpinned(server: JsonValue) -> bool:
    """The old lint's test, on a server whose ``args`` are strings; any other shape passes."""
    if not isinstance(server, dict):
        return False
    args = server.get("args", [])
    if not isinstance(args, list):
        return False
    strings = [arg for arg in args if isinstance(arg, str)]
    if len(strings) != len(args):
        return False
    joined = " ".join(strings)
    command = server.get("command", "")
    # The old ``str(command)``: no scalar other than a string can hold ``npx``.
    run_by_npx = isinstance(command, str) and NPX in command
    return LATEST in joined or (run_by_npx and _VERSION.search(joined) is None)


def _bypass(path: str, *, line: int, message: str, fix: str) -> Finding:
    return PERMISSIONS_BYPASS.finding(path=path, line=line, message=message, fix=fix)


SETTINGS_VALID: Final = Rule(
    id=SETTINGS_VALID_RULE,
    severity=Severity.ERROR,
    summary="settings.json and .mcp.json are JSON objects; settings hold no deprecated key",
    module=RULE_MODULES.get(SETTINGS_VALID_RULE),
    reads=frozenset(),
    check=_settings_valid,
)
PERMISSIONS_BYPASS: Final = Rule(
    id=PERMISSIONS_BYPASS_RULE,
    severity=Severity.ERROR,
    summary="no bypass mode or skip-permissions flag in settings, scripts, Makefile or CI",
    module=RULE_MODULES.get(PERMISSIONS_BYPASS_RULE),
    reads=frozenset({Read.HUB_LISTING}),
    check=_permissions_bypass,
)
MCP_PINNED: Final = Rule(
    id=MCP_PINNED_RULE,
    severity=Severity.ERROR,
    summary="each .mcp.json server is pinned to a version",
    module=RULE_MODULES.get(MCP_PINNED_RULE),
    reads=frozenset(),
    check=_mcp_pinned,
)
