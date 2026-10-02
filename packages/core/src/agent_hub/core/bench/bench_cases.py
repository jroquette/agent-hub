"""The bench case contract: what ``brain/workflow/bench/tasks.json`` may hold (plan E4).

The file is a strict JSON list of cases. A case is an object with ``id``, ``repo``, ``merge``,
``prompt``, ``hidden_tests`` and ``test_cmd``, and optionally ``setup_cmd``, ``env`` and
``excluded``; any other key is ignored, as the hub's script ignored it. Each value ends up in a
path (``id``), a git argument (``merge``, ``hidden_tests``) or a child's argv or environment, so
beyond its type it is bounded: an option-like or escaping value never reaches git or a process,
and no string a process gets holds a NUL character.

``read_cases`` reads the file; ``case_problems`` lists every problem, at most one per field, in
case then key order; ``unknown_repo_line`` is the script's own repo refusal, byte for byte;
``bench_cases`` turns cases ``case_problems`` found clean into ``BenchCase`` values.
"""

import json
import re
import unicodedata
from collections.abc import Callable, Collection, Iterator, Sequence
from dataclasses import dataclass
from typing import Final, TypeGuard

from pydantic import BaseModel, ConfigDict, Field

from agent_hub.core.hub_config.problems import json_path
from agent_hub.core.hub_config.versions import cut_echo
from agent_hub.core.json_form import InvalidJsonError, JsonValue, load_json_bytes

TASKS_PATH: Final = "brain/workflow/bench/tasks.json"
MAX_CASES_BYTES: Final = 1 << 20
MAX_CASES: Final = 200
CASE_ID_PATTERN: Final = "[A-Za-z0-9._-]{1,64}"
MERGE_PATTERN: Final = "[0-9a-f]{7,40}"
MAX_PROMPT_CHARS: Final = 20_000
MAX_HIDDEN_TESTS: Final = 100
MAX_TEST_PATH_CHARS: Final = 1024
MAX_TEST_CMD_ARGS: Final = 32
MAX_TEST_CMD_ARG_CHARS: Final = 1024
MAX_SETUP_CMD_CHARS: Final = 4096
MAX_ENV_KEYS: Final = 32
ENV_KEY_PATTERN: Final = "[A-Za-z_][A-Za-z0-9_]*"

MISSING: Final = "is missing"
_STRING: Final = "must be a string"
_STRINGS: Final = "must be a list of strings"
_OBJECT: Final = "must be an object"
_BOOLEAN: Final = "must be true or false"
_NUL: Final = "must not hold a NUL character"
_PATH_BOUND: Final = (
    "is not a literal relative path in the repo (no empty, `.`, `..` or `.git` segment in any"
    " case, no leading `/`, `-` or `:`, no `*`, `?`, `[`, `\\`, control, format or surrogate"
    f" character, 1 to {MAX_TEST_PATH_CHARS} characters)"
)
# Segments that name no file of the repo's tree: the tree itself, its parent, git's own store
# (compared case-folded: a case-insensitive file system reads ``.GIT`` as ``.git``).
_NOT_FILE_SEGMENTS: Final = frozenset({"", ".", "..", ".git"})
# Git reads ``:`` at the start as pathspec magic, these as globs and ``\`` as a glob escape; a
# path must name one file.
_PATHSPEC_CHARACTERS: Final = frozenset("*?[\\")
# Control, format (invisible, such as U+200C) and lone surrogate characters: a path shows as
# another, or cannot be encoded for git at all.
_HIDDEN_CATEGORIES: Final = frozenset({"Cc", "Cf", "Cs"})

# Explicit ASCII classes and ``fullmatch``: no Unicode digit and no trailing newline gets through.
_CASE_ID: Final = re.compile(CASE_ID_PATTERN)
_MERGE: Final = re.compile(MERGE_PATTERN)
_ENV_KEY: Final = re.compile(ENV_KEY_PATTERN)


@dataclass(frozen=True, kw_only=True, slots=True)
class CaseProblem:
    """One problem of the cases: the case's index, the key (``None``: the case itself), why."""

    index: int
    key: str | None
    message: str

    @property
    def text(self) -> str:
        """``[<index>].<key>: <message>``, the problem on one line."""
        loc: tuple[int | str, ...] = (self.index,) if self.key is None else (self.index, self.key)
        return f"{json_path(loc)}: {self.message}"


