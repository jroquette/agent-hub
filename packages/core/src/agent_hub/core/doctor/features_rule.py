"""``features.tracker``: every feature record is well formed and agrees with its spec (spec Q-16).

The port of the hub's feature check (``features_check.py`` and its ``Makefile`` loop): each
listed ``brain/features/<name>/features.json`` (a ``<name>`` starting with ``.`` is skipped, as a
shell glob does) is read as ``json.load`` read it (a repeated key: the last wins), and must hold
``{"feature", "linear", "acs": [{id, description, repo, verification, passes, evidence}]}``:
``linear`` ids carry the tracker team's prefix; ``repo`` is a ``repos[].dir`` or the hub's repo
name (the last segment of ``project.hub_repo``, whatever folder the hub sits in); ids look like
``AC-<n>`` or ``AC-<n>.<m>`` (``\\d`` takes any script's digits, as before) and are unique; a
pending AC's verification keeps its exit code; ``passes: true`` needs evidence. When a sibling
``spec.md`` is listed, the ``AC-…`` ids it names anywhere (a range's ends and a placeholder
included, which the hub's spec rule relies on) and the record's ids are the same set, each side
reported in numeric order. Every finding names the record, except a spec that cannot be read
(not UTF-8, or a link: links are never followed), which names the spec; the record is then
checked without the cross-check.
"""

import re
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Final, NamedTuple

from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import FEATURES_TRACKER_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.model import HubConfig
from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.hub_files.tree_snapshot import FileEntry, TreeEntry
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

FEATURES_FOLDER: Final = ("brain", "features")
RECORD_NAME: Final = "features.json"
SPEC_NAME: Final = "spec.md"

RECORD_FIX: Final = "fix the record in features.json"
MASKED_FIX: Final = "end the verification with the check itself, so a failure exits non-zero"
EVIDENCE_FIX: Final = "record the command run and its result in evidence"
SPEC_FIX: Final = "give spec.md and features.json the same AC ids"
JSON_FIX: Final = "fix the JSON of the record"
LINK_FIX: Final = "replace it with the file itself"
TEXT_FIX: Final = "save it as UTF-8 text"
NOT_READ: Final = "not read as a regular file (links are never followed)"
MASKED: Final = (
    "`verification` must keep its exit code (no trailing `echo $?`, `|| true` or `| tail`)"
)

_AC_ID: Final = re.compile(r"AC-\d+(?:\.\d+)*")
# An id anywhere in the spec, prose and code alike; ``AC-1.2x`` and a ``.<digit>`` tail are none.
_SPEC_ID: Final = re.compile(r"\b" + _AC_ID.pattern + r"\b(?!\.\d)")
# A last step of ``echo … $?``, ``|| true`` or a pipe into a pager always exits 0, so a failing
# check would read as passing. Only pending ACs: passed ones keep the command the evaluator ran.
_MASKED_EXIT: Final = re.compile(
    r"(;|&&)\s*echo\b[^;&|]*\$\?\s*$|\|\|\s*(true|:)\s*$|\|\s*(tail|head|less|more)\b[^|;&]*$"
)
_TEXT_FIELDS: Final = ("id", "description", "repo", "verification")


class _Problem(NamedTuple):
    """A finding's message and fix, before it is placed on a file."""

    message: str
    fix: str


@dataclass(frozen=True, kw_only=True, slots=True)
class _Project:
    """What the records are checked against: the repo names and the tracker's id prefix."""

    names: tuple[str, ...]
    prefix: str


