"""``hub doctor --staged``: what a commit is checked for, on what it stages only (ADR 0061).

A hub's ``.githooks/pre-commit`` runs ``./hub doctor --staged``. The CLI reads the staged paths
and their content from git's index, never the working tree, and these pure functions decide
what is checked:

- each feature folder ``brain/features/<name>/`` with a staged path (added, changed or deleted;
  a ``<name>`` starting with ``.`` is skipped, as ``features.tracker`` skips it) gets the
  ``features.tracker`` checks, on the index's files of that folder only
  (``staged_feature_folders``);
- ``config.schema`` and ``platform.version`` findings block only when ``hub.json`` is staged
  (``commit_findings``): a broken ``hub.json`` the commit does not touch is CI's to report;
- each staged regular file gets the hygiene checks the hub once took from ``pre-commit-hooks``
  (``hygiene_findings``): no trailing whitespace, one newline at the end, valid JSON for
  ``*.json``, valid YAML for ``*.yaml`` and ``*.yml``. A binary file (a NUL byte) or one that is
  not UTF-8 gets none. The YAML parser is the caller's (core holds no YAML library).

The whole-hub ``hub doctor`` stays in CI (``make check``), on the merged state.
"""

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Final

from agent_hub.core.doctor.finding import Finding
from agent_hub.core.doctor.registry import REGISTRY
from agent_hub.core.doctor.run_rules import UsageProblem, run_rules, select_rules, sort_findings
from agent_hub.core.doctor.snapshot import ConfigFailure, DoctorSnapshot, HubFiles
from agent_hub.core.hub_config.doctor_rules import (
    CONFIG_SCHEMA_RULE,
    FEATURES_TRACKER_RULE,
    PLATFORM_VERSION_RULE,
    Severity,
)
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry

HYGIENE_RULE: Final = "files.hygiene"
HUB_FILE: Final = "hub.json"
FEATURES_PREFIX: Final = "brain/features/"
WHITESPACE: Final = "trailing whitespace on {count} line(s), first at this line"
WHITESPACE_FIX: Final = "remove the spaces and tabs at the end of those lines"
NO_NEWLINE: Final = "the file does not end with a newline"
EXTRA_NEWLINES: Final = "the file ends with more than one newline"
NEWLINE_FIX: Final = "end the file with exactly one newline"
JSON_MESSAGE: Final = "not valid JSON: {problem}"
JSON_FIX: Final = "fix the JSON"
YAML_MESSAGE: Final = "not valid YAML: {problem}"
YAML_FIX: Final = "fix the YAML"
_CONFIG_RULES: Final = frozenset({CONFIG_SCHEMA_RULE, PLATFORM_VERSION_RULE})
# What ``bytes.rstrip()`` removes at a line's end, the line break aside.
_TRAILING: Final = b" \t\x0b\x0c\r"
_JSON_SUFFIXES: Final = (".json",)
_YAML_SUFFIXES: Final = (".yaml", ".yml")

type YamlProblem = Callable[[str], str | None]
CONFIG_SKIPPED: Final = (
    "hub doctor --staged: hub.json in the index cannot be used, and this commit does not stage it,"
    " so the staged features were not checked; CI's hub doctor reports it"
)


@dataclass(frozen=True, kw_only=True, slots=True)
class StagedIndex:
    """What git's index holds for one commit.

    ``staged`` is every path the commit adds, changes or deletes. ``entries`` holds, by path, the
    index's entry of each staged path still in the index and of each file of the staged feature
    folders (``feature_files``, sorted: the index's listing of those folders). A ``FileEntry``'s
    content is the staged blob.
    """

    staged: tuple[str, ...]
    entries: Mapping[str, TreeEntry]
    feature_files: tuple[str, ...]


@dataclass(frozen=True, kw_only=True, slots=True)
class StagedRun:
    """The findings that decide the commit, sorted, and the notes for stderr."""

    findings: tuple[Finding, ...]
    notes: tuple[str, ...]


def check_staged(
    index: StagedIndex,
    *,
    config: HubConfig | ConfigFailure,
    running_version: str,
    yaml_problem: YamlProblem,
) -> StagedRun:
    """The commit's checks: hygiene of each staged file, then the doctor rules on the index.

    ``config`` is ``config_state`` of the index's ``hub.json``. ``features.tracker`` runs on the
    staged feature folders' files only; the config rules' findings count only when ``hub.json``
    is staged. A config that cannot be used, with ``hub.json`` not staged, skips the doctor rules
    with a note.
    """
    hygiene = [
        finding
        for path in index.staged
        if isinstance(entry := index.entries.get(path), FileEntry) and entry.content is not None
        for finding in hygiene_findings(path, entry.content, yaml_problem=yaml_problem)
    ]
    hub_json_staged = HUB_FILE in index.staged
    failed = isinstance(config, ConfigFailure)
    if failed and not hub_json_staged:
        return StagedRun(findings=sort_findings(hygiene), notes=(CONFIG_SKIPPED,))
    doctor = _doctor_findings(index, config=config, running_version=running_version)
    kept = commit_findings(doctor, hub_json_staged=hub_json_staged)
    return StagedRun(findings=sort_findings([*hygiene, *kept]), notes=())


