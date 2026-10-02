import builtins
import json
import subprocess
from collections.abc import Callable
from typing import Any, NoReturn

import pytest

from agent_hub.core.doctor.bench_rule import BENCH_TASKS
from agent_hub.core.doctor.finding import Read
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import Severity
from agent_hub.core.hub_files.tree_snapshot import FileEntry, LinkEntry, TreeEntry

type SnapshotFactory = Callable[..., DoctorSnapshot]
type Shown = tuple[str | None, str, str]

TASKS = "brain/workflow/bench/tasks.json"
SHA = "0123456789abcdef0123456789abcdef01234567"
CASE_FIX = "fix the case in tasks.json"
JSON_FIX = "make tasks.json a strict JSON list of at most 200 cases"
NOT_READ = "not read as a regular file (links are never followed)"
LINK_FIX = "replace it with the file itself"
UNREAD = "could not be read"
UNREAD_FIX = "run hub doctor again"


def a_case(**changes: Any) -> dict[str, Any]:
    case: dict[str, Any] = {
        "id": "T1",
        "repo": "demo-api",
        "merge": SHA,
        "prompt": "Add the fix",
        "hidden_tests": ["tests/test_fix.py"],
        "test_cmd": ["python3", "-m", "pytest", "-q"],
    }
    return case | changes


def findings_of(snapshot: DoctorSnapshot) -> list[Shown]:
    found = list(BENCH_TASKS.check(snapshot))
    assert all(finding.rule == "bench.tasks" for finding in found)
    assert all(finding.severity is Severity.ERROR for finding in found)
    assert all(finding.line is None for finding in found)
    return [(finding.path, finding.message, finding.fix) for finding in found]


def checked(snapshot_of: SnapshotFactory, cases: object) -> list[Shown]:
    return findings_of(snapshot_of(files={TASKS: json.dumps(cases).encode()}))


def test_declares_rule_when_module_loaded() -> None:
    assert BENCH_TASKS.id == "bench.tasks"
    assert BENCH_TASKS.module == "bench"
    assert BENCH_TASKS.severity is Severity.ERROR
    assert BENCH_TASKS.reads == frozenset({Read.HUB_LISTING})
    assert BENCH_TASKS.summary == "brain/workflow/bench/tasks.json holds well-formed bench cases"


@pytest.mark.parametrize(
    ("files", "listed"),
    [
        ({}, None),
        ({TASKS: b"[]\n"}, None),
        (
            {TASKS: json.dumps([a_case(), a_case(id="T0", repo="gone", excluded=True)]).encode()},
            None,
        ),
        # Only a listed file counts: an entry the listing does not hold was never the tree's.
        ({TASKS: b"not json"}, ()),
        ({"brain/workflow/bench/other.json": b"not json"}, None),
    ],
    ids=["absent", "empty-list", "valid", "not-listed", "other-file"],
)
def test_stays_clean_when_file_absent_or_empty_list(
    snapshot_of: SnapshotFactory, files: dict[str, bytes], listed: tuple[str, ...] | None
) -> None:
    assert findings_of(snapshot_of(files=files, listed=listed)) == []


def test_reports_each_problem_when_cases_invalid(snapshot_of: SnapshotFactory) -> None:
    broken = a_case(id="T2", repo="zz", merge="--orphan", hidden_tests=["../x.py"])
    del broken["prompt"]
    cases = [a_case(), broken, a_case(), "T4", a_case(id="T5", test_cmd=[])]

    assert checked(snapshot_of, cases) == [
        (TASKS, "[1].merge: must be a commit sha: 7 to 40 characters among 0-9 and a-f", CASE_FIX),
        (TASKS, "[1].prompt: is missing", CASE_FIX),
        (
            TASKS,
            '[1].hidden_tests: "../x.py" is not a literal relative path in the repo'
            " (no empty, `.`, `..` or `.git` segment in any case, no leading `/`, `-` or `:`,"
            " no `*`, `?`, `[`, `\\`, control, format or surrogate character,"
            " 1 to 1024 characters)",
            CASE_FIX,
        ),
        (TASKS, '[1].repo: "zz" is not in repos (demo-api)', CASE_FIX),
        (TASKS, '[2].id: duplicate id "T1"', CASE_FIX),
        (TASKS, "[3]: must be an object", CASE_FIX),
        (
            TASKS,
            "[4].test_cmd: must be 1 to 32 non-empty strings of at most 1024 characters",
            CASE_FIX,
        ),
    ]


@pytest.mark.parametrize(
    ("entry", "expected"),
    [
        (
            FileEntry(executable=False, content=b"["),
            ("$: not valid JSON: Expecting value at line 1 column 2", JSON_FIX),
        ),
        (
            FileEntry(executable=False, content=b'[{"id": "T1", "id": "T2"}]'),
            ('$: not valid JSON here: the key "id" appears more than once', JSON_FIX),
        ),
        (
            FileEntry(executable=False, content=b'{"cases": []}'),
            ("$: the top level must be a list of cases", JSON_FIX),
        ),
        (
            FileEntry(executable=False, content=b"\xff"),
            ("$: not UTF-8 text: byte 0 cannot be decoded", JSON_FIX),
        ),
        (
            FileEntry(executable=False, content=b" " * (1 << 20) + b"[]"),
            ("$: larger than 1048576 bytes", JSON_FIX),
        ),
        (FileEntry(executable=False, content=None), (UNREAD, UNREAD_FIX)),
        (LinkEntry(target="../tasks.json", outside=False), (NOT_READ, LINK_FIX)),
    ],
    ids=["syntax", "repeated-key", "object", "not-utf8", "too-large", "unread", "link"],
)
def test_reports_not_json_when_file_unreadable(
    snapshot_of: SnapshotFactory, entry: TreeEntry, expected: tuple[str, str]
) -> None:
    snapshot = snapshot_of(entries={TASKS: entry})

    assert findings_of(snapshot) == [(TASKS, *expected)]


def test_runs_no_process_when_checked(
    snapshot_of: SnapshotFactory, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refused(*args: object, **kwargs: object) -> NoReturn:
        pytest.fail("bench.tasks must read the snapshot only")

    snapshot = snapshot_of(files={TASKS: json.dumps([a_case(repo="zz")]).encode()})
    monkeypatch.setattr(subprocess, "Popen", refused)
    monkeypatch.setattr(builtins, "open", refused)

    assert findings_of(snapshot) == [(TASKS, '[0].repo: "zz" is not in repos (demo-api)', CASE_FIX)]