class BenchCase(BaseModel):
    """A checked case; ``env`` values are written as the script wrote them (``str(value)``)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    repo: str
    merge: str
    prompt: str
    hidden_tests: tuple[str, ...]
    test_cmd: tuple[str, ...]
    setup_cmd: str = ""
    env: dict[str, str] = Field(default_factory=dict)
    excluded: bool = False


def read_cases(content: bytes) -> list[JsonValue] | str:
    """The cases ``content`` holds, or why it holds none: too large, not strict JSON, no list."""
    if len(content) > MAX_CASES_BYTES:
        return f"larger than {MAX_CASES_BYTES} bytes"
    try:
        document = load_json_bytes(content, strict=True)
    except InvalidJsonError as error:
        return error.message
    if not isinstance(document, list):
        return "the top level must be a list of cases"
    if len(document) > MAX_CASES:
        return f"more than {MAX_CASES} cases"
    return document


def case_problems(cases: Sequence[JsonValue], *, repos: Collection[str]) -> list[CaseProblem]:
    """Every problem of ``cases``; a case not ``excluded`` names one of ``repos``."""
    known = sorted(set(repos))
    seen: set[str] = set()
    return [
        problem
        for index, case in enumerate(cases)
        for problem in _problems_of(index, case, known=known, seen=seen)
    ]


def unknown_repo_line(cases: Sequence[JsonValue], *, repos: Collection[str]) -> str | None:
    """The script's line for the repos of non-excluded cases not in ``repos``; ``None`` if none.

    As the script read them: ``excluded`` by truth value, a missing ``repo`` as ``'None'``.
    """
    known = set(repos)
    named = {
        str(case.get("repo"))
        for case in cases
        if isinstance(case, dict) and not case.get("excluded")
    }
    unknown = sorted(named - known)
    if not unknown:
        return None
    return f"ERROR bench: case repo(s) {unknown} not in hub.json repos {sorted(known)}"


def bench_cases(cases: Sequence[JsonValue]) -> tuple[BenchCase, ...]:
    """The ``BenchCase`` of each case; for cases ``case_problems`` found clean only.

    Raises ``ValueError`` (a Pydantic ``ValidationError``) for a case of the wrong shape.
    """
    return tuple(_bench_case(case) for case in cases)


def _bench_case(case: JsonValue) -> BenchCase:
    if not isinstance(case, dict):
        msg = f"a case must be an object, got {type(case).__name__}"
        raise ValueError(msg)
    fields = {key: case[key] for key, _, _ in _FIELDS if key in case}
    env = case.get("env", {})
    if isinstance(env, dict):
        fields["env"] = {key: str(value) for key, value in env.items()}
    return BenchCase.model_validate(fields)


def _problems_of(
    index: int, case: JsonValue, *, known: Sequence[str], seen: set[str]
) -> Iterator[CaseProblem]:
    if not isinstance(case, dict):
        yield CaseProblem(index=index, key=None, message=_OBJECT)
        return
    for key, message in _field_problems(case):
        yield CaseProblem(index=index, key=key, message=message)
    case_id = case.get("id")
    if isinstance(case_id, str):
        # Compared case-folded: an id is a worktree folder name, and macOS folders ignore case.
        if case_id.casefold() in seen:
            yield CaseProblem(index=index, key="id", message=f"duplicate id {_echo(case_id)}")
        seen.add(case_id.casefold())
    repo = case.get("repo")
    if isinstance(repo, str) and case.get("excluded") is not True and repo not in known:
        message = f"{_echo(repo)} is not in repos ({', '.join(known)})"
        yield CaseProblem(index=index, key="repo", message=message)


def _field_problems(case: dict[str, JsonValue]) -> Iterator[tuple[str, str]]:
    for key, check, required in _FIELDS:
        if key not in case:
            if required:
                yield key, MISSING
            continue
        message = check(case[key])
        if message is not None:
            yield key, message


def _echo(text: str) -> str:
    """``text`` as a JSON string, cut: one line of bounded length whatever it holds."""
    return cut_echo(json.dumps(text))


def _nul_problem(texts: Iterator[str] | Sequence[str]) -> str | None:
    return _NUL if any("\x00" in text for text in texts) else None


def _is_strings(value: JsonValue) -> TypeGuard[list[str]]:
    return isinstance(value, list) and all(isinstance(item, str) for item in value)


def _id_problem(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return _STRING
    if not _CASE_ID.fullmatch(value):
        return "must be 1 to 64 characters among A-Z, a-z, 0-9, `.`, `_` and `-`"
    return None


def _repo_problem(value: JsonValue) -> str | None:
    # Whether it names a repo depends on ``excluded``: checked with the whole case.
    return None if isinstance(value, str) else _STRING


def _merge_problem(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return _STRING
    if not _MERGE.fullmatch(value):
        return "must be a commit sha: 7 to 40 characters among 0-9 and a-f"
    return None


def _prompt_problem(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return _STRING
    if not 1 <= len(value) <= MAX_PROMPT_CHARS:
        return f"must be 1 to {MAX_PROMPT_CHARS} characters"
    if value.startswith("-"):
        # ``claude -p <prompt>``: ``-p`` is a flag, so ``--settings=/x`` would be an option.
        return "must not start with `-`"
    return _nul_problem([value])


def _hidden_tests_problem(value: JsonValue) -> str | None:
    if not _is_strings(value):
        return _STRINGS
    if not 1 <= len(value) <= MAX_HIDDEN_TESTS:
        return f"must list 1 to {MAX_HIDDEN_TESTS} paths"
    if nul := _nul_problem(value):
        return nul
    outside = next((path for path in value if not _is_test_path(path)), None)
    return None if outside is None else f"{_echo(outside)} {_PATH_BOUND}"


def _is_test_path(path: str) -> bool:
    """One file's relative POSIX path, read by git literally: no option, magic, glob or escape.

    ``git checkout <merge> -- <path>`` takes a pathspec: ``.`` or ``*`` would copy the whole
    merge tree, so every run would pass; ``\\`` escapes the next character of a glob. No
    character is hidden or unencodable, and no segment is git's store in any case.
    """
    return (
        1 <= len(path) <= MAX_TEST_PATH_CHARS
        and not path.startswith(("-", ":"))
        and _NOT_FILE_SEGMENTS.isdisjoint(path.casefold().split("/"))
        and _PATHSPEC_CHARACTERS.isdisjoint(path)
        and not any(unicodedata.category(character) in _HIDDEN_CATEGORIES for character in path)
    )


def _test_cmd_problem(value: JsonValue) -> str | None:
    if not _is_strings(value):
        return _STRINGS
    if not 1 <= len(value) <= MAX_TEST_CMD_ARGS or not all(
        1 <= len(argument) <= MAX_TEST_CMD_ARG_CHARS for argument in value
    ):
        return (
            f"must be 1 to {MAX_TEST_CMD_ARGS} non-empty strings"
            f" of at most {MAX_TEST_CMD_ARG_CHARS} characters"
        )
    return _nul_problem(value)


def _setup_cmd_problem(value: JsonValue) -> str | None:
    if not isinstance(value, str):
        return _STRING
    if len(value) > MAX_SETUP_CMD_CHARS:
        return f"must be at most {MAX_SETUP_CMD_CHARS} characters"
    return _nul_problem([value])


def _env_problem(value: JsonValue) -> str | None:
    if not isinstance(value, dict):
        return _OBJECT
    if len(value) > MAX_ENV_KEYS:
        return f"must have at most {MAX_ENV_KEYS} keys"
    for key, item in value.items():
        if not _ENV_KEY.fullmatch(key):
            return f"key {_echo(key)} must match {ENV_KEY_PATTERN}"
        # ``bool`` is an ``int``: true and false are values too.
        if not isinstance(item, str | int | float):
            return f"{_echo(key)} must be a string, a number, true or false"
    return _nul_problem(item for item in value.values() if isinstance(item, str))


def _excluded_problem(value: JsonValue) -> str | None:
    return None if isinstance(value, bool) else _BOOLEAN


# (key, check, required), in the order problems are reported.
_FIELDS: Final[tuple[tuple[str, Callable[[JsonValue], str | None], bool], ...]] = (
    ("id", _id_problem, True),
    ("repo", _repo_problem, True),
    ("merge", _merge_problem, True),
    ("prompt", _prompt_problem, True),
    ("hidden_tests", _hidden_tests_problem, True),
    ("test_cmd", _test_cmd_problem, True),
    ("setup_cmd", _setup_cmd_problem, False),
    ("env", _env_problem, False),
    ("excluded", _excluded_problem, False),
)
