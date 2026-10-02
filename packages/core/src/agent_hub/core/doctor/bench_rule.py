"""``bench.tasks``: the bench cases in ``brain/workflow/bench/tasks.json`` are well formed.

Module ``bench`` owns it. The file is read from the snapshot when the hub listing holds it; no
file means no cases (spec Q-6), as does ``[]``. A file that is no regular file, could not be
read, or is not a strict JSON list of at most 200 cases is one finding; otherwise each problem
``case_problems`` finds is one finding (the case index in its message), against the repos of
``hub.json``. It runs no git and no process: the grader check is ``hub bench --validate``.
"""

from collections.abc import Iterable
from typing import Final

from agent_hub.core.bench.bench_cases import TASKS_PATH, case_problems, read_cases
from agent_hub.core.doctor.finding import Finding, Read, Rule
from agent_hub.core.doctor.snapshot import DoctorSnapshot
from agent_hub.core.hub_config.doctor_rules import BENCH_TASKS_RULE, RULE_MODULES, Severity
from agent_hub.core.hub_config.problems import ROOT_PATH
from agent_hub.core.hub_files.tree_snapshot import FileEntry

CASE_FIX: Final = "fix the case in tasks.json"
JSON_FIX: Final = "make tasks.json a strict JSON list of at most 200 cases"
NOT_READ: Final = "not read as a regular file (links are never followed)"
LINK_FIX: Final = "replace it with the file itself"
UNREAD: Final = "could not be read"
UNREAD_FIX: Final = "run hub doctor again"


def _bench_tasks(snapshot: DoctorSnapshot) -> Iterable[Finding]:
    if TASKS_PATH not in snapshot.hub.listed:
        return ()
    entry = snapshot.hub.entries.get(TASKS_PATH)
    if not isinstance(entry, FileEntry):
        return (_finding(NOT_READ, LINK_FIX),)
    if entry.content is None:
        return (_finding(UNREAD, UNREAD_FIX),)
    cases = read_cases(entry.content)
    if isinstance(cases, str):
        return (_finding(f"{ROOT_PATH}: {cases}", JSON_FIX),)
    repos = [repo.dir for repo in snapshot.hub_config.repos]
    return tuple(_finding(problem.text, CASE_FIX) for problem in case_problems(cases, repos=repos))


def _finding(message: str, fix: str) -> Finding:
    return BENCH_TASKS.finding(path=TASKS_PATH, message=message, fix=fix)


BENCH_TASKS: Final = Rule(
    id=BENCH_TASKS_RULE,
    severity=Severity.ERROR,
    summary="brain/workflow/bench/tasks.json holds well-formed bench cases",
    module=RULE_MODULES.get(BENCH_TASKS_RULE),
    reads=frozenset({Read.HUB_LISTING}),
    check=_bench_tasks,
)