def _features_tracker(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    project = _project_of(snapshot.hub_config)
    listed = frozenset(snapshot.hub.listed)
    entries = snapshot.hub.entries
    return tuple(
        finding
        for path in snapshot.hub.listed
        if _is_record(path)
        for finding in _record_findings(path, entries=entries, listed=listed, project=project)
    )


def _project_of(config: HubConfig) -> _Project:
    hub_name = config.project.hub_repo.rsplit("/", 1)[-1]
    names = sorted({*(repo.dir for repo in config.repos), hub_name})
    return _Project(names=tuple(names), prefix=f"{config.tracker.team}-")


def _is_record(path: str) -> bool:
    parts = tuple(path.split("/"))
    return (
        len(parts) == len(FEATURES_FOLDER) + 2
        and parts[: len(FEATURES_FOLDER)] == FEATURES_FOLDER
        and parts[-1] == RECORD_NAME
        and not parts[-2].startswith(".")
    )


def _record_findings(
    path: str, *, entries: Mapping[str, TreeEntry], listed: frozenset[str], project: _Project
) -> tuple[Finding, ...]:
    spec_path = path.removesuffix(RECORD_NAME) + SPEC_NAME
    spec = _spec_text(entries.get(spec_path)) if spec_path in listed else None
    document = _document(entries.get(path))
    if isinstance(document, _Problem):
        problems: tuple[_Problem, ...] = (document,)
    else:
        problems = _record_problems(
            document, spec=spec if isinstance(spec, str) else None, project=project
        )
    spec_problems = (spec,) if isinstance(spec, _Problem) else ()
    return (
        *(_finding(spec_path, problem) for problem in spec_problems),
        *(_finding(path, problem) for problem in problems),
    )


def _finding(path: str, problem: _Problem) -> Finding:
    return FEATURES_TRACKER.finding(path=path, message=problem.message, fix=problem.fix)


def _document(entry: TreeEntry | None) -> JsonValue | _Problem:
    if not isinstance(entry, FileEntry) or entry.content is None:
        return _Problem(NOT_READ, LINK_FIX)
    try:
        return load_json_bytes(entry.content)
    except InvalidJsonError as error:
        return _Problem(f"{ROOT_PATH}: {error.message}", JSON_FIX)


def _spec_text(entry: TreeEntry | None) -> str | _Problem:
    """The spec's text; any UTF-8 is read (a NUL too), as the old check opened it."""
    if not isinstance(entry, FileEntry) or entry.content is None:
        return _Problem(NOT_READ, LINK_FIX)
    try:
        return entry.content.decode("utf-8")
    except UnicodeDecodeError as error:
        return _Problem(f"not UTF-8 text: byte {error.start} cannot be decoded", TEXT_FIX)


def _record_problems(
    data: JsonValue, *, spec: str | None, project: _Project
) -> tuple[_Problem, ...]:
    if not isinstance(data, dict):
        return (_Problem("top level must be an object", RECORD_FIX),)
    problems = list(_header_problems(data, project=project))
    acs = data.get("acs")
    if not isinstance(acs, list) or not acs:
        return (*problems, _Problem("`acs` must be a non-empty list", RECORD_FIX))
    # Every id read, malformed ones too, in order: a duplicate is one seen before.
    seen: dict[str, None] = {}
    for index, ac in enumerate(acs):
        problems.extend(_ac_problems(index, ac, project=project, seen=seen))
    if spec is not None:
        problems.extend(_cross_check(spec, seen))
    return tuple(problems)


def _header_problems(data: Mapping[str, JsonValue], *, project: _Project) -> Iterator[_Problem]:
    feature = data.get("feature")
    if not isinstance(feature, str) or not feature:
        yield _Problem("`feature` must be a non-empty string", RECORD_FIX)
    linear = data.get("linear", [])
    team_id = re.compile(re.escape(project.prefix) + r"\d+")
    if not isinstance(linear, list) or not all(
        isinstance(item, str) and team_id.fullmatch(item) for item in linear
    ):
        yield _Problem(f"`linear` must be a list of {project.prefix}<n> ids", RECORD_FIX)


def _ac_problems(
    index: int, ac: JsonValue, *, project: _Project, seen: dict[str, None]
) -> list[_Problem]:
    where = f"acs[{index}]"
    if not isinstance(ac, dict):
        return [_Problem(f"{where}: must be an object", RECORD_FIX)]
    problems = [
        _Problem(f"{where}: `{field}` must be a non-empty string", RECORD_FIX)
        for field in _TEXT_FIELDS
        if not _filled(ac.get(field))
    ]
    if not isinstance(ac.get("passes"), bool):
        problems.append(_Problem(f"{where}: `passes` must be true or false", RECORD_FIX))
    ac_id = ac.get("id")
    if isinstance(ac_id, str):
        # From here the AC is named by its id.
        where = ac_id
        problems.extend(_id_problems(ac_id, seen))
    problems.extend(_value_problems(where, ac, project=project))
    return problems


def _filled(value: JsonValue) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _id_problems(ac_id: str, seen: dict[str, None]) -> list[_Problem]:
    problems = []
    if not _AC_ID.fullmatch(ac_id):
        problems.append(_Problem(f"{ac_id}: id must look like AC-<n>", RECORD_FIX))
    if ac_id in seen:
        problems.append(_Problem(f"{ac_id}: duplicate id", RECORD_FIX))
    seen[ac_id] = None
    return problems


def _value_problems(
    where: str, ac: Mapping[str, JsonValue], *, project: _Project
) -> Iterator[_Problem]:
    repo = ac.get("repo")
    if isinstance(repo, str) and repo not in project.names:
        names = ", ".join(project.names)
        yield _Problem(f"{where}: repo must be one of {names}", RECORD_FIX)
    verification = ac.get("verification")
    passes = ac.get("passes")
    if passes is False and isinstance(verification, str) and _MASKED_EXIT.search(verification):
        yield _Problem(f"{where}: {MASKED}", MASKED_FIX)
    evidence = ac.get("evidence")
    if evidence is not None and not isinstance(evidence, str):
        yield _Problem(f"{where}: `evidence` must be null or a string", RECORD_FIX)
    if passes is True and not _filled(evidence):
        yield _Problem(f"{where}: passes=true needs evidence (command + result)", EVIDENCE_FIX)


def _cross_check(spec: str, seen: Mapping[str, None]) -> Iterator[_Problem]:
    in_spec = dict.fromkeys(_SPEC_ID.findall(spec))
    for missing in sorted((ac_id for ac_id in in_spec if ac_id not in seen), key=_ac_key):
        yield _Problem(f"{missing}: in spec.md but not in features.json", SPEC_FIX)
    for extra in sorted((ac_id for ac_id in seen if ac_id not in in_spec), key=_ac_key):
        yield _Problem(f"{extra}: in features.json but not in spec.md", SPEC_FIX)


def _ac_key(ac_id: str) -> tuple[tuple[int, ...], str]:
    """Numeric order (``AC-2`` before ``AC-10``); a malformed id first, then by its text."""
    numbers = tuple(int(part) for part in ac_id[3:].split(".")) if _AC_ID.fullmatch(ac_id) else ()
    return numbers, ac_id


FEATURES_TRACKER: Final = Rule(
    id=FEATURES_TRACKER_RULE,
    severity=Severity.ERROR,
    summary="each brain/features/*/features.json is well formed and matches its spec.md",
    module=RULE_MODULES.get(FEATURES_TRACKER_RULE),
    reads=frozenset({Read.HUB_LISTING}),
    check=_features_tracker,
)