def _doctor_findings(
    index: StagedIndex, *, config: HubConfig | ConfigFailure, running_version: str
) -> tuple[Finding, ...]:
    """The config rules, and ``features.tracker`` when a feature folder is staged."""
    folders = staged_feature_folders(index.staged)
    only = (FEATURES_TRACKER_RULE,) if folders else (CONFIG_SCHEMA_RULE,)
    selection = select_rules(REGISTRY, config=config, only=only)
    if isinstance(selection, UsageProblem):
        selection = select_rules(REGISTRY, config=config, only=(CONFIG_SCHEMA_RULE,))
    if isinstance(selection, UsageProblem):  # pragma: no cover - config.schema is always known
        return ()
    listed = tuple(path for path in index.feature_files if path.startswith(folders))
    files = HubFiles(
        entries={path: index.entries[path] for path in listed if path in index.entries},
        listed=listed,
        problem=None,
        paths_read=True,
        listed_by_git=True,
    )
    snapshot = DoctorSnapshot(
        config=config,
        running_version=running_version,
        hub=files,
        lock=None,
        base_hooks=None,
        repos=(),
    )
    return run_rules(selection, snapshot)


def staged_feature_folders(paths: Iterable[str]) -> tuple[str, ...]:
    """The sorted ``brain/features/<name>/`` folders that hold one of ``paths``.

    Only a path inside a folder counts (``brain/features/<name>/<file>``), and a ``<name>``
    starting with ``.`` is skipped.
    """
    folders = set()
    for path in paths:
        if not path.startswith(FEATURES_PREFIX):
            continue
        parts = path[len(FEATURES_PREFIX) :].split("/")
        if len(parts) >= 2 and parts[0] and not parts[0].startswith("."):
            folders.add(f"{FEATURES_PREFIX}{parts[0]}/")
    return tuple(sorted(folders))


def commit_findings(findings: Iterable[Finding], *, hub_json_staged: bool) -> tuple[Finding, ...]:
    """``findings`` without the config rules' ones, unless the commit stages ``hub.json``."""
    if hub_json_staged:
        return tuple(findings)
    return tuple(finding for finding in findings if finding.rule not in _CONFIG_RULES)


def hygiene_findings(
    path: str, content: bytes, *, yaml_problem: YamlProblem
) -> tuple[Finding, ...]:
    """The hygiene errors of one staged file's content; none for a binary or non-UTF-8 file."""
    if b"\x00" in content:
        return ()
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return ()
    found = [*_whitespace(path, content), *_end_of_file(path, content)]
    lowered = path.lower()
    if lowered.endswith(_JSON_SUFFIXES):
        problem = _json_problem(text)
        if problem is not None:
            found.append(
                _error(path, None, message=JSON_MESSAGE.format(problem=problem), fix=JSON_FIX)
            )
    elif lowered.endswith(_YAML_SUFFIXES):
        problem = yaml_problem(text)
        if problem is not None:
            found.append(
                _error(path, None, message=YAML_MESSAGE.format(problem=problem), fix=YAML_FIX)
            )
    return tuple(found)


def _whitespace(path: str, content: bytes) -> tuple[Finding, ...]:
    # A CRLF line keeps its ``\r``: only what stands before the line break counts.
    flagged = [
        number
        for number, line in enumerate(content.split(b"\n"), start=1)
        if line.rstrip(_TRAILING) != line.removesuffix(b"\r")
    ]
    if not flagged:
        return ()
    message = WHITESPACE.format(count=len(flagged))
    return (_error(path, flagged[0], message=message, fix=WHITESPACE_FIX),)


def _end_of_file(path: str, content: bytes) -> tuple[Finding, ...]:
    """A non-empty file ends with exactly one ``\\n`` (or ``\\r\\n``); only newlines is too many."""
    if not content:
        return ()
    body = content.rstrip(b"\r\n")
    tail = content[len(body) :]
    if not tail:
        return (_error(path, None, message=NO_NEWLINE, fix=NEWLINE_FIX),)
    if not body or tail not in {b"\n", b"\r\n"}:
        return (_error(path, None, message=EXTRA_NEWLINES, fix=NEWLINE_FIX),)
    return ()


def _json_problem(text: str) -> str | None:
    """Why ``text`` is not one JSON document without repeated keys, else ``None``."""

    def no_repeats(pairs: list[tuple[str, object]]) -> dict[str, object]:
        seen: dict[str, object] = {}
        for key, value in pairs:
            if key in seen:
                msg = f"repeated key {cut_echo(key)!r}"
                raise ValueError(msg)
            seen[key] = value
        return seen

    try:
        json.loads(text, object_pairs_hook=no_repeats)
    except RecursionError:
        return "nested too deep"
    except ValueError as error:
        return cut_echo(str(error))
    return None


def _error(path: str, line: int | None, *, message: str, fix: str) -> Finding:
    return Finding(
        rule=HYGIENE_RULE, severity=Severity.ERROR, path=path, line=line, message=message, fix=fix
    )
